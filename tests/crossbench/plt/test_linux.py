# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import gzip
import pathlib
import textwrap
from unittest import mock

from pyfakefs.fake_filesystem import OSType
from typing_extensions import override

from crossbench import path as pth
from crossbench.helper.version import VersionParseError
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.linux import PERF_EVENT_PARANOID_PATH, SCRIPTS_DIR, \
    LinuxPlatform, parse_display_xrandr
from crossbench.plt.posix import PosixVersion
from crossbench.plt.process_meminfo import ProcessMeminfo
from tests import test_helper
from tests.crossbench.mock_helper import LinuxMockPlatform, MockPlatform, \
    RemoteLinuxMockPlatform, ShResult
from tests.crossbench.plt.helper import BaseLocalMockPlatformTestMixin, \
    BasePosixMockPlatformTestCase, PlatformClipboardTestCase

NOW_EPOCH = dt.datetime.now()


class _LinuxMockPlatformTestCase(BasePosixMockPlatformTestCase):
  platform: LinuxMockPlatform

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.os = OSType.LINUX

  @override
  def setup_host_platform(self) -> LinuxMockPlatform:
    return LinuxMockPlatform()

  def test_name(self):
    self.assertEqual(self.platform.name, "mock.linux")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "mock.linux")

  def test_is_linux(self):
    self.assertTrue(self.platform.is_linux)

  def test_clear_memory_page_cache(self):
    self.expect_sh("sync")
    self.expect_sh("tee", "/proc/sys/vm/drop_caches")
    with mock.patch.object(
        self.platform, "sh", wraps=self.platform.sh) as mock_sh:
      self.platform.clear_memory_page_cache()
    mock_sh.assert_has_calls([
        mock.call("sync"),
        mock.call("tee", "/proc/sys/vm/drop_caches", input=b"3\n"),
    ])

  def test_version(self):
    self.platform.mock_version_str = None
    self.expect_sh("uname", "-r", result="5.4.0-104-generic")
    self.assertEqual(self.platform.version_str, "5.4.0-104-generic")

    version = self.platform.version
    self.assertSequenceEqual(version.parts, (5, 4, 0))
    self.assertEqual(version.version_str, "5.4.0-104-generic")

  @mock.patch("psutil.cpu_count")
  def test_cpu_cores(self, mock_cpu_count):
    mock_cpu_count.return_value = 12
    self.assertEqual(self.platform.cpu_cores(logical=True), 12)
    mock_cpu_count.assert_called_once()

    mock_cpu_count.return_value = 6
    self.assertEqual(self.platform.cpu_cores(logical=False), 6)
    self.assertEqual(mock_cpu_count.call_count, 2)

  def test_parse_display_xrandr(self):
    xrandr_output = textwrap.dedent("""
      Screen 0: minimum 64 x 64, current 1728 x 946, maximum 32767 x 32767
      DUMMY0 connected primary 1728x946+0+0 456mm x 249mm
        1024x768      60.00  
        800x600       60.32    56.25  
        640x480       59.94  
        1600x1200_60  60.00  
        1600x1200_120 120.00  
        CRD_78       120.00*+
      DUMMY1 disconnected
        5120x1440_120 120.00  
        2160x3840_120 120.00  
      """)  # noqa: W291
    parsed = tuple(parse_display_xrandr(xrandr_output))
    self.assertEqual(len(parsed), 1)
    self.assertDictEqual(parsed[0], {
        "resolution": DisplayResolution(1728, 946),
        "refresh_rate": 120.0,
    })

  def test_meminfo_no_proc(self):
    path = SCRIPTS_DIR / "meminfo.sh"
    self.fs.create_file(path, contents="meminfo")

    self.platform.sh_results = [ShResult()]
    meminfo = LinuxPlatform.process_meminfo(self.platform, "some_process")
    self.assertEqual(len(meminfo), 0)

  def test_platform_version_cls(self):
    version = PosixVersion.parse("5.4.0-104-generic")
    self.assertSequenceEqual(version.parts, (5, 4, 0))
    self.assertEqual(version.version_str, "5.4.0-104-generic")
    with self.assertRaises(VersionParseError):
      PosixVersion.parse("foo")

  _MEMINFO_SCRIPT_OUTPUT = """
==== process 926961 ====
/usr/bin/some_process -a
==== smaps_rollup ====
00008000-7ffd0f5fe000 ---p 00000000 00:00 0 [rollup]
Rss:               80364 kB
Pss:               17815 kB
Pss_Dirty:          8715 kB
Swap:                  0 kB
SwapPss:               0 kB
==== process 930293 ====
/usr/bin/some_process -b
==== smaps_rollup ====
85800000000-7ffd0f5fe000 ---p 00000000 00:00 0 [rollup]
Rss:               44860 kB
Pss:                5074 kB
Private_Hugetlb:       0 kB
Swap:                  0 kB
Locked:                0 kB
==== process 930304 ====
/usr/bin/some_process -c
==== smaps_rollup ====
Rss:                2680 kB
Pss:                 521 kB
Swap:                400 kB
"""

  def test_meminfo(self):
    path = SCRIPTS_DIR / "meminfo.sh"
    self.fs.create_file(path, contents="meminfo")

    self.platform.sh_results = [ShResult(self._MEMINFO_SCRIPT_OUTPUT)]
    meminfo = LinuxPlatform.process_meminfo(self.platform, "some_process")
    self.assertSequenceEqual(meminfo, [
        ProcessMeminfo(926961, "/usr/bin/some_process -a", 17815, 80364, 0),
        ProcessMeminfo(930293, "/usr/bin/some_process -b", 5074, 44860, 0),
        ProcessMeminfo(930304, "/usr/bin/some_process -c", 521, 2680, 400),
    ])

  def test_gzip(self):
    test_file = self.platform.path("/tmp/test.txt")
    self.fs.create_file(test_file, contents="hello gzip")
    with mock.patch.object(
        self.platform,
        "which",
        return_value=self.platform.path("/usr/bin/gzip")):
      self.expect_sh("gzip", str(test_file))
      gz_file = self.platform.gzip(test_file)
    self.assertEqual(gz_file, self.platform.path("/tmp/test.txt.gz"))

  def test_gzip_python_fallback(self):
    test_file = self.platform.path("/tmp/test.txt")
    self.fs.create_file(test_file, contents="hello python gzip")
    with mock.patch.object(self.platform, "which", return_value=None):
      if self.platform.is_remote:
        with self.assertRaises(RuntimeError):
          self.platform.gzip(test_file)
        return
      gz_file = self.platform.gzip(test_file)
    self.assertEqual(gz_file, self.platform.path("/tmp/test.txt.gz"))
    self.assertFalse(self.fs.exists(test_file))
    self.assertTrue(self.fs.exists(gz_file))
    with gzip.open(gz_file, "rt", encoding="utf-8") as f:
      self.assertEqual(f.read(), "hello python gzip")

  def test_perf_event_paranoid(self) -> None:
    self.assertIsNone(self.platform.perf_event_paranoid())

    for expected in (2, -1, 4):
      self.platform.rm(PERF_EVENT_PARANOID_PATH, missing_ok=True)
      self.fs.create_file(PERF_EVENT_PARANOID_PATH, contents=f"{expected}\n")
      self.assertEqual(self.platform.perf_event_paranoid(), expected)


