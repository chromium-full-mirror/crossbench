# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import datetime as dt
from unittest import mock

import pandas as pd
from typing_extensions import override

from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.action_runner.action_runner import ActionRunner
from crossbench.action_runner.config import ActionRunnerConfig
from crossbench.benchmarks.loading.config.blocks import ActionBlock
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loading.page.interactive import InteractivePage
from crossbench.benchmarks.loadline import LoadLine2PhoneBenchmark, \
    LoadLine2PhoneDebugBenchmark, LoadLine2TabletBenchmark, \
    LoadLine2TabletDebugBenchmark, LoadLine2WebApiPhoneBenchmark, \
    LoadLine2WebApiPhoneDebugBenchmark
from crossbench.benchmarks.loadline.loadline_2 import LoadLine2CombinedPage, \
    process_scores
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.stories.story import Story
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.benchmarks.loadline.base import \
    BaseLoadLineBenchmarkTestCase, BaseLoadLineTestCase


class TestLoadLine2Helpers(BaseCrossbenchTestCase):

  def test_process_scores_single_run(self) -> None:
    query_result = pd.DataFrame(
        columns=[
            "value",
            "cb_browser",
            "metric",
            "cb_story",
            "cb_temperature",
            "cb_run",
        ],
        data=[
            [4.0, "chrome", "metric1", "story1", 0, 0],
            [16.0, "chrome", "metric2", "story2", 0, 0],
        ],
    )
    scores = process_scores(query_result, expected_metrics=2)

    self.assertSequenceEqual(scores.shape, (3, 1))
    self.assertEqual(scores["chrome"].loc["metric1"], "4.000")
    self.assertEqual(scores["chrome"].loc["metric2"], "16.000")
    self.assertEqual(scores["chrome"].loc["TOTAL_SCORE"], "8.000")

  def test_process_scores_multiple_runs(self) -> None:
    query_result = pd.DataFrame(
        columns=[
            "value",
            "cb_browser",
            "metric",
            "cb_story",
            "cb_temperature",
            "cb_run",
        ],
        data=[
            [4.0, "chrome", "metric1", "story1", 0, 0],
            [6.0, "chrome", "metric1", "story1", 0, 1],
        ],
    )
    scores = process_scores(query_result)

    self.assertEqual(scores["chrome"].loc["metric1"], "5.000 ± 12.706")

  def test_process_scores_globo_coefficient(self) -> None:
    query_result = pd.DataFrame(
        columns=[
            "value",
            "cb_browser",
            "metric",
            "cb_story",
            "cb_temperature",
            "cb_run",
        ],
        data=[
            [80.0, "chrome", "globo_homepage_interactive", "story1", 0, 0],
            [120.0, "chrome", "globo_homepage_interactive", "story1", 0, 1],
        ],
    )
    scores = process_scores(query_result, expected_metrics=1)

    self.assertEqual(scores["chrome"].loc["globo_homepage_interactive"],
                     "58.000 ± 147.392")
    self.assertEqual(scores["chrome"].loc["TOTAL_SCORE"], "58.000 ± 147.392")

  def test_process_scores_not_enough_metrics(self) -> None:
    query_result = pd.DataFrame(
        columns=[
            "value",
            "cb_browser",
            "metric",
            "cb_story",
            "cb_temperature",
            "cb_run",
        ],
        data=[
            [100.0, "chrome", "metric1", "story1", 0, 0],
        ],
    )
    scores = process_scores(query_result, expected_metrics=2)

    self.assertEqual(scores["chrome"].loc["metric1"], "100.000")
    self.assertNotIn("TOTAL_SCORE", scores["chrome"])

  def test_combined_page_android_load_block_triggers_sync_touch_nav(
      self) -> None:
    nav_action = JsAction(
        script="window.location.href = 'https://example.com';")
    wait_action = WaitAction(duration=dt.timedelta(milliseconds=100))
    load_block = ActionBlock(
        label="load", index=1, actions=(nav_action, wait_action))
    page = InteractivePage("test_page", (load_block,))
    combined_page = LoadLine2CombinedPage((page,))
    action_runner = mock.MagicMock(spec=ActionRunner)
    action_runner.browser_platform.is_android = True
    mock_actions = action_runner.actions.return_value.__enter__.return_value

    combined_page.run_with(action_runner, multiple_tabs=False)

    action_runner.actions.assert_called_once_with(
        "TouchSyncSetup", measure=False)
    self.assertIn("100vh", mock_actions.js.call_args[0][0])
    self.assertIn("https://example.com", mock_actions.js.call_args[0][0])
    action_runner.click_touch.assert_called_once()
    click_action = action_runner.click_touch.call_args[0][0]
    self.assertEqual(click_action.position.selector.selector, "html")
    remaining_blocks = action_runner.run_blocks.call_args[0][0]
    self.assertEqual(tuple(remaining_blocks[0].actions), (wait_action,))


