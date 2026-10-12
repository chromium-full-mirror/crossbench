# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import ClassVar

from crossbench.helper.version import VersionParseError
from crossbench.plt.android_adb import AndroidVersion
from crossbench.plt.macos import MacOsVersion
from crossbench.plt.posix import PosixVersion
from crossbench.plt.version import PlatformVersion
from crossbench.plt.win import WinVersion
from tests import test_helper
from tests.crossbench.helper.test_version import VersionTestCase


class PlatformVersionTestCase(VersionTestCase):
  VERSION_CLS: ClassVar[type[PlatformVersion]] = PlatformVersion

  def test_empty_parts(self):
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS(())

  def test_major(self):
    self.assertEqual(self.VERSION_CLS(120).major, 120)
    self.assertEqual(self.VERSION_CLS((120, 1)).major, 120)


class PosixVersionTestCase(PlatformVersionTestCase):
  VERSION_CLS = PosixVersion

  def test_parse(self):
    version = self.VERSION_CLS.parse("5.4.0-104-generic")
    self.assertSequenceEqual(version.parts, (5, 4, 0))
    self.assertEqual(version.version_str, "5.4.0-104-generic")
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS.parse("foo")


class MacOsVersionTestCase(PosixVersionTestCase):
  VERSION_CLS = MacOsVersion

  def test_parse(self):
    version = self.VERSION_CLS.parse("12.3.4")
    self.assertSequenceEqual(version.parts, (12, 3, 4))
    self.assertEqual(version.version_str, "12.3.4")
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS.parse("foo")


class AndroidVersionTestCase(PosixVersionTestCase):
  VERSION_CLS = AndroidVersion

  def test_parse(self):
    version = self.VERSION_CLS.parse("13 (Tiramisu)")
    self.assertSequenceEqual(version.parts, (13,))
    self.assertEqual(version.version_str, "13 (Tiramisu)")
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS.parse("foo")


class WinVersionTestCase(PlatformVersionTestCase):
  VERSION_CLS = WinVersion

  def test_parse(self):
    ver_output = "\nMicrosoft Windows [Version 10.0.22631.3593]\n"
    version = self.VERSION_CLS.parse(ver_output)
    self.assertSequenceEqual(version.parts, (10, 0, 22631, 3593))
    self.assertEqual(version.version_str, ver_output)
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS.parse("foo")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
