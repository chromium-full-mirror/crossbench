# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import atexit
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import functools
import gzip
import inspect
import logging
import os
import pathlib
import platform as py_platform
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import weakref
from typing import TYPE_CHECKING, Any, Callable, Final, Generator, Iterable, \
    Iterator, Mapping, Sequence

import google.api_core.exceptions as gcloud_exceptions
import google.cloud.storage as gcloud_storage
import psutil

from crossbench import __version__, parse
from crossbench import path as pth
from crossbench.helper import wait
from crossbench.helper.size import Size
from crossbench.parse import NumberParser, ObjectParser
from crossbench.plt import proc_helper
from crossbench.plt.arch import MachineArch
from crossbench.plt.bin import Binary
from crossbench.plt.port_manager import LocalPortManager, PortManager, \
    PortScope
from crossbench.plt.remote import RemotePopen

if TYPE_CHECKING:
  import google.cloud.storage.blob as gcloud_blob  # type: ignore

  from crossbench.action_runner.action.position import UiSelectorConfig
  from crossbench.action_runner.display_rectangle import DisplayRectangle
  from crossbench.action_runner.input_events import InputEvent
  from crossbench.action_runner.virtual_device.virtual_device_config import \
      VirtualDeviceConfig
  from crossbench.device_config import DeviceConfigKeyPath
  from crossbench.plt.display_info import DisplayInfo
  from crossbench.plt.process_meminfo import ProcessMeminfo
  from crossbench.plt.signals import AnySignals, Signals
  from crossbench.plt.types import CmdArg, ProcessIo, ProcessLike, TupleCmdArgs
  from crossbench.plt.version import PlatformVersion
  from crossbench.plt.version_details import VersionDetails
  from crossbench.types import JsonDict


class Environ(collections.abc.MutableMapping, metaclass=abc.ABCMeta):
  pass


class LocalEnviron(Environ):

  def __init__(self) -> None:
    self._environ = os.environ

  def __getitem__(self, key: str) -> str:
    return self._environ.__getitem__(key)

  def __setitem__(self, key: str, item: str) -> None:
    self._environ.__setitem__(key, item)

  def __delitem__(self, key: str) -> None:
    self._environ.__delitem__(key)

  def __iter__(self) -> Iterator[str]:
    return self._environ.__iter__()

  def __len__(self) -> int:
    return self._environ.__len__()


class SubprocessError(subprocess.CalledProcessError):
  """ Custom version that also prints stderr for debugging"""

  def __init__(self, platform: Platform,
               process: subprocess.CompletedProcess) -> None:
    self.platform = platform
    super().__init__(process.returncode, shlex.join(map(str, process.args)),
                     process.stdout, process.stderr)

  def __str__(self) -> str:
    super_str = super().__str__()
    if not self.stderr:
      return f"{self.platform}: {super_str}"
    return f"{self.platform}: {super_str}\nstderr:{self.stderr.decode()}"


@dataclasses.dataclass
class CPUFreqInfo:
  min: float
  max: float
  current: float


_NEXT_PLATFORM_ID = 0


def _next_id() -> int:
  global _NEXT_PLATFORM_ID  # noqa: PLW0603
  new_id = _NEXT_PLATFORM_ID
  _NEXT_PLATFORM_ID += 1
  return new_id


DEFAULT_CACHE_DIR: Final = pth.LocalPath(__file__).parents[2] / "cache"


