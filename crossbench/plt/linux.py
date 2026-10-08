# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import functools
import logging
import os
import re
from typing import TYPE_CHECKING, Any, ClassVar, Final, Iterator

from typing_extensions import override

from crossbench import path as pth
from crossbench.helper.size import Size
from crossbench.parse import NumberParser
from crossbench.plt.base import SubprocessError
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.posix import PosixPlatform, RemotePosixPlatform
from crossbench.plt.process_meminfo import ProcessMeminfo
from crossbench.plt.signals import LinuxSignals

if TYPE_CHECKING:
  from crossbench.plt.display_info import DisplayInfo
  from crossbench.plt.types import TupleCmdArgs

SCRIPTS_DIR: Final = pth.LocalPath(__file__).parent / "remote_scripts"
PERF_EVENT_PARANOID_PATH: Final = pth.AnyPosixPath(
    "/proc/sys/kernel/perf_event_paranoid")


@dataclasses.dataclass
class XrandrDisplayInfo:
  RESOLUTION_RE: ClassVar[re.Pattern] = re.compile(
      r"(?P<resX>[0-9]+)x(?P<resY>[0-9]+)")
  REFRESH_RATE_RE: ClassVar[re.Pattern] = re.compile(r"(?P<freq>[0-9.]+)\*")

  header: str
  resolutions: list[str] = dataclasses.field(default_factory=list)

  def is_connected(self) -> bool:
    return "disconnected" not in self.header

  def display_resolution(self) -> DisplayResolution | None:
    if match := self.RESOLUTION_RE.search(self.header):
      return DisplayResolution(
          NumberParser.positive_int(match.group("resX")),
          NumberParser.positive_int(match.group("resY")),
      )
    return None

  def refresh_rate(self) -> float:
    for resolution in self.resolutions:
      # The current refresh ret is marked with a `*`:
      if match := self.REFRESH_RATE_RE.search(resolution):
        return NumberParser.positive_float(match.group("freq"))
    return -1


def parse_display_xrandr(xrandr_str: str) -> Iterator[DisplayInfo]:
  """ Parse xrandr output:
  Screen 0: minimum 64 x 64, current 1728 x 946, maximum 32767 x 32767
  DUMMY0 connected primary 1728x946+0+0 456mm x 249mm
    1024x768      60.00
    1024x576      59.90
    CRD_78       120.00*
    ...
  DUMMY1 disconnected
    1600x1200_60  60.00
    ...
  """  # noqa: W291
  display_infos: list[XrandrDisplayInfo] = []
  current_info: XrandrDisplayInfo | None = None
  # Group display info and resolution entries:
  for line in xrandr_str.splitlines():
    if "connected" in line:
      current_info = XrandrDisplayInfo(line)
      display_infos.append(current_info)
    if current_info and line.startswith(" "):
      current_info.resolutions.append(line.strip())
  # Filter by connected displays and extract the resolution.
  for display_info in display_infos:
    if not display_info.is_connected():
      continue
    if resolution := display_info.display_resolution():
      yield {
          "resolution": resolution,
          "refresh_rate": display_info.refresh_rate(),
      }


