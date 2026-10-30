# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import copy
import csv
import datetime as dt
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence
from unittest import mock

from typing_extensions import override

from crossbench.benchmarks.speedometer.speedometer_3 import \
    MeasurementMethod, Speedometer3Benchmark, Speedometer3Story
from crossbench.browsers.viewport import Viewport
from crossbench.env.runner_env import EnvConfig, ValidationMode
from crossbench.runner.runner import Runner
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from crossbench.action_runner.config import ActionRunnerConfig
  from crossbench.benchmarks.speedometer.speedometer import \
      SpeedometerBenchmark, SpeedometerProbe, SpeedometerProbeContext, \
      SpeedometerStory
  from crossbench.stories.story import Story
  from crossbench.types import Json, JsonDict
  from tests.crossbench.mock_browser import MockBrowser


class SpeedometerBaseTestCase(
    helper.PressBaseBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  @override
  def benchmark_cls(self) -> type[SpeedometerBenchmark]:
    pass

  @property
  @abc.abstractmethod
  @override
  def story_cls(self) -> type[SpeedometerStory]:
    pass

  @property
  @abc.abstractmethod
  def probe_cls(self) -> type[SpeedometerProbe]:
    pass

  @property
  @abc.abstractmethod
  def probe_context_cls(self) -> type[SpeedometerProbeContext]:
    pass

  @property
  @abc.abstractmethod
  def name(self) -> str:
    pass

  @property
  def name_all(self) -> str:
    # Override if default() != all() stories.
    return self.name

  @dataclass
  class Namespace(argparse.Namespace):
    stories = "default"
    iterations: int = 10
    separate: bool = False
    custom_benchmark_url: str | None = None
    action_runner_config: ActionRunnerConfig | None = None
    story_tags: Sequence[str] | None = None

  def test_iterations_kwargs(self):
    args = self.Namespace()
    self.benchmark_cls.from_cli_args(args)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "iteration"):
      # Intentionally assigning str to int field to test CLI validation.
      # pyrefly: ignore[bad-assignment]
      args.iterations = "-10"
      self.benchmark_cls.from_cli_args(args)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "iteration"):
      # Intentionally assigning str to int field to test CLI validation.
      # pyrefly: ignore[bad-assignment]
      args.iterations = "1234"
      benchmark = self.benchmark_cls.from_cli_args(args)
    args.iterations = 1234
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.iterations, 1234)

  def test_cli_iterations(self):
    args = self.parse_args()
    self.assertEqual(args.iterations, self.story_cls.DEFAULT_ITERATIONS)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.iterations, self.story_cls.DEFAULT_ITERATIONS)
      self.assertNotIn("iterationCount", story.url_params)

    for val in (5, 15, 20):
      args = self.parse_args(f"--iterations={val}")
      self.assertEqual(args.iterations, val)
      benchmark = self.benchmark_cls.from_cli_args(args)
      for story in benchmark.stories:
        assert isinstance(story, self.story_cls)
        self.assertEqual(story.iterations, val)
        self.assertEqual(story.url_params.get("iterationCount"), str(val))

    for invalid in ("0", "-1", "-10", "abc", "1.5"):
      with self.subTest(invalid=invalid):
        with self.assertRaisesRegex(argparse.ArgumentError, "--iterations"):
          self.parse_args(f"--iterations={invalid}")

  def test_story_filtering_cli_args_all_separate(self):
    stories = self.story_cls.all(separate=True)
    args = self.Namespace()
    args.stories = "all"
    args.separate = True
    stories_all = self.benchmark_cls.stories_from_cli_args(args)
    self.assertSequenceEqual(
        [story.name for story in stories],
        [story.name for story in stories_all],
    )


  def test_story_filtering(self):
    with self.assertRaises(ValueError):
      self.story_cls.from_names([])
    stories = self.story_cls.default(separate=False)
    self.assertEqual(len(stories), 1)

    with self.assertRaises(ValueError):
      self.story_cls.from_names([], separate=True)
    stories = self.story_cls.default(separate=True)
    self.assertEqual(len(stories), len(self.story_cls.default_story_names()))

  def test_story_filtering_regexp_invalid(self):
    with self.assertRaises(ValueError):
      _ = self.story_filter(".*", separate=True).stories

  def test_story_filtering_regexp(self):
    stories = self.story_cls.all(separate=True)
    stories_b = self.story_filter([".*"], separate=True).stories
    self.assertSequenceEqual(
        [story.name for story in stories],
        [story.name for story in stories_b],
    )

  def _test_run(self,
                story_names: Sequence[str] | None = None,
                separate: bool = False,
                iterations: int = 2,
                repetitions: int = 3,
                warmup_repetitions: int = 0,
                custom_url: str | None = None,
                throw: bool = True) -> Runner:
    if story_names is None:
      default_story_name = self.story_cls.SUBSTORIES[0]
      self.assertTrue(default_story_name)
      story_names = [default_story_name]
    stories = self.story_cls.from_names(
        story_names, separate=separate, url=custom_url, iterations=iterations)

    # The order should match Runner.get_runs
    for _ in range(warmup_repetitions + repetitions):
      for story in stories:
        speedometer_probe_results = self._generate_test_probe_results(
            iterations, story)

        for browser in self.browsers:
          self._setup_run_js_expect(browser, speedometer_probe_results)
    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    benchmark: SpeedometerBenchmark = self.benchmark_cls(
        stories, custom_url=custom_url)
    self.assertTrue(len(benchmark.describe()) > 0)
    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        warmup_repetitions=warmup_repetitions,
        throw=throw,
        in_memory_result_db=True)
    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()
    return runner

  def _setup_run_js_expect(self, browser: MockBrowser,
                           speedometer_probe_results: Json) -> None:
    # Page is ready
    browser.expect_js(result=True)
    # _setup_substories
    browser.expect_js()
    # _setup_benchmark_client
    browser.expect_js()
    # _run_stories
    browser.expect_js()
    # Wait until done
    browser.expect_js(result=True)
    browser.expect_js(result=json.dumps(speedometer_probe_results))

  @abc.abstractmethod
  def _generate_test_probe_results(self, iterations, story):
    pass

  def _verify_results(
      self,
      runner: Runner,
      expected_num_urls: int | None = None) -> list[dict[str, str]]:
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      if expected_num_urls is not None:
        self.assertEqual(len(urls), expected_num_urls)
      self.assertTrue(browser.was_js_invoked(self.probe_context_cls.JS))
      self.assertSequenceEqual(browser.expected_js, [])

    with self.assertLogs(level="INFO") as cm:
      for probe in runner.probes:
        for run in runner.runs:
          probe.log_run_result(run)
    output = "\n".join(cm.output)
    self.assertIn("Speedometer results", output)

    with self.assertLogs(level="INFO") as cm:
      for probe in runner.probes:
        probe.log_browsers_result(runner.browser_group)
    output = "\n".join(cm.output)
    self.assertIn("Speedometer results", output)
    self.assertIn("102.22.33.44", output)
    self.assertIn("100.22.33.44", output)

    csv_files = list(runner.out_dir.glob("speedometer*.csv"))
    self.assertEqual(len(csv_files), 1)
    csv_file = self.out_dir / f"{self.probe_cls.NAME}.csv"
    rows: list[dict[str, str]] = [{}]
    with csv_file.open(encoding="utf-8") as f:
      reader = csv.DictReader(f, delimiter="\t")
      rows = list(reader)
    self.assertSequenceEqual(
        list(rows[0].keys()), ["label", "", "dev", "stable"])
    self.assertDictEqual(
        rows[1],
        {
            "label": "version",
            "dev": "102.22.33.44",
            "stable": "100.22.33.44",
            # Padding element after "label":
            "": "",
        })
    return rows

  def test_run_throw(self):
    runner = self._test_run(throw=True)
    self._verify_results(runner)

  def test_run_default(self):
    runner = self._test_run(iterations=10)
    self._verify_results(runner)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def test_run_warmups(self):
    runner = self._test_run(iterations=10, warmup_repetitions=1)
    self._verify_results(runner)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def test_run_custom_url(self):
    custom_url = "http://test.example.com/speedometer"
    runner = self._test_run(custom_url=custom_url, iterations=10)
    self._verify_results(runner)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(custom_url, urls)
      self.assertNotIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def test_run_custom_iterations(self):
    runner = self._test_run(iterations=7)
    self._verify_results(runner)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{self.story_cls.URL}?iterationCount=7", urls)
      self.assertNotIn(self.story_cls.URL, urls)
      self.assertNotIn(f"{self.story_cls.URL_LOCAL}?iterationCount=7", urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def _verify_results_stories(self, rows, story_names, label_suffix):
    labels = [row["label"] for row in rows]
    story_name_str = "_".join(story_names)
    self.assertNotIn(f"{self.benchmark_cls.NAME}_{story_name_str}", labels)
    for story_name in story_names:
      self.assertIn(f"{story_name}{label_suffix}", labels)

  def _run_combined(self, story_names: Sequence[str], label_suffix: str = ""):
    runner = self._test_run(story_names=story_names, separate=False)
    rows = self._verify_results(runner, expected_num_urls=3)
    self._verify_results_stories(rows, story_names, label_suffix)

  def _run_separate(self, story_names: Sequence[str], label_suffix: str = ""):
    runner = self._test_run(story_names=story_names, separate=True)
    rows = self._verify_results(runner, expected_num_urls=6)
    self._verify_results_stories(rows, story_names, label_suffix)

  def test_run_combined(self):
    self._run_combined(["VanillaJS-TodoMVC", "Elm-TodoMVC"])

  def test_run_separate(self):
    self._run_separate(["VanillaJS-TodoMVC", "Elm-TodoMVC"])


class Speedometer1BaseTestCase(SpeedometerBaseTestCase, metaclass=abc.ABCMeta):

  EXAMPLE_STORY_DATA: JsonDict = {
      "tests": {
          "Adding100Items": {
              "tests": {
                  "Sync": 74.6000000089407,
                  "Async": 6.299999997019768,
              },
              "total": 80.90000000596046,
          },
      },
      "total": 121.40000000596046,
  }

  @override
  def _generate_test_probe_results(self, iterations: int, story: Story) -> Json:
    return [{
        "tests": {
            substory_name: copy.deepcopy(self.EXAMPLE_STORY_DATA)
            for substory_name in story.substories
        },
        "total": 1000,
    }
            for _ in range(iterations)]

  def test_probe_results(self):
    story_names = ("VanillaJS-TodoMVC", "React-TodoMVC")
    self.browsers = [self.browsers[0]]
    runner = self._test_run(
        story_names=story_names, separate=False, repetitions=2)
    run_1, run_2 = runner.runs
    probe_file = f"{self.probe_cls.NAME}.json"
    with (run_1.out_dir / probe_file).open() as f:
      data_1 = json.load(f)
    with (run_2.out_dir / probe_file).open() as f:
      data_2 = json.load(f)
    keys_1 = tuple(data_1.keys())
    keys_2 = tuple(data_2.keys())
    self.assertSequenceEqual(keys_1, keys_2)
    self.assertIn("Score", keys_1)
    self.assertIn("Total", keys_1)

  @override
  def test_run_combined(self):
    self._run_combined(["VanillaJS-TodoMVC", "React-TodoMVC"],
                       label_suffix="/total")

  @override
  def test_run_separate(self):
    self._run_separate(["VanillaJS-TodoMVC", "React-TodoMVC"],
                       label_suffix="/total")

  def test_flags_not_supported(self):
    parser = self.create_parser()
    for flag in (
        "--sync-wait=10ms",
        "--sync-warmup=10ms",
        "--raf",
        "--timer",
        "--story-viewport=800x600",
        "--shuffle-seed=1234",
        "--detailed-metrics",
        "--details",
        "--measure-prepare",
    ):
      with self.subTest(flag=flag):
        with self.assertRaises((argparse.ArgumentError, SystemExit)):
          parser.parse_args([flag])


class Speedometer2BaseTestCase(SpeedometerBaseTestCase, metaclass=abc.ABCMeta):

  EXAMPLE_STORY_DATA: JsonDict = {
      "tests": {
          "Adding100Items": {
              "tests": {
                  "Sync": 74.6000000089407,
                  "Async": 6.299999997019768,
              },
              "total": 80.90000000596046,
          },
          "CompletingAllItems": {
              "tests": {
                  "Sync": 22.600000008940697,
                  "Async": 5.899999991059303,
              },
              "total": 28.5,
          },
          "DeletingItems": {
              "tests": {
                  "Sync": 11.800000011920929,
                  "Async": 0.19999998807907104,
              },
              "total": 12,
          },
      },
      "total": 121.40000000596046,
  }

  @override
  def _generate_test_probe_results(self, iterations: int, story: Story) -> Json:
    return [{
        "tests": {
            substory_name: copy.deepcopy(self.EXAMPLE_STORY_DATA)
            for substory_name in story.substories
        },
        "total": 1000,
        "mean": 2000,
        "geomean": 3000,
        "score": 10,
    }
            for _ in range(iterations)]

  def test_probe_results(self):
    story_names = ("VanillaJS-TodoMVC", "React-TodoMVC")
    self.browsers = [self.browsers[0]]
    runner = self._test_run(
        story_names=story_names, separate=False, repetitions=2)
    run_1, run_2 = runner.runs
    probe_file = f"{self.probe_cls.NAME}.json"
    with (run_1.out_dir / probe_file).open() as f:
      data_1 = json.load(f)
    with (run_2.out_dir / probe_file).open() as f:
      data_2 = json.load(f)
    keys_1 = tuple(data_1.keys())
    keys_2 = tuple(data_2.keys())
    self.assertSequenceEqual(keys_1, keys_2)
    # Make sure the aggregate metrics are at the end
    self.assertSequenceEqual(keys_1[-2:], ("Geomean", "Score"))

    with (runner.story_groups[0].path / probe_file).open() as f:
      stories_data = json.load(f)
    self.assertSequenceEqual(
        tuple(stories_data.keys())[-2:], ("Geomean", "Score"))

  @override
  def test_run_combined(self):
    self._run_combined(["VanillaJS-TodoMVC", "Elm-TodoMVC"],
                       label_suffix="/total")

  @override
  def test_run_separate(self):
    self._run_separate(["VanillaJS-TodoMVC", "Elm-TodoMVC"],
                       label_suffix="/total")

  def test_flags_not_supported(self):
    parser = self.create_parser()
    for flag in (
        "--sync-wait=10ms",
        "--sync-warmup=10ms",
        "--raf",
        "--timer",
        "--story-viewport=800x600",
        "--shuffle-seed=1234",
        "--detailed-metrics",
        "--details",
        "--measure-prepare",
    ):
      with self.subTest(flag=flag):
        with self.assertRaises((argparse.ArgumentError, SystemExit)):
          parser.parse_args([flag])


class Speedometer3BaseTestCase(SpeedometerBaseTestCase):

  @property
  @abc.abstractmethod
  @override
  def benchmark_cls(self) -> type[Speedometer3Benchmark]:
    pass

  @property
  @abc.abstractmethod
  @override
  def story_cls(self) -> type[Speedometer3Story]:
    pass

  @property
  @override
  def name_all(self):
    return "all"

  def _setup_run_js_expect(self, browser: MockBrowser,
                           speedometer_probe_results: Json) -> None:
    # Page is ready
    browser.expect_js(result=True)
    # _setup_benchmark_client
    browser.expect_js()
    # _run_stories
    browser.expect_js()
    # Wait until done
    browser.expect_js(result=True)
    browser.expect_js(result=json.dumps(speedometer_probe_results))

  @dataclass
  class Namespace(SpeedometerBaseTestCase.Namespace):
    sync_wait = dt.timedelta(0)
    sync_warmup = dt.timedelta(0)
    measurement_method = MeasurementMethod.RAF
    story_viewport = None
    shuffle_seed = None
    detailed_metrics = False
    measure_prepare = None

  EXAMPLE_STORY_DATA: dict[str, Any] = {}

  def _generate_s3_metrics(self, name, values):
    return {
        "children": [],
        "delta": 0,
        "geomean": 39.20000000298023,
        "max": 39.20000000298023,
        "mean": 39.20000000298023,
        "min": 39.20000000298023,
        "name": name,
        "percentDelta": 0,
        "sum": 39.20000000298023,
        "unit": "ms",
        "values": values,
    }

  @override
  def _generate_test_probe_results(self, iterations, story) -> Json:
    values = [21.3] * iterations
    probe_result = {}
    for substory_name in story.substories:
      probe_result[substory_name] = self._generate_s3_metrics(
          substory_name, values)

    for iteration in range(iterations):
      key = f"Iteration-{iteration}-Total"
      probe_result[key] = self._generate_s3_metrics(key, values)

    probe_result.update({
        "Geomean": self._generate_s3_metrics("Geomean", values),
        "Score": self._generate_s3_metrics("Score", values),
    })
    return probe_result

  @override
  def test_run_combined(self):
    self._run_combined(["TodoMVC-JavaScript-ES5", "TodoMVC-Backbone"])

  @override
  def test_run_separate(self):
    self._run_separate(["TodoMVC-JavaScript-ES5", "TodoMVC-Backbone"])

  def test_probe_results(self):
    story_names = ("TodoMVC-JavaScript-ES5", "TodoMVC-Backbone")
    self.browsers = [self.browsers[0]]
    runner = self._test_run(
        story_names=story_names, separate=False, repetitions=2)
    self.assertEqual(len(runner.runs), 2)
    run_1 = runner.runs[0]
    run_2 = runner.runs[1]
    probe_file = f"{self.probe_cls.NAME}.json"
    with (run_1.out_dir / probe_file).open() as f:
      data_1 = json.load(f)
    with (run_2.out_dir / probe_file).open() as f:
      data_2 = json.load(f)
    keys_1 = tuple(data_1.keys())
    keys_2 = tuple(data_2.keys())
    self.assertSequenceEqual(keys_1, keys_2)
    # Make sure the aggregate metrics are at the end
    expected_keys = (*story_names, "Iteration-0-Total", "Iteration-1-Total",
                     "Geomean", "Score")
    self.assertSequenceEqual(keys_1, expected_keys)

    with (runner.story_groups[0].path / probe_file).open() as f:
      stories_data = json.load(f)
    self.assertSequenceEqual(tuple(stories_data.keys()), expected_keys)

  def test_cli_sync_wait(self):
    parser = self.create_parser()
    args = parser.parse_args([])
    self.assertEqual(args.sync_wait, dt.timedelta(0))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("waitBeforeSync", story.url_params)

    args = parser.parse_args(["--sync-wait=100ms"])
    self.assertEqual(args.sync_wait, dt.timedelta(milliseconds=100))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("waitBeforeSync"), "100")

    args = parser.parse_args(["--sync-wait", "1.5s"])
    self.assertEqual(args.sync_wait, dt.timedelta(seconds=1.5))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("waitBeforeSync"), "1500")

    args = parser.parse_args(["--sync-wait", "2s"])
    self.assertEqual(args.sync_wait, dt.timedelta(seconds=2))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("waitBeforeSync"), "2000")

    args = parser.parse_args(["--sync-wait", "5"])
    self.assertEqual(args.sync_wait, dt.timedelta(seconds=5))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("waitBeforeSync"), "5000")

    args = parser.parse_args(["--sync-wait", "0"])
    self.assertEqual(args.sync_wait, dt.timedelta(0))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("waitBeforeSync", story.url_params)

    for invalid in ("-10ms", "-1s", "invalid"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentError):
          parser.parse_args([f"--sync-wait={invalid}"])

  def test_sync_wait_kwargs(self):
    args = self.Namespace()
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertDictEqual(story.url_params, {})

    args.sync_wait = dt.timedelta(seconds=123.4)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertDictEqual(story.url_params, {"waitBeforeSync": "123400"})

  def test_cli_sync_warmup(self):
    parser = self.create_parser()
    args = parser.parse_args([])
    self.assertEqual(args.sync_warmup, dt.timedelta(0))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("warmupBeforeSync", story.url_params)

    args = parser.parse_args(["--sync-warmup=150ms"])
    self.assertEqual(args.sync_warmup, dt.timedelta(milliseconds=150))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("warmupBeforeSync"), "150")

    args = parser.parse_args(["--sync-warmup", "1.5s"])
    self.assertEqual(args.sync_warmup, dt.timedelta(seconds=1.5))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("warmupBeforeSync"), "1500")

    args = parser.parse_args(["--sync-warmup", "2s"])
    self.assertEqual(args.sync_warmup, dt.timedelta(seconds=2))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("warmupBeforeSync"), "2000")

    args = parser.parse_args(["--sync-warmup", "0"])
    self.assertEqual(args.sync_warmup, dt.timedelta(0))
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("warmupBeforeSync", story.url_params)

    for invalid in ("-5s", "-100ms", "invalid"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentError):
          parser.parse_args([f"--sync-warmup={invalid}"])

  def test_sync_warmup_kwargs(self):
    args = self.Namespace()
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertFalse(story.url_params)

    args.sync_warmup = dt.timedelta(seconds=123.4)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertDictEqual(story.url_params, {"warmupBeforeSync": "123400"})

  def test_cli_measurement_method_flags(self):
    parser = self.create_parser()
    args = parser.parse_args([])
    self.assertEqual(args.measurement_method, MeasurementMethod.RAF)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("measurementMethod", story.url_params)

    args = parser.parse_args(["--raf"])
    self.assertEqual(args.measurement_method, MeasurementMethod.RAF)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("measurementMethod", story.url_params)

    args = parser.parse_args(["--timer"])
    self.assertEqual(args.measurement_method, MeasurementMethod.TIMER)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("measurementMethod"), "timer")

    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--raf", "--timer"])

  def test_measurement_method_kwargs(self):
    args = self.Namespace()
    args.stories = "default"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, self.name)
    self.assertDictEqual(story.url_params, {})

    args.measurement_method = MeasurementMethod.TIMER
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, self.name)
    self.assertDictEqual(story.url_params, {"measurementMethod": "timer"})

  def test_viewport_kwargs(self):
    args = self.Namespace()
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertFalse(story.url_params)

    args.story_viewport = Viewport(999, 888)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertDictEqual(story.url_params, {"viewport": "999x888"})

  def test_cli_shuffle_seed(self):
    parser = self.create_parser()
    args = parser.parse_args([])
    self.assertIsNone(args.shuffle_seed)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertNotIn("shuffleSeed", story.url_params)

    args = parser.parse_args(["--shuffle-seed=off"])
    self.assertEqual(args.shuffle_seed, "off")
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("shuffleSeed"), "off")

    args = parser.parse_args(["--shuffle-seed", "generate"])
    self.assertEqual(args.shuffle_seed, "generate")
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("shuffleSeed"), "generate")

    args = parser.parse_args(["--shuffle-seed=12345"])
    self.assertEqual(args.shuffle_seed, 12345)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("shuffleSeed"), "12345")

    args = parser.parse_args(["--shuffle-seed=-42"])
    self.assertEqual(args.shuffle_seed, -42)
    benchmark = self.benchmark_cls.from_cli_args(args)
    for story in benchmark.stories:
      assert isinstance(story, self.story_cls)
      self.assertEqual(story.url_params.get("shuffleSeed"), "-42")

    for invalid in ("invalid", "12.34", "true", "false"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentError):
          parser.parse_args([f"--shuffle-seed={invalid}"])

  def test_cli_detailed_metrics(self):
    args = self.parse_args()
    self.assertFalse(args.detailed_metrics)
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertFalse(benchmark.detailed_metrics)

    args = self.parse_args("--detailed-metrics")
    self.assertTrue(args.detailed_metrics)
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.detailed_metrics)

  def test_detailed_metrics_probe_filtering(self):
    benchmark_default = self.benchmark_cls.from_cli_args(self.Namespace())
    probe_default = self.probe_cls(benchmark=benchmark_default)
    self.assertTrue(probe_default.is_valid_metric_key("Score"))
    self.assertTrue(
        probe_default.is_valid_metric_key(self.story_cls.SUBSTORIES[0]))
    self.assertFalse(probe_default.is_valid_metric_key("Iteration-0-Total"))
    self.assertFalse(probe_default.is_valid_metric_key("Geomean"))
    self.assertFalse(probe_default.is_valid_metric_key("some/nested/metric"))

    args = self.parse_args("--detailed-metrics")
    benchmark_detailed = self.benchmark_cls.from_cli_args(args)
    probe_detailed = self.probe_cls(benchmark=benchmark_detailed)
    self.assertTrue(probe_detailed.is_valid_metric_key("Score"))
    self.assertTrue(
        probe_detailed.is_valid_metric_key(self.story_cls.SUBSTORIES[0]))
    self.assertTrue(probe_detailed.is_valid_metric_key("Iteration-0-Total"))
    self.assertTrue(probe_detailed.is_valid_metric_key("Geomean"))
    self.assertFalse(probe_detailed.is_valid_metric_key("some/nested/metric"))

  def test_cli_speedometer3_flag_aliases(self):
    details_expected = self.parse_args("--detailed-metrics")
    self.assertEqual(self.parse_args("--details"), details_expected)

    tag_expected = self.parse_args("--story-tags=chart")
    self.assertEqual(self.parse_args("--story-tag=chart"), tag_expected)

  def test_cli_story_tags(self):
    parser = self.create_parser()
    args = parser.parse_args(["--story-tags=default"])
    self.assertEqual(args.story_tags, "default")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    substory_names = {
        name for story in benchmark.stories for name in story.substories
    }
    self.assertSetEqual(substory_names,
                        set(self.story_cls.default_story_names()))

    args = parser.parse_args(["--story-tag=chart"])
    self.assertEqual(args.story_tags, "chart")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    for substory in story.substories:
      self.assertIn("chart", self.story_cls.STORY_DATA[substory])

    args = parser.parse_args(["--story-tag=todomvc,-complex"])
    self.assertEqual(args.story_tags, "todomvc,-complex")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    for substory in story.substories:
      tags = self.story_cls.STORY_DATA[substory]
      self.assertIn("todomvc", tags)
      self.assertNotIn("complex", tags)

    args = parser.parse_args(["--story-tags", "todomvc", "--separate"])
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(len(benchmark.stories) > 1)
    for s in benchmark.stories:
      assert isinstance(s, self.story_cls)
      self.assertEqual(len(s.substories), 1)
      self.assertIn("todomvc", self.story_cls.STORY_DATA[s.substories[0]])

  def test_cli_story_tags_invalid(self):
    parser = self.create_parser()
    args = parser.parse_args(["--story-tags=non_existent_tag_12345"])
    with self.assertRaisesRegex(ValueError, "[tT]ag"):
      self.benchmark_cls.from_cli_args(args)

    args = parser.parse_args(["--story-tags", "todomvc,-todomvc"])
    with self.assertRaisesRegex(ValueError, "[tT]ag"):
      self.benchmark_cls.from_cli_args(args)

  def test_all_stories_have_tags(self):
    for story_name in self.story_cls.all_story_names():
      story = self.story_cls.from_names([story_name])[0]
      self.assertIsNotNone(story.tags)
      self.assertTrue(len(story.tags) > 0, f"Story {story_name} has no tags")

  def test_all_stories_kwargs_url_params(self):
    args = self.Namespace()
    args.stories = "all"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, "all")
    self.assertDictEqual(story.url_params, {"tags": "all"})

  def test_story_filtering_cli_all(self):
    parser = self.create_parser()
    args = parser.parse_args(["--all"])
    self.assertEqual(args.stories, "all")
    self.assertIsNone(args.story_tags)
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, "all")
    self.assertDictEqual(story.url_params, {"tags": "all"})

  def test_single_story_kwargs(self):
    args = self.Namespace()
    args.stories = "TodoMVC-jQuery"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, "TodoMVC-jQuery")
    self.assertDictEqual(story.url_params, {"suites": "TodoMVC-jQuery"})

  @override
  def test_iterations_kwargs(self):
    args = self.Namespace()
    args.stories = "default"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.iterations, 10)
    self.assertDictEqual(story.url_params, {})

    args.iterations = 10
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.iterations, 10)
    self.assertDictEqual(story.url_params, {})

    args.iterations = 123
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.iterations, 123)
    self.assertDictEqual(story.url_params, {"iterationCount": "123"})

  @override
  def test_run_default(self):
    runner = self._test_run(iterations=10)
    self._verify_results(runner)
    default_story_name = self.story_cls.SUBSTORIES[0]
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{self.story_cls.URL}?suites={default_story_name}", urls)
      self.assertNotIn(
          f"{self.story_cls.URL_LOCAL}?suites={default_story_name}", urls)

  @override
  def test_run_warmups(self):
    runner = self._test_run(iterations=10, warmup_repetitions=1)
    self._verify_results(runner)
    default_story_name = self.story_cls.SUBSTORIES[0]
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{self.story_cls.URL}?suites={default_story_name}", urls)
      self.assertNotIn(
          f"{self.story_cls.URL_LOCAL}?suites={default_story_name}", urls)

  @override
  def test_run_custom_url(self):
    custom_url = "http://test.example.com/speedometer"
    runner = self._test_run(custom_url=custom_url, iterations=10)
    default_story_name = self.story_cls.SUBSTORIES[0]
    self._verify_results(runner)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{custom_url}?suites={default_story_name}", urls)
      self.assertNotIn(f"{self.story_cls.URL}?suites={default_story_name}",
                       urls)
      self.assertNotIn(
          f"{self.story_cls.URL_LOCAL}?suites={default_story_name}", urls)

  @override
  def test_run_custom_iterations(self):
    runner = self._test_run(iterations=7)
    self._verify_results(runner)
    default_story_name = self.story_cls.SUBSTORIES[0]
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(
          f"{self.story_cls.URL}?iterationCount=7&suites={default_story_name}",
          urls)
      self.assertNotIn(self.story_cls.URL, urls)
      self.assertNotIn(
          f"{self.story_cls.URL_LOCAL}?iterationCount=7"
          f"&suites={default_story_name}", urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)
