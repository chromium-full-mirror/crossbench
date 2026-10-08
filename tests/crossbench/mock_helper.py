# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import collections
import contextlib
import copy
import dataclasses
import enum
import functools
import os
import pathlib
import shlex
import subprocess
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, Iterator, Mapping, \
    MutableMapping, Sequence, TypeAlias
from unittest import mock

import psutil
from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.benchmarks.base import SubStoryBenchmark
from crossbench.cli.cli import CrossBenchCLI
from crossbench.plt.android_adb import Adb, AndroidAdbPlatform
from crossbench.plt.base import MachineArch, Platform, SubprocessError
from crossbench.plt.chromeos_ssh import ChromeOsSshPlatform
from crossbench.plt.evemu_platform_mixin import VirtualDeviceState
from crossbench.plt.ios import IOSPlatform
from crossbench.plt.linux import LinuxPlatform, RemoteLinuxPlatform
from crossbench.plt.linux_ssh import LinuxSshPlatform
from crossbench.plt.macos import MacOSPlatform
from crossbench.plt.port_manager import LocalPortManager, PortManager
from crossbench.plt.process_meminfo import ProcessMeminfo
from crossbench.plt.pyodide import PyodidePlatform
from crossbench.plt.win import WinPlatform
from crossbench.stories.story import Story

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.action_runner.virtual_device.pointing import \
      PointingVirtualDeviceConfig
  from crossbench.device_config import DeviceConfigKeyPath
  from crossbench.plt.signals import Signals
  from crossbench.plt.types import CmdArg, ListCmdArgs, ProcessIo, \
      ProcessLike, TupleCmdArgs
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner

GIB = 1014**3


@dataclasses.dataclass(frozen=True)
class DownloadMockData:
  url: str
  path: pth.AnyPath
  data: bytes | None = None


class ShResult:

  def __init__(self, result: str | bytes = "", returncode: int = 0) -> None:
    if isinstance(result, str):
      result = result.encode("utf-8")
    assert isinstance(result, bytes)
    self._result = result
    self._returncode = returncode

  @property
  def result(self) -> bytes:
    return self._result

  @property
  def stdout(self) -> bytes:
    return self.result

  @property
  def returncode(self) -> int:
    return self._returncode


class TrackingPortManagerMixin:

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.forwarded_ports: dict[int, int] = {}
    self.reverse_forwarded_ports: dict[int, int] = {}

  def forward(self, local_port: int, remote_port: int) -> int:
    local_port = super().forward(local_port, remote_port)
    self.forwarded_ports[local_port] = remote_port
    return local_port

  def stop_forward(self, local_port: int) -> None:
    if local_port in self.forwarded_ports:
      del self.forwarded_ports[local_port]

  def reverse_forward(self, remote_port: int, local_port: int) -> int:
    remote_port = super().reverse_forward(remote_port, local_port)
    self.reverse_forwarded_ports[remote_port] = local_port
    return remote_port

  def stop_reverse_forward(self, remote_port: int) -> None:
    if remote_port in self.reverse_forwarded_ports:
      del self.reverse_forwarded_ports[remote_port]


class MockRemoterPortManagerMixin:

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.current_port = 60000

  def _next_port(self) -> int:
    self.current_port += 1
    return self.current_port

  def reverse_forward(self, remote_port: int, local_port: int) -> int:
    del local_port
    if remote_port == 0:
      return self._next_port()
    return remote_port

  def forward(self, local_port: int, remote_port: int) -> int:
    del remote_port
    if local_port == 0:
      return self._next_port()
    return local_port


class MockLocalPortManager(TrackingPortManagerMixin, LocalPortManager):
  pass


class MockRemotePortManager(TrackingPortManagerMixin,
                            MockRemoterPortManagerMixin, PortManager):
  pass


ShResultType: TypeAlias = str | bytes | ShResult


