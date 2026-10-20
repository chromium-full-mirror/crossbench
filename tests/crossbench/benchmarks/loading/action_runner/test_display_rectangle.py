# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import unittest

from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.benchmarks.loading.point import Point
from tests import test_helper


class DisplayRectangleTestCase(unittest.TestCase):

  def test_display_rectangle_mul(self):
    rect: DisplayRectangle = DisplayRectangle(Point(1, 2), 3, 4)

    rect = rect * 5

    self.assertEqual(rect.origin.x, 5)
    self.assertEqual(rect.origin.y, 10)
    self.assertEqual(rect.width, 15)
    self.assertEqual(rect.height, 20)

  def test_display_rectangle_mid_x(self):
    rect: DisplayRectangle = DisplayRectangle(Point(1, 2), 6, 8)

    self.assertEqual(rect.mid_x, 4)

  def test_display_rectangle_mid_y(self):
    rect: DisplayRectangle = DisplayRectangle(Point(1, 2), 6, 8)

    self.assertEqual(rect.mid_y, 6)

  def test_display_rectangle_middle(self):
    rect: DisplayRectangle = DisplayRectangle(Point(1, 2), 6, 8)

    self.assertEqual(rect.middle, Point(4, 6))

  def test_display_rectangle_truthy(self):
    self.assertFalse(DisplayRectangle(Point(1, 2), 0, 0))
    self.assertFalse(DisplayRectangle(Point(5, 6), 0, 1))
    self.assertFalse(DisplayRectangle(Point(3, 4), 1, 0))
    self.assertTrue(DisplayRectangle(Point(1, 2), 1, 1))

  def test_display_rectangle_scrollable_area(self):
    rect = DisplayRectangle(Point(100, 200), 500, 600)

    (scrollable_top, scrollable_bottom,
     max_scroll_distance) = rect.get_scrollable_area()

    self.assertEqual(scrollable_top, 260)
    self.assertEqual(scrollable_bottom, 740)
    self.assertEqual(max_scroll_distance, 480)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
