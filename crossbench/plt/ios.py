# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import json
import re
from typing import TYPE_CHECKING, Final

from typing_extensions import override

from crossbench import path as pth
from crossbench.plt.base import Platform
from crossbench.plt.device_info import DeviceInfo
from crossbench.plt.port_manager import PortManager
from crossbench.plt.remote import RemotePlatformMixin
from crossbench.plt.version import PlatformVersion

if TYPE_CHECKING:
  from crossbench.plt.base import CPUFreqInfo
  from crossbench.plt.details import CpuDetails, OsDetails, PythonDetails
  from crossbench.plt.display_info import DisplayInfo
  from crossbench.plt.signals import AnySignals
  from crossbench.plt.types import ProcessInfo

pattern: re.Pattern[str] = re.compile(
    r"(?P<name>[^\(\)]+) \((?P<version>[0-9\.]+)\) (- Connecting )?"
    r"\((?P<udid>[0-9A-Z-]+)\)")


@dataclasses.dataclass(frozen=True)
class IOSDeviceInfo(DeviceInfo):
  version: str = ""
  is_simulator: bool = False

  @property
  def udid(self) -> str:
    return self.device_id

  def __str__(self) -> str:
    return f"{self.name} ({self.version}) ({self.udid})"


def ios_devices(platform: Platform) -> dict[str, IOSDeviceInfo]:
  devices = _devicectl_devices(platform)
  simulators = _simctl_devices(platform)
  assert not (set(devices) & set(simulators)), "Repeated UUIDs."
  return simulators | devices


def _devicectl_devices(platform: Platform) -> dict[str, IOSDeviceInfo]:
  results: dict[str, IOSDeviceInfo] = {}
  with platform.NamedTemporaryFile(suffix=".json") as tmp_file_path:
    platform.sh_stdout("xcrun", "devicectl", "list", "devices",
                       f"--json-output={tmp_file_path}")
    data = json.loads(platform.read_text(tmp_file_path))

  for device_data in data.get("result", {}).get("devices", []):
    if device_data["connectionProperties"]["tunnelState"] == "unavailable":
      continue
    device = IOSDeviceInfo(device_data["hardwareProperties"]["udid"],
                           device_data["deviceProperties"]["name"],
                           device_data["deviceProperties"]["osVersionNumber"])
    assert device.udid not in results, f"Duplicate UDID: {device.udid}"
    results[device.udid] = device
  return results


def _simctl_devices(platform: Platform) -> dict[str, IOSDeviceInfo]:
  """Return IOSDeviceInfo mapping for all booted simulators."""
  args = ("xcrun", "simctl", "list", "devices", "booted", "--json")
  sim_data = json.loads(platform.sh_stdout(*args))
  results: dict[str, IOSDeviceInfo] = {}
  prefix = "com.apple.CoreSimulator.SimRuntime.iOS-"
  for runtime, devices in sim_data.get("devices", {}).items():
    if not runtime.startswith(prefix):
      continue
    version = runtime[len(prefix):].replace("-", ".")
    for device_data in devices:
      # "xcrun simctl list devices booted" guarantees all devices are booted.
      assert device_data.get("state") == "Booted", "Unbooted device"
      device = IOSDeviceInfo(
          device_id=device_data["udid"],
          name=device_data["name"],
          version=version,
          is_simulator=True)
      assert device.udid not in results, f"Duplicate UDID: {device.udid}"
      results[device.udid] = device
  return results


class IOSPortManager(PortManager):

  @override
  def forward(self, local_port: int, remote_port: int) -> int:
    raise NotImplementedError

  @override
  def stop_forward(self, local_port: int) -> None:
    raise NotImplementedError

  @override
  def reverse_forward(self, remote_port: int, local_port: int) -> int:
    raise NotImplementedError

  @override
  def stop_reverse_forward(self, remote_port: int) -> None:
    raise NotImplementedError


