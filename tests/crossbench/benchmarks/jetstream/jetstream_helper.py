# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import abc
import argparse
import copy
import csv
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence
from unittest import mock

from typing_extensions import override

from crossbench.env.runner_env import EnvConfig, RunnerEnv, ValidationMode
from crossbench.runner.runner import Runner
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from crossbench.action_runner.config import ActionRunnerConfig
  from crossbench.benchmarks.jetstream.jetstream_2 import \
      JetStream2Benchmark, JetStream2Probe, JetStream2ProbeContext, \
      JetStream2Story
  from crossbench.benchmarks.jetstream.jetstream_3 import JetStream3Story


class JetStream2BaseTestCase(
    helper.PressBaseBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  @override
  def benchmark_cls(self) -> type[JetStream2Benchmark]:
    pass

  @property
  @abc.abstractmethod
  @override
  def story_cls(self) -> type[JetStream2Story]:
    pass

  @property
  @abc.abstractmethod
  def probe_cls(self) -> type[JetStream2Probe]:
    pass

  @property
  @abc.abstractmethod
  def probe_context_cls(self) -> type[JetStream2ProbeContext]:
    pass

  def test_run_throw(self):
    self._test_run(throw=True)

  def test_run_default(self):
    self._test_run()
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def test_run_custom_url(self):
    custom_url = "http://test.example.com/jetstream"
    self._test_run(custom_url)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertTrue(urls)
      self.assertNotIn(self.story_cls.URL, urls)
      self.assertNotIn(self.story_cls.URL_LOCAL, urls)

  def _test_run(self,
                custom_url: str | None = None,
                story_names=("WSL",),
                throw: bool = True):
    repetitions = 3
    stories = self.story_cls.from_names(story_names, url=custom_url)
    example_story_data = {
        "FirstIteration": 1,
        "Average": 0.1,
        "Worst4": 1.1,
        "Score": 1,
    }
    # The order should match Runner.get_runs
    for _ in range(repetitions):
      for _ in stories:
        jetstream_probe_results = {
            story.name: example_story_data for story in stories
        }
        for browser in self.browsers:
          self._test_run_browser_expectations(browser, jetstream_probe_results)

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
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertTrue(browser.was_js_invoked(self.probe_context_cls.JS))

    csv_file = self.out_dir / f"{self.probe_cls.NAME}.csv"
    with csv_file.open(encoding="utf-8") as f:
      csv_data = list(csv.DictReader(f, delimiter="\t"))
    self.assertSequenceEqual(
        list(csv_data[0].keys()), ["label", "", "dev", "stable"])
    self.assertDictEqual(
        csv_data[1],
        {
            "label": "version",
            "dev": "102.22.33.44",
            "stable": "100.22.33.44",
            # One padding element
            "": "",
        })

    with self.assertLogs(level="INFO") as cm:
      for probe in runner.probes:
        for run in runner.runs:
          probe.log_run_result(run)
    output = "\n".join(cm.output)
    self.assertIn("JetStream results", output)

    with self.assertLogs(level="INFO") as cm:
      for probe in runner.probes:
        probe.log_browsers_result(runner.browser_group)
    output = "\n".join(cm.output)
    self.assertIn("JetStream results", output)
    self.assertIn("102.22.33.44", output)
    self.assertIn("100.22.33.44", output)

  def _test_run_browser_expectations(self, browser,
                                     jetstream_probe_results) -> None:
    # Ready state complete
    browser.expect_js(result=True)
    # Page is ready
    browser.expect_js(result=True)
    # filter benchmarks
    browser.expect_js()
    # UI is updated and ready,
    browser.expect_js(result=True)
    # Start running benchmark
    browser.expect_js()
    # Wait until done
    browser.expect_js(result=True)
    browser.expect_js(result=json.dumps(jetstream_probe_results))

  @dataclass
  class Namespace(argparse.Namespace):
    stories = "default"
    iteration_count: int | None = None
    worst_case_count: int | None = None
    separate: bool = False
    custom_benchmark_url: str | None = None
    detailed_metrics: bool = False
    action_runner_config: ActionRunnerConfig | None = None
    story_tags: Sequence[str] | None = None

  def namespace(self) -> argparse.Namespace:
    return self.Namespace()

  def test_iterations_kwargs(self):
    args = self.Namespace()
    args.stories = "default"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {})

    args.iteration_count = 10
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"iterationCount": "10"})

    args.iteration_count = 123
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"iterationCount": "123"})