class LocalLinuxMockPlatformTestCase(BaseLocalMockPlatformTestMixin,
                                     _LinuxMockPlatformTestCase):
  __test__ = True


class RemoteLinuxMockPlatformTestCase(_LinuxMockPlatformTestCase):

  @override
  def setup_host_platform(self) -> LinuxMockPlatform:
    return LinuxMockPlatform()

  @override
  def setup_platform(self) -> MockPlatform:
    return RemoteLinuxMockPlatform(self.host_platform)

  def cpu_info(self, processor_id, physical_id, core_id):
    return textwrap.dedent(f"""
        processor       : {processor_id}
        vendor_id       : GenuineIntel
        cpu family      : 1
        model           : 12
        model name      : Intel(R) Xeon(R) 3456 CPU @ 7.80GHz
        stepping        : 9
        microcode       : 0x123456
        cpu MHz         : 1234.000
        cache size      : 3456 KB
        physical id     : {physical_id}
        core id         : {core_id}
        fpu             : yes
        fpu_exception   : yes
        cpuid level     : 12
        wp              : yes
      """)

  def expect_sh_cpu_info(self, cpu_info):
    self.expect_sh(
        "grep",
        "-E",
        "processor|core id|physical id",
        "/proc/cpuinfo",
        result=cpu_info)

  @override
  def test_cpu_cores(self):
    single_core_info = self.cpu_info(0, 0, 0)
    self.expect_sh_cpu_info(single_core_info)
    self.assertEqual(self.platform.cpu_cores(logical=True), 1)
    self.assertFalse(self.platform.expected_sh_cmds)
    # Check that caching works.
    self.assertEqual(self.platform.cpu_cores(logical=True), 1)

    self.expect_sh_cpu_info(single_core_info)
    self.assertEqual(self.platform.cpu_cores(logical=False), 1)
    self.assertFalse(self.platform.expected_sh_cmds)
    self.assertEqual(self.platform.cpu_cores(logical=False), 1)

  def test_cpu_cores_2_cpu_single_core(self):
    # 2 physical chips, 1 core, 2 threads
    dual_chip_result = (
        self.cpu_info(0, 0, 0) + self.cpu_info(1, 0, 0) +
        self.cpu_info(2, 1, 0) + self.cpu_info(3, 1, 0))
    self.expect_sh_cpu_info(dual_chip_result)
    self.assertEqual(self.platform.cpu_cores(logical=True), 4)
    self.assertFalse(self.platform.expected_sh_cmds)
    self.assertEqual(self.platform.cpu_cores(logical=True), 4)

    self.expect_sh_cpu_info(dual_chip_result)
    self.assertEqual(self.platform.cpu_cores(logical=False), 2)
    self.assertFalse(self.platform.expected_sh_cmds)
    self.assertEqual(self.platform.cpu_cores(logical=False), 2)

  def test_cpu_cores_1_cpu_dual_core(self):
    # 1 physical chips, 2 cores, 2 threads
    dual_core_result = (
        self.cpu_info(0, 0, 0) + self.cpu_info(1, 0, 1) +
        self.cpu_info(2, 0, 0) + self.cpu_info(3, 0, 1))
    self.expect_sh_cpu_info(dual_core_result)
    self.assertEqual(self.platform.cpu_cores(logical=True), 4)
    self.assertFalse(self.platform.expected_sh_cmds)
    self.assertEqual(self.platform.cpu_cores(logical=True), 4)

    self.expect_sh_cpu_info(dual_core_result)
    self.assertEqual(self.platform.cpu_cores(logical=False), 2)
    self.assertFalse(self.platform.expected_sh_cmds)
    self.assertEqual(self.platform.cpu_cores(logical=False), 2)

  def test_system_memory_bytes(self):
    self.expect_sh(
        "grep",
        "MemTotal",
        "/proc/meminfo",
        result="MemTotal:       16304400 kB\n")
    self.assertEqual(self.platform.system_memory_bytes, 16304400 * 1024)

  def test_system_memory_bytes_missing(self):
    self.expect_sh("grep", "MemTotal", "/proc/meminfo", result="")
    with self.assertRaisesRegex(RuntimeError, "Could not find MemTotal"):
      self.platform.system_memory_bytes

  # TODO: implement more mock tests
  def test_which_empty_path(self):
    with self.assertRaises(ValueError):
      self.platform.which("")
    with self.assertRaises(ValueError):
      self.platform.which(pathlib.Path())

  def test_search_binary_empty_path(self):
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary(pathlib.Path())
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary("")
    self.assertIn("empty", str(cm.exception))

  def test_local_reverse_port_forward_invalid(self):
    pass

  def test_local_reverse_port_forward(self):
    pass

  def test_local_port_forward(self):
    pass

  def test_gpu_vram_used_nvidia(self):
    self.fs.create_file("/usr/bin/nvidia-smi")
    self.expect_sh(
        "/usr/bin/nvidia-smi",
        "--query-gpu=memory.used",
        "--format=csv,noheader,nounits",
        result="1024\n2048\n",
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"gpu_0": 1024.0, "gpu_1": 2048.0})

  def test_gpu_vram_used_amd(self):
    self.fs.create_file(
        "/sys/class/drm/card0/device/mem_info_vram_used",
        contents=str(1024 * 1024 * 512),
    )
    self.fs.create_file(
        "/sys/class/drm/card0/device/mem_info_gtt_used",
        contents=str(1024 * 1024 * 256),
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"amd_gpu": 768.0})

  def test_gpu_vram_used_intel(self):
    self.fs.create_file(
        "/sys/class/drm/card0/lmem_used_bytes",
        contents=str(1024 * 1024 * 1024),
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"intel_gpu": 1024.0})

  def test_gpu_vram_used_none(self):
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {})


class LinuxPlatformClipboardTestCase(PlatformClipboardTestCase):
  __test__ = True

  @override
  def create_platform(self) -> LinuxPlatform:
    return LinuxPlatform()

  @override
  def clipboard_tool_configs(
      self) -> list[tuple[str, pth.LocalPath, list[str]]]:
    return [
        ("xclip", pth.LocalPath("/usr/bin/xclip"), ["-selection", "clipboard"]),
        ("wl-copy", pth.LocalPath("/usr/bin/wl-copy"), []),
        ("xsel", pth.LocalPath("/usr/bin/xsel"), ["--clipboard", "--input"]),
    ]


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
