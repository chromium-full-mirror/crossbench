# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from unittest import mock

import pandas as pd
from typing_extensions import override

from crossbench.action_runner.base import ActionRunner
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.cli.parser import CBArgumentParser
from crossbench.benchmarks.loadline import LoadLine1PhoneBenchmark, \
    LoadLine1PhoneDebugBenchmark, LoadLine1PhoneFastBenchmark, \
    LoadLine1TabletBenchmark, LoadLine1TabletDebugBenchmark, \
    LoadLine1TabletFastBenchmark, loadline_1
from crossbench.benchmarks.loadline.loadline import LoadLineProbe
from crossbench.probes.trace_processor.constants import QUERIES_DIR
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, BaseCrossbenchTestCase, \
    SysExitTestException
from tests.crossbench.benchmarks.helper import SubStoryTestCase
from tests.crossbench.benchmarks.loading.test_loading import \
    LoadingBenchmarkCliTestCaseMixin
from tests.crossbench.benchmarks.loadline.base import \
    BaseLoadLineBenchmarkTestCase, BaseLoadLineTestCase


class BaseLoadLine1BenchmarkTestCase(
    LoadingBenchmarkCliTestCaseMixin,
    BaseLoadLineBenchmarkTestCase,
    metaclass=abc.ABCMeta):

  @property
  @override
  def expected_tabs(self):
    return TabController.default()

  @property
  @override
  def expected_action_runner(self):
    return ActionRunner(self.mock_run())

  @property
  def tablet_benchmark_cls(self):
    return LoadLine1TabletBenchmark

  @property
  def phone_benchmark_cls(self):
    return LoadLine1PhoneBenchmark


class TestLoadLine1TabletBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1TabletBenchmark


class TestLoadLine1PhoneBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1PhoneBenchmark


class TestLoadLine1TabletDebugBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1TabletDebugBenchmark


class TestLoadLine1PhoneDebugBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1PhoneDebugBenchmark


class TestLoadLine1TabletFastBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1TabletFastBenchmark


class TestLoadLine1PhoneFastBenchmark(BaseLoadLine1BenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self):
    return LoadLine1PhoneFastBenchmark


class LoadLine1BenchmarkCliTestCase(BaseCliTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.setup_config_dir(QUERIES_DIR)

  def test_cli_help(self) -> None:
    with self.assertRaises(SysExitTestException):
      self.run_cli("loadline-phone", "--help")
    with self.assertRaises(SysExitTestException):
      self.run_cli("loadline-tablet", "--help")

  def test_separate_default(self) -> None:
    parser = CBArgumentParser()
    LoadLine1PhoneBenchmark.add_cli_arguments(parser)
    args = parser.parse_args([])
    self.assertTrue(args.separate)

  def test_run_default_phone(self) -> None:
    with self._patch_get_browser(), mock.patch.object(
        LoadLineProbe, "_is_device_online", return_value=True):
      for browser in self.browsers:
        browser.set_default_js_return(True)
      self.run_cli(
          "loadline-phone",
          "run",
          "--network=live",
          "--dry-run",
          "--env-validation=skip",
          "--throw",
          "--repetitions=1",
          "--stories=amazon_product",
      )

  def test_run_default_tablet(self) -> None:
    with self._patch_get_browser(), mock.patch.object(
        LoadLineProbe, "_is_device_online", return_value=True):
      for browser in self.browsers:
        browser.set_default_js_return(True)
      self.run_cli(
          "loadline-tablet",
          "run",
          "--network=live",
          "--dry-run",
          "--env-validation=skip",
          "--throw",
          "--repetitions=1",
          "--stories=amazon_product",
      )


class TestLoadLine1Helpers(BaseCrossbenchTestCase):

  def test_process_scores(self) -> None:
    query_result = pd.DataFrame(
        columns=["score", "cb_browser", "cb_story", "cb_temperature", "cb_run"],
        data=[
            [4, "chrome", "story1", 0, 0],
            [6, "chrome", "story1", 0, 1],
            [19, "chrome", "story2", 0, 0],
            [21, "chrome", "story2", 0, 1],
        ],
    )
    scores = loadline_1.process_scores(query_result)

    self.assertSequenceEqual(scores.shape, (1, 3))
    self.assertAlmostEqual(scores["TOTAL_SCORE"].iloc[0], 10)
    self.assertAlmostEqual(scores["story1"].iloc[0], 5)
    self.assertAlmostEqual(scores["story2"].iloc[0], 20)

  def test_process_breakdown(self) -> None:
    query_result = pd.DataFrame(
        columns=[
            "network",
            "process_launch",
            "renderer",
            "compositor",
            "gpu",
            "surfaceflinger",
            "cb_browser",
            "cb_story",
            "cb_temperature",
            "cb_run",
        ],
        data=[
            [5, 3, 9, 11, 10, 10, "chrome", "story1", 0, 0],
            [5, 3, 11, 9, 10, 10, "chrome", "story1", 0, 1],
            [7, 10, 19, 21, 20, 20, "chrome", "story2", 0, 0],
            [7, 10, 21, 19, 20, 20, "chrome", "story2", 0, 1],
        ],
    )
    breakdown = loadline_1.process_breakdown(query_result)

    self.assertSequenceEqual(breakdown.shape, (2, 5))
    self.assertAlmostEqual(breakdown["os"].iloc[0], 5)
    self.assertAlmostEqual(breakdown["os"].iloc[1], 10)
    self.assertAlmostEqual(breakdown["renderer"].iloc[0], 10)
    self.assertAlmostEqual(breakdown["renderer"].iloc[1], 20)
    self.assertAlmostEqual(breakdown["compositor"].iloc[0], 10)
    self.assertAlmostEqual(breakdown["compositor"].iloc[1], 20)
    self.assertAlmostEqual(breakdown["gpu"].iloc[0], 10)
    self.assertAlmostEqual(breakdown["gpu"].iloc[1], 20)
    self.assertAlmostEqual(breakdown["surfaceflinger"].iloc[0], 10)
    self.assertAlmostEqual(breakdown["surfaceflinger"].iloc[1], 20)


# Don't expose abstract base test cases.
del BaseLoadLineBenchmarkTestCase
del BaseCrossbenchTestCase
del BaseCliTestCase
del SubStoryTestCase
del BaseLoadLineTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
