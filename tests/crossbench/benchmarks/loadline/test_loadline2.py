# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from unittest import mock

import pandas as pd
from typing_extensions import override

from crossbench.action_runner.config import ActionRunnerConfig
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loadline import LoadLine2PhoneBenchmark, \
    LoadLine2PhoneDebugBenchmark, LoadLine2TabletBenchmark, \
    LoadLine2TabletDebugBenchmark, LoadLine2WebApiPhoneBenchmark, \
    LoadLine2WebApiPhoneDebugBenchmark
from crossbench.benchmarks.loadline.loadline_2 import process_scores
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