class Platform(abc.ABC):
  SEARCH_PATHS: tuple[pth.AnyPath, ...] = ()

  def __init__(self) -> None:
    self._id: Final[int] = _next_id()
    self._binary_lookup_override: dict[str, pth.AnyPath] = {}
    self._cache_dir_root: pth.AnyPath | None = None
    self._default_port_manager: Final[PortManager] = self._create_port_manager()
    self._default_tmp_dir: Final[pth.AnyPath] = self._create_default_tmp_dir()
    self._popens: weakref.WeakSet[subprocess.Popen] = weakref.WeakSet()
    self._virtual_device_configs: dict[str, VirtualDeviceConfig] = {}
    atexit.register(self.kill_all_popens)

  def _create_port_manager(self) -> PortManager:
    return LocalPortManager(self)

  def _create_default_tmp_dir(self) -> pth.AnyPath:
    self.assert_is_local()
    return self.path(tempfile.gettempdir())

  @property
  def virtual_devices(self) -> Mapping[str, VirtualDeviceConfig]:
    return self._virtual_device_configs

  def setup_virtual_devices(
      self, virtual_devices: tuple[VirtualDeviceConfig, ...]) -> None:
    for device in virtual_devices:
      self._virtual_device_configs[device.name] = device

  def teardown_virtual_devices(self) -> None:
    self._virtual_device_configs.clear()

  def assert_is_local(self) -> None:
    if self.is_local:
      return
    caller = "assert_is_local"
    caller = inspect.stack()[1].function
    raise RuntimeError(f"{type(self).__name__}.{caller}(...) is not supported "
                       "on remote platform")

  @property
  @abc.abstractmethod
  def signals(self) -> type[AnySignals]:
    pass

  @property
  def id(self) -> int:
    return self._id

  @property
  def unique_name(self) -> str:
    """Unique id per platform."""
    key_str = ".".join(self.key)
    return f"{key_str}.{self.id}"

  @property
  def name(self) -> str:
    """Descriptive name e.g. macos of the platform. non-unique."""
    if self.is_remote_ssh:
      return f"{self.os_name}_ssh"
    return self.os_name

  @property
  @abc.abstractmethod
  def os_name(self) -> str:
    """Base descriptive OS name e.g. macos."""

  @property
  @abc.abstractmethod
  def version_str(self) -> str:
    pass

  @property
  @abc.abstractmethod
  def version(self) -> PlatformVersion:
    pass

  @property
  def version_parts(self) -> tuple[int, ...]:
    return self.version.parts

  @property
  @abc.abstractmethod
  def model(self) -> str:
    pass

  @property
  @abc.abstractmethod
  def cpu(self) -> str:
    pass

  @functools.lru_cache(maxsize=2)
  def cpu_cores(self, logical: bool) -> int:
    self.assert_is_local()
    if cores := psutil.cpu_count(logical=logical):
      return cores
    return 0

  @property
  def full_version(self) -> str:
    return f"{self.name} {self.version_str} {self.machine}"

  def __str__(self) -> str:
    return self.unique_name

  @property
  def key(self) -> tuple[Any, ...]:
    return ("local", self.name, str(self.machine))

  @property
  def is_remote(self) -> bool:
    return False

  @property
  def is_local(self) -> bool:
    return not self.is_remote

  @property
  def is_pyodide(self) -> bool:
    """Returns True if running in a Pyodide WebAssembly environment."""
    return False

  @property
  def host_platform(self) -> Platform:
    return self

  @functools.cached_property
  def machine(self) -> MachineArch:
    raw = self._raw_machine_arch()
    if raw in ("i386", "i686", "x86", "ia32"):
      return MachineArch.IA32
    if raw in ("x86_64", "AMD64"):
      return MachineArch.X64
    if raw in ("arm64", "aarch64"):
      return MachineArch.ARM_64
    if raw in ("arm",):
      return MachineArch.ARM_32
    if raw in ("wasm32",):
      return MachineArch.WASM_32
    if raw in ("wasm64",):
      return MachineArch.WASM_64
    raise NotImplementedError(f"Unsupported machine type: {raw}")

  def _raw_machine_arch(self) -> str:
    self.assert_is_local()
    return py_platform.machine()

  @property
  def is_ia32(self) -> bool:
    return self.machine == MachineArch.IA32

  @property
  def is_x64(self) -> bool:
    return self.machine == MachineArch.X64

  @property
  def is_arm64(self) -> bool:
    return self.machine == MachineArch.ARM_64

  @property
  def is_wasm(self) -> bool:
    return self.machine.is_wasm

  @property
  def type_key(self) -> tuple[str, str]:
    """Key used for looking up platform specific objects."""
    return (self.os_name, str(self.machine))

  @property
  def is_macos(self) -> bool:
    return False

  @property
  def is_ios(self) -> bool:
    return False

  @property
  def is_apple(self) -> bool:
    return self.is_macos or self.is_ios

  @property
  def is_linux(self) -> bool:
    return False

  @property
  def is_android(self) -> bool:
    return False

  @property
  def is_chromeos(self) -> bool:
    return False

  @property
  def is_posix(self) -> bool:
    return self.is_macos or self.is_linux or self.is_android

  @property
  def is_win(self) -> bool:
    return False

  @property
  def pathsep(self) -> str:
    return ":"

  @property
  def is_remote_ssh(self) -> bool:
    return False

  @property
  def is_remote_desktop(self) -> bool:
    return False

  @property
  def environ(self) -> Environ:
    self.assert_is_local()
    return LocalEnviron()

  @property
  def is_battery_powered(self) -> bool:
    self.assert_is_local()
    if not psutil.sensors_battery:  # type: ignore
      return False
    status = psutil.sensors_battery()
    if not status:
      return False
    return not status.power_plugged

  @functools.lru_cache(maxsize=1)
  def cpu_details(self) -> dict[str, Any]:
    self.assert_is_local()
    details = {
        "physical cores": self.cpu_cores(logical=False),
        "logical cores": self.cpu_cores(logical=True),
        "usage": psutil.cpu_percent(percpu=True, interval=0.1),
        "total usage": psutil.cpu_percent(),
        "system load": psutil.getloadavg(),
        "info": self.cpu,
        "min frequency": "N/A",
        "max frequency": "N/A",
        "current frequency": "N/A",
    }
    if cpu_freq := self._cpu_freq():
      details.update({
          "min frequency": f"{cpu_freq.min:.2f}Mhz",
          "max frequency": f"{cpu_freq.max:.2f}Mhz",
          "current frequency": f"{cpu_freq.current:.2f}Mhz",
      })
    return details

  def _cpu_freq(self) -> CPUFreqInfo | None:
    self.assert_is_local()
    cpu_freq = psutil.cpu_freq()
    return CPUFreqInfo(cpu_freq.min, cpu_freq.max, cpu_freq.current)

  @property
  def system_memory_bytes(self) -> int:
    self.assert_is_local()
    return psutil.virtual_memory().total

  def total_memory_mb(self) -> int:
    return self.system_memory_bytes // Size.MiB

  def device_config(self) -> dict[str, Any]:
    """Returns a hierarchical dictionary of device/host configuration.

    Subclasses override this method to provide platform-specific configuration
    dumps (such as Android settings, getprop properties, and device_config).

    The returned dictionary is nested under a platform namespace (e.g.
    'android'). Intermediate nodes are mappings, and leaf nodes are string
    values. Leaf keys may be composite identifiers (such as 'namespace/key'
    or 'ro.product.model').

    The configuration is validated against benchmark requirements
    (Benchmark.required_device_config()) during run setup.
    """
    return {}

  def set_device_config_value(self, key_path: DeviceConfigKeyPath,
                              value: str | None) -> None:
    """Writes a single device configuration value, deleting it if None.

    Key paths are relative to the platform namespace of device_config(),
    e.g. ('settings', 'system', 'screen_brightness') on Android.

    Raises:
      ValueError: If key_path cannot be written on this platform, before
        the device is touched.
    """
    del value
    raise ValueError(f"Cannot set device config {'.'.join(key_path)!r}.")

  @functools.lru_cache(maxsize=1)
  def system_details(self) -> dict[str, Any]:
    details = {
        "machine": str(self.machine),
        "os": self.os_details(),
        "python": self.python_details(),
        "CPU": self.cpu_details(),
        "display": self.display_details(),
    }
    if self.is_local:
      details["crossbench"] = self.crossbench_details()
    return details

  @functools.lru_cache(maxsize=1)
  def os_details(self) -> JsonDict:
    self.assert_is_local()
    return {
        "system": py_platform.system(),
        "release": py_platform.release(),
        "version": py_platform.version(),
        "platform": py_platform.platform(),
    }

  @functools.lru_cache(maxsize=1)
  def python_details(self) -> JsonDict:
    self.assert_is_local()
    return {
        "version": py_platform.python_version(),
        "bits": 64 if sys.maxsize > 2**32 else 32,
    }

  @functools.lru_cache(maxsize=1)
  def crossbench_details(self) -> VersionDetails:
    self.assert_is_local()
    git_bin = self.which("git")
    root_dir = pth.ROOT_DIR
    if not git_bin or not (root_dir / ".git").exists():
      return {"version": __version__}

    def run_git(*args: CmdArg) -> str:
      res = self.sh_stdout(git_bin, *args, cwd=root_dir, check=False)
      return res.strip()

    return {
        "version": __version__,
        "current_hash": run_git("rev-parse", "HEAD"),
        "canonical_parent_hash": run_git("merge-base", "HEAD", "origin/main"),
        "has_uncommitted_changes": bool(run_git("status", "--porcelain")),
    }

  def display_details(self) -> tuple[DisplayInfo, ...]:
    # TODO: implement on more platforms
    return ()

  def get_relative_cpu_speed(self) -> float:
    return 1

  def is_thermal_throttled(self) -> bool:
    return self.get_relative_cpu_speed() < 1

  @abc.abstractmethod
  def uptime(self) -> dt.timedelta:
    pass

  def disk_usage(self, path: pth.AnyPathLike) -> psutil._common.sdiskusage:
    return psutil.disk_usage(str(self.local_path(path)))

  def cpu_usage(self) -> float:
    self.assert_is_local()
    return 1 - psutil.cpu_times_percent().idle / 100

  def _search_executable(
      self,
      name: str,
      macos: Sequence[str],
      win: Sequence[str],
      linux: Sequence[str],
      lookup_callable: Callable[[pth.AnyPath], pth.AnyPath | None],
  ) -> pth.AnyPath:
    executables: Sequence[str] = []
    if self.is_macos:
      executables = macos
    elif self.is_win:
      executables = win
    elif self.is_linux:
      executables = linux
    if not executables:
      raise ValueError(f"Executable {name} not supported on {self}")
    for name_or_path in executables:
      path = self.local_path(name_or_path).expanduser()
      binary = lookup_callable(path)
      if binary and self.exists(binary):
        return binary
    raise ValueError(f"Executable {name} not found on {self}")

  def search_app_or_executable(
      self,
      name: str,
      macos: Sequence[str] = (),
      win: Sequence[str] = (),
      linux: Sequence[str] = (),
  ) -> pth.AnyPath:
    return self._search_executable(name, macos, win, linux, self.search_app)

  def search_platform_binary(
      self,
      name: str,
      macos: Sequence[str] = (),
      win: Sequence[str] = (),
      linux: Sequence[str] = (),
  ) -> pth.AnyPath:
    return self._search_executable(name, macos, win, linux, self.search_binary)

  def search_app(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    """Look up a application bundle (macos) or binary (all other platforms) in
    the common search paths.
    """
    return self.search_binary(app_or_bin)

  @abc.abstractmethod
  def search_binary(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    """Look up a binary in the common search paths based of a path or a single
    segment path with just the binary name.
    Returns the location of the binary (and not the .app bundle on macOS).
    """

  def _search_binary_in_search_path(
      self, app_or_bin: pth.AnyPath) -> pth.AnyPath | None:
    for path in self.SEARCH_PATHS:
      # Recreate Path object for easier pyfakefs testing
      result_path = self.path(path) / app_or_bin
      if self.exists(result_path):
        return result_path
    return None

  @abc.abstractmethod
  def app_version(self, app_or_bin: pth.AnyPathLike) -> str:
    pass

  @property
  def is_headless(self) -> bool:
    return not self.has_display

  @property
  def has_display(self) -> bool:
    """Return a bool whether the platform has an active display.
    This can be false on linux without $DISPLAY, true an all other platforms."""
    return True

  def inject_input_events(self, device_name: str,
                          events: Iterable[InputEvent]) -> None:
    """
    Injects abstract input events and blocks until all events are
    processed.
    """
    raise NotImplementedError(
        f"inject_input_events not implemented for {self}.")

  def sleep(self, seconds: float | dt.timedelta) -> None:
    wait.sleep(seconds)

  def parse_binary_path(self,
                        value: pth.AnyPathLike,
                        name: str = "value") -> pth.AnyPath:
    # Helper to avoid circular imports.
    return parse.PathParser.binary_path(value, self, name)

  def parse_local_binary_path(self,
                              value: pth.AnyPathLike,
                              name: str = "value") -> pth.LocalPath:
    self.assert_is_local()
    # Helper to avoid circular imports.
    return parse.PathParser.local_binary_path(value, self, name)

  def which(self, binary_name: pth.AnyPathLike) -> pth.AnyPath | None:
    binary_name_path = self.path(binary_name)
    if not binary_name_path.parts:
      raise ValueError("Got empty path")
    self.assert_is_local()
    if binary_override := self.lookup_binary_override(binary_name):
      return binary_override
    binary_name_path = self.expanduser(binary_name_path)
    if result := shutil.which(os.fspath(binary_name_path)):
      return self.path(result)
    return None

  def lookup_binary_override(
      self, binary_name: pth.AnyPathLike) -> pth.AnyPath | None:
    return self._binary_lookup_override.get(os.fspath(binary_name))

  def set_binary_lookup_override(self, binary_name: pth.AnyPathLike,
                                 new_path: pth.AnyPath | None) -> None:
    name = os.fspath(binary_name)
    if new_path is None:
      prev_result = self._binary_lookup_override.pop(name, None)
      if prev_result is None:
        logging.debug(
            "Could not remove binary override for %s as it was never set",
            binary_name)
      return
    if self.search_binary(new_path) is None:
      raise ValueError(f"Suggested binary override for {name!r} "
                       f"does not exist: {new_path}")
    self._binary_lookup_override[name] = new_path

  @contextlib.contextmanager
  def override_binary(self, binary: pth.AnyPathLike | Binary,
                      result: pth.AnyPath | None) -> Iterator[None]:
    binary_name: pth.AnyPathLike = ""
    if isinstance(binary, Binary):
      binary_name = binary.name
    else:
      binary_name = binary
    prev_override = self.lookup_binary_override(binary_name)
    self.set_binary_lookup_override(binary_name, result)
    try:
      yield
    finally:
      self.set_binary_lookup_override(binary_name, prev_override)

  def send_signal(self, process: ProcessLike, signal: Signals) -> None:
    self.assert_is_local()
    if isinstance(process, int):
      os.kill(process, signal.value)
    else:
      process.send_signal(signal.value)

  def terminate(self, process: ProcessLike) -> None:
    self._handle_process_tree(process, lambda process: process.terminate())

  def kill(self, process: ProcessLike) -> None:
    self._handle_process_tree(process, lambda process: process.kill())

  def killall(self, process_name: str) -> None:
    del process_name
    raise NotImplementedError(f"killall not implemented for {self}")

  @property
  def active_popens(self) -> tuple[subprocess.Popen, ...]:
    return tuple(proc for proc in self._popens if proc.poll() is None)

  def kill_all_popens(self) -> None:
    for proc in self.active_popens:
      with contextlib.suppress(*proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS):
        self.kill(proc)

  def terminate_gracefully(self,
                           process: ProcessLike,
                           timeout: int = 1,
                           signal: Signals | None = None) -> None:
    proc_helper.terminate_gracefully(self, process, timeout, signal)

  def process_pid(self, process: ProcessLike) -> int:
    if isinstance(process, int):
      return process
    if isinstance(process, RemotePopen):
      assert self.is_remote, (
          f"Cannot access remote process {process} on local platform {self}")
      return process.remote_pid
    return process.pid

  def _handle_process_tree(self, process: ProcessLike,
                           callback: Callable[[psutil.Process], None]) -> None:
    self.assert_is_local()
    try:
      pid: int = self.process_pid(process)
      ps_process = psutil.Process(pid)
      for child_process in ps_process.children(recursive=True):
        with contextlib.suppress(*proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS):
          callback(child_process)
      callback(ps_process)
    except proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS:
      pass

  def processes(self, attrs: list[str] | None = None) -> list[dict[str, Any]]:
    # TODO(cbruni): support remote platforms
    assert self.is_local, "Only local platform supported"
    return self._collect_process_dict(psutil.process_iter(attrs=attrs), attrs)

  def process_running(self, process_name_list: Iterable[str]) -> str | None:
    self.assert_is_local()
    name_lookup = {name.lower(): name for name in process_name_list}
    # TODO(cbruni): support remote platforms
    for proc in psutil.process_iter(attrs=["name"]):
      with contextlib.suppress(*proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS):
        name = proc.info.get("name")
        if name and name.lower() in name_lookup:
          return name
    return None

  def process_children(self,
                       parent_pid: int,
                       recursive: bool = False,
                       attrs: list[str] | None = None) -> list[dict[str, Any]]:
    self.assert_is_local()
    # TODO(cbruni): support remote platforms
    try:
      process = psutil.Process(parent_pid)
    except proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS:
      return []
    return self._collect_process_dict(
        process.children(recursive=recursive), attrs=attrs)

  def _collect_process_dict(
      self,
      process_iterator: Iterable[psutil.Process],
      attrs: list[str] | None = None) -> list[dict[str, Any]]:
    process_info_list: list[dict[str, Any]] = []
    for process in process_iterator:
      with contextlib.suppress(*proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS):
        # psutil.Process does not always have an "info" property.
        # It is dynamically added only by psutil.process_iter().
        # Other sources like process.children() lack it, requiring getattr
        # fallback.
        if info := getattr(process, "info", None):
          process_info_list.append(info.copy())
        else:
          process_info_list.append(process.as_dict(attrs=attrs))
    return process_info_list

  def process_info(self,
                   process: ProcessLike,
                   attrs: list[str] | None = None) -> dict[str, Any] | None:
    self.assert_is_local()
    # TODO(cbruni): support remote platforms
    try:
      pid = self.process_pid(process)
      return psutil.Process(pid).as_dict(attrs=attrs)
    except proc_helper.PROCESS_NOT_FOUND_EXCEPTIONS:
      return None

  def is_process_running(self, process: ProcessLike) -> bool:
    info = self.process_info(process)
    return bool(info and info.get("status") != psutil.STATUS_ZOMBIE)

  def process_meminfo(self, process_name: str,
                      timeout: dt.timedelta) -> list[ProcessMeminfo]:
    del process_name, timeout
    raise NotImplementedError(f"process_meminfo not implemented for {self}.")

  def system_meminfo(self, timeout: dt.timedelta) -> dict[str, float]:
    del timeout
    raise NotImplementedError(f"system_meminfo not implemented for {self}.")

  def gpu_vram_used(self) -> dict[str, float]:
    """Returns a dictionary of GPU identifiers to VRAM / Unified memory
    used in MB."""
    return {}

  def foreground_process(self) -> dict[str, Any] | None:
    return None

  def dump_java_heap(self, identifier: str, label: str,
                     trace_buffer_size_kb: int,
                     timeout: dt.timedelta) -> pth.AnyPath:
    del identifier, label, trace_buffer_size_kb, timeout
    raise NotImplementedError(f"dump_java_heap not implemented for {self}.")

  @property
  def default_tmp_dir(self) -> pth.AnyPath:
    return self._default_tmp_dir

  @property
  def ports(self) -> PortScope:
    return self._default_port_manager.scope

  def is_port_used(self, port: int) -> bool:
    self.assert_is_local()
    for conn in psutil.net_connections(kind="inet"):
      if conn.status == psutil.CONN_LISTEN and conn.laddr:
        if conn.laddr.port == port:
          return True
    return False

  def wait_for_port(self, port: int, timeout: dt.timedelta) -> None:
    for _ in wait.wait_with_backoff(timeout):
      if self.is_port_used(port):
        break

  def get_free_port(self) -> int:
    self.assert_is_local()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
      s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      s.bind(("localhost", 0))
      return s.getsockname()[1]

  def local_cache_dir(self, name: str | None = None) -> pth.LocalPath:
    return self.local_path(self.cache_dir(name))

  def cache_dir(self, name: str | None = None) -> pth.AnyPath:
    if self._cache_dir_root is None:
      self._cache_dir_root = self._lazy_setup_cache_dir()
    assert self._cache_dir_root, "missing cache dir"
    if not name:
      dir = self._cache_dir_root
    else:
      dir = self._cache_dir_root / pth.safe_filename(name)
    self.mkdir(dir, parents=True, exist_ok=True)
    return dir

  def _lazy_setup_cache_dir(self) -> pth.AnyPath:
    if self.is_local and DEFAULT_CACHE_DIR:
      return self.local_path(DEFAULT_CACHE_DIR)
    tmp_cache_dir = self.default_tmp_dir / "crossbench_cache"
    atexit.register(self.rm, tmp_cache_dir, dir=True, missing_ok=True)
    return tmp_cache_dir

  def set_cache_dir(self, path: pth.AnyPath) -> None:
    self._cache_dir_root = self.path(path)
    self.mkdir(path, parents=True)

  def cat(self, file: pth.AnyPathLike, encoding: str = "utf-8") -> str:
    """Meow! I return the file contents as a str."""
    return self.local_path(file).read_text(encoding=encoding)

  def cat_bytes(self, file: pth.AnyPathLike) -> bytes:
    """Hiss! I return the file contents as bytes."""
    return self.local_path(file).read_bytes()

  def read_text(self, file: pth.AnyPathLike, encoding: str = "utf-8") -> str:
    return self.cat(file, encoding)

  def write_text(self,
                 file: pth.AnyPathLike,
                 data: str,
                 encoding: str = "utf-8") -> None:
    self.local_path(file).write_text(data, encoding)

  def read_bytes(self, file: pth.AnyPathLike) -> bytes:
    return self.cat_bytes(file)

  def write_bytes(self, file: pth.AnyPathLike, data: bytes) -> None:
    self.local_path(file).write_bytes(data)

  def pull(self, from_path: pth.AnyPath,
           to_path: pth.LocalPath) -> pth.LocalPath:
    """ Download / Copy a (remote) file to the local filesystem.
    By default this is just a copy operation on the local filesystem.
    """
    self.assert_is_local()
    return self.local_path(self.copy_file(from_path, to_path))

  def push(self, from_path: pth.LocalPath, to_path: pth.AnyPath) -> pth.AnyPath:
    """ Copy a local file to this (remote) platform.
    By default this is just a copy operation on the local filesystem.
    """
    self.assert_is_local()
    return self.copy_file(from_path, to_path)

  def copy(self, from_path: pth.AnyPath, to_path: pth.AnyPath) -> pth.AnyPath:
    """ Convenience implementation for copying local files and dirs """
    if not self.exists(from_path):
      raise ValueError(f"Cannot copy non-existing source path: {from_path}")
    if self.is_dir(from_path):
      return self.copy_dir(from_path, to_path)
    return self.copy_file(from_path, to_path)

  def copy_dir(self, from_path: pth.AnyPathLike,
               to_path: pth.AnyPathLike) -> pth.AnyPath:
    from_path = self.local_path(from_path)
    to_path = self.local_path(to_path)
    if from_path != to_path:
      self.mkdir(to_path.parent, parents=True, exist_ok=True)
      shutil.copytree(os.fspath(from_path), os.fspath(to_path))
    return to_path

  def copy_file(self, from_path: pth.AnyPathLike,
                to_path: pth.AnyPathLike) -> pth.AnyPath:
    from_path = self.local_path(from_path)
    to_path = self.local_path(to_path)
    if from_path != to_path:
      self.mkdir(to_path.parent, parents=True, exist_ok=True)
      shutil.copy2(os.fspath(from_path), os.fspath(to_path))
    return to_path

  def rm(self,
         path: pth.AnyPathLike,
         dir: bool = False,
         missing_ok: bool = False) -> None:
    """Remove a single file on this platform."""
    path = self.local_path(path)
    if dir:
      if missing_ok and not self.exists(path):
        return
      shutil.rmtree(os.fspath(path))
    else:
      path.unlink(missing_ok)

  def rename(self, src_path: pth.AnyPathLike,
             dst_path: pth.AnyPathLike) -> pth.AnyPath:
    """Remove a single file on this platform."""
    return self.local_path(src_path).rename(dst_path)

  def gzip(self, path: pth.AnyPathLike) -> pth.AnyPath:
    """Compress a file with gzip and return the compressed path."""
    if self.which("gzip"):
      platform_path = self.path(path)
      self.sh("gzip", platform_path)
      return platform_path.with_name(f"{platform_path.name}.gz")
    self.assert_is_local()
    local_path = self.local_path(path)
    dst_path = local_path.with_name(f"{local_path.name}.gz")
    logging.info("Compressing %s with python gzip", local_path)
    with local_path.open("rb") as f_in, gzip.open(dst_path, "wb") as f_out:
      shutil.copyfileobj(f_in, f_out)
    local_path.unlink()
    return dst_path

  def symlink_or_copy(self, src: pth.AnyPathLike,
                      dst: pth.AnyPathLike) -> pth.AnyPath:
    """Windows does not support symlinking without admin support.
    Copy files on windows (see WinPlatform) but symlink everywhere else."""
    assert not self.is_win, "Unsupported operation 'symlink_or_copy' on windows"
    dst_path = self.local_path(dst)
    dst_path.symlink_to(self.path(src))
    return dst_path

  def path(self, path: pth.AnyPathLike) -> pth.AnyPath:
    """"Used to convert any paths and strings to a platform specific
    remote path.
    For instance a remote ADB platform on windows returns posix paths:
      posix_path = adb_remote_platform.patch(windows_path)
    This is used when passing out platform specific paths to remote shell
    commands.
    """
    return self.local_path(path)

  def local_path(self, path: pth.AnyPathLike) -> pth.LocalPath:
    self.assert_is_local()
    return pth.LocalPath(path)

  def absolute(self, path: pth.AnyPathLike) -> pth.AnyPath:
    """Convert an arbitrary path to a platform-specific absolute path"""
    if self.is_local:
      return self.local_path(path).absolute()
    platform_path: pth.AnyPath = self.path(path)
    if platform_path.is_absolute():
      return platform_path
    raise RuntimeError(
        f"Converting relative to absolute paths is not supported on {self}")

  def is_absolute(self, path: pth.AnyPathLike) -> bool:
    path = self.path(path)
    return path.is_absolute()

  def expanduser(self, path: pth.AnyPathLike) -> pth.AnyPath:
    platform_path = self.path(path)
    parts = platform_path.parts
    if parts and parts[0] == "~":
      return self.home().joinpath(*parts[1:])
    return platform_path

  def join_path_list(self,
                     paths: Iterable[pth.AnyPathLike] | pth.AnyPathLike) -> str:
    """Joins paths into a search path string using the platform's pathsep."""
    if isinstance(paths, (str, os.PathLike)):
      paths = (paths,)
    normalized: list[str] = []
    for path in paths:
      if not path:
        continue
      if isinstance(path, str):
        normalized.extend(str(p) for p in self.split_path_list(path))
      else:
        normalized.append(str(self.path(path)))
    return self.pathsep.join(normalized)

  def split_path_list(self, paths_str: str) -> tuple[pth.AnyPath, ...]:
    """Splits a search path string into platform-specific paths."""
    if not paths_str:
      return ()
    return tuple(self.path(p) for p in paths_str.split(self.pathsep) if p)

  def home(self) -> pth.AnyPath:
    self.assert_is_local()
    return pathlib.Path.home()

  def touch(self, path: pth.AnyPathLike) -> None:
    self.local_path(path).touch(exist_ok=True)

  def mkdir(self,
            path: pth.AnyPathLike,
            parents: bool = True,
            exist_ok: bool = True) -> None:
    self.local_path(path).mkdir(parents=parents, exist_ok=exist_ok)

  def mkdtemp(self,
              suffix: str | None = None,
              prefix: str | None = None,
              dir: pth.AnyPathLike | None = None) -> pth.AnyPath:
    self.assert_is_local()
    return self.path(tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir))

  def mktemp(self,
             suffix: str | None = None,
             prefix: str | None = None,
             dir: pth.AnyPathLike | None = None) -> pth.AnyPath:
    self.assert_is_local()
    fd, name = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
    os.close(fd)
    return self.path(name)

  @contextlib.contextmanager
  def NamedTemporaryFile(  # noqa: N802
      self,
      suffix: str | None = None,
      prefix: str | None = None,
      dir: pth.AnyPathLike | None = None) -> Iterator[pth.AnyPath]:
    tmp_file: pth.AnyPath = self.mktemp(suffix, prefix, dir)
    try:
      yield tmp_file
    finally:
      self.rm(tmp_file, missing_ok=True)

  @contextlib.contextmanager
  def TemporaryDirectory(  # noqa: N802
      self,
      suffix: str | None = None,
      prefix: str | None = None,
      dir: pth.AnyPathLike | None = None) -> Iterator[pth.AnyPath]:
    tmp_dir = self.mkdtemp(suffix, prefix, dir)
    try:
      yield tmp_dir
    finally:
      self.rm(tmp_dir, dir=True, missing_ok=True)

  def exists(self, path: pth.AnyPathLike) -> bool:
    return self.local_path(path).exists()

  def is_file(self, path: pth.AnyPathLike) -> bool:
    return self.local_path(path).is_file()

  def is_dir(self, path: pth.AnyPathLike) -> bool:
    return self.local_path(path).is_dir()

  def iterdir(self,
              path: pth.AnyPathLike) -> Generator[pth.AnyPath, None, None]:
    return self.local_path(path).iterdir()

  def glob(self, path: pth.AnyPathLike,
           pattern: str) -> Generator[pth.AnyPath, None, None]:
    # TODO: support remotely
    return self.local_path(path).glob(pattern)

  def chmod(self, path: pth.AnyPathLike, mode: int) -> None:
    self.local_path(path).chmod(mode)

  def file_size(self, path: pth.AnyPathLike) -> int:
    # TODO: support remotely
    return self.local_path(path).stat().st_size

  def last_modified(self, path: pth.AnyPathLike) -> float:
    return self.local_path(path).stat().st_mtime

  def sh_stdout(self,
                *args: CmdArg,
                shell: bool = False,
                quiet: bool = False,
                encoding: str = "utf-8",
                stdin: ProcessIo = None,
                input: bytes | None = None,
                env: Mapping[str, str] | None = None,
                cwd: pth.AnyPath | None = None,
                check: bool = True) -> str:
    """ Platform-dependent wrapper around subprocess.run which captures the
      output as text (use sh_stdout_bytes for bytes).
      See subprocess.run for detailed argument help. """
    result = self.sh_stdout_bytes(
        *args,
        shell=shell,
        quiet=quiet,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        check=check)
    return result.decode(encoding)

  def sh_stdout_bytes(self,
                      *args: CmdArg,
                      shell: bool = False,
                      quiet: bool = False,
                      stdin: ProcessIo = None,
                      input: bytes | None = None,
                      env: Mapping[str, str] | None = None,
                      cwd: pth.AnyPath | None = None,
                      check: bool = True) -> bytes:
    """ Platform-dependent wrapper around subprocess.run which captures the
      output as bytes (use the sh_stdout for text).
      See subprocess.run for detailed argument help. """
    completed_process = self.sh(
        *args,
        shell=shell,
        capture_output=True,
        quiet=quiet,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        check=check)
    return completed_process.stdout

  def validate_shell_args(self, args: TupleCmdArgs, shell: bool) -> None:
    if shell and len(args) != 1:
      raise ValueError("Expected single sh arg with shell=True, "
                       f"but got: {args}")

  def popen(self,
            *args: CmdArg,
            bufsize: int = -1,
            shell: bool = False,
            stdout: ProcessIo = None,
            stderr: ProcessIo = None,
            stdin: ProcessIo = None,
            env: Mapping[str, str] | None = None,
            cwd: pth.AnyPath | None = None,
            encoding: str | None = None,
            quiet: bool = False,
            auto_terminate: bool = True) -> subprocess.Popen:
    """Platform-dependent wrapper around subprocess.Popen.
    See subprocess.run for detailed argument help.
    - auto_terminate: if enabled the Popen's will be tracked and auto-killed
      on platform teardown.
    """
    self.validate_shell_args(args, shell)
    if not quiet:
      logging.debug("SHELL: %s", shlex.join(map(str, args)))
      logging.debug("CWD: %s", pth.LocalPath.cwd())
    proc = self._popen(
        *args,
        bufsize=bufsize,
        shell=shell,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        env=env,
        cwd=cwd,
        encoding=encoding,
        quiet=quiet,
        auto_terminate=auto_terminate)
    if auto_terminate:
      self._popens.add(proc)
    return proc

  def _popen(self,
             *args: CmdArg,
             bufsize: int = -1,
             shell: bool = False,
             stdout: ProcessIo = None,
             stderr: ProcessIo = None,
             stdin: ProcessIo = None,
             env: Mapping[str, str] | None = None,
             cwd: pth.AnyPath | None = None,
             encoding: str | None = None,
             quiet: bool = False,
             auto_terminate: bool = True) -> subprocess.Popen:
    self.assert_is_local()
    del quiet, auto_terminate
    return subprocess.Popen(
        args,
        bufsize=bufsize,
        shell=shell,
        stdin=stdin,
        stderr=stderr,
        stdout=stdout,
        env=env,
        cwd=cwd,
        encoding=encoding)

  def clear_memory_page_cache(self) -> None:
    """Drop clean page caches, dentries, and inodes to free memory."""
    raise NotImplementedError(
        f"clear_memory_page_cache is not implemented on {self}")

  def sh(self,
         *args: CmdArg,
         shell: bool = False,
         capture_output: bool = False,
         stdout: ProcessIo = None,
         stderr: ProcessIo = None,
         stdin: ProcessIo = None,
         input: bytes | None = None,
         env: Mapping[str, str] | None = None,
         cwd: pth.AnyPath | None = None,
         quiet: bool = False,
         check: bool = True) -> subprocess.CompletedProcess:
    """ Platform-dependent wrapper around subprocess.run.
      See subprocess.run for detailed argument help. """
    self.assert_is_local()
    self.validate_shell_args(args, shell)
    if not quiet:
      logging.debug("SHELL: %s", shlex.join(map(str, args)))
      logging.debug("CWD: %s", pth.LocalPath.cwd())
    process = subprocess.run(
        args=args,
        shell=shell,
        stdin=stdin,
        input=input,
        stdout=stdout,
        stderr=stderr,
        env=env,
        capture_output=capture_output,
        check=False,
        cwd=cwd)
    if check and process.returncode != 0:
      raise SubprocessError(self, process)
    return process

  def exec_apple_script(self, script: str, *args: str) -> str:
    del script, args
    raise NotImplementedError("AppleScript is only available on MacOS")

  def log(self, *messages: Any, level: int = 2) -> None:
    message_str = " ".join(map(str, messages))
    if level == 3:
      level = logging.DEBUG
    if level == 2:
      level = logging.INFO
    if level == 1:
      level = logging.WARNING
    if level == 0:
      level = logging.ERROR
    logging.log(level, message_str)

  # TODO(cbruni): split into separate list_system_monitoring and
  # disable_system_monitoring methods
  def check_system_monitoring(self, disable: bool = False) -> bool:
    del disable
    return True

  def download_to(self, url: str, path: pth.AnyPath) -> pth.AnyPath:
    self.assert_is_local()
    logging.debug("DOWNLOAD: %s\n       TO: %s", url, path)
    assert not self.exists(path), f"Download destination {path} exists already."
    url = ObjectParser.url_str(url, schemes=("http", "https"))
    try:
      urllib.request.urlretrieve(url, path)  # noqa: S310
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
      self.rm(path, missing_ok=True)
      raise OSError(f"Could not load {url}") from e
    except BaseException:
      # Caches treat the existence of a file as proof that it is complete,
      # so never leave a partially downloaded file behind.
      self.rm(path, missing_ok=True)
      raise
    assert self.exists(path), (
        f"Downloading {url} failed. Downloaded file {path} doesn't exist.")
    return path

  def download_gcs_file(self, gcs_url: str, local_path: pth.LocalPath) -> None:
    blob: gcloud_blob.Blob = self.prepare_gcs_request(gcs_url)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
      blob.download_to_filename(str(local_path))
      downloaded_size: int = self.host_platform.file_size(local_path)
      if downloaded_size != blob.size:
        raise OSError(f"Size mismatch for {gcs_url}: expected "
                      f"{blob.size} bytes, but got {downloaded_size}.")
    except BaseException:
      # Caches treat the existence of a file as proof that it is complete,
      # so never leave a partially downloaded file behind.
      local_path.unlink(missing_ok=True)
      raise

  def get_gcs_blob(self, gcs_url: str) -> gcloud_blob.Blob:
    parsed = ObjectParser.url(gcs_url, schemes=("gs",))
    bucket_name = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket_name:
      raise ValueError(f"Missing bucket name in URL: {gcs_url}")
    generation: int | None = None
    if parsed.fragment:
      generation = NumberParser.positive_int(parsed.fragment,
                                             f"GCS generation in {gcs_url}")
    client = gcloud_storage.Client(project="")
    bucket = client.bucket(bucket_name)
    return bucket.blob(object_name, generation=generation)

  def check_gcs_file_exists(self, gcs_url: str) -> bool:
    blob = self.get_gcs_blob(gcs_url)
    try:
      return blob.exists()
    except gcloud_exceptions.Forbidden as e:
      raise PermissionError(f"Access denied to {gcs_url}. "
                            "Run 'gcloud auth login' to get access.") from e
    except gcloud_exceptions.NotFound:
      return False

  def prepare_gcs_request(self, gcs_url: str) -> gcloud_blob.Blob:
    blob = self.get_gcs_blob(gcs_url)
    blob.reload()
    return blob

  def concat_files(self,
                   inputs: Iterable[pth.LocalPath],
                   output: pth.LocalPath,
                   prefix: str = "") -> pth.LocalPath:
    self.assert_is_local()
    with output.open("w", encoding="utf-8") as output_f:
      if prefix:
        output_f.write(prefix)
      for input_file in inputs:
        assert input_file.is_file()
        with input_file.open(encoding="utf-8") as input_f:
          shutil.copyfileobj(input_f, output_f)
    return output

  @contextlib.contextmanager
  def wakelock(self) -> Iterator[None]:
    """
    Prevent the system from going to sleep while running active.
    """
    logging.debug("Missing wakelock support on %s", self)
    yield

  def set_all_cpus_power_mode(self, mode: str | None) -> None:
    raise NotImplementedError(
        "'set_all_cpus_power_mode' is only available on Android for now")

  def get_all_cpus_power_modes(self) -> set[str]:
    raise NotImplementedError(
        "'get_all_cpus_power_modes' is only available on Android for now")

  def set_main_display_brightness(self, brightness_level: int) -> None:
    raise NotImplementedError(
        "'set_main_display_brightness' is only available on MacOS for now")

  def get_main_display_brightness(self) -> int:
    raise NotImplementedError(
        "'get_main_display_brightness' is only available on MacOS for now")

  def set_display_refresh_rate(self,
                               refresh_rate: int,
                               retry: int = 3) -> tuple[bool, str]:
    raise NotImplementedError(
        "'set_display_refresh_rate' is only available on MacOS and "
        "Android for now")

  def reset_display_refresh_rate(self) -> None:
    pass

  def check_autobrightness(self) -> bool:
    raise NotImplementedError(
        "'check_autobrightness' is only available on MacOS for now")

  def screenshot(self, result_path: pth.AnyPath) -> None:
    # TODO: support screen coordinates
    raise NotImplementedError("'screenshot' is only available on MacOS for now")

  def display_resolution(self) -> tuple[int, int]:
    raise NotImplementedError(
        "'display_resolution' is only available on Android and ChromeOS for "
        "now")

  def get_ui_element_rect(
      self,
      ui_selector: UiSelectorConfig,
      timeout: dt.timedelta = dt.timedelta(seconds=10),
  ) -> DisplayRectangle:
    raise NotImplementedError(
        f"'get_ui_element_rect' is not supported on {self.name}")

  @contextlib.contextmanager
  def low_power_mode(self) -> Generator[None, Any, None]:
    raise NotImplementedError("'low_power_mode' is only supported on Android")

  @property
  def has_clipboard(self) -> bool:
    return False

  def set_clipboard(self, text: str) -> None:
    raise NotImplementedError(
        f"'set_clipboard' is not supported on {self.name}")

  def user_id(self) -> int:
    self.assert_is_local()
    return os.getuid()