class MockPlatformMixin:

  def __init__(self, *args, is_battery_powered=False, fake_fs=None, **kwargs):
    self._is_battery_powered = is_battery_powered
    # Cache some helper properties that might fail under pyfakefs.
    self._sh_cmds: list[TupleCmdArgs] = []
    self._expected_sh_cmds: list[TupleCmdArgs] | None = None
    self._sh_results: list[ShResult] = []
    self._download_results: list[DownloadMockData] = []
    self.file_contents: MutableMapping[pth.AnyPath, list[str]] = (
        collections.defaultdict(list))
    self.sleeps: list[dt.timedelta] = []
    self.use_mock_machine = True
    self.use_mock_name = True
    self.mock_version_str: str | None = "1.2.3.4.5"
    self._machine_arch: [MachineArch] = None  # type: ignore
    self.popens: list[MockPopen] = []
    self.mkdir_calls: int = 0
    self.screenshots: list[pth.AnyPath] = []
    self.clipboard: str | None = None
    # Backs device_config() and set_device_config_value().
    self.device_config_data: dict[str, Any] = {}
    self.device_config_writes: list[tuple[DeviceConfigKeyPath, str | None]] = []
    self.fake_fs = fake_fs
    self.use_fs = bool(fake_fs)
    super().__init__(*args, **kwargs)

  @property
  def has_clipboard(self) -> bool:
    return True

  def set_clipboard(self, text: str) -> None:
    self.clipboard = text

  def install_mock_binary(self, name, path: pth.AnyPathLike) -> pth.AnyPath:
    binary = self.path(path)
    assert self.fake_fs, "missing fake fs"
    if not self.fake_fs.exists(binary):
      self.fake_fs.create_file(binary)
    self.set_binary_lookup_override(name, binary)
    return binary

  def _create_default_tmp_dir(self) -> pth.AnyPath:
    if self.use_fs and self.is_remote:
      return self.path("/tmp")
    return super()._create_default_tmp_dir()

  def exists(self, path: pth.AnyPathLike) -> bool:
    if self.use_fs and self.is_remote:
      return pth.LocalPath(self.path(path)).exists()
    return super().exists(path)

  def is_file(self, path: pth.AnyPathLike) -> bool:
    if self.use_fs and self.is_remote:
      return pth.LocalPath(self.path(path)).is_file()
    return super().is_file(path)

  def is_dir(self, path: pth.AnyPathLike) -> bool:
    if self.use_fs and self.is_remote:
      return pth.LocalPath(self.path(path)).is_dir()
    return super().is_dir(path)

  def which(self, binary_name: pth.AnyPathLike) -> pth.AnyPath | None:
    if self.use_fs and self.is_remote:
      if binary_override := self.lookup_binary_override(binary_name):
        return binary_override
      return None
    return super().which(binary_name)

  @property
  def has_display(self) -> bool:
    return True

  def _create_port_manager(self) -> PortManager:
    if self.is_local:
      return MockLocalPortManager(self)
    return MockRemotePortManager(self)

  @property
  def port_manager(self) -> PortManager:
    return self._default_port_manager

  def os_details(self):
    return {
        "system": "mock os system",
        "release": "mock os release",
        "version": "mock os version",
        "platform": "mock os platform",
    }

  def expect_download(self,
                      url: str,
                      path: pth.AnyPath,
                      data: bytes | None = None):
    self._download_results.append(DownloadMockData(url, path, data))

  def download_to(self, url: str, path: pth.AnyPath) -> pth.AnyPath:
    assert self._download_results, (
        f"No more download test data, but requested: {url}")
    provided_data = self._download_results.pop()
    assert url == provided_data.url, (f"Expected download url {url}, "
                                      f"but got: {provided_data.url}")
    assert path == provided_data.path, (
        f"Expected download result path {path}, but got: {provided_data.path}")
    if provided_data.data:
      pathlib.Path(path).write_bytes(provided_data.data)
    else:
      self.touch(path)
    return path

  def expect_sh(self,
                *args: CmdArg | int,
                result: ShResultType = "",
                returncode: int = 0) -> None:
    if args:
      if self._expected_sh_cmds is None:
        self._expected_sh_cmds = []
      self._expected_sh_cmds.append(self._convert_sh_args(*args))
    if isinstance(result, (str, bytes)):
      result = ShResult(result, returncode)
    else:
      assert returncode == 0, "Cannot have ShResult and custom returncode"
    assert isinstance(result, ShResult)
    self._sh_results.append(result)

  def _convert_sh_args(self, *args: CmdArg | int) -> TupleCmdArgs:
    converted_args: ListCmdArgs = []
    for arg in args:
      if not isinstance(arg, (str, pathlib.PurePath)):
        arg = str(arg)
      converted_args.append(arg)
    return tuple(converted_args)

  @property
  def sh_results(self) -> list[ShResult]:
    return list(self._sh_results)

  @sh_results.setter
  def sh_results(self, results: Iterable[ShResult]) -> None:
    assert not self._sh_results, "Trying to override non-consumed results"
    assert not self._expected_sh_cmds, (
        "expect_sh() cannot be used together with sh_results")
    for result in results:
      self.expect_sh(result=result)

  @property
  def sh_cmds(self) -> list[TupleCmdArgs]:
    return list(self._sh_cmds)

  @property
  def expected_sh_cmds(self) -> list[TupleCmdArgs] | None:
    if self._expected_sh_cmds is None:
      return None
    return list(self._expected_sh_cmds)

  @property
  def os_name(self) -> str:
    if self.use_mock_name:
      return f"mock.{super().os_name}"
    return super().os_name

  @property
  def machine(self) -> MachineArch:
    if not self.use_mock_machine:
      return super().machine
    if self._machine_arch:
      return self._machine_arch
    return MachineArch.ARM_64

  @machine.setter
  def machine(self, value: MachineArch) -> None:
    self._machine_arch = value

  @property
  def version_str(self) -> str:
    if self.mock_version_str:
      return self.mock_version_str
    return super().version_str

  @property
  def model(self) -> str:
    return "TestBook Pro"

  @property
  def cpu(self) -> str:
    return "Mega CPU @ 3.00GHz"

  @property
  def is_battery_powered(self) -> bool:
    return self._is_battery_powered

  def is_thermal_throttled(self) -> bool:
    return False

  def disk_usage(self, path: pth.AnyPathLike) -> psutil._common.sdiskusage:
    del path
    return psutil._common.sdiskusage(  # noqa: SLF001
        total=GIB * 100,
        used=20 * GIB,
        free=80 * GIB,
        percent=20)

  def cpu_usage(self) -> float:
    return 0.1

  @functools.lru_cache(maxsize=1)
  def cpu_details(self) -> dict[str, Any]:
    return {"physical cores": 2, "logical cores": 4, "info": self.cpu}

  def write_text(self,
                 file: pth.AnyPathLike,
                 data: str,
                 encoding: str = "utf-8") -> None:
    file_path = self.path(file)
    self.file_contents[file_path].append(data)
    if self.use_fs:
      super().write_text(file_path, data, encoding)

  @functools.lru_cache(maxsize=1)
  def system_details(self):
    return {"CPU": "20-core 3.1 GHz"}

  @override
  def device_config(self) -> dict[str, Any]:
    return {self.name: copy.deepcopy(self.device_config_data)}

  @override
  def set_device_config_value(self, key_path: DeviceConfigKeyPath,
                              value: str | None) -> None:
    """Records the call, and writes the value, deleting it if None."""
    self.device_config_writes.append((key_path, value))
    *sections, key = key_path

    # Walk down to the section holding the key; missing sections raise.
    node = self.device_config_data
    for section in sections:
      node = node[section]

    if value is None:
      node.pop(key, None)
    else:
      node[key] = value

  def sleep(self, duration):
    self.sleeps.append(duration)

  def processes(self, attrs=()):
    del attrs
    return []

  def process_children(self,
                       parent_pid: int,
                       recursive=False,
                       attrs: list[str] | None = None):
    del parent_pid, recursive
    return []

  def foreground_process(self):
    return None

  def search_platform_binary(
      self,
      name: str,
      macos: Sequence[str] = (),
      win: Sequence[str] = (),
      linux: Sequence[str] = (),
  ) -> pth.AnyPath:
    del macos, win, linux
    return self.path(f"/usr/bin/{name}")

  def search_binary(self, app_or_bin: str | pth.AnyPath) -> pth.AnyPath | None:
    path = self.path(app_or_bin)
    if not path.parts:
      raise ValueError("Got empty path")
    if len(path.parts) == 1:
      path = self.path(f"/usr/bin/{app_or_bin}")
    if self.use_fs and self.is_file(path):
      return path
    return super().search_binary(app_or_bin)

  def sh_stdout_bytes(self,
                      *args: CmdArg,
                      shell: bool = False,
                      quiet: bool = False,
                      stdin: ProcessIo = None,
                      input: bytes | str | None = None,
                      env: Mapping[str, str] | None = None,
                      cwd: pth.AnyPath | None = None,
                      check: bool = True) -> bytes:
    return self.sh(
        *args,
        shell=shell,
        quiet=quiet,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        check=check,
        capture_output=True).stdout

  def sh(self,
         *args: CmdArg,
         shell: bool = False,
         capture_output: bool = False,
         stdout: ProcessIo = None,
         stderr: ProcessIo = None,
         stdin: ProcessIo = None,
         input: bytes | str | None = None,
         env: Mapping[str, str] | None = None,
         cwd: pth.AnyPath | None = None,
         quiet: bool = False,
         check: bool = True) -> subprocess.CompletedProcess:
    del capture_output, stderr, stdin, input, stdout, shell, quiet, env, cwd
    if self._expected_sh_cmds is not None:
      assert self._expected_sh_cmds, (
          f"Missing expected sh_cmds, but got: {args}")
      # Convert all args to str first, sh accepts both str and Paths.
      expected = tuple(map(str, self._expected_sh_cmds[0]))
      str_args = tuple(map(str, args))
      assert expected == str_args, (f"After {len(self._sh_cmds)} cmds: \n"
                                    f"  expected: {expected}\n"
                                    f"  got:      {str_args}")
      self._expected_sh_cmds.pop(0)
    self._sh_cmds.append(args)
    if not self._sh_results:
      cmd = shlex.join(map(str, args))
      raise ValueError(f"After {len(self._sh_cmds)} cmds: "
                       f"MockPlatform has no more sh outputs for cmd: {cmd}")

    sh_result: ShResult = self._sh_results.pop(0)
    process = subprocess.CompletedProcess(
        args, sh_result.returncode, stdout=sh_result.result)
    if check and process.returncode != 0:
      raise SubprocessError(self, process)

    return process

  def _popen(self,
             *args: CmdArg,
             bufsize=-1,
             shell: bool = False,
             stdout: ProcessIo = None,
             stderr: ProcessIo = None,
             stdin: ProcessIo = None,
             env: Mapping[str, str] | None = None,
             cwd: pth.AnyPath | None = None,
             encoding: str | None = None,
             quiet: bool = False,
             auto_terminate: bool = True) -> MockPopen:
    del bufsize, stdout, stderr, stdin, encoding, auto_terminate
    self.sh_stdout(*args, shell=shell, quiet=quiet, env=env, cwd=cwd)

    if not self.popens:
      raise ValueError("No valid mock popen.")

    mock_popen = self.popens.pop(0)
    mock_popen.start()
    return mock_popen

  def terminate_gracefully(self,
                           process: ProcessLike | MockPopen,
                           timeout: int = 1,
                           signal: Signals | None = None) -> None:
    if isinstance(process, MockPopen):
      process.terminate()
      return
    super().terminate_gracefully(process, timeout, signal)

  def mkdir(self,
            path: pth.AnyPathLike,
            parents: bool = True,
            exist_ok: bool = True) -> None:
    super().mkdir(path, parents, exist_ok)
    self.mkdir_calls += 1

  def process_meminfo(self, process_name: str,
                      timeout: dt.timedelta) -> list[ProcessMeminfo]:
    del timeout
    return [
        ProcessMeminfo(1, process_name, 2, 3, 4),
        ProcessMeminfo(2, process_name, 3, 4, 5),
    ]

  def system_meminfo(self, timeout: dt.timedelta) -> dict[str, float]:
    del timeout
    return {
        "total_ram_kb": 5,
        "cached_pss_kb": 4,
        "cached_kernel_kb": 3,
        "free_kb": 2,
    }

  @override
  def screenshot(self, result_path: pth.AnyPath) -> None:
    self.screenshots.append(result_path)

  @contextlib.contextmanager
  def wakelock(self) -> Iterator[None]:
    yield