# TODO: introduce JetStreamBaseTestCase
class JetStream3BaseTestCase(JetStream2BaseTestCase, metaclass=abc.ABCMeta):

  def test_all_stories_have_tags(self):
    for story_name in self.story_cls.all_story_names():
      story = self.story_cls.from_names([story_name])[0]
      self.assertIsNotNone(story.tags)
      self.assertTrue(len(story.tags) > 0, f"Story {story_name} has no tags")

  @dataclass
  class Namespace(JetStream2BaseTestCase.Namespace):
    prefetch_resources: bool = True

  @override
  def _test_run_browser_expectations(self, browser,
                                     jetstream_probe_results) -> None:
    # Ready state complete
    browser.expect_js(result=True)
    # UI is updated and ready,
    browser.expect_js(result=True)
    # Start running benchmark
    browser.expect_js()
    # Wait until done
    browser.expect_js(result=True)
    browser.expect_js(result=json.dumps(jetstream_probe_results))

  @property
  def story_data(self) -> Mapping[str, tuple[str, ...]]:
    return self.story_cls.STORY_DATA

  @property
  @abc.abstractmethod
  @override
  def story_cls(self) -> type[JetStream3Story]:
    pass

  @override
  def test_run_default(self):
    self._test_run()
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{self.story_cls.URL}?test=WSL", urls)
      self.assertNotIn(f"{self.story_cls.URL_LOCAL}?test=WSL", urls)

  @override
  def test_run_custom_url(self):
    custom_url = "http://test.example.com/jetstream"
    self._test_run(custom_url)
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertIn(f"{custom_url}?test=WSL", urls)
      self.assertNotIn(f"{self.story_cls.URL}?test=WSL", urls)
      self.assertNotIn(f"{self.story_cls.URL_LOCAL}?test=WSL", urls)

  def test_no_prefetch(self):
    args = self.Namespace()
    args.stories = "default"
    args.prefetch_resources = False
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"prefetchResources": "false"})

  def test_worst_case_count_kwargs(self):
    args = self.Namespace()
    args.stories = "default"
    args.worst_case_count = 4
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"worstCaseCount": "4"})

  def test_single_story_url_param(self):
    args = self.Namespace()
    args.stories = "lebab-wtb"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"test": "lebab-wtb"})

  def test_multiple_story_url_param(self):
    args = self.Namespace()
    args.stories = "lebab-wtb|espree-wtb"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertDictEqual(story.url_params, {"test": "lebab-wtb,espree-wtb"})

  def test_tags_wasm(self):
    args = self.Namespace()
    args.story_tags = ["wasm"]
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    for story in benchmark.stories:
      for substory in story.substories:
        tags = self.story_data[substory]
        self.assertIn("wasm", tags, f"missing wasm tag for {substory}: {tags}")

  def test_tags_wasm_default(self):
    args = self.Namespace()
    args.story_tags = ["wasm", "default"]
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    for story in benchmark.stories:
      for substory in story.substories:
        tags = self.story_data[substory]
        self.assertTrue("wasm" in tags or "default" in tags)

  def test_tags_default(self):
    args = self.Namespace()
    args.story_tags = ["default"]
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark.stories)
    substory_names = {
        name for story in benchmark.stories for name in story.substories
    }
    self.assertSetEqual(substory_names,
                        set(self.story_cls.default_story_names()))

  def test_tags_invalid(self):
    args = self.Namespace()
    args.story_tags = ["non-existent-tag"]
    with self.assertRaises(ValueError):
      self.benchmark_cls.from_cli_args(args)

  def test_all_stories_kwargs_url_params(self):
    args = self.Namespace()
    args.stories = "all"
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, "all")
    self.assertDictEqual(story.url_params, {"tags": "all"})

  def test_story_filtering_cli_all(self):
    args = self.parse_args("--all")
    self.assertEqual(args.stories, "all")
    self.assertIsNone(args.story_tags)
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    assert isinstance(story, self.story_cls)
    self.assertEqual(story.name, "all")
    self.assertDictEqual(story.url_params, {"tags": "all"})

    parser = self.create_parser()
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--all", "--stories=default"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--all", "--story-tags=all"])
