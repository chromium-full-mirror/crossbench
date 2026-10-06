# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import datetime as dt
import pathlib
from typing import Final
from unittest import mock

from typing_extensions import override

import crossbench.path as pth
from crossbench import plt
from crossbench.plt.posix import PosixPlatform
from tests.crossbench.base import CrossbenchFakeFsTestCase
from tests.crossbench.mock_helper import MockPlatform

GCS_URL: Final[str] = (
    "gs://chrome-partner-loadline/archive_phone_20260331.wprgo")
GCS_FILE_SIZE: Final[int] = 45678


class FakeGcsBlob:
  """Minimal stand-in for google.cloud.storage.blob.Blob."""

  def __init__(self,
               size: int,
               download_size: int,
               download_error: BaseException | None = None) -> None:
    # Size reported by the object metadata.
    self.size: int = size
    # Number of bytes written by a download.
    self.download_size: int = download_size
    # Raised by a download after writing download_size bytes.
    self.download_error: BaseException | None = download_error

  def reload(self) -> None:
    pass

  def download_to_filename(self, filename: str) -> None:
    pathlib.Path(filename).write_bytes(b"\0" * self.download_size)
    if self.download_error:
      raise self.download_error


class BaseMockPlatformTestCase(CrossbenchFakeFsTestCase, metaclass=abc.ABCMeta):
  __test__ = False

  @override
  def setUp(self) -> None:
    super().setUp()
    self.host_platform: MockPlatform = self.setup_host_platform()
    self.platform: plt.Platform = self.setup_platform()

  def setup_host_platform(self) -> MockPlatform:
    return MockPlatform()

  def setup_platform(self) -> MockPlatform:
    return self.host_platform

  def mock_platform_str(self, platform, name) -> None:
    # Mock out str(platform) to avoid secondary errors when printing the
    # platform name in failing tests.
    patcher = mock.patch.object(type(platform), "__str__", return_value=name)
    self.addCleanup(patcher.stop)
    patcher.start()

  def tearDown(self):
    expected_sh_cmds = self.host_platform.expected_sh_cmds
    if expected_sh_cmds is not None:
      self.assertSequenceEqual(expected_sh_cmds, [],
                               "Got additional unused shell cmds.")
    self.assertTrue(self.platform.ports.is_empty)
    super().tearDown()

  def expect_sh(self, *args, result="", returncode: int = 0):
    self.platform.expect_sh(*args, result=result, returncode=returncode)

  def test_is_android(self):
    self.assertFalse(self.platform.is_android)

  def test_is_macos(self):
    self.assertFalse(self.platform.is_macos)

  def test_is_ios(self):
    self.assertFalse(self.platform.is_ios)

  def test_is_linux(self):
    self.assertFalse(self.platform.is_linux)

  def test_is_win(self):
    self.assertFalse(self.platform.is_win)

  def test_is_posix(self):
    self.assertFalse(self.platform.is_posix)

  def test_is_remote_ssh(self):
    self.assertFalse(self.platform.is_remote_ssh)

  def test_is_chromeos(self):
    self.assertFalse(self.platform.is_chromeos)

  def test_is_pyodide(self):
    self.assertFalse(self.platform.is_pyodide)

  def test_pathsep(self):
    expected = ";" if self.platform.is_win else ":"
    self.assertEqual(self.platform.pathsep, expected)

  def test_join_path_list(self):
    self.assertEqual(self.platform.join_path_list(""), "")
    self.assertEqual(self.platform.join_path_list([]), "")
    p1 = self.platform.path("foo/bar")
    p2 = self.platform.path("baz/qux")
    self.assertEqual(self.platform.join_path_list(p1), str(p1))
    self.assertEqual(
        self.platform.join_path_list([p1, p2]),
        f"{p1}{self.platform.pathsep}{p2}")
    self.assertEqual(
        self.platform.join_path_list([p1, "", p2]),
        f"{p1}{self.platform.pathsep}{p2}")

  def test_split_path_list(self):
    self.assertEqual(self.platform.split_path_list(""), ())
    p1 = self.platform.path("foo/bar")
    p2 = self.platform.path("baz/qux")
    path_str = f"{p1}{self.platform.pathsep}{p2}"
    self.assertEqual(self.platform.split_path_list(path_str), (p1, p2))

  def test_port_forward_invalid(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(argparse.ArgumentTypeError, "local_port"):
        ports.forward(-1, -1)

  def test_reverse_port_forward_invalid(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(argparse.ArgumentTypeError, "remote_port"):
        ports.reverse_forward(-1, -1)

  def test_is_remote_desktop_no_script(self):
    if not self.platform.is_local and self.platform.is_linux:
      self.expect_sh(
          "'[' -e /opt/google/chrome-remote-desktop/is-remoting-session ']'",
          returncode=1)
    self.assertFalse(self.platform.is_remote_desktop)

  def _gcs_download_dest(self) -> pth.LocalPath:
    # GCS downloads always land on the host, even for remote platforms.
    return self.host_platform.local_path("/cache/wpr/archive.wprgo")

  def _download_gcs_file(self, blob: FakeGcsBlob, dest: pth.LocalPath) -> None:
    with mock.patch.object(self.platform, "get_gcs_blob", return_value=blob):
      self.platform.download_gcs_file(GCS_URL, dest)

  def test_download_gcs_file(self) -> None:
    dest = self._gcs_download_dest()
    self._download_gcs_file(FakeGcsBlob(GCS_FILE_SIZE, GCS_FILE_SIZE), dest)
    self.assertEqual(dest.stat().st_size, GCS_FILE_SIZE)

  def _assert_gcs_nothing_cached(self, dest: pth.LocalPath) -> None:
    # Nothing is cached, so the next run downloads the file again.
    self.assertFalse(dest.exists())
    self.assertEqual([], list(dest.parent.iterdir()))

  def test_download_gcs_file_failure_is_not_kept(self) -> None:
    dest = self._gcs_download_dest()
    for error in (OSError("Connection reset"), KeyboardInterrupt()):
      with self.subTest(error=type(error).__name__):
        # Downloads that fail halfway still leave bytes on disk.
        blob = FakeGcsBlob(GCS_FILE_SIZE, GCS_FILE_SIZE // 2, error)
        with self.assertRaises(type(error)):
          self._download_gcs_file(blob, dest)
        self._assert_gcs_nothing_cached(dest)

  def test_download_gcs_file_size_mismatch_is_rejected(self) -> None:
    dest = self._gcs_download_dest()
    for download_size in (0, GCS_FILE_SIZE - 1, GCS_FILE_SIZE + 1):
      with self.subTest(download_size=download_size):
        with self.assertRaisesRegex(OSError, "Size mismatch"):
          self._download_gcs_file(
              FakeGcsBlob(GCS_FILE_SIZE, download_size), dest)
        self._assert_gcs_nothing_cached(dest)


class BaseLocalMockPlatformTestMixin:

  def test_local_port_forward_invalid(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(ValueError, "local platform"):
        ports.forward(1000, 2000)

  def test_local_reverse_port_forward_invalid(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(ValueError, "local platform"):
        ports.reverse_forward(1000, 2000)

  def test_local_reverse_port_forward(self):
    with self.platform.ports.nested() as ports:
      port = self.platform.get_free_port()
      self.assertEqual(ports.reverse_forward(port, port), port)
      ports.stop_reverse_forward(port)

  def test_local_port_forward(self):
    with self.platform.ports.nested() as ports:
      port = self.platform.get_free_port()
      self.assertEqual(ports.forward(port, port), port)
      ports.stop_forward(port)


class BasePosixMockPlatformTestCase(BaseMockPlatformTestCase):
  platform: PosixPlatform

  @override
  def tearDown(self) -> None:
    assert isinstance(self.platform, PosixPlatform)
    super().tearDown()

  def test_is_posix(self):
    self.assertTrue(self.platform.is_posix)

  def test_path_conversion(self):
    self.assertIsInstance(self.platform.path("foo/bar"), pathlib.PurePosixPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PurePath("foo/bar")), pathlib.PurePosixPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PureWindowsPath("foo/bar")),
        pathlib.PurePosixPath)
    self.assertIsInstance(
        self.platform.path(pathlib.PurePosixPath("foo/bar")),
        pathlib.PurePosixPath)

  def test_win_absolute_path_conversion(self):
    if not plt.PLATFORM.is_win:
      return
    windows_path = pth.AnyWindowsPath("/foo/bar/file")
    abs_path = self.platform.absolute(windows_path)
    self.assertEqual(str(abs_path), "/foo/bar/file")
    self.assertIsInstance(abs_path, pth.AnyPosixPath)
    self.assertTrue(abs_path.is_absolute())
    self.assertTrue(self.platform.is_absolute(abs_path))

  def test_win_absolute_path_conversion_drive(self):
    if not plt.PLATFORM.is_win:
      return
    windows_path = pth.AnyWindowsPath("C:/foo/bar/file")
    abs_path = self.platform.absolute(windows_path)
    self.assertEqual(str(abs_path), "/foo/bar/file")
    self.assertIsInstance(abs_path, pth.AnyPosixPath)
    self.assertTrue(abs_path.is_absolute())
    self.assertTrue(self.platform.is_absolute(abs_path))

  def test_uptime(self):
    self.expect_sh(
        "uptime",
        result="12:25  up  3:26, 2 users, load averages: 4.27 4.29 4.80\n")
    uptime = self.platform.uptime()
    self.assertEqual(uptime, dt.timedelta(hours=3, minutes=26))
    self.expect_sh(
        "uptime",
        result=("12:54:27 up 5 days,  2:48,  3 users,  "
                "load average: 1.62, 2.15, 2.07\n"))
    uptime = self.platform.uptime()
    self.assertEqual(uptime, dt.timedelta(days=5, hours=2, minutes=48))
    self.expect_sh(
        "uptime",
        result="12:25  up 3 hrs, 2 users, load averages: 4.27 4.29 4.80\n")
    uptime = self.platform.uptime()
    self.assertEqual(uptime, dt.timedelta(hours=3))
    self.expect_sh(
        "uptime",
        result="12:25  up 5 days, 1 hr, 2 users, load averages: 4.27 4.29\n")
    uptime = self.platform.uptime()
    self.assertEqual(uptime, dt.timedelta(days=5, hours=1))
    self.expect_sh(
        "uptime",
        result="12:25  up 45 secs, 2 users, load averages: 4.27 4.29 4.80\n")
    uptime = self.platform.uptime()
    self.assertEqual(uptime, dt.timedelta(seconds=45))


class PlatformClipboardTestCase(
    CrossbenchFakeFsTestCase, metaclass=abc.ABCMeta):
  __test__ = False

  @abc.abstractmethod
  def create_platform(self) -> plt.Platform:
    pass

  @abc.abstractmethod
  def clipboard_tool_configs(
      self) -> list[tuple[str, pth.LocalPath, list[str]]]:
    pass

  def test_clipboard_not_found(self) -> None:
    platform = self.create_platform()
    self.assertFalse(platform.has_clipboard)
    with self.assertRaises(AssertionError):
      platform.set_clipboard("test")

  def test_set_clipboard(self) -> None:
    for tool_name, bin_path, extra_args in self.clipboard_tool_configs():
      with self.subTest(tool=tool_name):
        platform = self.create_platform()
        with mock.patch.object(platform, "which") as mock_which:
          # mock_which.side_effect handles calls to platform.which(name)
          # and returns bin_path only if name matches tool_name,
          # otherwise returning None.
          mock_which.side_effect = {tool_name: bin_path}.get
          self._test_set_clipboard(platform, bin_path, extra_args)

  def _test_set_clipboard(
      self,
      platform: plt.Platform,
      bin_path: pth.LocalPath,
      extra_args: list[str],
  ) -> None:
    self.assertTrue(platform.has_clipboard)
    with mock.patch.object(platform, "sh") as mock_sh:
      platform.set_clipboard("hello")

      mock_sh.assert_called_once_with(
          bin_path,
          *extra_args,
          input=b"hello",
          check=True,
      )