class MockFd:

  def __init__(self):
    self.expected_writes: list[bytes] = []
    self.read_returns: list[bytes] = []

  def __del__(self):
    assert not self.expected_writes
    assert not self.read_returns

  def write(self, data: bytes):
    if not self.expected_writes:
      raise ValueError("No expected writes.")

    expected = self.expected_writes.pop(0)

    assert data == expected, (
        f"Expected write does not match. Expected: {expected} Got: {data!r}")

  def readline(self):
    if not self.read_returns:
      raise ValueError("No read returns.")

    return self.read_returns.pop(0)

  def flush(self):
    return


class MockPopenState(enum.StrEnum):
  UNUSED = "unused"
  RUNNING = "running"
  TERMINATED = "terminated"
  KILLED = "killed"


class MockPopen:

  def __init__(self, stdout: MockFd | None = None, stdin: MockFd | None = None):
    self._stdout: MockFd = stdout or MockFd()
    self._stdin: MockFd = stdin or MockFd()
    self.state = MockPopenState.UNUSED

  def start(self):
    assert self.state == MockPopenState.UNUSED
    self.state = MockPopenState.RUNNING

  def poll(self):
    assert self.state != MockPopenState.UNUSED
    if self.state == MockPopenState.RUNNING:
      return None
    return 0

  def terminate(self):
    assert self.state != MockPopenState.UNUSED
    self.state = MockPopenState.TERMINATED

  def kill(self):
    assert self.state != MockPopenState.UNUSED
    self.state = MockPopenState.KILLED

  def wait(self):
    assert self.state != MockPopenState.UNUSED
    return

  @property
  def stdin(self):
    return self._stdin

  @property
  def stdout(self):
    return self._stdout


