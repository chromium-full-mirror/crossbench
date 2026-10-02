# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest
from xml.etree import ElementTree

from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.screenshot_annotation import \
    ScreenshotPointAnnotation, ScreenshotRectAnnotation, \
    annotate_screenshot_svg
from crossbench.benchmarks.loading.point import Point
from tests import test_helper


class ScreenshotAnnotationTestCase(unittest.TestCase):
  SVG_NAMESPACE = {"": "http://www.w3.org/2000/svg"}

  def test_empty(self):
    svg = ElementTree.fromstring(
        annotate_screenshot_svg(1366, 768, "screenshot.png", []))
    self.assertEqual(svg.attrib["width"], "1366")
    self.assertEqual(svg.attrib["height"], "768")
    image = svg.find(
        ".//image[@href='screenshot.png'][@width='1366'][@height='768']",
        self.SVG_NAMESPACE)
    self.assertIsNotNone(image)

  def test_point(self):
    svg = ElementTree.fromstring(
        annotate_screenshot_svg(
            1366, 768, "screenshot.png",
            [ScreenshotPointAnnotation("point", Point(123, 456))]))
    g = svg.find(".//g[title='point']", self.SVG_NAMESPACE)
    self.assertIsNotNone(g)
    rect = g.find("./rect[@x='122.5'][@y='455.5']", self.SVG_NAMESPACE)
    self.assertIsNotNone(rect)

  def test_rect(self):
    svg = ElementTree.fromstring(
        annotate_screenshot_svg(1366, 768, "screenshot.png", [
            ScreenshotRectAnnotation("rect",
                                     DisplayRectangle(Point(123, 456), 89, 97)),
        ]))
    rect = svg.find(
        ".//rect[title='rect'][@x='123'][@y='456'][@width='89'][@height='97']",
        self.SVG_NAMESPACE)
    self.assertIsNotNone(rect)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
