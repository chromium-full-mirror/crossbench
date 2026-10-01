# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench.helper.collection_helper import close_matches_message
from tests import test_helper


class CollectionHelperTestCase(unittest.TestCase):

  def test_close_matches_empty_choices(self):
    with self.assertRaises(ValueError):
      close_matches_message("foo", [])

  def test_close_matches_single_match(self):
    msg, alt = close_matches_message("perfettoo", ["perfetto", "trace"],
                                     "probe")
    self.assertEqual(alt, "perfetto")
    self.assertEqual(msg,
                     "Invalid probe: 'perfettoo'. Did you mean 'perfetto'?")

  def test_close_matches_multiple_matches(self):
    msg, alt = close_matches_message("linux", ["linux-perf", "linux-perff"],
                                     "bot")
    self.assertIsNone(alt)
    self.assertIn("Did you mean one of", msg)
    self.assertIn("linux-perf", msg)
    self.assertIn("linux-perff", msg)

  def test_close_matches_substring_fallback(self):
    msg, alt = close_matches_message("m1", ["mac-m1-perf", "linux-perf"], "bot")
    self.assertEqual(alt, "mac-m1-perf")
    self.assertEqual(msg, "Invalid bot: 'm1'. Did you mean 'mac-m1-perf'?")

  def test_close_matches_substring_fallback_multiple(self):
    msg, alt = close_matches_message(
        "m1", ["mac-m1-pro-perf", "mac-m1-max-perf", "linux-perf"], "bot")
    self.assertIsNone(alt)
    self.assertEqual(
        msg,
        "Invalid bot: 'm1'. Did you mean one of mac-m1-pro-perf, "
        "mac-m1-max-perf?",
    )

  def test_close_matches_no_match_small_choices(self):
    choices = ["foo", "bar"]
    msg, alt = close_matches_message("xyz", choices, "opt")
    self.assertIsNone(alt)
    self.assertEqual(msg, "Invalid opt: 'xyz'. Choices are foo,bar")

  def test_close_matches_no_match_large_choices(self):
    choices = [f"bot_{i}" for i in range(15)]
    msg, alt = close_matches_message("xyz", choices, "bot")
    self.assertIsNone(alt)
    self.assertIn("Choices are", msg)
    self.assertIn("... (15 total)", msg)

  def test_close_matches_custom_limit(self):
    choices = [f"bot_{i}" for i in range(8)]
    msg, _ = close_matches_message("xyz", choices, "bot", limit=5)
    self.assertIn("... (8 total)", msg)
    msg, _ = close_matches_message("xyz", choices, "bot", limit=10)
    self.assertNotIn("...", msg)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