# TODO: consider using some abstract MacOS base class.
# TODO: consider using https://github.com/facebook/idb
# TODO: implement mocked methods
# TODO: Follow remove-posix pattern and redirect all shell commands to the
#       host platform.
class IOSPlatform(RemotePlatformMixin, Platform):

  def __init__(self,
               host_platform: Platform,
               device_identifier: str | None = None) -> None:
    assert not host_platform.is_remote, (
        "ios on remote platform is not supported yet")
    super().__init__(host_platform)
    self._device: Final[IOSDeviceInfo] = self._find_ios_device(
        device_identifier)

  def _find_ios_device(self,
                       device_identifier: str | None = None) -> IOSDeviceInfo:
    devices: dict[str, IOSDeviceInfo] = ios_devices(self._host_platform)
    if not devices:
      raise ValueError("No devices attached.")
    if not device_identifier:
      if len(devices) != 1:
        raise ValueError(
            f"Too many devices attached, please specify one of: {devices}")
      return next(iter(devices.values()))
    if device := devices.get(device_identifier):
      return device
    matches: list[IOSDeviceInfo] = []
    for device in devices.values():
      if device_identifier in device.name:
        matches.append(device)
    if not matches:
      raise ValueError(
          f"No matching device for device identifier: {device_identifier}, "
          f"choices are {devices}")
    if len(matches) > 1:
      raise ValueError(
          f"Found {len(matches)} devices matching: '{device_identifier}'.\n"
          f"Choices: {matches}")
    return matches[0]

  @override
  def _create_port_manager(self) -> IOSPortManager:
    return IOSPortManager(self)

  @override
  def _create_default_tmp_dir(self) -> pth.AnyPath:
    # TODO: temp dir not supported on remote iOS platform
    return self.path("/var/tmp")  # noqa: S108

  @override
  def path(self, path: pth.AnyPathLike) -> pth.AnyPath:
    return pth.AnyPosixPath(path)

  @property
  @override
  def signals(self) -> type[AnySignals]:
    # TODO: Can iOS handle signal?
    raise NotImplementedError

  @override
  def uptime(self) -> dt.timedelta:
    # TODO: Can we get actual iOS uptime?
    return dt.timedelta()

  @override
  def _raw_machine_arch(self) -> str:
    return "arm64"

  @property
  def udid(self) -> str:
    return self._device.udid

  @property
  def is_simulator(self) -> bool:
    return self._device.is_simulator

  @property
  @override
  def os_name(self) -> str:
    return "ios"

  @property
  @override
  def model(self) -> str:
    return self._device.name

  @property
  @override
  def cpu(self) -> str:
    return "ios-arm64"

  @property
  @override
  def version(self) -> PlatformVersion:
    return PlatformVersion.parse(self.version_str)

  @property
  @override
  def version_str(self) -> str:
    return self._device.version

  @functools.lru_cache(maxsize=1)
  @override
  def cpu_details(self) -> CpuDetails:
    # TODO: Implement properly (i.e. remove all n/a values)
    return {
        "info": self.cpu,
        "physical_cores": self.cpu_cores(logical=False),
        "logical_cores": self.cpu_cores(logical=True),
        "usage": "n/a",
        "total_usage": "n/a",
        "system_load": "n/a",
        "min_frequency": "n/a",
        "max_frequency": "n/a",
        "current_frequency": "n/a",
    }

  @functools.lru_cache(maxsize=1)
  @override
  def os_details(self) -> OsDetails:
    return {
        "system": "ios",
        "platform": f"ios {self.version_str}",
        "version": self.version_str,
        "release": self.version_str,
    }

  @functools.lru_cache(maxsize=1)
  @override
  def python_details(self) -> PythonDetails:
    return {
        "version": "n/a",
        "bits": "n/a",
    }

  @functools.lru_cache(maxsize=2)
  @override
  def cpu_cores(self, logical: bool) -> int:
    return 0

  @override
  def _cpu_freq(self) -> CPUFreqInfo | None:
    return None

  def get_relative_cpu_speed(self) -> float:
    return 1.0

  @override
  def display_details(self) -> tuple[DisplayInfo, ...]:
    return ()

  @property
  @override
  def is_ios(self) -> bool:
    return True

  def _is_safari_app(self, app_or_bin: pth.AnyPathLike) -> bool:
    return "Safari.app" in pth.AnyPath(app_or_bin).parts

  @override
  def search_binary(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    resolved_app_or_bin: pth.AnyPath = self.expanduser(app_or_bin)
    if not resolved_app_or_bin.parts:
      raise ValueError("Got empty path")
    if self._is_safari_app(resolved_app_or_bin):
      return resolved_app_or_bin
    raise ValueError(
        f"Safari is the only supported app on ios, requested {app_or_bin}")

  @override
  def is_file(self, path: pth.AnyPathLike) -> bool:
    if self._is_safari_app(path):
      return True
    raise ValueError(
        f"Safari is the only supported app on ios, requested {path}")

  @override
  def app_version(self, app_or_bin: pth.AnyPathLike) -> str:
    if self._is_safari_app(app_or_bin):
      return self.version_str
    raise ValueError(
        "Safari is the only supported app on ios, requested {app_or_bin}")

  @override
  def process_children(self,
                       parent_pid: int,
                       recursive: bool = False,
                       attrs: list[str] | None = None) -> list[ProcessInfo]:
    return []
