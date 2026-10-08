# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import gc
import gzip
import json
import os
import pathlib
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import TYPE_CHECKING, Iterator
from unittest import mock

from typing_extensions import override

import crossbench.path as pth
from crossbench import __version__, plt
from crossbench.plt.base import DEFAULT_CACHE_DIR, SubprocessError
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.posix import PosixPlatform, RemotePosixPlatform
from crossbench.plt.remote import RemotePopen
from tests import test_helper
from tests.crossbench.mock_helper import MockRemotePortManager

if TYPE_CHECKING:
  from crossbench.plt.port_manager import PortManager


class BaseNativePlatformTestCase(unittest.TestCase):

  # Explicitly disabled base test class
  __test__ = False

  @override
  def setUp(self):
    self.platform: plt.Platform = plt.PLATFORM
    self.known_binary = "python3"

  def test_sleep(self):
    self.platform.sleep(0)
    self.platform.sleep(0.01)
    self.platform.sleep(dt.timedelta())
    self.platform.sleep(dt.timedelta(seconds=0.1))

  def test_cpu_details(self):
    details = self.platform.cpu_details()
    self.assertLess(0, details["physical cores"])

  def test_get_relative_cpu_speed(self):
    self.assertGreater(self.platform.get_relative_cpu_speed(), 0)

  def test_is_thermal_throttled(self):
    self.assertIsInstance(self.platform.is_thermal_throttled(), bool)

  def test_is_battery_powered(self):
    self.assertIsInstance(self.platform.is_battery_powered, bool)
    self.assertEqual(
        self.platform.is_battery_powered,
        plt.PLATFORM.is_battery_powered,
    )

  def test_cpu_usage(self):
    self.assertGreaterEqual(self.platform.cpu_usage(), 0)

  def test_system_memory_bytes(self):
    memory = self.platform.system_memory_bytes
    self.assertIsInstance(memory, int)
    self.assertGreater(memory, 0)

  def test_pathsep(self):
    expected = ";" if self.platform.is_win else ":"
    self.assertEqual(self.platform.pathsep, expected)

  def test_join_path_list(self):
    self.assertEqual(self.platform.join_path_list(""), "")
    self.assertEqual(self.platform.join_path_list([]), "")
    p1 = self.platform.path("/foo/bar")
    p2 = self.platform.path("/baz/qux")
    self.assertEqual(self.platform.join_path_list(p1), str(p1))
    self.assertEqual(
        self.platform.join_path_list([p1, p2]),
        f"{p1}{self.platform.pathsep}{p2}")

  def test_split_path_list(self):
    self.assertEqual(self.platform.split_path_list(""), ())
    p1 = self.platform.path("/foo/bar")
    p2 = self.platform.path("/baz/qux")
    path_str = f"{p1}{self.platform.pathsep}{p2}"
    self.assertEqual(self.platform.split_path_list(path_str), (p1, p2))

  def test_total_memory_mb(self):
    memory_mb = self.platform.total_memory_mb()
    self.assertIsInstance(memory_mb, int)
    self.assertGreater(memory_mb, 0)
    self.assertEqual(memory_mb,
                     self.platform.system_memory_bytes // (1024 * 1024))

  def test_system_details(self):
    self.assertIsNotNone(self.platform.system_details())

  def test_environ(self):
    env = self.platform.environ
    self.assertTrue(env)

  def test_version(self):
    version_a = self.platform.version
    version_b = self.platform.version
    self.assertIs(version_a, version_b)
    self.assertIsInstance(version_a.parts, tuple)
    self.assertTrue(len(version_a.parts) >= 1)
    self.assertGreater(version_a.major, 0)

  def test_which_empty_path(self):
    with self.assertRaises(ValueError):
      self.platform.which("")
    with self.assertRaises(ValueError):
      self.platform.which(pathlib.Path())

  def test_which_invalid_binary(self):
    with tempfile.TemporaryDirectory() as tmp_dirname:
      self.assertIsNone(self.platform.which(tmp_dirname))

  def test_search_binary_empty_path(self):
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_binary(pathlib.Path())
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_binary("")

  def test_search_app_empty_path(self):
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_app(pathlib.Path())
    with self.assertRaisesRegex(ValueError, r"(?i)empty path"):
      self.platform.search_app(pathlib.Path())

  def test_cat(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      file = tmp_dir / "test.txt"
      self.platform.write_text(file, "a b c d e f 11")
      result = self.platform.cat(file)
      self.assertEqual(result, "a b c d e f 11")

  def test_cat_bytes(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      file = tmp_dir / "test.data"
      self.platform.write_text(file, "a b c d e f 11")
      result = self.platform.cat_bytes(file)
      self.assertEqual(result, b"a b c d e f 11")

  def test_mkdir(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      path = tmp_dir / "foo" / "bar"
      self.assertFalse(self.platform.exists(path))
      self.platform.mkdir(path)
      self.assertTrue(self.platform.is_dir(path))
      if self.platform.is_local:
        self.assertTrue(pathlib.Path(path).is_dir())

  def test_rm_file(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      path = tmp_dir / "foo.txt"
      self.platform.touch(path)
      self.assertTrue(self.platform.is_file(path))
      if self.platform.is_local:
        self.assertTrue(pathlib.Path(path).is_file())
      self.platform.rm(path)
      self.assertFalse(self.platform.exists(path))

  def test_rm_dir(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      path = tmp_dir / "foo" / "bar"
      self.platform.mkdir(path, parents=True, exist_ok=False)
      self.assertTrue(self.platform.is_dir(path))
      if self.platform.is_local:
        self.assertTrue(path.is_dir())
      with self.assertRaisesRegex(Exception, str(path.parent)):
        self.platform.rm(path.parent)
      self.platform.rm(path.parent, dir=True)
      self.assertFalse(self.platform.exists(path))
      if self.platform.is_local:
        self.assertFalse(pathlib.Path(path).parent.exists())

  def test_mkdtemp(self):
    result = self.platform.mkdtemp(prefix="a_custom_prefix")
    self.assertTrue(self.platform.is_dir(result))
    self.assertIn("a_custom_prefix", result.name)
    self.platform.rm(result, dir=True)
    self.assertFalse(self.platform.exists(result))

  def test_mkdtemp_dir(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      result = self.platform.mkdtemp(dir=tmp_dir)
      self.assertTrue(self.platform.is_dir(result))
      self.assertTrue(result.is_relative_to(tmp_dir))
    self.assertFalse(self.platform.exists(result))

  def test_mktemp(self):
    result = self.platform.mktemp(prefix="a_custom_prefix")
    self.assertTrue(self.platform.is_file(result))
    self.assertIn("a_custom_prefix", result.name)
    self.platform.rm(result)
    self.assertFalse(self.platform.exists(result))

  def test_mktemp_dir(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      result = self.platform.mktemp(dir=tmp_dir)
      self.assertTrue(self.platform.is_file(result))
      self.assertTrue(result.is_relative_to(tmp_dir))
    self.assertFalse(self.platform.exists(result))

  def test_exists(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      self.assertTrue(self.platform.exists(tmp_dir))
      self.assertFalse(self.platform.exists(tmp_dir / "foo"))

  def test_touch(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = tmp_dir / "test.txt"
      if self.platform.is_local:
        self.assertFalse(tmp_file.exists())
      self.assertFalse(self.platform.exists(tmp_file))
      self.platform.touch(tmp_file)
      if self.platform.is_local:
        self.assertTrue(tmp_file.exists())
      self.assertTrue(self.platform.exists(tmp_file))
      if self.platform.is_local:
        self.assertEqual(tmp_file.stat().st_size, 0)

  def test_rename(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = tmp_dir / "test.txt"
      tmp_file_renamed = tmp_file.with_name("test_renamed.txt")
      self.platform.touch(tmp_file)
      if self.platform.is_local:
        self.assertTrue(tmp_file.exists())
        self.assertFalse(tmp_file_renamed.exists())
      self.assertTrue(self.platform.exists(tmp_file))
      self.assertFalse(self.platform.exists(tmp_file_renamed))

      result = self.platform.rename(tmp_file, tmp_file_renamed)
      self.assertEqual(result, tmp_file_renamed)
      if self.platform.is_local:
        self.assertFalse(tmp_file.exists())
        self.assertTrue(tmp_file_renamed.exists())
      self.assertFalse(self.platform.exists(tmp_file))
      self.assertTrue(self.platform.exists(tmp_file_renamed))

  def test_gzip(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      test_file = tmp_dir / "test.txt"
      content = "Hello, Crossbench gzip test!"
      self.platform.write_text(test_file, content)
      self.assertTrue(self.platform.exists(test_file))

      gz_file = self.platform.gzip(test_file)
      self.assertEqual(gz_file, test_file.with_name(f"{test_file.name}.gz"))
      self.assertTrue(self.platform.exists(gz_file))
      self.assertFalse(self.platform.exists(test_file))

      if self.platform.is_local:
        with gzip.open(
            self.platform.local_path(gz_file), "rt", encoding="utf-8") as f:
          self.assertEqual(f.read(), content)

  def test_gzip_python_fallback(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      test_file = tmp_dir / "test_fallback.txt"
      content = "Testing python gzip fallback!"
      self.platform.write_text(test_file, content)
      self.assertTrue(self.platform.exists(test_file))

      with mock.patch.object(self.platform, "which", return_value=None):
        if self.platform.is_remote:
          with self.assertRaises(RuntimeError):
            self.platform.gzip(test_file)
          return
        gz_file = self.platform.gzip(test_file)

      self.assertEqual(gz_file, test_file.with_name(f"{test_file.name}.gz"))
      self.assertTrue(self.platform.exists(gz_file))
      self.assertFalse(self.platform.exists(test_file))

      with gzip.open(
          self.platform.local_path(gz_file), "rt", encoding="utf-8") as f:
        self.assertEqual(f.read(), content)

  def test_default_tmp_dir(self):
    self.assertTrue(self.platform.is_dir(self.platform.default_tmp_dir))

  def test_NamedTemporaryFile(self):  # noqa: N802
    with self.platform.NamedTemporaryFile() as path:
      self.assertTrue(self.platform.is_file(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

    with self.platform.NamedTemporaryFile("custom_suffix") as path:
      self.assertTrue(path.name.endswith("custom_suffix"), path.name)
      self.assertTrue(self.platform.is_file(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

    with self.platform.NamedTemporaryFile("AaA", "BbB") as path:
      self.assertTrue(path.name.startswith("BbB"))
      self.assertTrue(path.name.endswith("AaA"))
      self.assertTrue(self.platform.is_file(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

  def test_TemporaryDirectory(self):  # noqa: N802
    with self.platform.TemporaryDirectory() as path:
      self.assertTrue(self.platform.is_dir(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

    with self.platform.TemporaryDirectory("custom_suffix") as path:
      self.assertTrue(path.name.endswith("custom_suffix"), path.name)
      self.assertTrue(self.platform.is_dir(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

    with self.platform.TemporaryDirectory("AaA", "BbB") as path:
      self.assertTrue(path.name.startswith("BbB"))
      self.assertTrue(path.name.endswith("AaA"))
      self.assertTrue(self.platform.is_dir(path))
      self.assertTrue(self.platform.exists(path))
    self.assertFalse(self.platform.exists(path))

  def test_copy(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      src_file = tmp_dir / "src.txt"
      dst_file = tmp_dir / "dst.txt"
      with self.assertRaises(ValueError) as cm:
        self.assertFalse(self.platform.exists(src_file))
        self.platform.copy(src_file, dst_file)
      self.assertIn(str(src_file), str(cm.exception))
      self.assertFalse(self.platform.exists(src_file))
      self.assertFalse(self.platform.exists(dst_file))

      self.platform.write_text(src_file, "some data")
      self.assertTrue(self.platform.exists(src_file))
      self.platform.copy(src_file, dst_file)
      self.assertTrue(self.platform.exists(src_file))
      self.assertTrue(self.platform.exists(dst_file))
      self.assertEqual(self.platform.cat(src_file), "some data")
      self.assertEqual(self.platform.cat(dst_file), "some data")
      # Copying the same file should have no effect:
      self.platform.copy(src_file, src_file)
      self.platform.copy(dst_file, dst_file)
      self.assertEqual(self.platform.cat(src_file), "some data")
      self.assertEqual(self.platform.cat(dst_file), "some data")

  def test_copy_dir(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      src_file = tmp_dir / "src/file.txt"
      dst_file = tmp_dir / "dst/file.txt"
      src_dir = src_file.parent
      dst_dir = dst_file.parent
      with self.assertRaises(ValueError) as cm:
        self.assertFalse(self.platform.exists(src_dir))
        self.platform.copy(src_dir, dst_dir)
      self.assertIn(str(src_dir), str(cm.exception))
      self.assertFalse(self.platform.exists(src_dir))
      self.assertFalse(self.platform.exists(dst_dir))

      self.platform.mkdir(src_dir)
      self.platform.write_text(src_file, "some data")
      self.assertTrue(self.platform.exists(src_file))

      self.platform.copy(src_dir, dst_dir)
      self.assertTrue(self.platform.exists(src_file))
      self.assertTrue(self.platform.exists(dst_file))
      self.assertEqual(self.platform.cat(src_file), "some data")
      self.assertEqual(self.platform.cat(dst_file), "some data")
      # Copying the same file should have no effect:
      self.platform.copy(src_dir, src_dir)
      self.platform.copy(dst_dir, dst_dir)
      self.assertEqual(self.platform.cat(src_file), "some data")
      self.assertEqual(self.platform.cat(dst_file), "some data")

  def test_home(self):
    if self.platform.is_local:
      self.assertEqual(self.platform.home(), pathlib.Path.home())
    else:
      self.assertTrue(self.platform.is_dir(self.platform.home()))

  def test_expanduser(self) -> None:
    home: pth.AnyPath | None
    try:
      home = self.platform.home()
    except RuntimeError:
      home = None

    if home is not None:
      self._compare_expanded("~", home)
    else:
      with self.assertRaises(RuntimeError):
        self.platform.expanduser("~")

    if home is not None:
      self._compare_expanded("~/foo", home / "foo")
    else:
      with self.assertRaises(RuntimeError):
        self.platform.expanduser("~/foo")

  def test_expanduser_no_home(self) -> None:
    self._compare_expanded("~~", "~~")
    self._compare_expanded("~~/foo", "~~/foo")
    self._compare_expanded("foo", "foo")
    self._compare_expanded("foo/bar", "foo/bar")
    self._compare_expanded("foo/~bar", "foo/~bar")

  def _compare_expanded(self, lhs: str, rhs: pth.AnyPathLike) -> None:
    self.assertEqual(self.platform.expanduser(lhs), self.platform.path(rhs))

  def test_absolute_absolute(self):
    if self.platform.is_win:
      absolute_path = pathlib.Path("C:/foo")
    else:
      absolute_path = pathlib.Path("/foo")
    self.assertTrue(absolute_path.is_absolute())
    self.assertEqual(self.platform.absolute(absolute_path), absolute_path)

  def test_absolute_relative(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    relative_path = pathlib.Path("../../foo")
    self.assertFalse(relative_path.is_absolute())
    self.assertEqual(
        self.platform.absolute(relative_path), relative_path.absolute())

  def test_glob(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    with self.platform.TemporaryDirectory() as tmp_dir:
      self.assertFalse(list(self.platform.glob(tmp_dir, "*")))
      a = tmp_dir / "a"
      b = tmp_dir / "b"
      self.platform.touch(a)
      self.platform.touch(b)
      self.assertSequenceEqual(sorted(self.platform.glob(tmp_dir, "*")), [a, b])

  def test_write_text(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = tmp_dir / "test.txt"
      self.assertFalse(self.platform.exists(tmp_file))
      self.platform.mkdir(tmp_file.parent)
      self.platform.touch(tmp_file)
      self.assertFalse(self.platform.cat(tmp_file))

      self.platform.write_text(tmp_file, "こんにちは")
      self.assertTrue(self.platform.exists(tmp_file))
      self.assertEqual(self.platform.cat(tmp_file), "こんにちは")

  def test_write_text_dir(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    with self.platform.TemporaryDirectory() as tmp_dirname:
      self.assertTrue(self.platform.is_dir(tmp_dirname))
      tmp_dir_path = self.platform.path(tmp_dirname)
      self.assertTrue(self.platform.is_dir(tmp_dir_path))
      with self.assertRaises(Exception) as cm:
        self.platform.write_text(tmp_dirname, "data")
      self.assertIn(tmp_dir_path.name, str(cm.exception))

  def test_write_bytes(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = tmp_dir / "test.txt"
      self.assertFalse(self.platform.exists(tmp_file))
      self.platform.mkdir(tmp_file.parent)
      self.platform.touch(tmp_file)
      self.assertFalse(self.platform.cat_bytes(tmp_file))

      self.platform.write_bytes(tmp_file, b"custom data")
      self.assertTrue(self.platform.exists(tmp_file))
      self.assertEqual(self.platform.cat_bytes(tmp_file), b"custom data")

  def test_path_tests(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      self.assertTrue(self.platform.exists(tmp_dir))
      self.assertTrue(self.platform.is_dir(tmp_dir))
      self.assertFalse(self.platform.is_file(tmp_dir))

      foo_dir = tmp_dir / "foo"
      self.assertFalse(self.platform.exists(foo_dir))
      self.assertFalse(self.platform.is_dir(foo_dir))
      self.assertFalse(self.platform.is_file(foo_dir))
      self.platform.mkdir(foo_dir)
      self.assertTrue(self.platform.exists(foo_dir))
      self.assertTrue(self.platform.is_dir(foo_dir))
      self.assertFalse(self.platform.is_file(foo_dir))

      bar_file = tmp_dir / "bar.txt"
      self.assertFalse(self.platform.exists(bar_file))
      self.assertFalse(self.platform.is_dir(bar_file))
      self.assertFalse(self.platform.is_file(bar_file))
      self.platform.touch(bar_file)
      self.assertTrue(self.platform.exists(bar_file))
      self.assertFalse(self.platform.is_dir(bar_file))
      self.assertTrue(self.platform.is_file(bar_file))

  def test_chmod(self):
    if self.platform.is_remote:
      return
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = pth.LocalPath(tmp_dir) / "test.txt"
      self.assertFalse(self.platform.exists(tmp_file))
      self.platform.write_text(tmp_file, "")
      mode = 0o400
      self.platform.chmod(tmp_file, mode)
      self.assertEqual(tmp_file.stat()[stat.ST_MODE] & mode, mode)
      mode = 0o600
      self.assertNotEqual(tmp_file.stat()[stat.ST_MODE] & mode, mode)
      self.platform.chmod(tmp_file, mode)
      self.assertEqual(tmp_file.stat()[stat.ST_MODE] & mode, mode)

  @contextlib.contextmanager
  def _mock_default_cache_dir(self) -> Iterator[pth.AnyPath]:
    # Isolate DEFAULT_CACHE_DIR per test to avoid races in parallel runs.
    old_cache_dir_root = self.platform._cache_dir_root
    self.platform._cache_dir_root = None
    try:
      with self.platform.TemporaryDirectory() as tmp_dir:
        default_cache_dir = tmp_dir / "cache"
        with mock.patch("crossbench.plt.base.DEFAULT_CACHE_DIR",
                        default_cache_dir):
          yield default_cache_dir
    finally:
      self.platform._cache_dir_root = old_cache_dir_root

  def test_cache_dir(self):
    with self._mock_default_cache_dir() as tmp_cache_dir:
      self.platform.set_cache_dir(tmp_cache_dir)
      cache_dir = self.platform.cache_dir("test")
      self.assertTrue(self.platform.is_dir(cache_dir))
      self.assertEqual(cache_dir.parent, tmp_cache_dir)

  def test_default_local_cache_dir(self):
    if self.platform.is_remote:
      return
    self.assertEqual(DEFAULT_CACHE_DIR, pth.ROOT_DIR / "cache")
    with self._mock_default_cache_dir() as mock_default_cache_dir:
      self.assertFalse(self.platform.exists(mock_default_cache_dir))
      cache_dir = self.platform.local_cache_dir()
      self.assertTrue(self.platform.is_dir(cache_dir))
      self.assertEqual(cache_dir, mock_default_cache_dir)

  def test_local_cache_dir(self):
    if self.platform.is_remote:
      return
    with self._mock_default_cache_dir() as mock_default_cache_dir:
      self.assertFalse(self.platform.exists(mock_default_cache_dir))
      cache_dir = self.platform.local_cache_dir("test")
      self.assertTrue(self.platform.is_dir(cache_dir))
      self.assertEqual(cache_dir.parent, mock_default_cache_dir)

  def test_has_display(self):
    self.assertIn(self.platform.has_display, (True, False))

  def test_processes(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    if self.platform.is_win:
      self.skipTest("Too Slow on windows")
    processes = self.platform.processes(["name"])
    self.assertTrue(processes)
    for process_info in processes:
      self.assertIn("name", process_info)
      self.assertEqual(set(process_info.keys()), {"name"})

    # Test with multiple attributes
    processes_multi = self.platform.processes(["pid", "name"])
    self.assertTrue(processes_multi)
    for process_info in processes_multi:
      self.assertIn("name", process_info)
      self.assertIn("pid", process_info)
      self.assertEqual(set(process_info.keys()), {"pid", "name"})

  def test_processes_forwards_attrs_to_as_dict(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")

    class FakeProcess:

      def __init__(self) -> None:
        self.attrs: list[str] | None = None

      def as_dict(self, attrs: list[str] | None = None) -> dict[str, str]:
        assert attrs
        self.attrs = attrs
        return {attr: attr for attr in attrs}

    fake_process = FakeProcess()
    attrs = ["name", "pid"]
    with mock.patch(
        "crossbench.plt.base.psutil.process_iter",
        return_value=[fake_process]) as process_iter:
      processes = self.platform.processes(attrs)

    process_iter.assert_called_once_with(attrs=attrs)
    self.assertEqual(fake_process.attrs, attrs)
    self.assertSequenceEqual(processes, [{"name": "name", "pid": "pid"}])

  def test_process_running(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    if self.platform.is_win:
      self.skipTest("Too Slow on windows")
    self.assertFalse(self.platform.process_running([]))
    self.assertFalse(
        self.platform.process_running(["crossbench_invalid_test_bin"]))
    executable = pathlib.Path(sys.executable)
    self.assertTrue(self.platform.process_running([executable.name]))

  def test_process_info(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    process_info = self.platform.process_info(os.getpid())
    self.assertIn("python", process_info["name"].lower())

    # Test with explicit attrs
    process_info_attrs = self.platform.process_info(
        os.getpid(), attrs=["pid", "name"])
    self.assertIsNotNone(process_info_attrs)
    self.assertSetEqual(set(process_info_attrs.keys()), {"pid", "name"})
    self.assertIn("python", process_info_attrs["name"].lower())

  def test_process_children(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    process_info = self.platform.process_children(os.getpid())
    self.assertIsInstance(process_info, list)
    process_info = self.platform.process_children(os.getpid(), recursive=True)
    self.assertIsInstance(process_info, list)

  def test_process_children_forwards_attrs_to_as_dict(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")

    class FakeProcess:

      def __init__(self) -> None:
        self.attrs: list[str] | None = None

      def as_dict(self, attrs: list[str] | None = None) -> dict[str, str]:
        assert attrs
        assert not self.attrs
        self.attrs = attrs
        return {attr: attr for attr in attrs}

    class FakeParentProcess:

      def __init__(self, children: list[FakeProcess]) -> None:
        self._children = children

      def children(self, recursive: bool = False) -> list[FakeProcess]:
        return self._children

    fake_child = FakeProcess()
    fake_parent = FakeParentProcess([fake_child])
    attrs = ["name", "pid"]
    with mock.patch(
        "crossbench.plt.base.psutil.Process",
        return_value=fake_parent) as process_mock:
      children = self.platform.process_children(1234, attrs=attrs)

    process_mock.assert_called_once_with(1234)
    self.assertEqual(fake_child.attrs, attrs)
    self.assertEqual(children, [{"name": "name", "pid": "pid"}])

  def test_get_free_port(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    port = self.platform.get_free_port()
    self.assertGreater(port, 0)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
      s.bind(("localhost", port))
      self.assertNotEqual(port, self.platform.get_free_port())

  def test_is_port_used(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    port = self.platform.get_free_port()
    self.assertFalse(self.platform.is_port_used(port))
    with socket.create_server(("localhost", port)):
      self.assertTrue(self.platform.is_port_used(port))

  def test_wait_for_port(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    port = self.platform.get_free_port()
    with self.assertRaises(TimeoutError):
      self.platform.wait_for_port(port, timeout=dt.timedelta(seconds=0.01))

  def test_wait_for_port_active(self):
    if self.platform.is_remote:
      self.skipTest("Not supported yet on remote platforms.")
    port = self.platform.get_free_port()
    with socket.create_server(("localhost", port)):
      self.platform.wait_for_port(port, timeout=dt.timedelta(seconds=0.01))

  @unittest.skipIf(
      not plt.PLATFORM.which("python3"), reason="python3 not installed")
  def test_binary_lookup_override(self):
    test_binary = "crossbench-non-existing-test-binary"
    self.assertIsNone(self.platform.lookup_binary_override(test_binary))
    self.assertIsNone(self.platform.which(test_binary))
    # Use an arbitrary existing binary for testing.
    override_binary = self.platform.which(self.known_binary)
    self.assertTrue(override_binary)
    with self.platform.override_binary(test_binary, override_binary):
      self.assertEqual(self.platform.which(test_binary), override_binary)
      with self.platform.override_binary(test_binary, None):
        self.assertIsNone(self.platform.lookup_binary_override(test_binary))
        self.assertIsNone(self.platform.which(test_binary))
      self.assertEqual(self.platform.which(test_binary), override_binary)
    self.assertIsNone(self.platform.lookup_binary_override(test_binary))
    self.assertIsNone(self.platform.which(test_binary))

  @unittest.skipIf(
      not plt.PLATFORM.which("python3"), reason="python3 not installed")
  def test_binary_lookup_override_home_dir(self):
    # Test overriding a binary in the home directory
    test_binary_home = "~/crossbench-non-existing-test-binary"

    self.assertIsNone(self.platform.lookup_binary_override(test_binary_home))
    self.assertIsNone(self.platform.which(test_binary_home))

    override_binary = self.platform.which(self.known_binary)
    self.assertTrue(override_binary)

    with self.platform.override_binary(test_binary_home, override_binary):
      self.assertEqual(self.platform.which(test_binary_home), override_binary)

  def test_signals(self):
    for signal_name in dir(self.platform.signals):
      if not signal_name.startswith("SIG"):
        continue
      value = getattr(self.platform.signals, signal_name)
      native_value = getattr(signal, signal_name)
      self.assertEqual(value, native_value,
                       f"Mismatching values for {signal_name}")

  def test_uptime(self):
    uptime: dt.timedelta = self.platform.uptime()
    self.assertLess(0, uptime.total_seconds())


class PosixNativePlatformTestCase(BaseNativePlatformTestCase):
  platform: PosixPlatform
  # MacOs has custom subclass
  __test__ = plt.PLATFORM.is_posix and not plt.PLATFORM.is_macos

  @override
  def setUp(self):
    super().setUp()
    assert isinstance(plt.PLATFORM, PosixPlatform)
    self.platform: PosixPlatform = plt.PLATFORM

  def test_sh(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      self.platform.touch(tmp_dir / "file")
      ls = self.platform.sh_stdout("ls", tmp_dir)
      self.assertEqual(ls, "file\n")
      lsa = self.platform.sh_stdout("ls", "-a", tmp_dir)
      self.assertTrue(lsa)
      self.assertNotEqual(ls, lsa)

  def test_sh_input(self):
    hello_world = self.platform.sh_stdout("cat", input=b"hello world")
    self.assertEqual(hello_world, "hello world")
    hello_world_bytes = self.platform.sh_stdout_bytes(
        "cat", input=b"hello world bytes")
    self.assertEqual(hello_world_bytes, b"hello world bytes")

  def test_sh_bytes(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      self.platform.touch(tmp_dir / "file")
      ls_bytes = self.platform.sh_stdout_bytes("ls", tmp_dir)
      self.assertIsInstance(ls_bytes, bytes)
      ls_str = self.platform.sh_stdout("ls", tmp_dir)
      self.assertEqual(ls_str, ls_bytes.decode("utf-8"))
      self.assertEqual(ls_str, "file\n")

  def test_which(self):
    ls_bin = self.platform.which("ls")
    self.assertIsNotNone(ls_bin)
    known_binary = self.platform.which(self.known_binary)
    self.assertIsNotNone(known_binary)
    self.assertNotEqual(ls_bin, known_binary)
    self.assertTrue(self.platform.exists(ls_bin))
    self.assertTrue(self.platform.exists(known_binary))

  def test_system_details(self):
    details = self.platform.system_details()
    self.assertTrue(details)
    self.assertTrue(json.dumps(details))
    if not self.platform.is_remote:
      self.assertIn("crossbench", details)

  def test_crossbench_details(self):
    self.platform.crossbench_details.cache_clear()
    if self.platform.is_remote:
      with self.assertRaises(RuntimeError):
        self.platform.crossbench_details()
      return
    details = self.platform.crossbench_details()
    self.assertTrue(details)
    self.assertTrue(json.dumps(details))
    self.assertEqual(details["version"], __version__)
    for key, expected_type in (
        ("current_hash", str),
        ("canonical_parent_hash", str),
        ("has_uncommitted_changes", bool),
    ):
      self.assertIn(key, details)
      self.assertIsInstance(details[key], expected_type)

  def test_crossbench_details_no_git_binary(self):
    if self.platform.is_remote:
      return
    self.platform.crossbench_details.cache_clear()
    with mock.patch("shutil.which", return_value=None):
      details = self.platform.crossbench_details()
      self.assertDictEqual(details, {"version": __version__})

  def test_crossbench_details_no_git_dir(self):
    if self.platform.is_remote:
      return
    self.platform.crossbench_details.cache_clear()
    fake_root = pth.LocalPath("/non/existent/crossbench/root")
    with mock.patch.object(pth, "ROOT_DIR", new=fake_root):
      details = self.platform.crossbench_details()
      self.assertDictEqual(details, {"version": __version__})

  def test_crossbench_details_git_error(self):
    if self.platform.is_remote:
      return
    self.platform.crossbench_details.cache_clear()
    failed_proc = mock.Mock(returncode=128, stdout=b"", stderr=b"")
    with mock.patch("subprocess.run", return_value=failed_proc):
      details = self.platform.crossbench_details()
      self.assertEqual(details["version"], __version__)
      self.assertEqual(details["current_hash"], "")
      self.assertEqual(details["canonical_parent_hash"], "")
      self.assertFalse(details["has_uncommitted_changes"])

  def test_os_details(self):
    details = self.platform.os_details()
    self.assertTrue(details)
    self.assertTrue(json.dumps(details))
    self.assertIn("system", details)
    self.assertIn("release", details)
    self.assertIn("version", details)

  def test_cpu_details(self):
    details = self.platform.cpu_details()
    self.assertTrue(details)
    self.assertTrue(json.dumps(details))
    self.assertIn("info", details)
    self.assertIn("physical cores", details)
    self.assertIn("logical cores", details)
    self.assertIn("min frequency", details)
    self.assertIn("max frequency", details)

  def test_python_details(self):
    details = self.platform.python_details()
    self.assertTrue(details)
    self.assertTrue(json.dumps(details))
    self.assertIn("version", details)

  def test_search_binary(self):
    result_path = self.platform.search_binary(pathlib.Path("ls"))
    self.assertIsNotNone(result_path)
    self.assertIn("ls", result_path.parts)
    self.assertTrue(self.platform.exists(result_path))

  def test_search_binary_posix_lookup_override(self):
    path = pathlib.Path("ls")
    overridden_binary = self.platform.which("cp")
    with self.platform.override_binary(path, overridden_binary):
      result_path = self.platform.search_binary(path)
      self.assertEqual(result_path, overridden_binary)
      self.assertTrue(self.platform.exists(result_path))

    result_path_2 = self.platform.search_binary(path)
    self.assertNotEqual(result_path_2, result_path)
    self.assertTrue(self.platform.exists(result_path_2))
    self.assertIsNone(self.platform.lookup_binary_override(path))

  def test_environ(self):
    env = self.platform.environ
    self.assertTrue(env)
    self.assertIn("PATH", env)
    self.assertTrue(list(env))

  def test_environ_set_property_fails_on_remote(self):
    if self.platform.is_local:
      return
    env = self.platform.environ
    custom_key = f"CROSSBENCH_TEST_KEY_{len(env)}"
    self.assertNotIn(custom_key, env)
    with self.assertRaises(NotImplementedError):
      env[custom_key] = 1234
    with self.assertRaises(NotImplementedError):
      env[custom_key] = "1234"

  def test_environ_set_property(self):
    if self.platform.is_remote:
      return
    env = self.platform.environ
    custom_key = f"CROSSBENCH_TEST_KEY_{len(env)}"
    self.assertNotIn(custom_key, env)
    with self.assertRaises(TypeError):
      env[custom_key] = 1234
    env[custom_key] = "1234"
    self.assertEqual(env[custom_key], "1234")
    self.assertIn(custom_key, env)
    del env[custom_key]
    self.assertNotIn(custom_key, env)

  def test_app_version(self):
    python_path = sys.executable
    with self.assertRaises(ValueError):
      self.platform.app_version("path/to/invalid/test/crossbench/bin")
    version = self.platform.app_version(python_path)
    self.assertTrue(version)

  def test_last_modified(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      tmp_file = tmp_dir / "test.txt"
      self.platform.touch(tmp_file)
      last_modified_timestamp = self.platform.last_modified(tmp_file)
      self.assertGreater(last_modified_timestamp, 0)
      # Sleep 1 second as the `stat` command used on posix platforms only has
      # second-level precision for file modification times.
      self.platform.sleep(1)
      self.platform.touch(tmp_file)
      new_last_modified_timestamp = self.platform.last_modified(tmp_file)
      self.assertGreater(new_last_modified_timestamp, last_modified_timestamp)

  def test_shell_piping(self):
    with self.platform.NamedTemporaryFile() as file:
      result = self.platform.sh_stdout(
          f"echo 'test data' > {file} && cat {file}", shell=True)
      self.assertEqual(result, "test data\n")

  def test_simple_shell_status_ok(self):
    self.platform.sh("ls", shell=False)
    self.platform.sh("ls && ls", shell=True)
    self.assertTrue(self.platform.sh_stdout("ls", shell=False))
    self.assertTrue(self.platform.sh_stdout("ls && ls", shell=True))

  def test_simple_shell_fail(self):
    with self.assertRaises(SubprocessError):
      self.platform.sh("ls", "path/to/invalid/test/crossbench/dir", shell=False)
    with self.assertRaises(SubprocessError):
      self.platform.sh(
          "ls path/to/invalid/test/crossbench/dir && ls", shell=True)
    with self.assertRaises(SubprocessError):
      self.platform.sh_stdout(
          "ls", "path/to/invalid/test/crossbench/dir", shell=False)
    with self.assertRaises(SubprocessError):
      self.platform.sh_stdout(
          "ls path/to/invalid/test/crossbench/dir && ls", shell=True)

  def test_simple_shell_fail_ignore(self):
    self.platform.sh(
        "ls", "path/to/invalid/test/crossbench/dir", shell=False, check=False)
    self.platform.sh(
        "ls path/to/invalid/test/crossbench/dir && ls", shell=True, check=False)
    self.assertEqual(
        self.platform.sh_stdout(
            "ls",
            "path/to/invalid/test/crossbench/dir",
            shell=False,
            check=False), "")
    self.assertEqual(
        self.platform.sh_stdout(
            "ls path/to/invalid/test/crossbench/dir && ls",
            shell=True,
            check=False), "")

  def test_popen_watch(self):
    with self.platform.popen("sleep", "5") as popen:
      self.assertIn(popen, self.platform.active_popens)
      self.assertTrue(popen.pid)
      self.assertTrue(self.platform.host_platform.process_info(popen.pid))
      self.assertTrue(self.platform.process_info(popen))
      popen.kill()

  def test_popen_encoding(self):
    if self.platform.is_remote:
      self.skipTest("Missing remote platform popen")
      return
    proc = self.platform.popen(
        sys.executable,
        "-c",
        "print('hello from popen')",
        stdout=subprocess.PIPE,
        encoding="utf-8")
    try:
      assert proc.stdout
      self.assertEqual(proc.stdout.read().strip(), "hello from popen")
    finally:
      self.platform.terminate(proc)

  def test_popen_auto_terminate_false(self):
    with self.platform.popen("sleep", "5", auto_terminate=False) as proc:
      self.assertNotIn(proc, self.platform.active_popens)
      proc.kill()

  def test_popen_weaklist_gc(self):

    def spawn() -> int:
      with self.platform.popen("true") as proc:
        return proc.pid

    pid = spawn()
    gc.collect()
    active_pids = [p.pid for p in self.platform.active_popens]
    self.assertNotIn(pid, active_pids)

  def test_kill_all_popens(self):
    with (self.platform.popen("sleep", "5") as
          proc1, self.platform.popen("sleep", "5") as proc2):
      self.assertIn(proc1, self.platform.active_popens)
      self.assertIn(proc2, self.platform.active_popens)
      self.platform.kill_all_popens()
      proc1.wait(timeout=2)
      proc2.wait(timeout=2)
      self.assertEqual(self.platform.active_popens, ())
      self.assertIsNotNone(proc1.poll())
      self.assertIsNotNone(proc2.poll())
      self.assertIsNone(self.platform.process_info(proc1))
      self.assertIsNone(self.platform.process_info(proc2))

  def test_display_details(self):
    displays = self.platform.display_details()
    if not self.platform.has_display:
      self.assertFalse(displays)
      return
    self.assertTrue(displays)
    self.assertTrue(json.dumps(displays))
    for display in displays:
      resolution = display["resolution"]
      self.assertIsInstance(resolution, DisplayResolution)
      self.assertGreater(resolution.width, 0)
      self.assertGreater(resolution.height, 0)
      refresh_rate = display["refresh_rate"]
      if refresh_rate != -1.0:
        self.assertGreater(refresh_rate, 0)
    # cached
    displays_2 = self.platform.display_details()
    self.assertIs(displays, displays_2)


class MockRemotePosixPlatform(RemotePosixPlatform, type(plt.PLATFORM)):

  def __init__(self) -> None:
    super().__init__(plt.PLATFORM)

  @override
  def _create_port_manager(self) -> PortManager:
    return MockRemotePortManager(self)

  @override
  def local_path(self, path):
    # override to bypass is_local checks
    return pathlib.Path(path)

  @override
  def build_shell_cmd(self, *args, shell: bool = False, env=None, cwd=None):
    del env, cwd
    if shell:
      return ["sh", "-c", str(args[0])]
    return [str(arg) for arg in args]

  @override
  def sh(self, *args, **kwargs):
    return plt.PLATFORM.sh(*args, **kwargs)

  @override
  def sh_stdout(self, *args, **kwargs):
    return plt.PLATFORM.sh_stdout(*args, **kwargs)

  def push(self, from_path, to_path):
    return self.copy_file(from_path, to_path)


class MockRemotePosixPlatformTestCase(PosixNativePlatformTestCase):
  """All Posix operations should also work on a remote platform (e.g. via SSH).
  This test fakes this by temporarily changing the current PLATFORM's is_remote
  getter to return True"""
  __test__ = plt.PLATFORM.is_posix

  @override
  def setUp(self):
    super().setUp()
    self.platform = MockRemotePosixPlatform()

  def test_is_remote(self):
    self.assertTrue(self.platform.is_remote)

  def tests_default_tmp_dir(self):
    self.assertEqual(self.platform.default_tmp_dir,
                     plt.PLATFORM.default_tmp_dir)

  def test_environ_set_property(self):
    raise self.skipTest("Not supported on remote platforms")

  def test_cpu_usage(self):
    raise self.skipTest("Not supported on remote platforms")

  def test_chmod(self):
    with tempfile.TemporaryDirectory() as tmp_dirname:
      tmp_dir = pathlib.Path(tmp_dirname)
      tmp_file = tmp_dir / "test.txt"
      self.assertFalse(self.platform.exists(tmp_file))
      self.platform.touch(tmp_file)
      self.assertNotEqual(tmp_file.stat()[stat.ST_MODE] & 0o755, 0o755)
      self.platform.chmod(tmp_file, 0o755)
      self.assertEqual(tmp_file.stat()[stat.ST_MODE] & 0o755, 0o755)

  def test_remote_popen_kill_sends_remote_signal(self):
    with self.platform.popen("sleep", "5") as proc:
      self.assertIsInstance(proc, RemotePopen)
      self.assertNotEqual(proc.remote_pid, proc.pid)
      self.assertIn(proc, self.platform.active_popens)
      self.assertNotIn(proc, self.platform.host_platform.active_popens)
      with (mock.patch.object(self.platform, "sh", wraps=self.platform.sh) as
            mock_sh, mock.patch("subprocess.Popen.send_signal") as
            mock_local_send_signal):
        self.platform.kill_all_popens()
      mock_local_send_signal.assert_not_called()
      mock_sh.assert_called_once_with(
          "kill", "-9", str(proc.remote_pid), check=False, capture_output=True)
      proc.wait(timeout=2)
      self.assertEqual(self.platform.active_popens, ())
      self.assertIsNone(self.platform.process_info(proc.remote_pid))
      self.assertIsNone(self.platform.host_platform.process_info(proc.pid))


class MacOSNativePlatformTestCase(PosixNativePlatformTestCase):
  platform: plt.MacOSPlatform
  __test__ = plt.PLATFORM.is_macos

  @override
  def setUp(self):
    super().setUp()
    assert isinstance(plt.PLATFORM, plt.MacOSPlatform)
    self.platform = plt.PLATFORM

  def test_set_display_refresh_rate(self):
    if not self.platform.has_display:
      self.skipTest("No display")
    displays = self.platform.display_details()
    if not displays:
      self.skipTest("No displays")
    rate = displays[0].get("refresh_rate")
    if rate is None or rate <= 0:
      self.skipTest("Refresh rate not supported")

    with mock.patch.object(self.platform, "sleep") as mock_sleep:
      success, _ = self.platform.set_display_refresh_rate(rate)
      self.assertTrue(success)
      mock_sleep.assert_not_called()

  def test_search_app_binary_not_found(self):
    binary = self.platform.search_binary(pathlib.Path("Invalid App Name"))
    self.assertIsNone(binary)
    binary = self.platform.search_binary(pathlib.Path("Non-existent App.app"))
    self.assertIsNone(binary)

  def test_search_app_binary(self):
    binary = self.platform.search_binary(pathlib.Path("Safari.app"))
    self.assertIsNotNone(binary)
    self.assertTrue(self.platform.is_file(binary))
    # We should get the binary not the app bundle
    self.assertFalse(binary.suffix, ".app")
    self.assertEqual(binary.name, "Safari")

  def test_search_app_binary_override(self):
    overridden_binary = pathlib.Path("/System/Applications/Calendar.app")
    with self.platform.override_binary("Safari.app", overridden_binary):
      binary = self.platform.search_binary(pathlib.Path("Safari.app"))
      self.assertIsNotNone(binary)
      self.assertTrue(self.platform.is_file(binary))
      # We should get the binary not the app bundle
      self.assertFalse(binary.suffix, ".app")
    self.assertEqual(binary.name, "Calendar")

  def test_search_app_invalid(self):
    with self.assertRaises(ValueError):
      self.platform.search_app(pathlib.Path("Invalid App Name"))

  def test_search_app_none(self):
    self.assertIsNone(self.platform.search_app(pathlib.Path("No App.app")))

  def test_search_app(self):
    binary = self.platform.search_app(pathlib.Path("Safari.app"))
    self.assertIsNotNone(binary)
    self.assertTrue(self.platform.exists(binary))
    self.assertTrue(self.platform.is_dir(binary))

  def test_search_app_override(self):
    overridden_binary = pathlib.Path("/System/Applications/Calendar.app")
    with self.platform.override_binary("Safari.app", overridden_binary):
      binary = self.platform.search_app(pathlib.Path("Safari.app"))
      self.assertIsNotNone(binary)
      self.assertTrue(self.platform.exists(binary))
      self.assertTrue(self.platform.is_dir(binary))
      self.assertEqual(binary.name, "Calendar.app")

  def test_app_version_app(self):
    app = pathlib.Path(self.platform.search_app(pathlib.Path("Safari.app")))
    self.assertIsNotNone(app)
    self.assertTrue(app.is_dir())
    version = self.platform.app_version(app)
    self.assertRegex(version, r"[0-9]+\.[0-9]+")

  def test_app_version_app_binary(self):
    binary = pathlib.Path(
        self.platform.search_binary(pathlib.Path("Safari.app")))
    self.assertIsNotNone(binary)
    self.assertTrue(binary.is_file())
    version = self.platform.app_version(binary)
    self.assertRegex(version, r"[0-9]+\.[0-9]+")

  def test_app_version_binary(self):
    binary = pathlib.Path("/usr/bin/safaridriver")
    self.assertTrue(binary.is_file())
    version = self.platform.app_version(binary)
    self.assertRegex(version, r"[0-9]+\.[0-9]+")

  def test_name(self):
    self.assertEqual(self.platform.name, "macos")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "macos")

  def test_version(self):
    self.assertTrue(self.platform.version_str)
    self.assertRegex(self.platform.version_str, r"[0-9]+\.[0-9]")

  def test_device(self):
    self.assertTrue(self.platform.model)
    self.assertRegex(self.platform.model, r"[a-zA-Z]+[0-9]+,[0-9]+")

  def test_cpu(self):
    self.assertTrue(self.platform.cpu)
    self.assertRegex(self.platform.cpu, r".* [0-9]+ cores")

  def test_foreground_process(self):
    self.assertTrue(self.platform.foreground_process())

  def test_is_macos(self):
    self.assertTrue(self.platform.is_macos)
    self.assertFalse(self.platform.is_linux)
    self.assertFalse(self.platform.is_win)
    self.assertFalse(self.platform.is_remote)

  def _platform_supports_autobrightness(self):
    if "Apple M" in plt.PLATFORM.cpu:
      self.skipTest("Skipping this due to crbug.com/396417022.")
    try:
      if self.platform.check_autobrightness():
        return
    except Exception:
      pass
    self.skipTest("Skipping test; could not check autobrightness.")

  def test_set_main_screen_brightness(self):
    self._platform_supports_autobrightness()
    prev_level = plt.PLATFORM.get_main_display_brightness()
    brightness_level = 32
    plt.PLATFORM.set_main_display_brightness(brightness_level)
    self.assertEqual(brightness_level,
                     plt.PLATFORM.get_main_display_brightness())
    plt.PLATFORM.set_main_display_brightness(prev_level)
    self.assertEqual(prev_level, plt.PLATFORM.get_main_display_brightness())

  def test_check_autobrightness(self):
    if test_helper.is_on_swarming():
      self.skipTest("Skipping this to run in CQ due to crbug.com/396405604.")
    # True or false, it should be handled gracefully (i.e. not throw).
    self.platform.check_autobrightness()

  def test_exec_apple_script(self):
    self.assertEqual(
        self.platform.exec_apple_script('copy "a value" to stdout').strip(),
        "a value")

  def test_exec_apple_script_args(self):
    result = self.platform.exec_apple_script("copy item 1 of argv to stdout",
                                             "a value", "b")
    self.assertEqual(result.strip(), "a value")
    result = self.platform.exec_apple_script("copy item 2 of argv to stdout",
                                             "a value", "b")
    self.assertEqual(result.strip(), "b")

  def test_exec_apple_script_invalid(self):
    with self.assertRaises(plt.SubprocessError):
      self.platform.exec_apple_script("something is not right 11")


class WinNativePlatformTestCase(BaseNativePlatformTestCase):
  platform: plt.WinPlatform
  __test__ = plt.PLATFORM.is_win

  @override
  def setUp(self):
    super().setUp()
    assert isinstance(plt.PLATFORM, plt.WinPlatform)
    self.platform = plt.PLATFORM

  def test_sh(self):
    ls = self.platform.sh_stdout("ls")
    self.assertTrue(ls)

  def test_search_binary(self):
    with self.assertRaises(ValueError):
      self.platform.search_binary(pathlib.Path("does not exist"))
    path = pathlib.Path(
        self.platform.search_binary(
            pathlib.Path("Windows NT/Accessories/wordpad.exe")))
    self.assertTrue(path and path.exists())

  def test_app_version(self):
    path = pathlib.Path(
        self.platform.search_binary(
            pathlib.Path("Windows NT/Accessories/wordpad.exe")))
    self.assertTrue(path and path.exists())
    version = self.platform.app_version(path)
    self.assertIsNotNone(version)

  def test_is_macos(self):
    self.assertFalse(self.platform.is_macos)
    self.assertFalse(self.platform.is_linux)
    self.assertTrue(self.platform.is_win)
    self.assertFalse(self.platform.is_remote)

  def test_has_display(self):
    self.assertIn(self.platform.has_display, (True, False))

  def test_version(self):
    self.assertTrue(self.platform.version_str)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
