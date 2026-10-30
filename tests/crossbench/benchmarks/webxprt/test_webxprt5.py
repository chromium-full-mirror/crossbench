# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import copy
import json
from typing import TYPE_CHECKING
from unittest import mock

from typing_extensions import override

import crossbench.benchmarks.webxprt as wx
from crossbench import path as pth
from crossbench.benchmarks.webxprt.webxprt_main import WebXPRT5Benchmark, \
    WebXPRT5Probe, WebXPRT5ProbeContext, WebXPRT5Story
from crossbench.cli.parser import CBArgumentParser
from crossbench.env.runner_env import EnvConfig, ValidationMode
from crossbench.runner.runner import Runner
from tests import test_helper
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from tests.crossbench.mock_browser import MockBrowser


class WebXPRT5TestCase(helper.PressBaseBenchmarkTestCase):

  @override
  def setUp(self):
    super().setUp()
    self.setup_config_dir(pth.LocalPath(wx.__file__).parent)

  @property
  @override
  def benchmark_cls(self) -> type[WebXPRT5Benchmark]:
    return WebXPRT5Benchmark

  @property
  @override
  def story_cls(self) -> type[WebXPRT5Story]:
    return WebXPRT5Story

  @property
  def probe_cls(self) -> type[WebXPRT5Probe]:
    return WebXPRT5Probe

  @property
  def probe_context_cls(self) -> type[WebXPRT5ProbeContext]:
    return WebXPRT5ProbeContext

  def _setup_run_js_expect(self,
                           browser: MockBrowser,
                           probe_results: dict,
                           uncheck_count: int = 6) -> None:
    # Ready state check for show_url (
    # wait_js_condition document.readyState === 'complete')
    browser.expect_js(result=True)
    # 6 uncheck JS calls during setup_stories for Video_Effects
    for _ in range(uncheck_count):
      browser.expect_js()
    # Setup actions: wait_js_condition for checkedWorkloads
    browser.expect_js(result=True)
    # Run actions: click startBtn
    browser.expect_js()
    browser.set_current_url(
        "https://www.principledtechnologies.com/wx5/results.html")
    # Teardown actions: wait_js_condition #resultsContent is visible
    browser.expect_js(result=True)
    # Probe result to_json: execute JS to read results
    browser.expect_js(result=json.dumps(probe_results))

  def test_run_default(self):
    stories = self.story_cls.all()
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)

    probe_results = {
        "Score": 150.0,
        "Variance": 3,
        "Geomean": 3037,
        "Video_Effects": 1200.0,
        "Detect_Faces": 2305.0,
        "Image_Classification": 2846.45,
        "Document_Scanning": 1737.37,
        "Photo_Effects": 3345.2,
        "School_Science_Project": 2170.88,
        "Homework_Spellcheck": 982.0,
    }

    repetitions = 1
    for _ in range(repetitions):
      for browser in self.browsers:
        self._setup_run_js_expect(browser, probe_results, uncheck_count=0)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True)

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.story_cls.URL, urls)
      self.assertSequenceEqual(browser.expected_js, [])

    with self.assertLogs(level="INFO") as log_cm:
      for probe in runner.probes:
        for run in runner.runs:
          probe.log_run_result(run)
    output = "\n".join(log_cm.output)
    for metric in ("Score", "Variance", "Geomean", "Video_Effects",
                   "Detect_Faces", "Image_Classification", "Document_Scanning",
                   "Photo_Effects", "School_Science_Project",
                   "Homework_Spellcheck"):
      self.assertIn(metric, output)

  def test_run_single(self):
    stories = self.story_cls.from_names(["video-effects"])
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)

    probe_results = {
        "Video_Effects": 1200.0,
    }

    repetitions = 1
    for _ in range(repetitions):
      for browser in self.browsers:
        self._setup_run_js_expect(browser, probe_results, uncheck_count=6)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True)

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.story_cls.URL, urls)
      self.assertSequenceEqual(browser.expected_js, [])

    with self.assertLogs(level="INFO") as log_cm:
      for probe in runner.probes:
        for run in runner.runs:
          probe.log_run_result(run)
    output = "\n".join(log_cm.output)
    self.assertIn("WebXPRT 5 results", output)
    self.assertIn("Video_Effects", output)
    self.assertIn("1200.0", output)

  def test_run_single_with_repetitions(self):
    stories = self.story_cls.from_names(["video-effects"])
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)

    probe_results = [{
        "Video_Effects": 1200.0,
    }, {
        "Video_Effects": 1500.0,
    }]

    repetitions = 2
    for index in range(repetitions):
      for browser in self.browsers:
        self._setup_run_js_expect(
            browser, probe_results[index], uncheck_count=6)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True)

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.story_cls.URL, urls)
      self.assertSequenceEqual(browser.expected_js, [])

    with self.assertLogs(level="INFO") as log_cm:
      for probe in runner.probes:
        for run in runner.runs:
          probe.log_run_result(run)
    output = "\n".join(log_cm.output)
    self.assertIn("WebXPRT 5 results", output)
    self.assertIn("Video_Effects", output)
    self.assertIn("1200.0", output)
    self.assertIn("1500.0", output)

  def test_flatten_json_data_all_stories(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())
    raw_data = {
        "name":
            "All_123",
        "tests": [{
            "testType": "all",
            "additionalInfo": {
                "scoreCalculated": 1,
                "score": 60,
                "variance": 1.25,
                "geomean": 1438.88,
            },
        }],
        "workloads": [
            {
                "workloadID": 0,
                "workload": "Video background blur with AI",
                "dur": 3343.7,
                "iter": 0,
            },
            {
                "workloadID": 0,
                "workload": "Video background blur with AI",
                "dur": 3280.3,
                "iter": 1,
            },
            {
                "workloadID": 1,
                "workload": "Detect faces with AI",
                "dur": 700.0,
                "iter": 0,
            },
            {
                "workloadID": 1,
                "workload": "Detect faces with AI",
                "dur": 800.0,
                "iter": 1,
            },
        ],
    }
    with mock.patch.object(context, "_get_expected_iters", return_value=2):
      flattened = context.flatten_json_data(raw_data)
    self.assertIsInstance(flattened, dict)
    self.assertEqual(flattened["Score"], 60.0)
    self.assertEqual(flattened["Geomean"], 1438.88)
    self.assertEqual(flattened["Variance"], 1.25)
    self.assertIsInstance(flattened["Video_Effects"], float)
    self.assertIsInstance(flattened["Detect_Faces"], float)
    self.assertAlmostEqual(flattened["Video_Effects"], (3343.7 + 3280.3) / 2)
    self.assertAlmostEqual(flattened["Detect_Faces"], (700.0 + 800.0) / 2)
    self.assertNotIn("Video background blur with AI", flattened)

  def test_flatten_json_data_custom_stories(self):
    stories = self.story_cls.from_names(["video-effects"])
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())
    raw_data = {
        "name":
            "Custom_123",
        "tests": [{
            "testType": "custom",
            "additionalInfo": {
                "scoreCalculated": 0,
                "score": 0,
                "variance": 0,
                "geomean": 0,
            },
        }],
        "workloads": [{
            "workloadID": 0,
            "workload": "Video background blur with AI",
            "dur": 3343.7,
            "iter": 0,
        }],
    }
    with mock.patch.object(context, "_get_expected_iters", return_value=1):
      flattened = context.flatten_json_data(raw_data)
    self.assertIsInstance(flattened, dict)
    self.assertNotIn("Score", flattened)
    self.assertNotIn("Geomean", flattened)
    self.assertNotIn("Variance", flattened)
    self.assertEqual(flattened["Video_Effects"], 3343.7)

  def test_flatten_json_data_full_run(self):
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(self.story_cls.all())),
        mock.MagicMock(),
    )
    raw_data = {
        "url":
            "https://www.principledtechnologies.com/wx5/results.html",
        "name":
            "All_123",
        "tests": [{
            "testname": "All_123",
            "mode": "cycle",
            "testType": "all",
            "numWorkloads": 7,
            "iters": 7,
            "additionalInfo": {
                "scoreCalculated": 1,
                "score": 65,
                "variance": 4,
                "geomean": 1326.12,
            },
        }],
        "workloads": [
            {
                "workloadID": 0,
                "workload": "Video background blur with AI",
                "iter": 0,
                "dur": 2924.1,
            },
            {
                "workloadID": 0,
                "workload": "Video background blur with AI",
                "iter": 1,
                "dur": 3043.0,
            },
            {
                "workloadID": 1,
                "workload": "Detect faces with AI",
                "iter": 0,
                "dur": 755.5,
            },
            {
                "workloadID": 4,
                "workload": "Photo effects",
                "iter": 0,
                "dur": 624.8,
            },
        ],
    }

    def mock_extract_workload_metrics(json_data, result):
      result["Video_Effects"] = (2924.1 + 3043.0) / 2
      result["Detect_Faces"] = 755.5
      result["Photo_Effects"] = 624.8

    with mock.patch.object(
        context,
        "_extract_workload_metrics",
        side_effect=mock_extract_workload_metrics):
      flattened = context.flatten_json_data(raw_data)
    self.assertIsInstance(flattened, dict)
    self.assertEqual(flattened["Score"], 65.0)
    self.assertEqual(flattened["Geomean"], 1326.12)
    self.assertEqual(flattened["Variance"], 4.0)
    self.assertIsInstance(flattened["Video_Effects"], float)
    self.assertAlmostEqual(flattened["Video_Effects"], (2924.1 + 3043.0) / 2)
    self.assertEqual(flattened["Detect_Faces"], 755.5)
    self.assertEqual(flattened["Photo_Effects"], 624.8)

  def test_flatten_json_data_single_workload_run(self):
    context = self.probe_context_cls(
        self.probe_cls(
            benchmark=self.benchmark_cls(
                self.story_cls.from_names(["photo-effects"]))),
        mock.MagicMock(),
    )
    raw_data = {
        "url":
            "https://www.principledtechnologies.com/wx5/results.html",
        "name":
            "customtest_123",
        "tests": [{
            "testname": "customtest_123",
            "mode": "cycle_one",
            "testType": "custom",
            "numWorkloads": 1,
            "iters": 7,
            "additionalInfo": {
                "scoreCalculated": 0,
                "score": 0,
                "variance": 0,
            },
        }],
        "workloads": [
            {
                "workloadID": 4,
                "workload": "Photo effects",
                "iter": 0,
                "dur": 616.0,
            },
            {
                "workloadID": 4,
                "workload": "Photo effects",
                "iter": 1,
                "dur": 592.8,
            },
        ],
    }
    with mock.patch.object(context, "_get_expected_iters", return_value=2):
      flattened = context.flatten_json_data(raw_data)
    self.assertIsInstance(flattened, dict)
    self.assertNotIn("Score", flattened)
    self.assertNotIn("Geomean", flattened)
    self.assertNotIn("Variance", flattened)
    self.assertIsInstance(flattened["Photo_Effects"], float)
    self.assertAlmostEqual(flattened["Photo_Effects"], (616.0 + 592.8) / 2)

  def test_flatten_json_data_mismatched_iters_raises_error(self):
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(self.story_cls.all())),
        mock.MagicMock(),
    )
    raw_data = {
        "tests": [{
            "testType": "all",
            "iters": 7,
            "additionalInfo": {
                "scoreCalculated": 1,
                "score": 60,
            },
        }],
        "workloads": [{
            "workloadID": 0,
            "workload": "Video background blur with AI",
            "iter": 0,
            "dur": 2924.1,
        }],
    }
    with self.assertRaises(ValueError) as cm:
      context.flatten_json_data(raw_data)
    self.assertIn("Expected 7 iterations for workload Video_Effects, but got 1",
                  str(cm.exception))

  def test_to_json_empty_payload_raises_error(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())

    mock_actions = mock.MagicMock()
    mock_actions.js.return_value = "{}"
    self.assertRaises(argparse.ArgumentTypeError, context.to_json, mock_actions)

    mock_actions.js.return_value = ""
    self.assertRaises(json.JSONDecodeError, context.to_json, mock_actions)

  def test_flatten_json_data_empty_raise_error(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())
    self.assertRaises(argparse.ArgumentTypeError, context.flatten_json_data, {})

  def test_extract_metric_value(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())

    data = {"score": 200, "geomean": 50.5, "zero": 0, "bad": "abc"}
    self.assertEqual(context._extract_metric_value(data, "score"), 200.0)
    self.assertEqual(context._extract_metric_value(data, "geomean"), 50.5)
    self.assertIsNone(
        context._extract_metric_value(data, "Score", min_value=150))
    self.assertIsNone(context._extract_metric_value(data, "zero", min_value=0))
    self.assertRaises(argparse.ArgumentTypeError, context._extract_metric_value,
                      data, "bad")
    self.assertIsNone(context._extract_metric_value(data, "missing"))

  def test_extract_workload_metrics(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())
    json_data = {
        "tests": [{
            "iters": 2,
        }],
        "workloads": [
            {
                "workloadID": 0,
                "dur": 1000.0,
            },
            {
                "workloadID": 0,
                "dur": 1500.0,
            },
            {
                "workloadID": 1,
                "dur": 800.0,
            },
            {
                "workloadID": 1,
                "dur": 900.0,
            },
        ],
    }
    result: dict[str, float] = {}
    context._extract_workload_metrics(json_data, result)
    self.assertAlmostEqual(result["Video_Effects"], 1250.0)
    self.assertAlmostEqual(result["Detect_Faces"], 850.0)

  def test_extract_workload_metrics_mismatched_iters(self):
    stories = self.story_cls.all()
    context = self.probe_context_cls(
        self.probe_cls(benchmark=self.benchmark_cls(stories)), mock.MagicMock())
    json_data = {
        "tests": [{
            "iters": 3,
        }],
        "workloads": [
            {
                "workloadID": 0,
                "dur": 1000.0,
            },
            {
                "workloadID": 0,
                "dur": 1500.0,
            },
        ],
    }
    result: dict[str, float] = {}
    with self.assertRaises(ValueError) as cm:
      context._extract_workload_metrics(json_data, result)
    self.assertIn("Expected 3 iterations for workload Video_Effects, but got 2",
                  str(cm.exception))

  def test_story_filter_single(self):
    parser = CBArgumentParser()
    self.benchmark_cls.add_cli_arguments(parser)
    args = parser.parse_args(["--story", "video-effects"])
    story_filter = self.story_filter_cls.from_cli_args(self.story_cls, args)
    self.assertEqual(len(story_filter.stories), 1)
    self.assertSequenceEqual(story_filter.stories[0].substories,
                             ("video-effects",))

  def test_story_filter_all(self):
    parser = CBArgumentParser()
    self.benchmark_cls.add_cli_arguments(parser)
    args = parser.parse_args(["--stories", "all"])
    story_filter = self.story_filter_cls.from_cli_args(self.story_cls, args)
    self.assertEqual(len(story_filter.stories), 1)
    self.assertEqual(story_filter.stories[0].substories,
                     self.story_cls.SUBSTORIES)

  def test_story_filter_invalid_multiple(self):
    parser = CBArgumentParser()
    self.benchmark_cls.add_cli_arguments(parser)
    args = parser.parse_args(["--stories", "video-effects,face-detection"])
    with self.assertRaises(argparse.ArgumentTypeError):
      self.story_filter_cls.from_cli_args(self.story_cls, args)

  def test_story_filter_separate_multiple(self):
    parser = CBArgumentParser()
    self.benchmark_cls.add_cli_arguments(parser)
    args = parser.parse_args(
        ["--stories", "video-effects,face-detection", "--separate"])
    story_filter = self.story_filter_cls.from_cli_args(self.story_cls, args)
    self.assertEqual(len(story_filter.stories), 2)
    self.assertSequenceEqual(story_filter.stories[0].substories,
                             ("video-effects",))
    self.assertSequenceEqual(story_filter.stories[1].substories,
                             ("face-detection",))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