class PosixMockPlatformMixin(MockPlatformMixin):
  pass


class WinMockPlatformMixin(MockPlatformMixin):
  # TODO: use wrapper fake path to get windows-path formatting by default
  # when running on posix.

  def path(self, path: pth.AnyPathLike) -> pth.AnyPath:
    return pathlib.PureWindowsPath(os.fspath(path))

  def local_path(self, path: pth.AnyPathLike) -> pth.LocalPath:
    self.assert_is_local()
    if isinstance(path, pathlib.PureWindowsPath):
      return pth.LocalPath(path.as_posix())
    if isinstance(path, str):
      return pth.LocalPath(pathlib.PureWindowsPath(path).as_posix())
    return pth.LocalPath(path)


class LinuxMockPlatform(PosixMockPlatformMixin, LinuxPlatform):
  pass


class PyodideMockPlatform(LinuxMockPlatform, PyodidePlatform):
  pass


class RemoteLinuxMockPlatform(PosixMockPlatformMixin, RemoteLinuxPlatform):
  pass


class LinuxSshMockPlatform(PosixMockPlatformMixin, LinuxSshPlatform):
  pass


class ChromeOsSshMockPlatform(PosixMockPlatformMixin, ChromeOsSshPlatform):
  pass


class MacOsMockPlatform(PosixMockPlatformMixin, MacOSPlatform):
  pass


