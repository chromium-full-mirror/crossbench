# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench.helper.size import SIZE_UNITS, Size
from tests import test_helper


class SizeTestCase(unittest.TestCase):

  def test_enum_members_and_values(self) -> None:
    self.assertIsInstance(Size.KiB, int)
    self.assertIsInstance(Size.KiB, Size)
    self.assertEqual(Size.B, 1)
    self.assertEqual(Size.KiB, 1024)
    self.assertEqual(Size.MiB, 1024 * 1024)
    self.assertEqual(Size.GiB, 1024 * 1024 * 1024)
    self.assertEqual(Size.TiB, 1024 * 1024 * 1024 * 1024)

    self.assertEqual(Size.B.name, "B")
    self.assertEqual(Size.KiB.name, "KiB")
    self.assertEqual(Size.MiB.name, "MiB")
    self.assertEqual(Size.GiB.name, "GiB")
    self.assertEqual(Size.TiB.name, "TiB")

    self.assertEqual(Size.B.value, 1)
    self.assertEqual(Size.KiB.value, 1024)
    self.assertEqual(Size.MiB.value, 1024 * 1024)
    self.assertEqual(Size.GiB.value, 1024 * 1024 * 1024)
    self.assertEqual(Size.TiB.value, 1024 * 1024 * 1024 * 1024)

  def test_enum_lookups(self) -> None:
    self.assertIs(Size(1), Size.B)
    self.assertIs(Size(1024), Size.KiB)
    self.assertIs(Size(1024 * 1024), Size.MiB)
    self.assertIs(Size(1024 * 1024 * 1024), Size.GiB)
    self.assertIs(Size(1024 * 1024 * 1024 * 1024), Size.TiB)

    self.assertIs(Size["B"], Size.B)
    self.assertIs(Size["KiB"], Size.KiB)
    self.assertIs(Size["MiB"], Size.MiB)
    self.assertIs(Size["GiB"], Size.GiB)
    self.assertIs(Size["TiB"], Size.TiB)

    with self.assertRaises(ValueError):
      Size(0)
    with self.assertRaises(ValueError):
      Size(42)
    with self.assertRaises(KeyError):
      _ = Size["KB"]
    with self.assertRaises(KeyError):
      _ = Size["MB"]

  def test_enum_iteration_and_units(self) -> None:
    members = list(Size)
    self.assertEqual(len(members), 5)
    self.assertEqual(
        members,
        [Size.B, Size.KiB, Size.MiB, Size.GiB, Size.TiB],
    )
    self.assertEqual(SIZE_UNITS, tuple(member.name for member in Size))
    for member in Size:
      self.assertIn(member, Size)
      self.assertIn(member.name, SIZE_UNITS)

  def test_size_units_order_and_values(self) -> None:
    expected_units = ("B", "KiB", "MiB", "GiB", "TiB")
    expected_values = (
        1,
        1024,
        1024 * 1024,
        1024 * 1024 * 1024,
        1024 * 1024 * 1024 * 1024,
    )
    self.assertEqual(SIZE_UNITS, expected_units)
    self.assertEqual(tuple(member.name for member in Size), expected_units)
    self.assertEqual(tuple(member.value for member in Size), expected_values)
    self.assertEqual(Size.KiB, Size.B * 1024)
    self.assertEqual(Size.MiB, Size.KiB * 1024)
    self.assertEqual(Size.GiB, Size.MiB * 1024)
    self.assertEqual(Size.TiB, Size.GiB * 1024)
    prev_val = 0
    for idx, member in enumerate(Size):
      self.assertEqual(member.name, expected_units[idx])
      self.assertEqual(member.value, expected_values[idx])
      self.assertGreater(member.value, prev_val)
      prev_val = member.value

  def test_arithmetic_and_comparison(self) -> None:
    self.assertTrue(Size.B < Size.KiB < Size.MiB < Size.GiB < Size.TiB)
    self.assertEqual(2 * Size.KiB, 2048)
    self.assertEqual(Size.MiB // Size.KiB, 1024)
    self.assertEqual(float(Size.MiB) / Size.KiB, 1024.0)
    self.assertEqual(Size.KiB + 512, 1536)
    self.assertEqual(int(Size.KiB), 1024)
    self.assertEqual(float(Size.KiB), 1024.0)

  def test_format_bytes(self) -> None:
    self.assertEqual(Size.format(0), "0.00 B")
    self.assertEqual(Size.format(0.5), "0.50 B")
    self.assertEqual(Size.format(1), "1.00 B")
    self.assertEqual(Size.format(1.23), "1.23 B")
    self.assertEqual(Size.format(100), "100.00 B")
    self.assertEqual(Size.format(100.75), "100.75 B")
    self.assertEqual(Size.format(1023), "1023.00 B")

  def test_format_kib(self) -> None:
    self.assertEqual(Size.format(1024), "1.00 KiB")
    self.assertEqual(Size.format(1234), "1.21 KiB")
    self.assertEqual(Size.format(1536), "1.50 KiB")
    self.assertEqual(Size.format(int(1.75 * Size.KiB)), "1.75 KiB")
    self.assertEqual(Size.format(2048), "2.00 KiB")
    self.assertEqual(Size.format(2500), "2.44 KiB")

  def test_format_mib(self) -> None:
    self.assertEqual(Size.format(1024 * 1024), "1.00 MiB")
    self.assertEqual(Size.format(int(1.75 * Size.MiB)), "1.75 MiB")
    self.assertEqual(Size.format(int(2.345 * Size.MiB)), "2.34 MiB")
    self.assertEqual(Size.format(int(2.5 * 1024 * 1024)), "2.50 MiB")
    self.assertEqual(Size.format(10_000_000), "9.54 MiB")

  def test_format_gib(self) -> None:
    self.assertEqual(Size.format(1024 * 1024 * 1024), "1.00 GiB")
    self.assertEqual(Size.format(int(1.75 * Size.GiB)), "1.75 GiB")
    self.assertEqual(Size.format(int(2.456 * Size.GiB)), "2.46 GiB")
    self.assertEqual(Size.format(5_000_000_000), "4.66 GiB")

  def test_format_tib(self) -> None:
    self.assertEqual(Size.format(1024 * 1024 * 1024 * 1024), "1.00 TiB")
    self.assertEqual(Size.format(int(1.75 * Size.TiB)), "1.75 TiB")
    self.assertEqual(Size.format(int(3.14159 * Size.TiB)), "3.14 TiB")
    self.assertEqual(
        Size.format(2048 * 1024 * 1024 * 1024 * 1024), "2048.00 TiB")

  def test_format_digits(self) -> None:
    self.assertEqual(Size.format(1536, digits=0), "2 KiB")
    self.assertEqual(Size.format(1536, digits=1), "1.5 KiB")
    self.assertEqual(Size.format(1536, digits=2), "1.50 KiB")
    self.assertEqual(Size.format(1536, digits=3), "1.500 KiB")
    self.assertEqual(Size.format(100, digits=0), "100 B")

  def test_format_negative(self) -> None:
    self.assertEqual(Size.format(-100), "-100.00 B")
    self.assertEqual(Size.format(-1024), "-1.00 KiB")
    self.assertEqual(Size.format(-1536, digits=1), "-1.5 KiB")
    self.assertEqual(Size.format(-1536, digits=0), "-2 KiB")
    self.assertEqual(Size.format(-1024 * 1024), "-1.00 MiB")
    self.assertEqual(Size.format(-1024 * 1024 * 1024), "-1.00 GiB")
    self.assertEqual(Size.format(-0.0), "0.00 B")
    self.assertEqual(Size.format(-0.001, digits=2), "0.00 B")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
