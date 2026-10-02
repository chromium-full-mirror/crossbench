# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import functools
import logging
import os
import shutil
from typing import TYPE_CHECKING

from typing_extensions import override

if TYPE_CHECKING:
  from crossbench.plt.types import TupleCmdArgs

from crossbench import path as pth
from crossbench.helper.size import Size
from crossbench.plt.base import Platform
from crossbench.plt.signals import WinSignals
from crossbench.plt.version import PlatformVersion


class WinVersion(PlatformVersion):
  pass


class WinPlatform(Platform):
  # TODO: support remote platforms
  SEARCH_PATHS = (
      pth.LocalPath("."),
      pth.LocalPath(os.path.expandvars("%ProgramFiles%")),
      pth.LocalPath(os.path.expandvars("%ProgramFiles(x86)%")),
      pth.LocalPath(os.path.expandvars("%APPDATA%")),
      pth.LocalPath(os.path.expandvars("%LOCALAPPDATA%")),
  )

  @property
  def signals(self) -> type[WinSignals]:
    return WinSignals

  @property
  @override
  def is_win(self) -> bool:
    return True

  @property
  @override
  def os_name(self) -> str:
    return "win"

  @property
  @override
  def model(self) -> str:
    # TODO: implement
    return ""

  def cmd_stdout(self, *args, **kwargs) -> str:
    cmd = ["cmd", "/c", *args]
    return self.sh_stdout(*cmd, **kwargs)

  def powershell_stdout(self, *args, **kwargs) -> str:
    cmd = ["powershell", "-c", *args]
    return self.sh_stdout(*cmd, **kwargs)

  @functools.cached_property
  @override
  def version_str(self) -> str:
    return self.cmd_stdout("ver").strip()

  @functools.cached_property
  @override
  def version(self) -> WinVersion:
    return WinVersion.parse(self.version_str)

  @functools.cached_property
  @override
  def cpu(self) -> str:
    return self.powershell_stdout(
        "Get-CIMInstance -query 'select * from Win32_Processor' | ft Name",
    ).strip().splitlines()[2].strip()

  @override
  def killall(self, process_name: str) -> None:
    if not process_name.lower().endswith(".exe"):
      process_name += ".exe"
    # https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill
    self.sh("taskkill", "/F", "/IM", process_name, check=False)

  @override
  def _raw_machine_arch(self) -> str:
    self.assert_is_local()
    # The method in base class doesn't always give the correct answer,
    # because it uses py_platform.machine, which give the architecture of
    # the Python binary. It is possible to run x64 Python on ARM Windows.
    cpu_caption = self.powershell_stdout(
        "Get-CIMInstance -query 'select * from Win32_Processor' | ft Caption",
    ).strip().splitlines()[2].strip().lower()
    if cpu_caption.startswith("arm"):
      return "arm64" if "64-bit" in cpu_caption else "arm"
    return super()._raw_machine_arch()

  @override
  def uptime(self) -> dt.timedelta:
    """Parse powershell last boot time time-span into a timedelta object.
    Example Output:
    Days              : 14
    Hours             : 2
    Minutes           : 19
    Seconds           : 54
    Milliseconds      : 978
    Ticks             : 12179949789862
    TotalDays         : 14.0971641086366
    TotalHours        : 338.331938607278
    TotalMinutes      : 20299.9163164367
    TotalSeconds      : 1217994.9789862
    TotalMilliseconds : 1217994978.9862
    """
    uptime_output = self.powershell_stdout(
        "(New-TimeSpan -Start ("
        "Get-CimInstance Win32_OperatingSystem).LastBootUpTime"
        ")")
    results = {}
    for line in uptime_output.splitlines():
      line = line.strip()
      if not line:
        continue
      unit, value = line.split(":", maxsplit=1)
      unit = unit.strip()
      value_f: float = float(value)
      results[unit] = value_f
    return dt.timedelta(
        days=results["Days"],
        hours=results["Hours"],
        minutes=results["Minutes"],
        seconds=results["Seconds"],
        milliseconds=results["Milliseconds"])

  @override
  def search_binary(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    self.assert_is_local()
    app_or_bin_path: pth.AnyPath = self.path(app_or_bin)
    if not app_or_bin_path.parts:
      raise ValueError("Got empty path")
    if app_or_bin_path.suffix.lower() not in (".exe", ".bat"):
      raise ValueError("Expected executable path with '.exe' or '.bat' suffix, "
                       f"but got: {app_or_bin_path.name!r}")
    if result_path := self.which(app_or_bin):
      if not self.exists(result_path):
        raise RuntimeError(f"Resolved binary {result_path} does not exist.")
      return result_path
    return self._search_binary_in_search_path(app_or_bin_path)

  @override
  def app_version(self, app_or_bin: pth.AnyPathLike) -> str:
    app_or_bin = self.path(app_or_bin)
    if not self.exists(app_or_bin):
      raise ValueError(f"Binary {app_or_bin} does not exist.")
    if version := self.sh_stdout(
        "powershell", "-command",
        f"(Get-Item '{app_or_bin}').VersionInfo.ProductVersion").strip():
      name = self.sh_stdout(
          "powershell", "-command",
          f"(Get-Item '{app_or_bin}').VersionInfo.ProductName").strip()
      return f"{name} {version}"
    try:
      # Fall back to command-line tools.
      if version := self.sh_stdout(app_or_bin, "--version").strip():
        return version
    except Exception as e:  # noqa: BLE001
      logging.debug("Failed to extract binary tool version: %s", e)
    raise ValueError(f"Could not extract version for {app_or_bin}")

  @override
  def symlink_or_copy(self, src: pth.AnyPathLike,
                      dst: pth.AnyPathLike) -> pth.AnyPath:
    """Windows does not support symlinking without admin support.
    Copy files on windows but symlink everywhere else (see base Platform)."""
    self.assert_is_local()
    dst_path = self.path(dst)
    shutil.copy(os.fspath(self.path(src)), os.fspath(dst_path))
    return dst_path

  @functools.cached_property
  def _clipboard_bin(self) -> TupleCmdArgs | None:
    if path := self.which("clip"):
      return (path,)
    return None

  @property
  @override
  def has_clipboard(self) -> bool:
    return self._clipboard_bin is not None

  @override
  def set_clipboard(self, text: str) -> None:
    assert self._clipboard_bin
    self.sh(*self._clipboard_bin, input=text.encode("utf-8"), check=True)

  @override
  def gpu_vram_used(self) -> dict[str, float]:
    # 1. Try nvidia-smi
    nvidia_smi = self.which("nvidia-smi")
    if not nvidia_smi:
      default_path = self.path(
          r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
      if self.exists(default_path):
        nvidia_smi = default_path

    if nvidia_smi:
      out = self.sh_stdout(
          nvidia_smi,
          "--query-gpu=memory.used",
          "--format=csv,noheader,nounits",
          check=False)
      vram_dict: dict[str, float] = {}
      for i, line in enumerate(out.splitlines()):
        if line := line.strip():
          with contextlib.suppress(ValueError):
            vram_dict[f"gpu_{i}"] = float(line.split()[0])
      if vram_dict:
        return vram_dict

    # 2. Try WMIC / Performance Counters (DedicatedUsage + SharedUsage)
    out = self.sh_stdout(
        "wmic",
        "path",
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory",
        "get",
        "DedicatedUsage,SharedUsage",
        check=False)
    total_bytes = 0
    for line in out.splitlines():
      line = line.strip()
      if not line or "DedicatedUsage" in line:
        continue
      for part in line.split():
        if part.isdigit():
          total_bytes += int(part)
    if total_bytes > 0:
      return {"gpu_wmic": total_bytes / Size.MiB}

    return super().gpu_vram_used()
