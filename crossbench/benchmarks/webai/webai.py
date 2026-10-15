# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import datetime as dt
import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Sequence

from typing_extensions import override

from crossbench.benchmarks.base import PressBenchmark, \
    PressBenchmarkStoryFilter
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.probes.json import JsonResultProbe, JsonResultProbeContext
from crossbench.probes.metric import Metric, MetricsMerger
from crossbench.stories.press_benchmark import PressBenchmarkStory

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.benchmarks.base import VersionParts
  from crossbench.probes.results import ProbeResult, ProbeResultDict
  from crossbench.runner.actions import Actions
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run
  from crossbench.types import Json


class WebAIProbe(BenchmarkProbeMixin, JsonResultProbe, metaclass=abc.ABCMeta):
  """
  WebAI-specific probe.
  Extracts all WebAI times and scores.
  """
  NAME: ClassVar[str] = "webai"

  @override
  def create_context(self, run: Run) -> WebAIProbeContext:
    context = super().create_context(run)
    assert isinstance(context, WebAIProbeContext)
    return context

  @override
  def get_context_cls(self) -> type[WebAIProbeContext]:
    return WebAIProbeContext

  @override
  def merge_stories(self, group: StoriesRunGroup) -> ProbeResult:
    merged = MetricsMerger.merge_json_list(
        repetitions_group.results[self].json
        for repetitions_group in group.repetitions_groups)
    return self.write_group_result(group, merged)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    return self.merge_browsers_json_list(group).merge(
        self.merge_browsers_csv_list(group))

  @override
  def log_run_result(self, run: Run) -> None:
    self._log_result(run.results, single_result=True)

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    self._log_result(group.results, single_result=False)

  def _log_result(self, result_dict: ProbeResultDict,
                  single_result: bool) -> None:
    if self not in result_dict:
      return
    results_json: pth.LocalPath = result_dict[self].json
    logging.info("-" * 80)
    logging.critical("WebAI results:")
    if not single_result:
      logging.critical("  %s", result_dict[self].csv)
      logging.critical("  %s", result_dict[self].get("xlsx"))
    logging.info("- " * 40)

    with results_json.open(encoding="utf-8") as f:
      data = json.load(f)
      if single_result:
        score = data.get("Score")
        if score is None:
          for value in data.values():
            if isinstance(value, dict) and "Score" in value:
              score = value["Score"]
              break
        logging.critical("Score %s", score)
      else:
        self._log_result_metrics(data)

  @override
  def _extract_result_metrics_table(self, metrics: dict[str, Any],
                                    table: dict[str, list[str]]) -> None:
    for metric_key, metric in metrics.items():
      if isinstance(metric,
                    dict) and "average" in metric and "stddev" in metric:
        table[metric_key].append(
            Metric.format(metric["average"], metric["stddev"]))
      elif isinstance(metric, (int, float)):
        table[metric_key].append(str(metric))


class WebAIProbeContext(JsonResultProbeContext):
  JS: ClassVar = "return JSON.stringify(window.benchmarkClient.metrics);"

  @override
  def to_json(self, actions: Actions) -> Json:
    json_payload = actions.js(self.JS)
    return json.loads(json_payload)

  @override
  def flatten_json_data(self, json_data: Any) -> Json:
    if isinstance(json_data, list):
      merged = MetricsMerger(json_data).to_json(
          value_fn=lambda values: values.average)
      return merged
    if isinstance(json_data, dict):
      result: dict[str, Any] = {}
      for name, metric in json_data.items():
        if isinstance(metric, dict):
          if "mean" in metric:
            result[name] = metric["mean"]
          else:
            result[name] = metric
        else:
          result[name] = metric
      return result
    return json_data


class WebAIStory(PressBenchmarkStory):
  NAME: ClassVar[str] = "webai"
  URL: ClassVar[str] = "https://browserben.ch/webai-compute-benchmark/main/"
  URL_OFFICIAL: ClassVar[
      str] = "https://browserben.ch/webai-compute-benchmark/main/"
  URL_LOCAL: ClassVar[str] = "http://localhost:8000/"
  SUBSTORIES: ClassVar[tuple[str, ...]] = (
      "webai_default",
      "webgpu",
      "webnn",
      "wasm",
  )

  @classmethod
  @override
  def default_story_names(cls) -> tuple[str, ...]:
    return ("webai_default",)

  def __init__(self,
               substories: Sequence[str] = (),
               url: str | None = None) -> None:
    if not substories:
      substories = self.SUBSTORIES
    super().__init__(substories=substories, url=url or self.URL)

  @property
  @override
  def substory_duration(self) -> dt.timedelta:
    return dt.timedelta(minutes=5)

  @property
  @override
  def slow_duration(self) -> dt.timedelta:
    return dt.timedelta(hours=2)

  @override
  def setup(self, run: Run) -> None:
    with run.actions("Setup") as actions:
      actions.show_url(self.url)
      actions.wait_js_condition(
          "return !!window.benchmarkClient", 0.5, timeout=10)
      # Similar to Speedometer 3, WebAI might need some client setup
      actions.js("""
        window.testDone = false;
        const client = window.benchmarkClient;
        const originalDidFinishLastIteration = client.didFinishLastIteration;
        client.didFinishLastIteration = function(...args) {
          originalDidFinishLastIteration.apply(this, args);
          window.testDone = true;
        };
      """)

  def run(self, run: Run) -> None:
    with run.actions("Running") as actions:
      # Try to find a start button and click it
      actions.js("""
        if (window.startTest) {
          window.startTest();
        } else {
          let startButton = document.querySelector(
              "#runSuites, .start-tests-button, button.start");
          if (startButton) startButton.click();
        }
      """)
    with run.actions("Waiting for completion") as actions:
      actions.wait_js_condition(
          "return window.testDone", 0.5, timeout=self.slow_duration)


class WebAIBenchmark(PressBenchmark):
  """
  Benchmark runner for WebAI.
  """
  NAME: ClassVar[str] = "webai"
  DEFAULT_STORY_CLS = WebAIStory
  PROBES: ClassVar[tuple[type[WebAIProbe], ...]] = (WebAIProbe,)
  STORY_FILTER_CLS: ClassVar = PressBenchmarkStoryFilter

  @classmethod
  @override
  def short_base_name(cls) -> str:
    return "webai"

  @classmethod
  @override
  def base_name(cls) -> str:
    return "webai"

  @classmethod
  @override
  def version(cls) -> VersionParts:
    return ("main",)