class LinuxPlatform(PosixPlatform):
  SEARCH_PATHS: tuple[pth.AnyPath, ...] = (
      pth.AnyPosixPath("."),
      pth.AnyPosixPath("/usr/local/sbin"),
      pth.AnyPosixPath("/usr/local/bin"),
      pth.AnyPosixPath("/usr/sbin"),
      pth.AnyPosixPath("/usr/bin"),
      pth.AnyPosixPath("/sbin"),
      pth.AnyPosixPath("/bin"),
      pth.AnyPosixPath("/opt/google"),
  )

  @property
  @override
  def is_linux(self) -> bool:
    return True

  @property
  @override
  def os_name(self) -> str:
    return "linux"

  @property
  def signals(self) -> type[LinuxSignals]:
    return LinuxSignals

  def check_system_monitoring(self, disable: bool = False) -> bool:
    del disable
    return True

  @functools.cached_property
  @override
  def model(self) -> str:
    try:
      id_dir = self.path("/sys/devices/virtual/dmi/id")
      vendor = self.cat(id_dir / "sys_vendor").strip()
      product = self.cat(id_dir / "product_name").strip()
      return f"{vendor} {product}"
    except (FileNotFoundError, SubprocessError):
      return "UNKNOWN"

  @property
  @override
  def has_display(self) -> bool:
    return "DISPLAY" in os.environ

  @property
  @override
  def is_remote_desktop(self) -> bool:
    script = self.path("/opt/google/chrome-remote-desktop/is-remoting-session")
    if self.exists(script):
      return self.sh(script, check=False, quiet=True).returncode == 0
    return False

  @property
  @override
  def is_battery_powered(self) -> bool:
    if self.is_local:
      return super().is_battery_powered
    if on_ac_power := self.which("on_ac_power"):
      return self.sh(on_ac_power, check=False).returncode == 1
    return False

  @functools.lru_cache(maxsize=1)
  @override
  def system_details(self) -> dict[str, Any]:
    details = super().system_details()
    for info_bin in ("lscpu", "inxi"):
      if info_bin_path := self.which(info_bin):
        details[info_bin] = self.sh_stdout(info_bin_path)
    return details

  @property
  @override
  def system_memory_bytes(self) -> int:
    if self.is_local:
      return super().system_memory_bytes
    output = self.sh_stdout("grep", "MemTotal", "/proc/meminfo")
    match = re.search(r"MemTotal:\s+(\d+)\s+kB", output)
    if match:
      return int(match.group(1)) * Size.KiB
    raise RuntimeError("Could not find MemTotal in /proc/meminfo")

  def search_binary(self, app_or_bin: pth.AnyPathLike) -> pth.AnyPath | None:
    app_or_bin_path: pth.AnyPath = self.path(app_or_bin)
    if result_path := self.which(app_or_bin_path):
      if not self.exists(result_path):
        raise RuntimeError(f"Resolved binary {result_path} does not exist.")
      return result_path
    return self._search_binary_in_search_path(app_or_bin_path)

  def screenshot(self, result_path: pth.AnyPath) -> None:
    # TODO: maybe use imagemagick's 'import' as more portable alternative
    if not self.has_display:
      logging.warning("DISPLAY environment variable is not set. "
                      "gnome-screenshot may fail or hang.")
    self.sh("gnome-screenshot", "--file", result_path)

  @functools.lru_cache(maxsize=1)
  def display_details(self) -> tuple[DisplayInfo, ...]:
    if not self.has_display:
      return ()
    if xrandr_str := self.sh_stdout("xrandr"):
      return tuple(parse_display_xrandr(xrandr_str))
    return ()

  _MEMINFO_SCRIPT_PROCESS_PATTERN: Final[re.Pattern] = re.compile(
      r"==== process (\d+) ====")
  _MEMINFO_SCRIPT_SMAPS_HEADER_PATTERN: Final[re.Pattern] = re.compile(
      r"==== smaps_rollup ====")
  _SMAPS_ROLLUP_PATTERN: Final[re.Pattern] = re.compile(
      r".*Rss:\s+(?P<rss_total>\d+) kB.*"
      r"Pss:\s+(?P<pss_total>\d+) kB.*"
      r"Swap:\s+(?P<swap_total>\d+)",
      flags=re.DOTALL)

  @override
  def process_meminfo(
      self,
      process_name: str,
      timeout: dt.timedelta = dt.timedelta(seconds=10),
  ) -> list[ProcessMeminfo]:
    del timeout

    script = (SCRIPTS_DIR / "meminfo.sh").read_text()

    with self.NamedTemporaryFile() as script_file:
      self.write_text(script_file, script)
      # Script outputs the following format repeated per process:
      # ==== process <pid> ====
      # <proc/cmdline>
      # ==== smaps_rollup ====
      # <proc/smaps_rollup>
      output = self.sh_stdout("bash", str(script_file), process_name)
      processes = self._MEMINFO_SCRIPT_PROCESS_PATTERN.split(output)[1:]
      # processes even indices are pids, the odd indices after is the output for
      # that pid.
      meminfos: list[ProcessMeminfo] = []
      for i in range(0, len(processes), 2):
        pid = int(processes[i])
        [
            cmdline,
            smaps_rollup,
        ] = self._MEMINFO_SCRIPT_SMAPS_HEADER_PATTERN.split(processes[i + 1])
        match = self._SMAPS_ROLLUP_PATTERN.search(smaps_rollup)
        assert match
        meminfos.append(
            ProcessMeminfo(
                pid=pid,
                name=cmdline.strip(),
                pss_total=int(match["pss_total"]),
                rss_total=int(match["rss_total"]),
                swap_total=int(match["swap_total"])))
      return meminfos

  @override
  def gpu_vram_used(self) -> dict[str, float]:
    # 1. Try nvidia-smi
    if nvidia_smi := self.which("nvidia-smi"):
      try:
        out = self.sh_stdout(nvidia_smi, "--query-gpu=memory.used",
                             "--format=csv,noheader,nounits")
        vram_dict: dict[str, float] = {}
        for i, line in enumerate(out.splitlines()):
          if line := line.strip():
            vram_dict[f"gpu_{i}"] = float(line.split()[0])
        if vram_dict:
          return vram_dict
      except (SubprocessError, OSError, ValueError) as e:
        logging.debug("Failed to query nvidia-smi: %s", e)

    # 2. Try AMD DRM sysfs (both VRAM and GTT for APUs)
    try:
      total_bytes = 0
      for drm_path in self.glob(self.path("/sys/class/drm"), "card*/device"):
        vram_file = drm_path / "mem_info_vram_used"
        gtt_file = drm_path / "mem_info_gtt_used"
        if self.exists(vram_file):
          with contextlib.suppress(OSError, ValueError):
            total_bytes += int(self.cat(vram_file).strip())
        if self.exists(gtt_file):
          with contextlib.suppress(OSError, ValueError):
            total_bytes += int(self.cat(gtt_file).strip())
      if total_bytes > 0:
        return {"amd_gpu": total_bytes / Size.MiB}
    except OSError as e:
      logging.debug("Failed to query AMD sysfs: %s", e)

    # 3. Try Intel DRM sysfs (lmem_used_bytes for Intel Arc dGPU)
    try:
      total_lmem = 0
      for lmem_file in self.glob(
          self.path("/sys/class/drm"), "card*/lmem_used_bytes"):
        with contextlib.suppress(OSError, ValueError):
          total_lmem += int(self.cat(lmem_file).strip())
      if total_lmem > 0:
        return {"intel_gpu": total_lmem / Size.MiB}
    except OSError as e:
      logging.debug("Failed to query Intel sysfs: %s", e)

    return super().gpu_vram_used()

  @functools.cached_property
  def _clipboard_bin(self) -> TupleCmdArgs | None:
    if path := self.which("xclip"):
      return (path, "-selection", "clipboard")
    if path := self.which("wl-copy"):
      return (path,)
    if path := self.which("xsel"):
      return (path, "--clipboard", "--input")
    return None

  @property
  @override
  def has_clipboard(self) -> bool:
    return self._clipboard_bin is not None

  @override
  def set_clipboard(self, text: str) -> None:
    assert self._clipboard_bin
    self.sh(*self._clipboard_bin, input=text.encode("utf-8"), check=True)

  def perf_event_paranoid(self) -> int | None:
    if not self.is_file(PERF_EVENT_PARANOID_PATH):
      return None
    return NumberParser.any_int(
        self.cat(PERF_EVENT_PARANOID_PATH).strip(),
        "kernel.perf_event_paranoid")


class RemoteLinuxPlatform(RemotePosixPlatform, LinuxPlatform):
  pass
