# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import copy
import csv
from typing import TYPE_CHECKING
from unittest import mock

from typing_extensions import override

from crossbench.env.runner_env import EnvConfig, RunnerEnv, ValidationMode
from crossbench.plt.display_info import DisplayRefreshRateResult
from crossbench.runner.runner import Runner
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from crossbench.benchmarks.motionmark.motionmark_1 import \
      MotionMark1Benchmark, MotionMark1Probe, MotionMark1ProbeContext, \
      MotionMark1Story


class MotionMark1BaseTestCase(
    helper.PressBaseBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  @override
  def benchmark_cls(self) -> type[MotionMark1Benchmark]:
    pass

  @property
  @abc.abstractmethod
  @override
  def story_cls(self) -> type[MotionMark1Story]:
    pass

  @property
  @abc.abstractmethod
  def probe_cls(self) -> type[MotionMark1Probe]:
    pass

  @property
  @abc.abstractmethod
  def probe_context_cls(self) -> type[MotionMark1ProbeContext]:
    pass

  EXAMPLE_PROBE_DATA = [{
      "testsResults": {
          "MotionMark": {
              "Multiply": {
                  "complexity": {
                      "complexity":
                          1169.7666313745012,
                      "stdev":
                          2.6693101402239985,
                      "bootstrap": {
                          "confidenceLow": 1154.0859381321234,
                          "confidenceHigh": 1210.464520355893,
                          "median": 1180.8987652049277,
                          "mean": 1163.0061487765158,
                          "confidencePercentage": 0.8,
                      },
                      "segment1": [[1, 16.666666666666668],
                                   [1, 16.666666666666668]],
                      "segment2": [[1, 6.728874992470971],
                                   [3105, 13.858528114770454]],
                  },
                  "controller": {
                      "score": 1168.106104032434,
                      "average": 1168.106104032434,
                      "stdev": 37.027504395081785,
                      "percent": 3.1698750881669624,
                  },
                  "score": 1180.8987652049277,
                  "scoreLowerBound": 1154.0859381321234,
                  "scoreUpperBound": 1210.464520355893,
              },
          },
      },
      "score": 1180.8987652049277,
      "scoreLowerBound": 1154.0859381321234,
      "scoreUpperBound": 1210.464520355893,
  }]

  @override
  def setUp(self):
    super().setUp()
    self.set_display_refresh_rate_patcher = mock.patch.object(
        self.platform,
        "set_display_refresh_rate",
        return_value=DisplayRefreshRateResult(True, "mocked"))
    self.addCleanup(self.set_display_refresh_rate_patcher.stop)
    self.set_display_refresh_rate_patcher.start()

    self.reset_display_refresh_rate_patcher = mock.patch.object(
        self.platform, "reset_display_refresh_rate")
    self.addCleanup(self.reset_display_refresh_rate_patcher.stop)
    self.reset_display_refresh_rate_patcher.start()

  def test_all_stories(self):
    stories = self.story_filter(["all"], separate=True).stories
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, self.story_cls)
    names = {story.name for story in stories}
    self.assertEqual(len(names), len(stories))
    self.assertEqual(len(names), len(self.story_cls.SUBSTORIES))

  def test_default_stories(self):
    stories = self.story_filter(["default"], separate=True).stories
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, self.story_cls)
    names = {story.name for story in stories}
    self.assertEqual(len(names), len(stories))
    self.assertEqual(len(names), len(self.story_cls.ALL_STORIES["MotionMark"]))

  def test_run_throw(self):
    self._test_run(throw=True)

  def test_run_default(self):
    self._test_run()
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{self.story_cls.URL}/developer.html", urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)
      self.assertNotIn(f"{self.story_cls.URL_LOCAL}/developer.html", urls)

  def test_run_custom_url(self):
    custom_url = "http://test.example.com/motionmark"
    self._test_run(custom_url)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{custom_url}/developer.html", urls)
      self.assertNotIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def _test_run(self, custom_url: str | None = None, throw: bool = False):
    stories = self.story_cls.from_names(["Multiply"], url=custom_url)
    repetitions = 3
    # The order should match Runner.get_runs
    for _ in range(repetitions):
      for _ in stories:
        for browser in self.browsers:
          # Ready state complete
          browser.expect_js(result=True)
          # Page is ready
          browser.expect_js(result=True)
          # NOF enabled benchmarks
          browser.expect_js(result=1)
          # Start running benchmark
          browser.expect_js()
          # Wait until done
          browser.expect_js(result=True)
          browser.expect_js(result=self.EXAMPLE_PROBE_DATA)
    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)
    benchmark = self.benchmark_cls(stories, custom_url=custom_url)
    self.assertTrue(len(benchmark.describe()) > 0)
    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=throw,
        in_memory_result_db=True)
    with mock.patch.object(RunnerEnv, "validate_url", return_value=True) as cm:
      runner.run()
    cm.assert_called_once()
    assert runner.is_success
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertTrue(browser.was_js_invoked(self.probe_context_cls.JS))
    with (self.out_dir /
          f"{self.probe_cls.NAME}.csv").open(encoding="utf-8") as f:
      csv_data = list(csv.DictReader(f, delimiter="\t"))
    self.assertSequenceEqual(
        list(csv_data[0].keys()), ["label", "", "dev", "stable"])
    self.assertDictEqual(
        csv_data[1],
        {
            "label": "version",
            "dev": "102.22.33.44",
            "stable": "100.22.33.44",
            # One padding element (after "label"):
            "": "",
        })
