# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import datetime as dt
import functools
import logging
import math
import os
import re
import shlex
import subprocess
import time
from typing import TYPE_CHECKING, Any, Final, Generator, Iterable, Mapping, \
    Sequence

from mobly.controllers import android_device
from snippet_uiautomator import uiautomator
from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.keyboard_layout import \
    REVERSE_US_KEYBOARD_LAYOUT, W3C_TO_ANDROID_KEYCODE
from crossbench.action_runner.unified_input_action_runner import \
    UnifiedInputActionRunner
from crossbench.benchmarks.loading.point import Point
from crossbench.browsers.chromium.devtools import DevToolsRemoteClient
from crossbench.flags.base import Flags, FlagsData
from crossbench.helper.path_finder import BundletoolFinder
from crossbench.helper.size import Size
from crossbench.parse import NumberParser
from crossbench.plt import axml
from crossbench.plt.arch import MachineArch
from crossbench.plt.base import SubprocessError
from crossbench.plt.bin import Binaries
from crossbench.plt.device_info import DeviceInfo
from crossbench.plt.evemu_platform_mixin import EvemuPlatformMixin
from crossbench.plt.port_manager import PortManager
from crossbench.plt.posix import PosixVersion, RemotePosixPlatform
from crossbench.plt.process_meminfo import ProcessMeminfo
from third_party.protoc import activitymanagerservice_pb2, battery_pb2, \
    enums_pb2, windowmanagerservice_pb2

if TYPE_CHECKING:
  from crossbench.action_runner.virtual_device.virtual_device_config import \
      VirtualDeviceConfig
  from crossbench.action_runner.virtual_device.virtual_device_type import \
      VirtualDeviceType
  from crossbench.device_config import DeviceConfigKeyPath
  from crossbench.plt.base import Platform
  from crossbench.plt.display_info import DisplayInfo
  from crossbench.plt.types import CmdArg, ListCmdArgs, ProcessIo, TupleCmdArgs
  from crossbench.types import JsonDict


class _MoblyDebugFilter(logging.Filter):
  """Filters out overly verbose debug logging from mobly/snippet_uiautomator."""

  def filter(self, record: logging.LogRecord) -> bool:
    if record.levelno <= logging.DEBUG and "mobly" in record.pathname:
      return False
    return True


logging.getLogger().addFilter(_MoblyDebugFilter())


class _CrossbenchUiAutomatorDevice(android_device.AndroidDevice):
  """Custom AndroidDevice that allows bypassing Mobly's auto-root behavior.
  This avoids restarting adbd and dropping all existing adb forward/reverse
  ports.
  """

  def __init__(self, serial: str = "", root_device: bool = True):
    self._root_device = root_device
    super().__init__(serial)

  @override
  def root_adb(self) -> None:
    if not self._root_device:
      return
    super().root_adb()


# Defines the Android permissions to be granted.
# TODO(381985595): make this configurable.
ANDROID_PERMISSIONS: Final = ("POST_NOTIFICATIONS", "CAMERA", "RECORD_AUDIO")

_AAPT_PACKAGE_NAME_RE = re.compile(r"^package: name='([^']+)'")

_WINDOW_BOUNDS_RE: Final[re.Pattern] = re.compile(
    r"mAppBounds=Rect\((?P<left>\d+), (?P<top>\d+) - (?P<right>\d+),"
    r" (?P<bottom>\d+)\)")

_STATUS_BAR_INSETS_RE: Final[re.Pattern] = re.compile(
    r"type=statusBars.*?insetsSize=Insets\{left=\d+, top=(?P<top>\d+)")
_NAV_BAR_INSETS_RE: Final[re.Pattern] = re.compile(
    r"type=navigationBars.*?insetsSize=Insets\{left=\d+, top=\d+,"
    r" right=\d+, bottom=(?P<bottom>\d+)")

# Template for Perfetto config to capture Java heaps.
ANDROID_JAVA_HPROF_PERFETTO_CFG = """buffers {{
  size_kb: {size_kb}
  fill_policy: DISCARD
}}

data_sources {{
  config {{
    name: "android.java_hprof"
    java_hprof_config {{
      process_cmdline: "{process_cmdline}"
      dump_smaps: true
    }}
  }}
}}

data_sources {{
  config {{
    name: "android.packages_list"
  }}
}}

data_source_stop_timeout_ms: {data_source_stop_timeout_ms}
duration_ms: 1000
"""


@dataclasses.dataclass(frozen=True)
class AndroidDeviceInfo(DeviceInfo):
  model: str = ""
  product: str = ""
  transport_id: str = ""

  @property
  def serial_id(self) -> str:
    return self.device_id


def _find_adb_bin(platform: Platform,
                  adb_bin: pth.AnyPath | None = None) -> pth.AnyPath:
  if adb_bin:
    return platform.parse_binary_path(adb_bin)
  if adb_bin := Binaries.ADB.search(platform):
    return adb_bin
  raise ValueError(
      "Could not find adb binary."
      "See https://developer.android.com/tools/adb fore more details.")


def adb_devices(
    platform: Platform,
    adb_bin: pth.AnyPath | None = None) -> dict[str, AndroidDeviceInfo]:
  adb_bin = adb_bin or _find_adb_bin(platform)
  output = platform.sh_stdout(adb_bin, "devices", "-l")
  raw_lines = output.strip().splitlines()[1:]
  result: dict[str, AndroidDeviceInfo] = {}
  for line in raw_lines:
    serial_id, details_str = line.split(" ", maxsplit=1)
    details: dict[str, str] = _parse_adb_device_info(details_str)
    device = AndroidDeviceInfo(
        device_id=serial_id.strip(),
        name=details.get("device", ""),
        model=details.get("model", ""),
        product=details.get("product", ""),
        transport_id=details.get("transport_id", ""))
    result[device.serial_id] = device
  return result


def _parse_adb_device_info(value: str) -> dict[str, str]:
  """
  Convert a line from adb devices -l into a descriptive dictionary.
  `value` is a line of output, typically:
  ABCDEF01234567 device 2-1 product:shiba model:AOSP device:shiba transport_id:3

  Some older versions of adb would not contain the `2-1` part.
  """
  parts = value.strip().split(" ")
  assert parts[0], "device"
  return dict(part.split(":") for part in parts[1:] if ":" in part)


