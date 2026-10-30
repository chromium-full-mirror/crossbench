# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import copy
import json
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence

from typing_extensions import override

from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.env.runner_env import EnvConfig, ValidationMode
from crossbench.runner.runner import CacheTemperature, Runner
from tests.crossbench.base import BaseCrossbenchTestCase, \
    CrossbenchFakeFsTestCase, CrossbenchPlatformMockMixin
from tests.crossbench.mock_helper import MockPlatform
from tests.crossbench.runner.helper import CrossbenchMagicMockMixin

if TYPE_CHECKING:
  from crossbench.benchmarks.loading.page.base import Page
  from crossbench.probes.probe import Probe


class BaseProbeTestCase(
    CrossbenchPlatformMockMixin,
    CrossbenchMagicMockMixin,
    CrossbenchFakeFsTestCase,
    metaclass=abc.ABCMeta):

  @override
  def setUp(self) -> None:
    self.platform = self.setup_platform()
    self.platform.use_fs = True
    super().setUp()
    self.setup_platform_mock()

  def setup_platform(self) -> MockPlatform:
    return MockPlatform()

  def tearDown(self) -> None:
    self.assertSequenceEqual(self.platform.sh_results, [])
    super().tearDown()


class GenericProbeTestCase(BaseCrossbenchTestCase):

  def create_runner(self,
                    stories: Sequence[Page],
                    js_side_effects: list[Any] | Callable[[Page], list[Any]],
                    separate: bool = False,
                    repetitions: int = 3,
                    warmup_repetitions: int = 0,
                    cache_temperatures: Iterable[CacheTemperature] = (
                        CacheTemperature.DEFAULT,),
                    throw: bool = True) -> Runner:
    self.assertTrue(stories)
    if not separate and len(stories) > 1:
      stories = [CombinedPage(stories)]
    if isinstance(js_side_effects, list):

      def js_side_effects_fn(story):
        del story
        return js_side_effects
    else:
      js_side_effects_fn = js_side_effects
    # The order should match Runner.get_runs
    for _ in range(warmup_repetitions + repetitions):
      for story in stories:
        story_js_side_effects = js_side_effects_fn(story)
        for browser in self.browsers:
          for js_result in story_js_side_effects:
            browser.expect_js(result=js_result)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    benchmark = LoadingBenchmark(stories)
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
        cache_temperatures=cache_temperatures,
        throw=throw,
        in_memory_result_db=True)
    return runner

  def get_non_empty_json_results(self, runner: Runner,
                                 probe: Probe) -> tuple[Any, Any, Any, Any]:
    story_json_file = runner.runs[0].results[probe].json
    with story_json_file.open() as f:
      story_json_data = json.load(f)
    self.assertIsNotNone(story_json_data)

    repetitions_json_file = runner.repetitions_groups[0].results[probe].json
    with repetitions_json_file.open() as f:
      repetitions_json_data = json.load(f)
    self.assertIsNotNone(repetitions_json_data)

    stories_json_file = runner.story_groups[0].results[probe].json
    with stories_json_file.open() as f:
      stories_json_data = json.load(f)
    self.assertIsNotNone(stories_json_data)

    browsers_json_file = runner.browser_group.results[probe].json
    with browsers_json_file.open() as f:
      browsers_json_data = json.load(f)
    self.assertIsNotNone(browsers_json_data)
    return (story_json_data, repetitions_json_data, stories_json_data,
            browsers_json_data)

  def get_non_empty_results_str(
      self,
      runner: Runner,
      probe: Probe,
      suffix: str,
      has_browsers_data: bool = True) -> tuple[str, str, str, str]:
    story_file = runner.runs[0].results[probe].get_all(suffix)[0]
    story_data = story_file.read_text()
    self.assertTrue(story_data)

    repetitions_file = runner.repetitions_groups[0].results[probe].get_all(
        suffix)[0]
    repetitions_data = repetitions_file.read_text()
    self.assertTrue(repetitions_data)

    stories_file = runner.story_groups[0].results[probe].get_all(suffix)[0]
    stories_data = stories_file.read_text()
    self.assertTrue(stories_data)

    if has_browsers_data:
      browsers_file = runner.browser_group.results[probe].get_all(suffix)[0]
      browsers_data = browsers_file.read_text()
      self.assertTrue(browsers_data)
    else:
      browsers_data = ""

    return (story_data, repetitions_data, stories_data, browsers_data)
