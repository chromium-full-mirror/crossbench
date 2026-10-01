# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench import path as pth
from tests import test_helper


class PlatformHelperTestCase(unittest.TestCase):

  def test_safe_filename(self):
    self.assertEqual(pth.safe_filename("abc-ABC"), "abc-ABC")
    self.assertEqual(pth.safe_filename("abc_ABC.bak2.jpg"), "abc_ABC.bak2.jpg")

  def test_safe_filename_unsafe(self):
    self.assertEqual(pth.safe_filename("äbc_ÂBC"), "abc_ABC")
    self.assertEqual(pth.safe_filename("abc?*//\\ABC"), "abc_____ABC")
    self.assertEqual(pth.safe_filename("äbc_**_ÂBC"), "abc____ABC")

  def test_safe_filename_len(self):
    test_str = "x" * 1024
    with self.assertRaises(ValueError):
      pth.safe_filename(test_str, strict_len=True)
    self.assertEqual(len(pth.safe_filename(test_str)), pth.MAX_PART_LEN)

  def test_results_dirs(self) -> None:
    self.assertEqual(pth.RESULTS_DIR, pth.ROOT_DIR / "results")
    self.assertEqual(pth.LATEST_RESULT_DIR, pth.RESULTS_DIR / "latest")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
