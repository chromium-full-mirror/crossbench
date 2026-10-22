# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import os
import pathlib
import unittest
from unittest import mock

from pyfakefs.fake_filesystem import OSType

import crossbench.path as pth
from crossbench import plt
from crossbench.plt import PLATFORM
from crossbench.plt.bin import AndroidBinary, AndroidBuildToolPath, Binaries, \
    Binary, BinaryNotFoundError, BinaryPath, ChromeBuildPath, ChromeOSBinary, \
    ChromePath, EnvVarPath, LinuxBinary, MacOsBinary, PerfettoChromePath, \
    PosixBinary, SystemPath, WinBinary, XcodeXctestrunPath, \
    _find_chromium_checkout
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase
from tests.crossbench.mock_helper import AndroidAdbMockPlatform, \
    ChromeOsSshMockPlatform, LinuxMockPlatform, MacOsMockPlatform, MockAdb, \
    WinMockPlatform


class BinaryTestCase(CrossbenchFakeFsTestCase):

  def all_mock_platforms(self):
    yield LinuxMockPlatform()
    yield MacOsMockPlatform()
    yield WinMockPlatform()

  def all_platforms(self):
    yield PLATFORM
    yield from self.all_mock_platforms()

  def create_binary_path(self, path: pth.AnyPathLike) -> pth.LocalPath:
    result = pth.LocalPath(path)
    self.fs.create_file(result, st_size=100)
    return result

  def test_create_without_binary(self):
    with self.assertRaises(ValueError):
      Binary(name="test")
    with self.assertRaises(ValueError):
      Binary(name="test", posix="")

  def test_new_windows_binary_invalid(self):
    with self.assertRaises(ValueError):
      WinBinary("custom")
    with self.assertRaises(ValueError):
      WinBinary(pth.AnyPath("custom"))
    with self.assertRaises(ValueError):
      WinBinary(pth.AnyPath("foo/bar/custom.py"))

  def test_new_windows_binary_properties(self):
    binary = WinBinary("crossbench_mock_binary.exe")
    self.assertEqual(binary.name, "crossbench_mock_binary.exe")

  def test_new_windows_binary_override_resolution(self):
    binary = WinBinary("crossbench_mock_binary.exe")
    platform = WinMockPlatform()
    path = platform.local_path("C:/Users/user-name/AppData/Local/Programs/"
                               "crossbench/crossbench_mock_binary.exe")
    self.fs.create_file(path, st_size=100)

    # Validates resolution behaviors inside the active override_binary context.
    with mock.patch("shutil.which", return_value=path) as cm:
      with platform.override_binary(binary, path):
        self.assertEqual(binary.resolve(platform), path)
        self.assertEqual(binary.resolve_cached(platform), path)
    cm.assert_called_once_with(os.fspath(platform.path(path)))

  def test_new_windows_binary_resolve_cached(self):
    binary = WinBinary("crossbench_mock_binary.exe")
    platform = WinMockPlatform()
    path = platform.local_path("C:/Users/user-name/AppData/Local/Programs/"
                               "crossbench/crossbench_mock_binary.exe")
    self.fs.create_file(path, st_size=100)

    with mock.patch("shutil.which", return_value=path):
      with platform.override_binary(binary, path):
        self.assertEqual(binary.resolve_cached(platform), path)

    # resolve_cached() must return the memoized path even after context exit.
    self.assertEqual(binary.resolve_cached(platform), path)
    # resolve() bypassing caches correctly raises BinaryNotFoundError.
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve(platform)

  def test_basic_accessor(self):
    binary = Binary("test", default="foo/bar/test")
    self.assertEqual(binary.name, "test")

  def test_basic_accessor_multiple(self):
    binary = Binary("test", default=("foo/bar/test1", "foo/bar/test2"))
    self.assertEqual(binary.name, "test")

  def test_binary_exists(self) -> None:
    platform = LinuxMockPlatform()
    binary = Binary("custom_tool", default="/bin/custom_tool")
    self.assertFalse(binary.exists(platform))
    self.fs.create_file("/bin/custom_tool")
    self.assertTrue(binary.exists(platform))
    self.fs.remove("/bin/custom_tool")
    self.assertFalse(binary.exists(platform))

  def test_unknown_binary(self):
    binary = Binary("crossbench_mock_binary", default="crossbench_mock_binary")
    for platform in self.all_platforms():
      with self.subTest(platform=str(platform)):
        with self.assertRaises(BinaryNotFoundError):
          binary.resolve(platform)

  def test_known_binary_default(self):
    for platform in self.all_mock_platforms():
      with self.subTest(platform=str(platform)):
        default = pth.AnyPath("foo/bar/default/crossbench_mock_binary")
        result = default
        if platform.is_win:
          result = pth.AnyPath("foo/bar/default/crossbench_mock_binary.exe")
        binary = Binary("crossbench_mock_binary", default=default)
        self.validate_known_binary_default(platform, result, binary)

  def test_known_binary_default_exe(self):
    for platform in self.all_mock_platforms():
      with self.subTest(platform=str(platform)):
        default = pth.AnyPath("foo/bar/default/crossbench_mock_binary.exe")
        binary = Binary("crossbench_mock_binary", default=default)
        self.validate_known_binary_default(platform, default, binary)

  def test_known_binary_default_bat(self):
    for platform in self.all_mock_platforms():
      with self.subTest(platform=str(platform)):
        default = pth.AnyPath("foo/bar/default/crossbench_mock_binary.bat")
        binary = Binary("crossbench_mock_binary", default=default)
        self.validate_known_binary_default(platform, default, binary)

  def validate_known_binary_default(self, platform: plt.Platform,
                                    result: pth.AnyPath, binary: Binary):
    self.assertSequenceEqual(
        [path_entry.binary for path_entry in binary.platform_path(platform)],
        [result])
    self.assertFalse(binary.exists(platform))
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve(platform)
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve_cached(platform)
    self.fs.create_file(result, st_size=100)
    self.assertTrue(binary.exists(platform))
    self.assertEqual(pth.AnyPath(binary.resolve(platform)), result)
    self.assertEqual(pth.AnyPath(binary.resolve_cached(platform)), result)
    self.fs.remove(result)
    self.assertFalse(binary.exists(platform))
    self.assertEqual(pth.AnyPath(binary.resolve_cached(platform)), result)
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve(platform)

  def test_known_binary_default_multiple(self):
    for platform in self.all_mock_platforms():
      with self.subTest(platform=str(platform)):
        default_miss = pth.AnyPath("foo/bar/default/fake")
        default = pth.AnyPath("foo/bar/default/crossbench_mock_binary")
        result = default
        if platform.is_win:
          default_miss = pth.AnyPath("foo/bar/default/fake.exe")
          result = pth.AnyPath("foo/bar/default/crossbench_mock_binary.exe")
        binary = Binary(
            "crossbench_mock_binary", default=(default_miss, default))
        self.validate_known_binary_default_multiple(platform, default_miss,
                                                    result, binary)

  def validate_known_binary_default_multiple(self, platform: plt.Platform,
                                             default_miss: pth.AnyPath,
                                             result: pth.AnyPath,
                                             binary: Binary):
    self.assertSequenceEqual(
        [path_entry.binary for path_entry in binary.platform_path(platform)],
        [default_miss, result])
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve(platform)
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve_cached(platform)
    self.fs.create_file(result, st_size=100)
    self.assertEqual(pth.AnyPath(binary.resolve(platform)), result)
    self.assertEqual(pth.AnyPath(binary.resolve_cached(platform)), result)
    self.fs.remove(result)
    with self.assertRaises(BinaryNotFoundError):
      binary.resolve(platform)

  @unittest.skipUnless(plt.PLATFORM.is_posix, "Only supported on posix")
  def test_known_binary_chromeos(self):
    path = pth.AnyPosixPath("foo/bar/default/crossbench_mock_binary")
    binary = Binary("crossbench_mock_binary", chromeos=path)
    self.validate_known_binary_chromeos(path, binary)
    binary = ChromeOSBinary(path)
    self.validate_known_binary_chromeos(path, binary)

  def validate_known_binary_chromeos(self, result, binary):
    result = pth.AnyPosixPath(result)
    platform = ChromeOsSshMockPlatform(
        host_platform=LinuxMockPlatform(),
        host="dut",
        port=0,
        ssh_port=22,
        ssh_user="root")

    with mock.patch.object(
        platform, "which", return_value=result) as mock_which:
      with mock.patch.object(
          platform, "exists", return_value=True) as mock_exists:
        self.assertEqual(str(binary.resolve(platform)), str(result))
        self.assertEqual(str(binary.resolve_cached(platform)), str(result))
        mock_which.assert_called_with(result)
        mock_exists.assert_called_with(result)

    for platform in self.all_mock_platforms():
      if platform.is_chromeos:
        continue
      self.assertSequenceEqual(binary.platform_path(platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(platform)

  @unittest.skipUnless(plt.PLATFORM.is_posix, "Only supported on posix")
  def test_known_binary_linux(self):
    result = self.create_binary_path(
        pth.AnyPosixPath("foo/bar/default/crossbench_mock_binary"))
    binary = Binary("crossbench_mock_binary", linux=result)
    self.validate_known_binary_linux(result, binary)
    binary = LinuxBinary(result)
    self.validate_known_binary_linux(result, binary)

  def validate_known_binary_linux(self, result, binary):
    result = pth.AnyPosixPath(result)
    platform = LinuxMockPlatform()
    self.assertEqual(str(binary.resolve(platform)), str(result))
    self.assertEqual(str(binary.resolve_cached(platform)), str(result))

    for platform in self.all_mock_platforms():
      if platform.is_linux:
        continue
      self.assertSequenceEqual(binary.platform_path(platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(platform)

  @unittest.skipUnless(plt.PLATFORM.is_posix, "Only supported on posix")
  def test_known_binary_macos(self):
    result = self.create_binary_path("foo/bar/default/crossbench_mock_binary")
    binary = Binary("crossbench_mock_binary", macos=result)
    self.validate_known_binary_macos(result, binary)
    binary = MacOsBinary(result)
    self.validate_known_binary_macos(result, binary)

  def validate_known_binary_macos(self, result, binary):
    platform = MacOsMockPlatform()
    self.assertEqual(binary.resolve(platform), result)
    self.assertEqual(binary.resolve_cached(platform), result)

    for platform in self.all_mock_platforms():
      if platform.is_macos:
        continue
      self.assertSequenceEqual(binary.platform_path(platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(platform)

  @unittest.skipUnless(plt.PLATFORM.is_posix, "Only supported on posix")
  def test_known_binary_posix(self):
    result = self.create_binary_path("foo/bar/default/crossbench_mock_binary")
    binary = Binary("crossbench_mock_binary", posix=result)
    self.validate_known_binary_posix(result, binary)
    binary = PosixBinary(result)
    self.validate_known_binary_posix(result, binary)

  def validate_known_binary_posix(self, result, binary):
    for platform in self.all_mock_platforms():
      if not platform.is_posix:
        continue
      self.assertEqual(binary.resolve(platform), result)
      self.assertEqual(binary.resolve_cached(platform), result)

    for platform in self.all_mock_platforms():
      if platform.is_posix:
        continue
      self.assertSequenceEqual(binary.platform_path(platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(platform)

  def test_known_binary_win(self):
    self.fs.os = OSType.WINDOWS
    result = self.create_binary_path(
        "foo/bar/default/crossbench_mock_binary.exe")
    result = pathlib.PureWindowsPath(result)
    binary = Binary("crossbench_mock_binary", win=result)
    self.validate_known_binary_win(result, binary)
    binary = WinBinary(result)
    self.validate_known_binary_win(result, binary)

  def validate_known_binary_win(self, result, binary):
    platform = WinMockPlatform()
    self.assertEqual(binary.resolve(platform), result)
    self.assertEqual(binary.resolve_cached(platform), result)

    for platform in self.all_mock_platforms():
      if platform.is_win:
        continue
      self.assertSequenceEqual(binary.platform_path(platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(platform)

  @unittest.skipUnless(plt.PLATFORM.is_posix, "Only supported on posix")
  def test_known_binary_android(self):
    path = pth.AnyPosixPath("foo/bar/default/crossbench_mock_binary")
    host_platform = LinuxMockPlatform()
    adb_bin = host_platform.local_path("/usr/bin/adb")
    self.fs.create_file(adb_bin, contents="adb")

    # The AndroidAdbPlatform base constructor executes an 'adb devices -l'
    # subprocess query on the host system to extract device/serial identity.
    host_platform.expect_sh(
        adb_bin,
        "devices",
        "-l",
        result=("List of attached devices\n"
                "1.1.1.1 device product:mock model:mock"))

    platform = AndroidAdbMockPlatform(host_platform, adb=MockAdb(host_platform))

    binary = Binary("crossbench_mock_binary", android=path)
    self.validate_known_binary_android(platform, path, binary)
    binary = AndroidBinary(path)
    self.validate_known_binary_android(platform, path, binary)

  def validate_known_binary_android(self, platform: plt.Platform,
                                    result: pth.AnyPath, binary: Binary):
    result = pth.AnyPosixPath(result)

    with mock.patch.object(
        platform, "which", return_value=result) as mock_which:
      self.assertEqual(str(binary.resolve(platform)), str(result))
      self.assertEqual(str(binary.resolve_cached(platform)), str(result))
      mock_which.assert_called_with(result)

    for other_platform in self.all_mock_platforms():
      self.assertSequenceEqual(binary.platform_path(other_platform), ())
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve(other_platform)
      with self.assertRaises(BinaryNotFoundError):
        binary.resolve_cached(other_platform)


class BinariesTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    _find_chromium_checkout.cache_clear()

  def test_adb_bin_paths(self):
    linux_plt = LinuxMockPlatform()
    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)
    _find_chromium_checkout.cache_clear()

    adb_path = chrome_src / "third_party/android_sdk/public/platform-tools/adb"
    self.fs.create_file(adb_path, st_size=100)

    self.assertEqual(Binaries.ADB.resolve(linux_plt), adb_path)

  def test_llvm_symbolizer_paths(self) -> None:
    linux_plt = LinuxMockPlatform()
    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)
    _find_chromium_checkout.cache_clear()

    llvm_path = (
        chrome_src /
        "third_party/llvm-build/Release+Asserts/bin/llvm-symbolizer")
    self.fs.create_file(llvm_path, st_size=100)

    self.assertEqual(Binaries.LLVM_SYMBOLIZER.resolve(linux_plt), llvm_path)

    win_plt = WinMockPlatform()
    win_paths = Binaries.LLVM_SYMBOLIZER.platform_path(win_plt)
    self.assertIsInstance(win_paths[0], ChromePath)
    self.assertEqual(
        win_paths[0].relative_path,
        pth.AnyPath(
            "third_party/llvm-build/Release+Asserts/bin/llvm-symbolizer.exe"))
    self.assertIsInstance(win_paths[1], SystemPath)
    self.assertEqual(win_paths[1].binary, pth.AnyPath("llvm-symbolizer.exe"))

  def test_traceconv_paths(self) -> None:
    linux_plt = LinuxMockPlatform()
    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)
    _find_chromium_checkout.cache_clear()

    traceconv_path = chrome_src / "third_party/perfetto/tools/traceconv"
    self.fs.create_file(traceconv_path, st_size=100)

    self.assertEqual(Binaries.TRACECONV.resolve(linux_plt), traceconv_path)

  def test_trace_processor_shell_paths(self) -> None:
    linux_plt = LinuxMockPlatform()
    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)
    _find_chromium_checkout.cache_clear()

    # 1. Resolves in out/Default via ChromeBuildPath
    tp_build_path = chrome_src / "out/Default/trace_processor_shell"
    self.fs.create_file(tp_build_path, st_size=100)
    self.assertEqual(
        Binaries.TRACE_PROCESSOR_SHELL.resolve(linux_plt), tp_build_path)

    # 2. Falls back to tools/trace_processor via PerfettoChromePath
    linux_plt.rm(tp_build_path)
    tp_tools_path = chrome_src / "third_party/perfetto/tools/trace_processor"
    self.fs.create_file(tp_tools_path, st_size=100)
    self.assertEqual(
        Binaries.TRACE_PROCESSOR_SHELL.resolve(linux_plt), tp_tools_path)


class BinaryPathTestCase(CrossbenchFakeFsTestCase):

  def test_base_binary_path_defaults(self) -> None:

    class CustomBinaryPath(BinaryPath):

      def resolve(self, platform: plt.Platform) -> pth.AnyPath | None:
        return None

    custom = CustomBinaryPath()
    self.assertIsNone(custom.path)
    self.assertIs(custom.for_windows(), custom)
    custom.validate_win()

  def test_system_path(self):
    linux_plt = LinuxMockPlatform()
    sys_path = SystemPath("my_binary")
    self.fs.create_file(linux_plt.local_path("/usr/bin/my_binary"))
    self.assertEqual(
        sys_path.resolve(linux_plt), linux_plt.local_path("/usr/bin/my_binary"))

  def test_system_path_for_windows(self):
    sys_path = SystemPath("adb")
    win_path = sys_path.for_windows()
    self.assertIsInstance(win_path, SystemPath)
    self.assertEqual(win_path.binary, pth.AnyPath("adb.exe"))

    sys_path_nested = SystemPath("my_tools/adb")
    win_path_nested = sys_path_nested.for_windows()
    self.assertIsInstance(win_path_nested, SystemPath)
    self.assertEqual(win_path_nested.binary, pth.AnyPath("my_tools/adb.exe"))

    sys_path_exe = SystemPath("adb.exe")
    self.assertIs(sys_path_exe.for_windows(), sys_path_exe)
    self.assertEqual(sys_path_exe.binary, pth.AnyPath("adb.exe"))

    sys_path_nested_exe = SystemPath("my_tools/adb.exe")
    self.assertIs(sys_path_nested_exe.for_windows(), sys_path_nested_exe)
    self.assertEqual(sys_path_nested_exe.binary,
                     pth.AnyPath("my_tools/adb.exe"))

    sys_path_bat = SystemPath("adb.bat")
    self.assertIs(sys_path_bat.for_windows(), sys_path_bat)
    self.assertEqual(sys_path_bat.binary, pth.AnyPath("adb.bat"))

    sys_path_nested_bat = SystemPath("my_tools/adb.bat")
    self.assertIs(sys_path_nested_bat.for_windows(), sys_path_nested_bat)
    self.assertEqual(sys_path_nested_bat.binary,
                     pth.AnyPath("my_tools/adb.bat"))

    sys_path_upper_exe = SystemPath("adb.EXE")
    self.assertIs(sys_path_upper_exe.for_windows(), sys_path_upper_exe)
    sys_path_upper_bat = SystemPath("adb.BAT")
    self.assertIs(sys_path_upper_bat.for_windows(), sys_path_upper_bat)

  def test_env_path(self):
    linux_plt = LinuxMockPlatform()
    with self.assertRaises(AssertionError):
      EnvVarPath("")

    env_path = EnvVarPath("CB_TEST_ADB_PATH")
    self.assertIsNone(env_path.resolve(linux_plt))
    adb = linux_plt.local_path("/fake/sdk/platform-tools/adb")
    linux_plt.environ["CB_TEST_ADB_PATH"] = str(adb)

    self.fs.create_file(adb)
    self.assertEqual(env_path.resolve(linux_plt), adb)

  def test_env_path_for_windows(self):
    env_path = EnvVarPath("CB_TEST_ADB_PATH")
    self.assertIs(env_path.for_windows(), env_path)
    self.assertEqual(env_path.env_var, "CB_TEST_ADB_PATH")

  def test_system_path_home_dir(self):
    linux_plt = LinuxMockPlatform()
    adb_path = linux_plt.home() / "my_tools" / "adb"
    self.fs.create_file(adb_path)

    # Assert that ~/ paths gracefully resolve to platform.home()
    with mock.patch.object(linux_plt, "which", return_value=adb_path) as cm:
      self.assertEqual(
          SystemPath("~/my_tools/adb").resolve(linux_plt), adb_path)
    cm.assert_called_once_with(linux_plt.path("~/my_tools/adb"))

  def test_system_path_validation(self):
    with self.assertRaisesRegex(ValueError, ".exe"):
      SystemPath("my_tools/adb").validate_win()
    with self.assertRaisesRegex(ValueError, ".exe"):
      SystemPath("~/my_tools/adb").validate_win()
    SystemPath("my_tools/adb.bat").validate_win()
    SystemPath("my_tools/adb.exe").validate_win()
    SystemPath("~/my_tools/adb.bat").validate_win()
    SystemPath("~/my_tools/adb.exe").validate_win()

  def test_chrome_path_validation(self):
    with self.assertRaises(AssertionError):
      ChromePath("")
    with self.assertRaises(AssertionError):
      ChromePath(pth.AnyPath())
    with self.assertRaisesRegex(ValueError, ".exe"):
      ChromePath("third_party/hello/adb").validate_win()
    ChromePath("third_party/hello/adb.exe").validate_win()
    ChromePath("third_party/hello/adb.bat").validate_win()

  def test_chrome_path(self):
    linux_plt = LinuxMockPlatform()

    # Test AnyPath compatibility natively
    path_test = ChromePath(pth.AnyPath("src/chrome"))
    self.assertEqual(path_test.relative_path.name, "chrome")
    chrome_path = ChromePath("third_party/hello/adb")

    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)

    adb = chrome_src / "third_party/hello/adb"
    self.fs.create_file(adb)

    self.assertEqual(chrome_path.resolve(linux_plt), adb)

  def test_chrome_path_for_windows(self):
    chrome_path = ChromePath("third_party/hello/adb")
    win_path = chrome_path.for_windows()
    self.assertIsInstance(win_path, ChromePath)
    self.assertEqual(win_path.relative_path,
                     pth.AnyPath("third_party/hello/adb.exe"))

    chrome_path_exe = ChromePath("third_party/hello/adb.exe")
    self.assertIs(chrome_path_exe.for_windows(), chrome_path_exe)
    self.assertEqual(chrome_path_exe.relative_path,
                     pth.AnyPath("third_party/hello/adb.exe"))

    chrome_path_bat = ChromePath("third_party/hello/adb.bat")
    self.assertIs(chrome_path_bat.for_windows(), chrome_path_bat)
    self.assertEqual(chrome_path_bat.relative_path,
                     pth.AnyPath("third_party/hello/adb.bat"))

    chrome_path_upper_exe = ChromePath("third_party/hello/adb.EXE")
    self.assertIs(chrome_path_upper_exe.for_windows(), chrome_path_upper_exe)
    chrome_path_upper_bat = ChromePath("third_party/hello/adb.BAT")
    self.assertIs(chrome_path_upper_bat.for_windows(), chrome_path_upper_bat)

  def test_chrome_build_path_validation(self) -> None:
    with self.assertRaises(ValueError):
      ChromeBuildPath("foo/bar")
    with self.assertRaisesRegex(ValueError, ".exe"):
      ChromeBuildPath("trace_processor_shell").validate_win()
    ChromeBuildPath("trace_processor_shell.exe").validate_win()
    ChromeBuildPath("trace_processor_shell.bat").validate_win()

  def test_chrome_build_path_for_windows(self) -> None:
    build_path = ChromeBuildPath("trace_processor_shell")
    win_path = build_path.for_windows()
    self.assertIsInstance(win_path, ChromeBuildPath)
    assert isinstance(win_path, ChromeBuildPath)
    self.assertEqual(win_path.binary, pth.AnyPath("trace_processor_shell.exe"))
    build_path_exe = ChromeBuildPath("trace_processor_shell.exe")
    self.assertIs(build_path_exe.for_windows(), build_path_exe)

  def test_chrome_build_path_env_var(self) -> None:
    linux_plt = LinuxMockPlatform()
    build_path = ChromeBuildPath("trace_processor_shell")

    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)

    # No out directory
    self.assertIsNone(build_path.resolve(linux_plt))

    out_dir = chrome_src / "out"
    self.fs.create_dir(out_dir)

    # Empty out directory
    self.assertIsNone(build_path.resolve(linux_plt))

    release_dir = out_dir / "Release"
    self.fs.create_dir(release_dir)
    target_bin = release_dir / "trace_processor_shell"
    self.fs.create_file(target_bin)

    self.assertEqual(build_path.resolve(linux_plt), target_bin)

    # Test glob fallback for non-standard build directory name
    self.fs.remove(target_bin)
    self.assertIsNone(build_path.resolve(linux_plt))
    custom_dir = out_dir / "custom_arm64"
    self.fs.create_dir(custom_dir)
    custom_bin = custom_dir / "trace_processor_shell"
    self.fs.create_file(custom_bin)
    self.assertEqual(build_path.resolve(linux_plt), custom_bin)

  def test_perfetto_chrome_path_validation(self) -> None:
    with self.assertRaises(ValueError):
      PerfettoChromePath("foo/bar")
    with self.assertRaisesRegex(ValueError, ".exe"):
      PerfettoChromePath("trace_processor").validate_win()
    PerfettoChromePath("trace_processor.exe").validate_win()
    PerfettoChromePath("trace_processor.bat").validate_win()

  def test_perfetto_chrome_path_for_windows(self) -> None:
    perfetto_path = PerfettoChromePath("trace_processor")
    win_path = perfetto_path.for_windows()
    self.assertIsInstance(win_path, PerfettoChromePath)
    assert isinstance(win_path, PerfettoChromePath)
    self.assertEqual(
        win_path.relative_path,
        pth.AnyPath("third_party/perfetto/tools/trace_processor.exe"))
    self.assertEqual(win_path.binary, pth.AnyPath("trace_processor.exe"))
    perfetto_path_exe = PerfettoChromePath("trace_processor.exe")
    self.assertIs(perfetto_path_exe.for_windows(), perfetto_path_exe)

  def test_perfetto_chrome_path(self) -> None:
    linux_plt = LinuxMockPlatform()
    perfetto_path = PerfettoChromePath("trace_processor")

    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)
    _find_chromium_checkout.cache_clear()

    # No perfetto tools binary
    self.assertIsNone(perfetto_path.resolve(linux_plt))

    target_bin = chrome_src / "third_party/perfetto/tools/trace_processor"
    self.fs.create_file(target_bin)

    self.assertEqual(perfetto_path.resolve(linux_plt), target_bin)

  def test_android_build_tool_path(self):
    linux_plt = LinuxMockPlatform()

    chrome_src = linux_plt.local_path("/fake/chrome/src")
    self.setup_chromium_checkout(chrome_src)
    linux_plt.environ["CHROMIUM_SRC"] = str(chrome_src)

    tool_path = AndroidBuildToolPath("aapt", "~/Android/Sdk")

    # Chrome SDK is available, but build-tools dir is missing
    self.assertIsNone(tool_path.resolve(linux_plt))

    build_tools = chrome_src / "third_party/android_sdk/public/build-tools"
    self.fs.create_dir(build_tools)

    # Empty build tools dir
    self.assertIsNone(tool_path.resolve(linux_plt))

    # Add a version
    v33 = build_tools / "33.0.0"
    self.fs.create_dir(v33)
    self.assertIsNone(tool_path.resolve(linux_plt))

    self.fs.create_file(v33 / "aapt")
    self.assertEqual(tool_path.resolve(linux_plt), v33 / "aapt")

    # Add higher version
    v34 = build_tools / "34.0.0"
    self.fs.create_dir(v34)
    self.fs.create_file(v34 / "aapt")
    self.assertEqual(tool_path.resolve(linux_plt), v34 / "aapt")

  def test_android_build_tool_path_for_windows(self):
    tool_path = AndroidBuildToolPath("aapt", "~/Android/Sdk")
    win_path = tool_path.for_windows()
    self.assertIsInstance(win_path, AndroidBuildToolPath)
    self.assertEqual(win_path.tool_name, "aapt.exe")
    self.assertEqual(win_path.fallback_sdk_path, pth.AnyPath("~/Android/Sdk"))

    tool_path_no_sdk = AndroidBuildToolPath("aapt")
    win_path_no_sdk = tool_path_no_sdk.for_windows()
    self.assertIsInstance(win_path_no_sdk, AndroidBuildToolPath)
    self.assertEqual(win_path_no_sdk.tool_name, "aapt.exe")
    self.assertIsNone(win_path_no_sdk.fallback_sdk_path)

    tool_path_exe = AndroidBuildToolPath("aapt.exe", "~/Android/Sdk")
    self.assertIs(tool_path_exe.for_windows(), tool_path_exe)
    self.assertEqual(tool_path_exe.tool_name, "aapt.exe")

    tool_path_bat = AndroidBuildToolPath("aapt.bat", "~/Android/Sdk")
    self.assertIs(tool_path_bat.for_windows(), tool_path_bat)
    self.assertEqual(tool_path_bat.tool_name, "aapt.bat")

    tool_path_upper_exe = AndroidBuildToolPath("aapt.EXE")
    self.assertIs(tool_path_upper_exe.for_windows(), tool_path_upper_exe)
    tool_path_upper_bat = AndroidBuildToolPath("aapt.BAT")
    self.assertIs(tool_path_upper_bat.for_windows(), tool_path_upper_bat)

  def test_android_build_tool_path_validation(self):
    with self.assertRaisesRegex(ValueError, ".exe"):
      AndroidBuildToolPath("aapt").validate_win()
    AndroidBuildToolPath("aapt.exe").validate_win()
    AndroidBuildToolPath("aapt.bat").validate_win()

  def test_android_build_tool_path_fallback(self):
    linux_plt = LinuxMockPlatform()
    tool_path_fallback = AndroidBuildToolPath("aapt", "~/Android/Sdk")
    _find_chromium_checkout.cache_clear()

    sys_sdk = linux_plt.home() / "Android/Sdk/build-tools"
    self.fs.create_dir(sys_sdk)
    sys_v37 = sys_sdk / "37.0.0"
    self.fs.create_dir(sys_v37)
    self.fs.create_file(sys_v37 / "aapt")

    self.assertEqual(tool_path_fallback.resolve(linux_plt), sys_v37 / "aapt")

  def test_xcode_xctestrun_path(self) -> None:
    macos_plt = MacOsMockPlatform()
    with self.assertRaises(AssertionError):
      XcodeXctestrunPath("")

    ios_path = XcodeXctestrunPath("iphoneos")
    sim_path = XcodeXctestrunPath("iphonesimulator")

    products = (
        macos_plt.home() /
        "Library/Developer/Xcode/DerivedData/WebDriverAgent-x/Build/Products")
    stale = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
    fresh = products / "WebDriverAgentRunner_iphoneos26.0-arm64.xctestrun"
    sim = products / "WebDriverAgentRunner_iphonesimulator26.5-arm64.xctestrun"

    # No DerivedData directory at all.
    self.assertIsNone(ios_path.resolve(macos_plt))
    # DerivedData exists but contains no matching .xctestrun.
    self.fs.create_dir(products)
    self.assertIsNone(ios_path.resolve(macos_plt))

    for path in (stale, fresh, sim):
      self.fs.create_file(path)
    # The higher SDK version string is the *older* build: selection must be
    # by modification time, not by name.
    os.utime(stale, (100, 100))
    os.utime(fresh, (200, 200))
    # The simulator build is newest, but must not win for a real device.
    os.utime(sim, (300, 300))

    self.assertEqual(ios_path.resolve(macos_plt), fresh)
    self.assertEqual(sim_path.resolve(macos_plt), sim)

  def test_xcode_xctestrun_path_for_windows(self) -> None:
    ios_path = XcodeXctestrunPath("iphoneos")
    self.assertIs(ios_path.for_windows(), ios_path)
    self.assertEqual(ios_path.sdk, "iphoneos")

  def test_wda_xctestrun_paths(self) -> None:
    macos_plt = MacOsMockPlatform()
    products = (
        macos_plt.home() /
        "Library/Developer/Xcode/DerivedData/WebDriverAgent-x/Build/Products")
    fresh = products / "WebDriverAgentRunner_iphoneos26.0-arm64.xctestrun"
    sim = products / "WebDriverAgentRunner_iphonesimulator26.5-arm64.xctestrun"
    self.fs.create_file(fresh)
    self.fs.create_file(sim)

    self.assertEqual(Binaries.WDA_XCTESTRUN.resolve(macos_plt), fresh)
    self.assertEqual(Binaries.WDA_XCTESTRUN_SIMULATOR.resolve(macos_plt), sim)

    override = macos_plt.local_path("/custom/wda.xctestrun")
    self.fs.create_file(override)
    with macos_plt.override_binary(Binaries.WDA_XCTESTRUN, override):
      self.assertEqual(Binaries.WDA_XCTESTRUN.resolve(macos_plt), override)
    self.assertEqual(Binaries.WDA_XCTESTRUN.resolve(macos_plt), fresh)

  def test_binaries_names(self):
    for prop_name, binary_instance in vars(Binaries).items():
      if prop_name.startswith("__"):
        continue
      self.assertIsInstance(binary_instance, Binary, prop_name)
      self.assertEqual(prop_name.lower(),
                       binary_instance.name.replace("-", "_"))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