class BaseLoadLine2BenchmarkTestCase(
    BaseLoadLineBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @override
  def expected_tabs(self):
    return None

  @property
  def tablet_benchmark_cls(self):
    return LoadLine2TabletBenchmark

  @property
  def phone_benchmark_cls(self):
    return LoadLine2PhoneBenchmark

  def test_kwargs_from_cli(self) -> None:
    args = self.parse_args(
        "--deterministic",
        "--action-runner-config={}",
        "--stories=google_search_result",
    )
    kwargs = self.benchmark_cls.kwargs_from_cli(args)
    self.assertTrue(kwargs["deterministic"])
    self.assertIsInstance(kwargs["action_runner_config"], ActionRunnerConfig)
    self.assertEqual(len(kwargs["stories"]), 1)
    self.assertIsInstance(kwargs["stories"][0], CombinedPage)


class TestLoadLine2PhoneBenchmark(BaseLoadLine2BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2PhoneBenchmark

  def test_deterministic_flag(self) -> None:
    args = self.parse_args("--deterministic")
    self.assertTrue(args.deterministic)
    kwargs = self.benchmark_cls.kwargs_from_cli(args)
    self.assertTrue(kwargs["deterministic"])

  def test_extra_flags(self) -> None:
    story = mock.Mock(spec=Story)
    flags = self.benchmark_cls.extra_flags(BrowserAttributes.CHROMIUM_BASED,
                                           story)
    self.assertIn("--site-per-process", flags)
    self.assertIn("--disable-back-forward-cache", flags)
    self.assertIn("--disable-external-intent-requests", flags)
    self.assertIn("SpareRendererForSitePerProcess",
                  flags.get("--disable-features", ""))


class TestLoadLine2TabletBenchmark(BaseLoadLine2BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2TabletBenchmark

  def test_tablet_extra_flags(self) -> None:
    story = mock.Mock(spec=Story)
    flags_phone = LoadLine2PhoneBenchmark.extra_flags(
        BrowserAttributes.CHROMIUM_BASED, story)
    self.assertNotIn("--request-desktop-sites", flags_phone)

    flags_tablet = LoadLine2TabletBenchmark.extra_flags(
        BrowserAttributes.CHROMIUM_BASED, story)
    self.assertIn("--request-desktop-sites", flags_tablet)


class TestLoadLine2PhoneDebugBenchmark(BaseLoadLine2BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2PhoneDebugBenchmark


class TestLoadLine2TabletDebugBenchmark(BaseLoadLine2BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2TabletDebugBenchmark


class BaseLoadLine2WebApiBenchmarkTestCase(
    BaseLoadLineBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @override
  def expected_tabs(self):
    return None

  def test_extra_flags(self) -> None:
    story = mock.Mock(spec=Story)
    flags = self.benchmark_cls.extra_flags(BrowserAttributes.CHROMIUM_BASED,
                                           story)
    self.assertIn("--site-per-process", flags)


class TestLoadLine2WebApiPhoneBenchmark(BaseLoadLine2WebApiBenchmarkTestCase):

  def test_benchmark_version_flag(self) -> None:
    pass

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2WebApiPhoneBenchmark


class TestLoadLine2WebApiPhoneDebugBenchmark(
    BaseLoadLine2WebApiBenchmarkTestCase):

  def test_benchmark_version_flag(self) -> None:
    pass

  @property
  @override
  def benchmark_cls(self):
    return LoadLine2WebApiPhoneDebugBenchmark


# Don't expose abstract base test cases.
del BaseLoadLineTestCase
del BaseLoadLine2BenchmarkTestCase
del BaseLoadLine2WebApiBenchmarkTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
