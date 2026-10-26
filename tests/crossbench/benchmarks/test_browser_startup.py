# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING, Sequence

from crossbench.benchmarks.loading.browser_startup import \
    BrowserStartupBenchmark
from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loading.page.interactive import InteractivePage
from crossbench.cli.parser import CBArgumentParser
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, BaseCrossbenchTestCase

if TYPE_CHECKING:
  import argparse


class TestBrowserStartupBenchmark(BaseCrossbenchTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.setup_config_dir(
        BrowserStartupBenchmark.default_probe_config_path().parent)

  def parse_args(self, *args: str | Sequence[str]) -> argparse.Namespace:
    parser = BrowserStartupBenchmark.add_cli_arguments(CBArgumentParser())
    flattened_args: list[str] = []
    for arg in args:
      if isinstance(arg, str):
        flattened_args.append(arg)
      else:
        flattened_args.extend(arg)
    return parser.parse_args(flattened_args)

  def test_describe(self) -> None:
    desc = BrowserStartupBenchmark.describe()
    self.assertEqual(desc["name"], "browser-startup")
    self.assertEqual(desc["aliases"], "None")
    self.assertTrue(len(desc["description"]) > 0)
    self.assertEqual(
        desc["stories"],
        {
            "newtab_startup": "chrome://newtab/",
            "blank_startup": "about:blank",
            "google_startup": "https://www.google.com/",
        })

  def test_all_story_names(self) -> None:
    self.assertSequenceEqual(
        BrowserStartupBenchmark.all_story_names(),
        ("newtab_startup", "blank_startup", "google_startup"))

  def test_properties(self) -> None:
    self.assertEqual(BrowserStartupBenchmark.NAME, "browser-startup")
    self.assertSequenceEqual(BrowserStartupBenchmark.aliases(), ())
    self.assertTrue(
        BrowserStartupBenchmark.default_probe_config_path().is_file())
    self.assertTrue(
        BrowserStartupBenchmark.default_pages_config_path().is_file())

  def test_get_pages_config(self) -> None:
    config = BrowserStartupBenchmark.get_pages_config()
    self.assertIsInstance(config, PagesConfig)
    self.assertEqual(len(config.pages), 3)
    page_labels = [page.label for page in config.pages]
    self.assertSequenceEqual(
        page_labels, ["newtab_startup", "blank_startup", "google_startup"])

  def test_separate_stories_by_default(self) -> None:
    args = self.parse_args()
    self.assertTrue(args.separate)
    benchmark = BrowserStartupBenchmark.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 3)
    for story in benchmark.stories:
      self.assertIsInstance(story, InteractivePage)
    story_names = [story.name for story in benchmark.stories]
    self.assertSequenceEqual(
        story_names, ["newtab_startup", "blank_startup", "google_startup"])

  def test_combined_stories_flag(self) -> None:
    args = self.parse_args("--combined")
    self.assertFalse(args.separate)
    benchmark = BrowserStartupBenchmark.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 1)
    self.assertIsInstance(benchmark.stories[0], CombinedPage)

  def test_stories_filtering(self) -> None:
    args = self.parse_args("--stories=newtab_startup")
    benchmark = BrowserStartupBenchmark.from_cli_args(args)
    story_names = [story.name for story in benchmark.stories]
    self.assertSequenceEqual(story_names, ["newtab_startup"])

  def test_stories_filtering_exclude(self) -> None:
    args = self.parse_args("--stories=.*,-google_startup")
    benchmark = BrowserStartupBenchmark.from_cli_args(args)
    story_names = [story.name for story in benchmark.stories]
    self.assertSequenceEqual(story_names, ["newtab_startup", "blank_startup"])

  def test_custom_page_config(self) -> None:
    config_file = pathlib.Path("custom_startup_pages.json")
    config_data = {
        "pages": {
            "custom_newtab": [{
                "action": "get",
                "url": "chrome://newtab/",
                "ready_state": "complete",
            }],
            "custom_blank": [{
                "action": "get",
                "url": "about:blank",
                "ready_state": "complete",
            }],
        },
    }
    self.fs.create_file(config_file, contents=json.dumps(config_data))
    args = self.parse_args(f"--page-config={config_file}",
                           "--stories=custom_newtab")
    benchmark = BrowserStartupBenchmark.from_cli_args(args)
    story_names = [story.name for story in benchmark.stories]
    self.assertSequenceEqual(story_names, ["custom_newtab"])


class TestBrowserStartupCli(BaseCliTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.setup_config_dir(
        BrowserStartupBenchmark.default_probe_config_path().parent)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
