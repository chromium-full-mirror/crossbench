# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import os
import pathlib
import textwrap
from unittest import mock

from pyfakefs.fake_filesystem import OSType
from typing_extensions import override

from crossbench import path as pth
from crossbench.helper.version import VersionParseError
from crossbench.plt.win import WinPlatform, WinVersion
from tests import test_helper
from tests.crossbench.mock_helper import WinMockPlatform
from tests.crossbench.plt.helper import BaseLocalMockPlatformTestMixin, \
    BaseMockPlatformTestCase, PlatformClipboardTestCase


class WinMockPlatformTestCase(BaseLocalMockPlatformTestMixin,
                              BaseMockPlatformTestCase):
  __test__ = True

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.os = OSType.WINDOWS

  @override
  def setup_host_platform(self):
    return WinMockPlatform()

  def path(self, path: pth.AnyPathLike) -> pathlib.PureWindowsPath:
    return pathlib.PureWindowsPath(path)

  def test_is_win(self):
    self.assertTrue(self.platform.is_win)

  def test_pathsep(self):
    self.assertEqual(self.platform.pathsep, ";")

  def test_name(self):
    self.assertEqual(self.platform.name, "mock.win")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "mock.win")

  def test_version(self):
    self.platform.mock_version_str = None
    ver_output = "\nMicrosoft Windows [Version 10.0.22631.3593]\n"
    self.expect_sh("cmd", "/c", "ver", result=ver_output)
    self.assertEqual(self.platform.version_str, ver_output.strip())
    version = self.platform.version
    self.assertSequenceEqual(version.parts, (10, 0, 22631, 3593))
    self.assertEqual(version.version_str, ver_output.strip())

  def test_killall(self):
    self.expect_sh("taskkill", "/F", "/IM", "chrome.exe", result="")
    self.platform.killall("chrome")

  def test_path_conversion(self):
    self.assertIsInstance(
        self.platform.path("foo/bar"), pathlib.PureWindowsPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PurePath("foo/bar")),
        pathlib.PureWindowsPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PureWindowsPath("foo/bar")),
        pathlib.PureWindowsPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PurePosixPath("foo/bar")),
        pathlib.PureWindowsPath)

  def test_expanduser(self) -> None:
    home = self.path("C:/Users/testuser")
    with mock.patch.object(self.platform, "home", return_value=home):
      self.assertEqual(self.platform.expanduser("~"), home)
      self.assertEqual(self.platform.expanduser("~/"), home)
      self.assertEqual(self.platform.expanduser("~/foo"), home / "foo")
      self.assertEqual(self.platform.expanduser("~/foo/bar"), home / "foo/bar")
      self.assertEqual(self.platform.expanduser("~\\"), home)
      self.assertEqual(self.platform.expanduser("~\\foo"), home / "foo")
      self.assertEqual(
          self.platform.expanduser("~\\foo\\bar"), home / "foo/bar")
      self.assertEqual(
          self.platform.expanduser(pathlib.PureWindowsPath("~\\foo")),
          home / "foo")
      self.assertEqual(
          self.platform.expanduser(pth.AnyWindowsPath("~\\foo")), home / "foo")
      self.assertEqual(
          self.platform.expanduser(pathlib.PurePosixPath("~/foo")),
          home / "foo")
      self.assertEqual(
          self.platform.expanduser(pth.AnyPosixPath("~/foo")), home / "foo")

  def test_expanduser_no_home(self) -> None:
    for path_str in (
        "",
        ".",
        "foo",
        "foo/bar",
        "foo\\bar",
        "foo/~bar",
        "foo\\~bar",
        "~~",
        "~~/foo",
        "~~\\foo",
        "~otheruser",
        "~otheruser\\foo",
        "C:/Users/foo",
        "C:\\Users\\foo",
        "C:\\foo\\~bar",
    ):
      with self.subTest(path=path_str):
        self.assertEqual(
            self.platform.expanduser(path_str), self.path(path_str))

  def test_which(self):
    bin_path = self.path("foo/bar/default/crossbench_mock_binary.exe")
    self.assertIsNone(self.platform.which(bin_path))
    with mock.patch("shutil.which", return_value=bin_path) as cm:
      self.assertEqual(self.platform.which(bin_path), bin_path)
    cm.assert_called_once_with(os.fspath(bin_path))

  def test_which_invalid(self):
    with self.assertRaises(ValueError) as cm:
      self.platform.which("")
    self.assertIn("empty", str(cm.exception))

  def test_which_empty_path(self):
    with self.assertRaises(ValueError):
      self.platform.which("")
    with self.assertRaises(ValueError):
      self.platform.which(pathlib.Path())

  def test_search_binary_empty_path(self):
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_binary(pathlib.Path())
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_binary("")
    with self.assertRaisesRegex(ValueError, ".exe"):
      self.platform.search_binary("foo/bar")

  def test_search_binary_broken_which(self):
    bin_path = self.path("foo/bar/default/crossbench_mock_binary.exe")
    self.assertIsNone(self.platform.search_app(bin_path))
    with mock.patch("shutil.which", return_value=bin_path) as cm:
      with self.assertRaisesRegex(RuntimeError, "exist"):
        self.assertEqual(self.platform.search_app(bin_path), bin_path)
    cm.assert_called_once_with(os.fspath(bin_path))

  def test_search_binary(self):
    bin_path = self.path("foo/bar/default/crossbench_mock_binary.exe")
    self.assertFalse(self.platform.exists(bin_path))
    self.assertIsNone(self.platform.search_app(bin_path))
    self.fs.create_file(self.platform.local_path(bin_path), st_size=100)
    self.assertTrue(self.platform.exists(bin_path))
    with mock.patch("shutil.which", return_value=bin_path) as cm:
      self.assertEqual(self.platform.search_app(bin_path), bin_path)
    cm.assert_called_once_with(os.fspath(bin_path))

  def test_machine_arch_amd64(self):
    cpu_caption = textwrap.dedent("""
        Caption
        -------
        Intel64 Family 6 Model 154 Stepping 3


    """)
    self.expect_sh(
        "powershell",
        "-c",
        "Get-CIMInstance -query 'select * from Win32_Processor' | ft Caption",
        result=cpu_caption)
    self.platform.use_mock_machine = False
    with mock.patch("platform.machine", return_value="AMD64"):
      self.assertTrue(self.platform.is_x64)
      self.assertFalse(self.platform.is_arm64)

  def test_machine_arch_arm64(self):
    cpu_caption = textwrap.dedent("""
        Caption
        -------
        ARMv8 (64-bit) Family 8 Model 1 Revision 201


    """)
    self.expect_sh(
        "powershell",
        "-c",
        "Get-CIMInstance -query 'select * from Win32_Processor' | ft Caption",
        result=cpu_caption)
    self.platform.use_mock_machine = False
    self.assertTrue(self.platform.is_arm64)
    self.assertFalse(self.platform.is_x64)

  def test_uptime(self):
    time_span = textwrap.dedent("""
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
    """)
    self.expect_sh(
        "powershell",
        "-c", ("(New-TimeSpan -Start "
               "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime)"),
        result=time_span)
    uptime = self.platform.uptime()
    self.assertEqual(
        uptime,
        dt.timedelta(
            days=14, hours=2, minutes=19, seconds=54, milliseconds=978))

  def test_platform_version_cls(self):
    ver_output = "\nMicrosoft Windows [Version 10.0.22631.3593]\n"
    version = WinVersion.parse(ver_output)
    self.assertSequenceEqual(version.parts, (10, 0, 22631, 3593))
    self.assertEqual(version.version_str, ver_output)
    with self.assertRaises(VersionParseError):
      WinVersion.parse("foo")

  def test_gpu_vram_used_nvidia(self):
    nvidia_smi = self.path(
        "C:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe")
    self.fs.create_file(nvidia_smi)
    self.expect_sh(
        nvidia_smi,
        "--query-gpu=memory.used",
        "--format=csv,noheader,nounits",
        result="1024\n2048\n",
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"gpu_0": 1024.0, "gpu_1": 2048.0})

  def test_gpu_vram_used_wmic(self):
    self.expect_sh(
        "wmic",
        "path",
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory",
        "get",
        "DedicatedUsage,SharedUsage",
        result="DedicatedUsage  SharedUsage\n1073741824      536870912\n",
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"gpu_wmic": 1536.0})

  def test_gpu_vram_used_none(self):
    self.expect_sh(
        "wmic",
        "path",
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory",
        "get",
        "DedicatedUsage,SharedUsage",
        result="DedicatedUsage  SharedUsage\n0               0\n",
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {})


class WinPlatformClipboardTestCase(PlatformClipboardTestCase):
  __test__ = True

  @override
  def create_platform(self) -> WinPlatform:
    return WinPlatform()

  @override
  def clipboard_tool_configs(
      self) -> list[tuple[str, pth.LocalPath, list[str]]]:
    return [("clip", pth.LocalPath("C:/Windows/System32/clip.exe"), [])]


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
