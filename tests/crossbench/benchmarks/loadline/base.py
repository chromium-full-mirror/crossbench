# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import datetime as dt
import json
import pathlib
from io import StringIO
from typing import TYPE_CHECKING, Sequence
from unittest import mock

from typing_extensions import override

from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.benchmarks.loadline.loadline import LoadLineBenchmark, \
    LoadLinePageFilter
from tests.crossbench.base import SysExitTestException
from tests.crossbench.benchmarks.helper import SubStoryTestCase

if TYPE_CHECKING:
  from crossbench.benchmarks.loading.page.interactive import InteractivePage


class BaseLoadLineTestCase(SubStoryTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  @override
  def benchmark_cls(self) -> type[LoadLineBenchmark]:
    pass

  @override
  def setUp(self) -> None:
    super().setUp()
    self.setup_loadline_configs()

  @abc.abstractmethod
  def get_story_filter_args(self) -> argparse.Namespace:
    pass

  @override
  # Narrows SubStoryTestCase.story_filter with LoadLine-specific parameters.
  # pyrefly: ignore[bad-override-param-name]
  def story_filter(
      self,
      patterns: Sequence[str],
      separate: bool = True,
  ) -> LoadLinePageFilter:
    args = self.get_story_filter_args()
    story_filter = super().story_filter(patterns, args=args, separate=separate)
    assert isinstance(story_filter, LoadLinePageFilter)
    return story_filter

  def test_all_stories(self) -> None:
    # TODO: preload the story names from the config files
    stories = self.story_filter(["all"]).stories
    self.assertFalse(stories)

  def test_default_stories(self) -> None:
    # TODO: preload the story names from the config files
    stories = self.story_filter(["default"]).stories
    self.assertFalse(stories)

  def test_get_pages_config(self) -> None:
    self.benchmark_cls.get_pages_config()

  @property
  @abc.abstractmethod
  def loadline_version_string(self) -> str:
    pass

  def test_benchmark_version_flag(self) -> None:
    parser = self.create_parser()
    with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
      with self.assertRaises((SystemExit, SysExitTestException)):
        parser.parse_args(["--benchmark-version"])
      self.assertIn(self.loadline_version_string, mock_stdout.getvalue())

  @abc.abstractmethod
  def _get_interactive_pages(self, benchmark) -> Sequence[InteractivePage]:
    pass

  def test_custom_page_config(self) -> None:
    config_file = pathlib.Path("custom_pages.json")
    config_data = {
        "pages": {
            "custom_p1": [{
                "action": "get",
                "url": "https://example.com/1",
            }],
            "custom_p2": [{
                "action": "get",
                "url": "https://example.com/2",
            }],
        },
    }
    self.fs.create_file(config_file, contents=json.dumps(config_data))
    args = self.parse_args(f"--page-config={config_file}")
    benchmark = self.benchmark_cls.from_cli_args(args)
    pages = self._get_interactive_pages(benchmark)
    self.assertEqual(len(pages), 2)

  def test_parser_defaults(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.tabs, TabController.default())
    self.assertEqual(args.playback, PlaybackController.default())
    self.assertEqual(args.about_blank_duration, dt.timedelta())
    self.assertTrue(args.run_login)
    self.assertTrue(args.run_setup)
    self.assertEqual(args.stories, "default")
    self.assertIsNone(args.story_tags)
    self.assertTrue(args.separate)
    self.assertIsNone(args.pages_config)


class BaseLoadLineBenchmarkTestCase(
    BaseLoadLineTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  def expected_tabs(self):
    pass

  @override
  def get_story_filter_args(self) -> argparse.Namespace:
    return argparse.Namespace(
        about_blank_duration=dt.timedelta(),
        playback=PlaybackController.default(),
        tabs=self.expected_tabs,
        run_login=True,
        run_setup=True,
    )

  @property
  def tablet_benchmark_cls(self) -> type[LoadLineBenchmark] | None:
    return None

  @property
  def phone_benchmark_cls(self) -> type[LoadLineBenchmark] | None:
    return None

  def test_get_pages_config_variants(self):
    if self.tablet_benchmark_cls and self.phone_benchmark_cls:
      configs = [
          self.tablet_benchmark_cls.get_pages_config(),
          self.phone_benchmark_cls.get_pages_config(),
      ]
      self.assertNotEqual(configs[0], configs[1])