class Adb:

  def __init__(self,
               host_platform: Platform,
               device_identifier: str | None = None,
               adb_bin: pth.AnyPath | None = None,
               bundletool: pth.AnyPath | None = None) -> None:
    self._host_platform: Final[Platform] = host_platform
    self._adb_bin: Final[pth.AnyPath] = _find_adb_bin(host_platform, adb_bin)
    self._bundletool: Final[pth.AnyPath
                            | None] = BundletoolFinder.find_binary(
                                host_platform, bundletool)
    serial_id, device_info = self._start(device_identifier)
    self._serial_id: Final[str] = serial_id
    self._device_info: Final[AndroidDeviceInfo] = device_info

  def _start(
      self,
      device_identifier: str | None = None) -> tuple[str, AndroidDeviceInfo]:
    self.start_server()
    serial_id, device_info = self._find_serial_id(device_identifier)
    logging.debug("ADB Selected device: %s %s", serial_id, device_info)
    assert serial_id, "Missing serial id"
    return serial_id, device_info

  def _find_serial_id(
      self,
      device_identifier: str | None = None) -> tuple[str, AndroidDeviceInfo]:
    devices = self.devices()
    if not devices:
      raise ValueError("adb could not find any attached devices."
                       "Connect your device and use 'adb devices' to list all.")
    if device_identifier is None:
      if len(devices) != 1:
        raise ValueError(
            f"Too many adb devices attached, please specify one of: {devices}")
      device_identifier = next(iter(devices.keys()))
    if not device_identifier:
      raise ValueError(f"Invalid device identifier: {device_identifier!r}")
    if device_identifier in devices:
      return device_identifier, devices[device_identifier]
    matches: list[str] = []
    under_name = device_identifier.replace(" ", "_")
    for key, device in devices.items():
      if device_identifier in device.model or under_name in device.model:
        matches.append(key)
    if not matches:
      raise ValueError(
          f"Could not find adb device matching: '{device_identifier}'")
    if len(matches) > 1:
      raise ValueError(
          f"Found {len(matches)} adb devices matching: '{device_identifier}'.\n"
          f"Choices: {matches}")
    return matches[0], devices[matches[0]]

  def __str__(self) -> str:
    info = f"info='{self._device_info}'"
    if model := self._device_info.model:
      info = f"model={model!r}"
    return f"adb(device_id={self._serial_id!r}, {info})"

  def has_root(self) -> bool:
    return self.shell_stdout("id").startswith("uid=0(root)")

  def path(self, path: pth.AnyPathLike) -> pth.AnyPath:
    return pth.AnyPosixPath(path)

  @property
  def serial_id(self) -> str:
    return self._serial_id

  @property
  def adb_bin(self) -> pth.AnyPath:
    return self._adb_bin

  @functools.cached_property
  def sdk_version(self) -> int:
    return int(self.getprop("ro.build.version.sdk"))

  @functools.cached_property
  def build_version(self) -> int:
    return int(self.getprop("ro.build.version.release"))

  @functools.cached_property
  def build_description(self) -> str:
    return self.getprop("ro.build.description")

  @property
  def device_info(self) -> AndroidDeviceInfo:
    return self._device_info

  def _build_adb_cmd(self,
                     *args: CmdArg,
                     use_serial_id: bool = True) -> ListCmdArgs:
    adb_cmd: ListCmdArgs = [self._adb_bin]
    if use_serial_id:
      adb_cmd.extend(("-s", self._serial_id))
    adb_cmd.extend(args)
    return adb_cmd

  def _adb(self,
           *args: CmdArg,
           shell: bool = False,
           capture_output: bool = False,
           stdout: ProcessIo = None,
           stderr: ProcessIo = None,
           stdin: ProcessIo = None,
           input: bytes | None = None,
           quiet: bool = False,
           check: bool = True,
           use_serial_id: bool = True) -> subprocess.CompletedProcess:
    del shell
    adb_cmd = self._build_adb_cmd(*args, use_serial_id=use_serial_id)
    return self._host_platform.sh(
        *adb_cmd,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        input=input,
        quiet=quiet,
        check=check)

  def _adb_stdout(self,
                  *args: CmdArg,
                  quiet: bool = False,
                  stdin: ProcessIo = None,
                  input: bytes | None = None,
                  encoding: str = "utf-8",
                  use_serial_id: bool = True,
                  check: bool = True) -> str:
    result = self._adb_stdout_bytes(
        *args,
        quiet=quiet,
        stdin=stdin,
        input=input,
        use_serial_id=use_serial_id,
        check=check)
    return result.decode(encoding)

  def _adb_stdout_bytes(self,
                        *args: CmdArg,
                        quiet: bool = False,
                        stdin: ProcessIo = None,
                        input: bytes | None = None,
                        use_serial_id: bool = True,
                        check: bool = True) -> bytes:
    adb_cmd = self._build_adb_cmd(*args, use_serial_id=use_serial_id)
    return self._host_platform.sh_stdout_bytes(
        *adb_cmd, quiet=quiet, check=check, stdin=stdin, input=input)

  def _get_current_user(self) -> str | None:
    try:
      return self.shell_stdout("am", "get-current-user").strip()
    except SubprocessError as e:
      logging.info(
          "get-current-user failed, return code %d, stderr %s, stdout %s",
          e.returncode, e.stderr, e.stdout)
      return None

  def build_shell_cmd(
      self,
      *args: CmdArg,
      shell: bool = False,
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
  ) -> ListCmdArgs:
    if env:
      # TODO: support env with "export FOO=bar;" prefixes
      raise ValueError("ADB shell only supports an empty env for now.")
    if cwd:
      # TODO: support env with "cd foo/bar &&" prefix
      raise ValueError("ADB shell does not support custom cwd")
    self._host_platform.validate_shell_args(args, shell)
    shell_cmd: ListCmdArgs = ["shell"]
    if not shell:
      shell_cmd.append(shlex.join(map(str, args)))
    elif len(args) == 1:
      shell_cmd.append(args[0])
    else:
      raise ValueError("Expected single sh arg with shell=True, "
                       f"but got: {args}")
    adb_shell_cmd = self._build_adb_cmd(*shell_cmd)
    return adb_shell_cmd

  def shell_stdout(self,
                   *args: CmdArg,
                   shell: bool = False,
                   quiet: bool = False,
                   encoding: str = "utf-8",
                   stdin: ProcessIo = None,
                   input: bytes | None = None,
                   env: Mapping[str, str] | None = None,
                   cwd: pth.AnyPath | None = None,
                   check: bool = True) -> str:
    result = self.shell_stdout_bytes(
        *args,
        shell=shell,
        quiet=quiet,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        check=check)
    return result.decode(encoding)

  def shell_stdout_bytes(self,
                         *args: CmdArg,
                         shell: bool = False,
                         quiet: bool = False,
                         stdin: ProcessIo = None,
                         input: bytes | None = None,
                         env: Mapping[str, str] | None = None,
                         cwd: pth.AnyPath | None = None,
                         check: bool = True) -> bytes:
    # -e: choose escape character, or "none"; default '~'
    # -n: don't read from stdin
    # -T: disable pty allocation
    # -t: allocate a pty if on a tty (-tt: force pty allocation)
    # -x: disable remote exit codes and stdout/stderr separation
    shell_cmd = self.build_shell_cmd(*args, shell=shell, env=env, cwd=cwd)
    return self._host_platform.sh_stdout_bytes(
        *shell_cmd, stdin=stdin, input=input, quiet=quiet, check=check)

  def shell(self,
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
    # See shell_stdout for more `adb shell` options.
    shell_cmd = self.build_shell_cmd(*args, shell=shell, env=env, cwd=cwd)
    return self._host_platform.sh(
        *shell_cmd,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        input=input,
        quiet=quiet,
        check=check)

  def start_server(self) -> None:
    self._adb_stdout("start-server", use_serial_id=False)

  def stop_server(self) -> None:
    self.kill_server()

  def kill_server(self) -> None:
    self._adb_stdout("kill-server", use_serial_id=False)

  def root(self) -> None:
    self._adb("root", use_serial_id=False)

  def unroot(self) -> None:
    self._adb("unroot", use_serial_id=False)

  def devices(self) -> dict[str, AndroidDeviceInfo]:
    return adb_devices(self._host_platform, self._adb_bin)

  def forward(self,
              local: int,
              remote: int | str,
              local_protocol: str = "tcp",
              remote_protocol: str = "tcp",
              flags_data: FlagsData = None) -> int:
    cmd_args: list[Any] = ["forward"]
    if flags_data:
      parsed_flags = Flags(flags_data)
      cmd_args.extend(list(parsed_flags))
    cmd_args.append(f"{local_protocol}:{local}")
    cmd_args.append(f"{remote_protocol}:{remote}")
    stdout = self._adb_stdout(*cmd_args).strip()
    if not stdout:
      used_ports = self._adb_stdout("forward", "--list")
      raise ValueError(
          f"Could not setup port-forwarding, ports in use:\n{used_ports}")
    local_port = NumberParser.port_number(stdout, "local_port")
    return local_port

  def forward_remove(self, local: int, protocol: str = "tcp") -> None:
    self._adb("forward", "--remove", f"{protocol}:{local}")

  def reverse(self, remote: int, local: int, protocol: str = "tcp") -> int:
    stdout = self._adb_stdout("reverse", f"{protocol}:{remote}",
                              f"{protocol}:{local}").strip()
    if not stdout:
      used_ports = self._adb_stdout("reverse", "--list")
      raise ValueError("Could not setup reverse port-forwarding, "
                       f"ports in use:\n{used_ports}")
    remote_port = NumberParser.port_number(stdout, "remote_port")
    return remote_port

  def reverse_remove(self, remote: int, protocol: str = "tcp") -> None:
    self._adb("reverse", "--remove", f"{protocol}:{remote}")

  def pull(self, device_src_path: pth.AnyPath,
           local_dest_path: pth.LocalPath) -> None:
    self._adb("pull", self.path(device_src_path), local_dest_path)

  def push(self, local_src_path: pth.LocalPath,
           device_dest_path: pth.AnyPath) -> None:
    self._adb("push", local_src_path, self.path(device_dest_path))

  def cmd(self,
          *args: str,
          quiet: bool = False,
          encoding: str = "utf-8") -> str:
    cmd: ListCmdArgs = ["cmd", *args]
    return self.shell_stdout(*cmd, quiet=quiet, encoding=encoding)

  def dumpsys(self,
              *args: str,
              quiet: bool = False,
              encoding: str = "utf-8") -> str:
    cmd: ListCmdArgs = ["dumpsys", *args]
    return self.shell_stdout(*cmd, quiet=quiet, encoding=encoding)

  def dumpsys_bytes(self, *args: str, quiet: bool = False) -> bytes:
    cmd: ListCmdArgs = ["dumpsys", *args]
    return self.shell_stdout_bytes(*cmd, quiet=quiet)

  def getprop(self,
              *args: str,
              quiet: bool = False,
              encoding: str = "utf-8") -> str:
    cmd: ListCmdArgs = ["getprop", *args]
    return self.shell_stdout(*cmd, quiet=quiet, encoding=encoding).strip()

  def services(self, quiet: bool = False, encoding: str = "utf-8") -> list[str]:
    lines = list(
        self.cmd("-l", quiet=quiet, encoding=encoding).strip().splitlines())
    lines = lines[1:]
    lines.sort()
    return [line.strip() for line in lines]

  def packages(self, quiet: bool = False, encoding: str = "utf-8") -> list[str]:
    # adb shell cmd package list packages
    raw_list = self.cmd(
        "package", "list", "packages", quiet=quiet,
        encoding=encoding).strip().splitlines()
    packages = [package.split(":", maxsplit=2)[1] for package in raw_list]
    packages.sort()
    return packages

  def users(self) -> list[str]:
    try:
      output = self.shell_stdout("pm", "list", "users")
      users = re.findall(r"UserInfo\{([0-9]+):", output)
      if users:
        return users
    except SubprocessError as e:
      logging.debug("pm list users failed: %s", e)

    if current_user := self._get_current_user():
      return [current_user]
    return []

  def force_stop(self, package_name: str) -> None:
    if not package_name:
      raise ValueError("Got empty package name")
    if users := self.users():
      for user in users:
        try:
          self.shell("am", "force-stop", "--user", user, package_name)
        except SubprocessError as e:
          logging.warning("Could not force-stop %s for user %s: %s",
                          package_name, user, e)
    else:
      try:
        self.shell("am", "force-stop", package_name)
      except SubprocessError as e:
        logging.warning("Could not force-stop %s: %s", package_name, e)

  def force_clear(self, package_name: str) -> None:
    if not package_name:
      raise ValueError("Got empty package name")
    users = self.users()
    if not users:
      try:
        self.shell("pm", "clear", package_name)
      except SubprocessError as e:
        logging.warning("Could not clear %s: %s", package_name, e)
    else:
      for user in users:
        try:
          self.shell("pm", "clear", "--user", user, package_name)
        except SubprocessError as e:
          logging.warning("Could not clear %s for user %s: %s", package_name,
                          user, e)

  def is_installed(self, package_name: str) -> bool:
    if not package_name:
      raise ValueError("Got empty package name")
    package_path = self.shell_stdout(
        "pm", "path", package_name, check=False).strip()
    return package_path.startswith("package:")

  def install(self,
              bundle: pth.AnyPath,
              allow_downgrade: bool = False,
              modules: str | None = None) -> None:
    if bundle.suffix == ".apks":
      self.install_apks(bundle, allow_downgrade, modules)
    if bundle.suffix == ".apk":
      self.install_apk(bundle, allow_downgrade)

  def install_apk(self,
                  apk: pth.AnyPath,
                  allow_downgrade: bool = False) -> None:
    if not self._host_platform.exists(apk):
      raise ValueError(f"APK {apk} does not exist {self._host_platform}.")
    args = ["install"]
    if allow_downgrade:
      args.append("-d")
    args.append(str(apk))
    self._adb(*args)

  def install_apks(self,
                   apks: pth.AnyPath,
                   allow_downgrade: bool = False,
                   modules: str | None = None) -> None:
    if not self._host_platform.exists(apks):
      raise ValueError(f"APK {apks} does not exist on {self._host_platform}.")
    if self._bundletool is None:
      raise RuntimeError(
          "Could not find bundletool binary required for install_apks")
    if self._bundletool.suffix == ".jar":
      binary = ["java", "-jar", str(self._bundletool)]
    else:
      binary = [str(self._bundletool)]
    cmd = [
        *binary,
        "install-apks",
        f"--apks={apks}",
        f"--adb={self._adb_bin}",
        f"--device-id={self._serial_id}",
    ]
    if allow_downgrade:
      cmd.append("--allow-downgrade")
    if modules:
      cmd.append(f"--modules={modules}")
    self._host_platform.sh(*cmd)

  def uninstall(self, package_name: str, missing_ok: bool = False) -> None:
    if not package_name:
      raise ValueError("Got empty package name")
    try:
      self._adb("uninstall", package_name)
    except Exception as e:  # noqa: BLE001
      if missing_ok:
        logging.debug("Could not uninstall %s: %s", package_name, e)
      else:
        raise

  def grant_permissions(self, package_name: str) -> None:
    if self.build_version < 13:
      # Notification permission setting is needed for Android 13 and above.
      # https://developer.android.com/develop/ui/views/notifications/notification-permission
      return
    if not package_name:
      raise ValueError("Got empty package name")
    user: str | None = self._get_current_user()
    for perm in ANDROID_PERMISSIONS:
      cmd: ListCmdArgs = ["pm", "grant"]
      if user:
        cmd.extend(["--user", user])
      cmd.extend([package_name, f"android.permission.{perm}"])
      self.shell(*cmd)

  FOCUSED_WINDOW_RE: Final[re.Pattern] = re.compile(
      r"mCurrentFocus=(Window\{.*\})")

  def focused_window(self) -> str | None:
    activity_dump = self.dumpsys("activity", "activities")
    match = re.search(self.FOCUSED_WINDOW_RE, activity_dump)
    if match:
      return match.group(1)
    return None


class AndroidAdbPortManager(PortManager):

  def __init__(self, platform: AndroidAdbPlatform, adb: Adb) -> None:
    super().__init__(platform)
    self._adb: Adb = adb

  @property
  def host_platform(self) -> Platform:
    return self._platform.host_platform

  @override
  def forward(self, local_port: int, remote_port: int) -> int:
    local_port = NumberParser.positive_zero_int(local_port, "local_port")
    remote_port = NumberParser.port_number(remote_port, "remote_port")
    local_port = self._adb.forward(
        local_port, remote_port, local_protocol="tcp", remote_protocol="tcp")
    logging.debug("Forwarded Remote Port: %s:%s <= %s:%s",
                  self.host_platform.name, local_port, self, remote_port)
    return local_port

  @override
  def forward_devtools(self, local_port: int, remote_identifier: str) -> int:
    local_port = NumberParser.positive_zero_int(local_port, "local_port")
    local_port = self._adb.forward(
        local=local_port,
        remote=remote_identifier,
        local_protocol="tcp",
        remote_protocol="localabstract")
    logging.debug("Forwarded DevTools Port: %s:%s <= %s:%s",
                  self.host_platform.name, local_port, self, remote_identifier)
    return local_port

  @override
  def stop_forward(self, local_port: int) -> None:
    self._adb.forward_remove(local_port, protocol="tcp")

  @override
  def reverse_forward(self, remote_port: int, local_port: int) -> int:
    remote_port = NumberParser.positive_zero_int(remote_port, "remote_port")
    local_port = NumberParser.port_number(local_port, "local_port")
    remote_port = self._adb.reverse(remote_port, local_port, protocol="tcp")
    logging.debug("Forwarded Local Port: %s:%s => %s:%s", self.host_platform,
                  local_port, self, remote_port)
    return remote_port

  @override
  def stop_reverse_forward(self, remote_port: int) -> None:
    self._adb.reverse_remove(remote_port, protocol="tcp")


class AndroidVersion(PosixVersion):
  pass


# Namespaces of the 'settings' tool, read and written by device config.
_SETTINGS_NAMESPACES: Final[tuple[str, ...]] = ("global", "secure", "system")


class _AndroidDeviceConfigReader:
  """Reads and parses configuration data from an Android device via ADB."""

  def __init__(self, adb: Adb) -> None:
    self._adb: Final[Adb] = adb

  def device_config(self) -> dict[str, str]:
    """Retrieves namespaced flags from 'cmd device_config list'.

    Returns a flat dictionary mapping 'namespace/key' to value, matching
    the native 'cmd device_config list' output format.
    """
    output = self._adb.shell_stdout("cmd", "device_config", "list")
    return self._parse_key_values(output)

  def getprop(self) -> dict[str, str]:
    """Retrieves Android system properties (getprop)."""
    output = self._adb.shell_stdout("getprop")
    # Format: '[prop.name]: [value]', e.g. '[ro.product.model]: [Pixel 10]'.
    # Parsed into key-value pairs: {"ro.product.model": "Pixel 10"}.
    pattern = re.compile(r"^\[(?P<key>[^\]]+)\]: \[(?P<value>[^\]]*)\]$")
    return {
        match.group("key"): match.group("value")
        for line in output.splitlines()
        if (match := pattern.fullmatch(line.strip()))
    }

  def settings(self) -> dict[str, dict[str, str]]:
    """Retrieves Android global, secure, and system settings."""
    settings_dict: dict[str, dict[str, str]] = {}
    for namespace in _SETTINGS_NAMESPACES:
      output = self._adb.shell_stdout("settings", "list", namespace)
      settings_dict[namespace] = self._parse_key_values(output)
    return settings_dict

  @classmethod
  def _parse_key_values(cls, output: str) -> dict[str, str]:
    """Parses 'key=value' lines into a dictionary."""
    result: dict[str, str] = {}
    for line in output.splitlines():
      # Partition on the first '=' because values may contain '='.
      key, sep, value = line.partition("=")
      if sep and (stripped_key := key.strip()):
        result[stripped_key] = value.strip()
    return result


class AndroidAdbPlatform(EvemuPlatformMixin, RemotePosixPlatform):

  def __init__(
      self,
      host_platform: Platform,
      device_identifier: str | None = None,
      adb: Adb | None = None,
  ) -> None:
    assert not host_platform.is_remote, (
        "adb on remote platform is not supported yet")
    self._adb: Final[Adb] = adb or Adb(host_platform, device_identifier)
    self._devtools_client: DevToolsRemoteClient | None = None
    self._uiautomator_device_instance: (android_device.AndroidDevice
                                        | None) = None
    self._uiautomator_device_root: bool = False
    super().__init__(host_platform)

  def start_devtools(self) -> None:
    if not self._devtools_client:
      self._devtools_client = DevToolsRemoteClient(platform=self)
    self._devtools_client.connect()

  def stop_devtools(self) -> None:
    if self._devtools_client:
      self._devtools_client.disconnect()

  def send_cdp_command(self,
                       method: str,
                       params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not self._devtools_client:
      self.start_devtools()
    assert self._devtools_client is not None, "DevTools client not initialized"
    success, res = self._devtools_client.send_command({
        "id": self._devtools_client.get_next_id(),
        "method": method,
        "params": params or {},
    })
    if not success:
      raise RuntimeError(f"CDP command '{method}' failed: {res}")
    return res

  def switch_to_new_tab(self, url: str = "about:blank") -> None:
    if not self._devtools_client:
      self.start_devtools()
    assert self._devtools_client is not None, "DevTools client not initialized"
    self._devtools_client.switch_to_new_tab(url)

  def _create_port_manager(self) -> PortManager:
    return AndroidAdbPortManager(self, self._adb)

  MIN_UINPUT_SDK_VERSION: Final[int] = 37
  MIN_DROP_CACHES_SDK_VERSION: Final[int] = 31
  _SHIFT_KEYS: Final[frozenset[str]] = frozenset(("ShiftLeft", "ShiftRight"))

  def _uinput_unsupported_msg(self, context: str = "") -> str:
    msg = (f"Virtual device uinput injection is only supported on Android SDK "
           f"{self.MIN_UINPUT_SDK_VERSION}+ (got SDK {self.adb.sdk_version}).")
    if context:
      return f"{msg} {context}"
    return msg

  @override
  def setup_virtual_devices(
      self, virtual_devices: tuple[VirtualDeviceConfig, ...]) -> None:
    if not virtual_devices:
      return
    if self.adb.sdk_version < self.MIN_UINPUT_SDK_VERSION:
      logging.warning(
          self._uinput_unsupported_msg(
              "Falling back to legacy input injection."))
      return
    super().setup_virtual_devices(virtual_devices)

  @override
  def inject_input_events(self, device_name: str,
                          events: Iterable[InputEvent]) -> None:
    if self.adb.sdk_version < self.MIN_UINPUT_SDK_VERSION:
      self._legacy_inject_input_events(events)
      return
    super().inject_input_events(device_name, events)

  def _legacy_inject_input_events(self, events: Iterable[InputEvent]) -> None:
    text_buffer: list[str] = []
    touch_events: list[TouchEvent] = []
    shift_down: bool = False
    total_wait: dt.timedelta = dt.timedelta()
    for event in events:
      if isinstance(event, WaitEvent):
        total_wait += event.duration
      elif isinstance(event, TouchEvent):
        touch_events.append(event)
      elif isinstance(event, (MouseButtonEvent, MouseMoveEvent)):
        raise NotImplementedError(
            self._uinput_unsupported_msg(
                "Mouse input injection is not supported."))
      elif isinstance(event, KeyEvent):
        shift_down, total_wait = self._legacy_inject_key_event(
            event, text_buffer, shift_down, total_wait)
      else:
        raise ValueError(f"Unsupported InputEvent type: {type(event)}")
    if touch_events:
      self._legacy_inject_touch_events(touch_events, total_wait)
    if text_buffer:
      self._legacy_type_text("".join(text_buffer), total_wait)

  def _legacy_inject_key_event(
      self, event: KeyEvent, text_buffer: list[str], shift_down: bool,
      total_wait: dt.timedelta) -> tuple[bool, dt.timedelta]:
    if event.key_code in self._SHIFT_KEYS:
      return event.is_down, total_wait
    if not event.is_down:
      return shift_down, total_wait
    if char := REVERSE_US_KEYBOARD_LAYOUT.get((event.key_code, shift_down)):
      text_buffer.append(char)
      return shift_down, total_wait
    if text_buffer:
      self._legacy_type_text("".join(text_buffer), total_wait)
      text_buffer.clear()
      total_wait = dt.timedelta()
    keycode: str = W3C_TO_ANDROID_KEYCODE.get(event.key_code, event.key_code)
    self.sh("input", "keyevent", keycode)
    return shift_down, total_wait

  def _legacy_inject_touch_events(self, touch_events: Sequence[TouchEvent],
                                  duration: dt.timedelta) -> None:
    start: Point = touch_events[0].position
    end: Point = touch_events[-1].position
    touch_down_count: int = sum(1 for e in touch_events if e.is_down)
    if touch_down_count == 1 and start == end:
      if duration > UnifiedInputActionRunner.DEFAULT_CLICK_DURATION:
        raise NotImplementedError(
            self._uinput_unsupported_msg(
                "Non-zero click duration (long-press) is not supported."))
      self.sh("input", "tap", str(start.x), str(start.y))
      return
    duration_millis: int = round(duration / dt.timedelta(milliseconds=1))
    self.sh("input", "swipe", str(start.x), str(start.y), str(end.x),
            str(end.y), str(duration_millis))

  def _legacy_type_text(self, text: str, duration: dt.timedelta) -> None:
    if duration <= dt.timedelta():
      self._legacy_input_text(text)
      return
    character_delay_s: float = (duration / len(text)).total_seconds()
    character_expected_end_time: float = time.time()
    for char in text:
      character_expected_end_time += character_delay_s
      self._legacy_input_text(char)
      expected_end_delta: float = character_expected_end_time - time.time()
      if expected_end_delta > 0:
        self.sleep(expected_end_delta)

  def _legacy_input_text(self, text: str) -> None:
    self.sh("input", "keyboard", "text", text.replace(" ", "%s"))

  @override
  def _execute_evemu_script(self, device_name: str, script: str) -> None:
    if self.adb.sdk_version < self.MIN_UINPUT_SDK_VERSION:
      raise NotImplementedError(self._uinput_unsupported_msg())
    super()._execute_evemu_script(device_name, script)

  @override
  def _create_default_tmp_dir(self) -> pth.AnyPath:
    return self.path("/data/local/tmp/")

  @override
  def _get_evemu_device_cmd(self,
                            device_type: VirtualDeviceType) -> TupleCmdArgs:
    del device_type
    return ("uinput", "-")

  @property
  @override
  def is_android(self) -> bool:
    return True

  @property
  @override
  def os_name(self) -> str:
    return "android"

  @override
  def clear_memory_page_cache(self) -> None:
    if self.adb.sdk_version < self.MIN_DROP_CACHES_SDK_VERSION:
      logging.error(
          "Cannot clear memory page cache on Android SDK < %d (got SDK %d).",
          self.MIN_DROP_CACHES_SDK_VERSION, self.adb.sdk_version)
      return
    self.sh("sync")
    self.sh("setprop", "perf.drop_caches", "3")

  @functools.cached_property
  @override
  def version_str(self) -> str:
    return str(self.adb.build_version)

  @functools.cached_property
  @override
  def version(self) -> AndroidVersion:
    return AndroidVersion.parse(self.adb.build_description)

  @functools.cached_property
  @override
  def model(self) -> str:
    return self.adb.getprop("ro.product.model")

  @property
  def serial_id(self) -> str:
    return self._adb.serial_id

  @property
  @override
  def key(self) -> tuple[Any, ...]:
    return ("android", self.serial_id)

  def _uiautomator_device(
      self,
      root_device: bool = True,
  ) -> android_device.AndroidDevice:
    if self._uiautomator_device_instance is not None:
      # We are reusing the device except if it's not rooted and root is
      # required.
      if not self._uiautomator_device_root and root_device:
        ad = self._uiautomator_device_instance
        ad.services.unregister_all()
        atexit.unregister(ad.services.unregister_all)
        self._uiautomator_device_instance = None
      else:
        return self._uiautomator_device_instance

    ad = _CrossbenchUiAutomatorDevice(self.serial_id, root_device=root_device)
    atexit.register(ad.services.unregister_all)
    ad.services.register(uiautomator.ANDROID_SERVICE_NAME,
                         uiautomator.UiAutomatorService)
    self._uiautomator_device_instance = ad
    self._uiautomator_device_root = root_device
    return ad

  @contextlib.contextmanager
  def uiautomator_device(
      self,
      root_device: bool = True,
  ) -> Generator[android_device.AndroidDevice, Any, None]:
    # uiautomator requires adb in PATH
    adb_dir = os.path.dirname(self.adb.adb_bin)  # noqa: PTH120
    environ = self.host_platform.environ
    old_path = environ.get("PATH", "")
    if adb_dir:
      if old_path:
        environ["PATH"] = f"{old_path}{os.pathsep}{adb_dir}"
      else:
        environ["PATH"] = adb_dir

    try:
      yield self._uiautomator_device(root_device)
    finally:
      if adb_dir:
        environ["PATH"] = old_path

  @functools.cached_property
  @override
  def cpu(self) -> str:
    variant = self.adb.getprop("dalvik.vm.isa.arm.variant")
    platform = self.adb.getprop("ro.board.platform")
    cpu_str = f"{variant} {platform}"

    # Some android devices do not populate props for CPU info.
    # In that case, fallback to attempting to parse /proc/cpuinfo
    if not variant or not platform:
      return super().cpu

    if num_cores := self.cpu_cores(logical=False):
      cpu_str = f"{cpu_str} {num_cores} cores"
    return cpu_str

  def cpu_usage(self) -> float:
    return math.nan

  @property
  def adb(self) -> Adb:
    return self._adb

  @override
  def set_all_cpus_power_mode(self, mode: str | None) -> None:
    if not mode:
      return
    self.adb.shell(  # noqa: S604
        f"for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; "
        f"do echo {shlex.quote(mode)} > $f; done",
        shell=True,
        stderr=subprocess.DEVNULL)

  @override
  def get_all_cpus_power_modes(self) -> set[str]:
    # Needs shell=True since we're reading multiple files in one go.
    output = self.adb.shell_stdout(  # noqa: S604
        "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor",
        shell=True)
    return set(output.strip().splitlines())

  _MACHINE_ARCH_LOOKUP: Final = {
      "arm64-v8a": MachineArch.ARM_64,
      "armeabi-v7a": MachineArch.ARM_32,
      "x86": MachineArch.IA32,
      "x86_64": MachineArch.X64,
  }

  @functools.cached_property
  @override
  def machine(self) -> MachineArch:
    cpu_abi = self.adb.getprop("ro.product.cpu.abi")
    arch = self._MACHINE_ARCH_LOOKUP.get(cpu_abi, None)
    if not arch:
      raise ValueError(f"Unknown android CPU ABI: {cpu_abi}")
    return arch

  @override
  def get_relative_cpu_speed(self) -> float:
    # TODO figure out
    return 1.0

  def app_path_to_package(self, app_path: pth.AnyPathLike) -> str:
    path = self.host_platform.local_path(app_path)
    if self.host_platform.is_file(path) and path.suffix in (".apk", ".apks"):
      return self._get_package_name(path)
    parts = path.parts
    if len(parts) != 1:
      raise ValueError(f"Invalid android package name: '{path}'")
    package: str = parts[0]
    packages = self.adb.packages()
    if package not in packages:
      raise ValueError(f"Package '{package}' is not installed on {self._adb}")
    return package

  def _get_package_name(self, path: pth.LocalPath) -> str:
    if aapt_bin := Binaries.AAPT.search(self.host_platform):
      return self._get_package_name_with_aapt(aapt_bin, path)
    # Fallback to python-only code
    return axml.manifest_package_name(path)

  def _get_package_name_with_aapt(self, aapt_bin: pth.AnyPath,
                                  path: pth.AnyPath) -> str:
    # aapt dump badging path/to/app.apk | grep package: name=
    output = self.host_platform.sh_stdout(aapt_bin, "dump", "badging", path)
    for line in output.splitlines():
      # package: name='com.android.chrome' ...
      if match := _AAPT_PACKAGE_NAME_RE.search(line):
        return match.group(1)
    raise ValueError(f"Could not find package name in aapt output for {path}")

  @override
  def search_binary(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    app_or_bin_path: pth.AnyPath = self.path(app_or_bin)
    if result_path := self.which(app_or_bin_path):
      return result_path
    if str(app_or_bin) in self.adb.packages():
      return app_or_bin_path
    return None

  @override
  def home(self) -> pth.AnyPath:
    raise RuntimeError("Cannot access home dir on (non-rooted) android device")

  _VERSION_NAME_RE: Final[re.Pattern] = re.compile(
      r"versionName=(?P<version>.+)")

  @override
  def app_version(self, app_or_bin: pth.AnyPathLike) -> str:
    # adb shell dumpsys package com.chrome.canary | grep versionName -C2
    package = self.app_path_to_package(app_or_bin)
    package_info = self.adb.dumpsys("package", str(package))
    match_result = self._VERSION_NAME_RE.search(package_info)
    if match_result is None:
      raise ValueError(
          f"Could not find version for '{package}': {package_info}")
    return match_result.group("version")

  @override
  def process_children(self,
                       parent_pid: int,
                       recursive: bool = False,
                       attrs: list[str] | None = None) -> list[dict[str, Any]]:
    # TODO: implement
    return []

  @override
  def foreground_process(self) -> dict[str, Any] | None:
    # adb shell dumpsys activity activities
    # TODO: implement
    return None

  @override
  def check_autobrightness(self) -> bool:
    # adb shell dumpsys display
    # TODO: implement.
    return True

  _BRIGHTNESS_RE: Final[re.Pattern] = re.compile(
      r"mLatestFloatBrightness=(?P<brightness>[0-9]+\.[0-9]+)")

  @override
  def get_main_display_brightness(self) -> int:
    display_info: str = self.adb.dumpsys("display")
    match_result = self._BRIGHTNESS_RE.search(display_info)
    if match_result is None:
      raise ValueError("Could not parse adb display brightness.")
    return int(float(match_result.group("brightness")) * 100)

  @override
  def build_shell_cmd(
      self,
      *args: CmdArg,
      shell: bool = False,
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
  ) -> ListCmdArgs:
    return self.adb.build_shell_cmd(*args, shell=shell, env=env, cwd=cwd)

  @override
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
    return self.adb.shell(
        *args,
        shell=shell,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        quiet=quiet,
        check=check)

  @override
  def sh_stdout_bytes(self,
                      *args: CmdArg,
                      shell: bool = False,
                      quiet: bool = False,
                      stdin: ProcessIo = None,
                      input: bytes | None = None,
                      env: Mapping[str, str] | None = None,
                      cwd: pth.AnyPath | None = None,
                      check: bool = True) -> bytes:
    return self.adb.shell_stdout_bytes(
        *args,
        shell=shell,
        stdin=stdin,
        input=input,
        env=env,
        cwd=cwd,
        quiet=quiet,
        check=check)

  @override
  def pull(self, from_path: pth.AnyPath,
           to_path: pth.LocalPath) -> pth.LocalPath:
    device_path = self.path(from_path)
    if not self.exists(device_path):
      raise ValueError(f"Source file '{from_path}' does not exist on {self}")
    local_host_path = self.host_path(to_path)
    local_host_path.parent.mkdir(parents=True, exist_ok=True)
    self.adb.pull(device_path, local_host_path)
    return to_path

  @override
  def push(self, from_path: pth.LocalPath, to_path: pth.AnyPath) -> pth.AnyPath:
    to_path = self.path(to_path)
    self.adb.push(self.host_path(from_path), to_path)
    return to_path

  def _mktemp_sh(self,
                 is_dir: bool,
                 suffix: str | None = None,
                 prefix: str | None = None,
                 dir: pth.AnyPathLike | None = None) -> pth.AnyPath:
    temp_path = super()._mktemp_sh(is_dir, prefix=prefix, dir=dir)
    if not suffix:
      return temp_path
    # android's mktemp does not support suffix on some platforms.
    temp_path_with_suffix = temp_path.with_name(f"{temp_path.name}{suffix}")
    self.rename(temp_path, temp_path_with_suffix)
    return temp_path_with_suffix

  @override
  def killall(self, process_name: str) -> None:
    self.sh("pkill", process_name, check=False)

  @override
  def processes(self, attrs: list[str] | None = None) -> list[dict[str, Any]]:
    lines = self.sh_stdout("ps", "-A", "-o", "PID,NAME").splitlines()
    if len(lines) == 1:
      return []

    res: list[dict[str, Any]] = []
    for line in lines[1:]:
      tokens = line.strip().split(maxsplit=1)
      assert len(tokens) == 2, f"Got invalid process tokens: {tokens}"
      res.append({"pid": int(tokens[0]), "name": tokens[1]})
    return res

  _DUMPSYS_TIMEOUT_RE: Final[re.Pattern] = re.compile(
      rb"\*\*\* SERVICE '[^']+' DUMP TIMEOUT \(\d+ms\) EXPIRED \*\*\*")

  @override
  def process_meminfo(
      self,
      process_name: str,
      timeout: dt.timedelta = dt.timedelta(seconds=10),
  ) -> list[ProcessMeminfo]:
    timeout_ms = int(timeout / dt.timedelta(milliseconds=1))
    meminfo_output: bytes = self.adb.dumpsys_bytes("-T", str(timeout_ms),
                                                   "meminfo", "--proto",
                                                   "--package", process_name)
    if self._DUMPSYS_TIMEOUT_RE.search(meminfo_output):
      raise TimeoutError("dumpsys meminfo timed out")
    proto_dump = activitymanagerservice_pb2.MemInfoDumpProto()
    proto_dump.ParseFromString(meminfo_output)
    meminfos: list[ProcessMeminfo] = []
    for app_process in proto_dump.app_processes:
      mem_info = app_process.process_memory.total_heap.mem_info
      meminfos.append(
          ProcessMeminfo(
              pid=app_process.process_memory.pid,
              name=app_process.process_memory.process_name,
              pss_total=mem_info.total_pss_kb,
              rss_total=mem_info.total_rss_kb,
              swap_total=mem_info.dirty_swap_pss_kb or mem_info.dirty_swap_kb))
    return meminfos

  _DUMPSYS_SYSTEM_TOTAL_FREE_RE: Final[re.Pattern] = re.compile(
      br"Total RAM: (?P<total_ram_kb>[0-9][,0-9]*)K.*"
      br"\n Free RAM: [0-9][,0-9]*K \( *"
      br"(?P<cached_pss_kb>[0-9][,0-9]*)K cached pss \+ +"
      br"(?P<cached_kernel_kb>[0-9][,0-9]*)K cached kernel \+ +"
      br"(?P<free_kb>[0-9][,0-9]*)K free\)"
      # Include other footer lines so we don't have to parse the whole output
      # for optional fields.
      br".*$",
      re.DOTALL)

  _DUMPSYS_SYSTEM_DMA_BUF_RE: Final[re.Pattern] = re.compile(
      br"DMA-BUF: +(?P<dma_buf_kb>[0-9][,0-9]*)K \("
      br" +(?P<dma_buf_mapped_kb>[0-9][,0-9]*)K mapped \+"
      br" +(?P<dma_buf_unmapped_kb>[0-9][,0-9]*)K unmapped\)", re.DOTALL)

  def _groupdict_to_system_meminfo(
      self, groupdict: dict[str, bytes]) -> dict[str, float]:
    return {
        key: float(value.replace(b",", b""))
        for [key, value] in groupdict.items()
    }

  @property
  @override
  def system_memory_bytes(self) -> int:
    meminfo = self.system_meminfo()
    if "total_ram_kb" in meminfo:
      return int(meminfo["total_ram_kb"] * Size.KiB)
    raise RuntimeError("Total RAM not found in system_meminfo")

  def system_meminfo(
      self,
      timeout: dt.timedelta = dt.timedelta(seconds=10)) -> dict[str, float]:
    timeout_ms = int(timeout / dt.timedelta(milliseconds=1))
    # TODO: switch to proto parsing if/when DMA-BUF counters are in proto
    # output.
    meminfo_output: bytes = self.adb.dumpsys_bytes("-T", str(timeout_ms),
                                                   "meminfo")
    if self._DUMPSYS_TIMEOUT_RE.search(meminfo_output):
      raise TimeoutError("dumpsys meminfo timed out")

    meminfo: dict[str, float] = {}
    footer_match = self._DUMPSYS_SYSTEM_TOTAL_FREE_RE.search(meminfo_output)
    if not footer_match:
      raise RuntimeError("No 'Total RAM' line found in dumpsys meminfo output")
    meminfo.update(self._groupdict_to_system_meminfo(footer_match.groupdict()))

    dma_buf_match = self._DUMPSYS_SYSTEM_DMA_BUF_RE.search(footer_match[0])
    if dma_buf_match:
      meminfo.update(
          self._groupdict_to_system_meminfo(dma_buf_match.groupdict()))

    return meminfo

  def dump_java_heap(self, identifier: str, label: str,
                     trace_buffer_size_kb: int,
                     timeout: dt.timedelta) -> pth.AnyPath:

    timeout_ms = timeout / dt.timedelta(milliseconds=1)
    cfg_path = self.path(f"/data/misc/perfetto-configs/{label}.txtpb")
    dump_path = self.path(f"/data/misc/perfetto-traces/{label}.trace.pb")
    cfg = ANDROID_JAVA_HPROF_PERFETTO_CFG.format(
        size_kb=trace_buffer_size_kb,
        process_cmdline=identifier,
        data_source_stop_timeout_ms=timeout_ms)
    try:
      self.write_text(cfg_path, cfg)
      self.sh("perfetto", "--config", cfg_path, "--txt", "--out", dump_path)
    except Exception:
      self.rm(dump_path, missing_ok=True)
      raise

    self.rm(cfg_path, missing_ok=True)
    return dump_path

  @functools.lru_cache(maxsize=1)
  @override
  def cpu_details(self) -> dict[str, Any]:
    # TODO: Implement properly (i.e. remove all n/a values)
    return {
        "info": self.cpu,
        "physical cores": self.cpu_cores(logical=False),
        "logical cores": self.cpu_cores(logical=True),
        "usage": "n/a",
        "total usage": "n/a",
        "system load": "n/a",
        "min frequency": "n/a",
        "max frequency": "n/a",
        "current frequency": "n/a",
    }

  @functools.lru_cache(maxsize=1)
  @override
  def system_details(self) -> dict[str, Any]:
    system_details = super().system_details()
    system_details.update({
        "Android": _AndroidDeviceConfigReader(self.adb).getprop(),
    })
    return system_details

  @override
  def device_config(self) -> dict[str, Any]:
    reader = _AndroidDeviceConfigReader(self.adb)
    return {
        "android": {
            "device_config": reader.device_config(),
            "getprop": reader.getprop(),
            "settings": reader.settings(),
        },
    }

  @override
  def set_device_config_value(self, key_path: DeviceConfigKeyPath,
                              value: str | None) -> None:
    tool: tuple[str, ...] = ()
    namespace = key = ""
    match key_path:
      case ("settings", namespace, key) if namespace in _SETTINGS_NAMESPACES:
        tool = ("settings",)
      case ("device_config", flag):
        tool = ("cmd", "device_config")
        namespace, _, key = flag.partition("/")
    if not (tool and namespace and key):
      raise ValueError(f"Cannot set device config {'.'.join(key_path)!r}.")
    if value is None:
      self.adb.shell(*tool, "delete", namespace, key)
    else:
      self.adb.shell(*tool, "put", namespace, key, value)

  @functools.lru_cache(maxsize=1)
  @override
  def python_details(self) -> JsonDict:
    # TODO: Implement properly (i.e. remove all n/a values)
    return {
        "version": "n/a",
        "bits": "n/a",
    }

  @property
  @override
  def is_battery_powered(self) -> bool:
    battery_info_bytes = self.adb.dumpsys_bytes("battery", "--proto")
    battery_info = battery_pb2.BatteryServiceDumpProto()
    battery_info.ParseFromString(battery_info_bytes)
    return (battery_info.plugged ==
            enums_pb2.BatteryPluggedStateEnum.BATTERY_PLUGGED_NONE)

  @override
  def screenshot(self, result_path: pth.AnyPath) -> None:
    self.sh("screencap", "-p", result_path)

  _DUMPSYS_WINDOW_DISPLAYS_RE: Final[re.Pattern] = re.compile(
      r" cur=(?P<x>\d+)x(?P<y>\d+) ")

  @functools.lru_cache(maxsize=1)
  def display_details(self) -> tuple[DisplayInfo, ...]:
    return ({"resolution": self.display_resolution(), "refresh_rate": -1},)

  @override
  def display_resolution(self) -> tuple[int, int]:
    displays_bytes = self.adb.dumpsys_bytes("window", "displays", "--proto")

    displays = windowmanagerservice_pb2.WindowManagerServiceDumpProto()
    displays.ParseFromString(displays_bytes)

    width = (
        displays.root_window_container.window_container.configuration_container
        .full_configuration.window_configuration.max_bounds.right)
    height = (
        displays.root_window_container.window_container.configuration_container
        .full_configuration.window_configuration.max_bounds.bottom)

    return (width, height)

  # TODO(b/553272919): Remove once Android cutover to UnifiedInputActionRunner
  # is finished.
  @override
  def get_window_rect(self, window_name: str) -> DisplayRectangle:
    assert window_name, "window_name is required"
    # Wrap window bounds (left, top - right, bottom) into `DisplayRectangle` for
    # the corresponding window name within the z-order window stack, sourced
    # from `dumpsys window` output.
    # According to Android `Rect` docs, the right and bottom coordinates are
    # exclusive, representing the boundary immediately after the last pixel.
    # https://developer.android.com/reference/android/graphics/Rect
    raw_window_dump = self.sh_stdout("dumpsys", "window", "windows")
    raw_window_config = raw_window_dump[raw_window_dump.find(window_name):]

    match = _WINDOW_BOUNDS_RE.search(raw_window_config)
    if not match:
      raise RuntimeError(f"Could not find window bounds for {window_name}")

    left = int(match["left"])
    top = int(match["top"])
    right = int(match["right"])
    bottom = int(match["bottom"])

    # On Android 15+ (SDK 35+), edge-to-edge enforcement causes mAppBounds to
    # encompass the entire display (top == 0), including the status and nav
    # bars. Adjust the window rect by deducting the system bar insets.
    if top == 0:
      if status_match := _STATUS_BAR_INSETS_RE.search(raw_window_dump):
        top += int(status_match["top"])
      if nav_match := _NAV_BAR_INSETS_RE.search(raw_window_dump):
        bottom -= int(nav_match["bottom"])

    width = right - left
    height = bottom - top

    return DisplayRectangle(Point(left, top), width, height)

  @override
  def set_display_refresh_rate(self,
                               refresh_rate: int,
                               retry: int = 3) -> tuple[bool, str]:
    rate_str = str(float(refresh_rate))
    for _ in range(retry):
      self.sh("settings", "put", "system", "min_refresh_rate", rate_str)
      self.sh("settings", "put", "system", "peak_refresh_rate", rate_str)
      self.sleep(1)
      output = self.adb.dumpsys("display")
      for line in output.splitlines():
        if "mActiveRenderFrameRate" in line and "=" in line:
          val_str = line.split("=", maxsplit=1)[1].strip()
          try:
            if round(float(val_str)) == refresh_rate:
              return True, f"Refresh rate successfully set to {refresh_rate}Hz"
          except ValueError:
            pass
    return False, f"Failed to set display refresh rate to {refresh_rate}Hz"

  @override
  def reset_display_refresh_rate(self) -> None:
    self.sh("settings", "delete", "system", "min_refresh_rate", check=False)
    self.sh("settings", "delete", "system", "peak_refresh_rate", check=False)

  def user_id(self) -> int:
    return NumberParser.any_int(self.sh_stdout("am", "get-current-user"))

  @override
  @contextlib.contextmanager
  def low_power_mode(self) -> Generator[None, Any, None]:
    try:
      self.lock_screen()
      self.doze()
      yield
    finally:
      self.exit_doze()
      self.unlock_screen()

  def doze(self) -> None:
    self.adb.dumpsys("deviceidle", "force-idle")

  def exit_doze(self) -> None:
    self.adb.dumpsys("deviceidle", "unforce")
    self.adb.dumpsys("battery", "reset")

  def lock_screen(self) -> None:
    self.adb.shell("input", "keyevent", "KEYCODE_POWER")

  def unlock_screen(self) -> None:
    # Wake up the device
    self.adb.shell("input", "keyevent", "KEYCODE_WAKEUP")
    # Unlock the device
    self.adb.shell("input", "keyevent", "KEYCODE_MENU")

  @override
  def gpu_vram_used(self) -> dict[str, float]:
    """Queries graphics / unified memory allocation on Android."""
    # Try Qualcomm Adreno sysfs if available
    try:
      page_alloc = self.path("/sys/class/kgsl/kgsl-3d0/page_alloc")
      if self.exists(page_alloc):
        val = int(self.cat(page_alloc).strip())
        if val > 0:
          return {"adreno_gpu": val / Size.MiB}
    except Exception as e:  # noqa: BLE001
      logging.debug("Failed to read kgsl page_alloc: %s", e)

    return super().gpu_vram_used()
