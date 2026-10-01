# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench.helper import txt_helper
from tests import test_helper


class TxtHelperTestCase(unittest.TestCase):

  def test_plural_str(self):
    self.assertEqual(txt_helper.plural_str(1, "attempt"), "attempt")
    self.assertEqual(txt_helper.plural_str(0, "attempt"), "attempts")
    self.assertEqual(txt_helper.plural_str(2, "attempt"), "attempts")
    self.assertEqual(txt_helper.plural_str(1, "commit"), "commit")
    self.assertEqual(txt_helper.plural_str(5, "commit"), "commits")
    self.assertEqual(txt_helper.plural_str(1, "person", "people"), "person")
    self.assertEqual(txt_helper.plural_str(2, "person", "people"), "people")

  def test_wrap_lines(self):
    body = "short line\n" + "a" * 100
    lines = list(txt_helper.wrap_lines(body, width=50, indent="  "))
    self.assertEqual(lines[0], "  short line")
    self.assertEqual(lines[1], "  " + "a" * 50)
    self.assertEqual(lines[2], "  " + "a" * 50)

  def test_type_name(self):
    self.assertEqual(
        txt_helper.type_name(TxtHelperTestCase),
        f"{__name__}.TxtHelperTestCase")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
