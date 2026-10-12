# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest
from typing import Callable, ClassVar

from crossbench.helper.class_helper import get_all_subclasses
from crossbench.helper.version import Version, VersionParseError, \
    VersionPartsData
from tests import test_helper


class VersionTestCase(unittest.TestCase):
  VERSION_CLS: ClassVar[type[Version]] = Version

  def _version_factories(
      self) -> tuple[Callable[[VersionPartsData], Version], ...]:
    return (self.VERSION_CLS,)

  def test_basic(self):
    version = self.VERSION_CLS((1, 2, 3), version_str="1.2.3")
    self.assertEqual(version.parts, (1, 2, 3))
    self.assertEqual(version.parts_str, "1.2.3")
    self.assertEqual(version.version_str, "1.2.3")
    if version.is_complete:
      self.assertEqual(version.comparable_parts(4), (1, 2, 3))
    else:
      self.assertEqual(version.comparable_parts(4), (1, 2, 3, 0xFFFF))
    self.assertEqual(version, self.VERSION_CLS([1, 2, 3]))
    self.assertEqual(hash(version), hash(self.VERSION_CLS((1, 2, 3))))

  def test_int_parts(self):
    for factory in self._version_factories():
      version = factory(120)
      self.assertEqual(version.parts, (120,))
      self.assertEqual(version.parts_str, "120")
      self.assertEqual(version, factory((120,)))
      self.assertEqual(version, factory([120]))

  def test_invalid_parts(self):
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS(-1)
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS((1, -2))
    with self.assertRaises(VersionParseError):
      self.VERSION_CLS(None)  # type: ignore

  def test_compare_parts(self):
    self.assertLess(self.VERSION_CLS(120), self.VERSION_CLS(121))
    self.assertLess(self.VERSION_CLS((120, 0)), self.VERSION_CLS((120, 1)))
    self.assertLessEqual(self.VERSION_CLS(120), self.VERSION_CLS(120))
    self.assertNotEqual(self.VERSION_CLS(120), "120")
    with self.assertRaises(TypeError):
      _ = self.VERSION_CLS(120) <= "120"  # type: ignore

  def test_subclasses(self):
    for sub_cls in get_all_subclasses(self.VERSION_CLS):
      with self.subTest(sub_cls=sub_cls.__name__):
        version = sub_cls(120)
        self.assertEqual(version.parts, (120,))
        self.assertEqual(version.parts_str, "120")
        self.assertEqual(version, sub_cls((120,)))
        self.assertEqual(version, sub_cls([120]))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