class MacIOSMockPlatform(PosixMockPlatformMixin, IOSPlatform):
  pass


class WinMockPlatform(WinMockPlatformMixin, WinPlatform):
  pass


class MockAdb(Adb):
  mock_sdk_version: int = AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION

  @functools.cached_property
  @override
  def sdk_version(self) -> int:
    try:
      return super().sdk_version
    except Exception:
      return self.mock_sdk_version

  @override
  def start_server(self) -> None:
    pass

  @override
  def stop_server(self) -> None:
    pass

  @override
  def kill_server(self) -> None:
    pass


class AndroidAdbMockPlatform(MockPlatformMixin, AndroidAdbPlatform):

  def _init_mock_virtual_device(self, device_name: str,
                                device_type: VirtualDeviceType) -> None:
    if self._is_device_running(device_name):
      return
    mock_proc = mock.MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.stdin = mock.MagicMock()
    self._virtual_devices[device_name] = VirtualDeviceState(
        mock_proc, device_type=device_type)

  @override
  def _init_virtual_keyboard(self, device_name: str) -> None:
    self._init_mock_virtual_device(device_name, VirtualDeviceType.KEYBOARD)

  @override
  def _init_pointing_virtual_device(self,
                                    device_config: PointingVirtualDeviceConfig,
                                    header_template: str) -> None:
    assert header_template, "No evemu header template provided"
    self._init_mock_virtual_device(device_config.name,
                                   device_config.device_type)


class GenericMockPlatform(MockPlatformMixin, Platform):
  pass


if plt.PLATFORM.is_linux:
  MockPlatform = LinuxMockPlatform
elif plt.PLATFORM.is_macos:
  MockPlatform = MacOsMockPlatform
elif plt.PLATFORM.is_win:
  MockPlatform = WinMockPlatform
else:
  raise RuntimeError(f"Unsupported platform: {plt.PLATFORM}")


class MockStory(Story):

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return ("story_1", "story_2")

  def run(self, run: Run) -> None:
    pass


class MockBenchmark(SubStoryBenchmark):
  NAME = "mock-benchmark"
  DEFAULT_STORY_CLS: ClassVar = MockStory


class MockCLI(CrossBenchCLI):
  runner: Runner
  platform: Platform

  def __init__(self, platform: Platform, enable_logging: bool = True) -> None:
    self.platform = platform
    super().__init__(enable_logging=enable_logging)
