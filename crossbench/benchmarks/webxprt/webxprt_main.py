# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import datetime as dt
import json
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING, ClassVar, Final, Generic, Iterable, \
    Mapping, Sequence, TypeVar

from tabulate import tabulate
from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.enums import ReadyState
from crossbench.benchmarks.base import PressBenchmark, \
    PressBenchmarkStoryFilter
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.parse import NumberParser, ObjectParser
from crossbench.probes.json import JsonResultProbe, JsonResultProbeContext
from crossbench.probes.metric import Metric, MetricsMerger
from crossbench.runner.run import Run
from crossbench.stories.press_benchmark import PressBenchmarkStory

if TYPE_CHECKING:
  from crossbench.benchmarks.base import VersionParts
  from crossbench.probes.results import ProbeResult, ProbeResultDict
  from crossbench.runner.actions import Actions
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run
  from crossbench.types import Json, JsonDict

WebXPRTProbeT = TypeVar("WebXPRTProbeT", bound="WebXPRT5Probe")


class WebXPRT5Probe(
    BenchmarkProbeMixin, JsonResultProbe, metaclass=abc.ABCMeta):
  """WebXPRT5-specific probe."""
  NAME: ClassVar[str] = "webxprt5"

  @override
  def get_context_cls(self) -> type[WebXPRT5ProbeContext[WebXPRT5Probe]]:
    return WebXPRT5ProbeContext

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
    assert not result_dict[self].is_empty, "Expected non-empty probe result"
    results_json: pth.LocalPath = result_dict[self].json
    logging.info("-" * 80)
    logging.critical("WebXPRT 5 results:")
    if not single_result:
      logging.critical("  %s", result_dict[self].csv)
      logging.info("- " * 40)

    with results_json.open(encoding="utf-8") as f:
      data: JsonDict = json.load(f)
      if single_result:
        score_keys = ("Score", "Geomean", "Variance")
        score_table: list[list[Json]] = [
            [key, data.pop(key)] for key in score_keys if key in data
        ]
        if score_table:
          logging.critical(
              tabulate(score_table, tablefmt="plain", floatfmt=".3f"))
          logging.info(" ")
        logging.critical(
            tabulate(
                data.items(),
                headers=("Workload", "Duration (ms)"),
                floatfmt=".3f"))
        logging.info("- " * 40)
      else:
        self._log_result_metrics(data)

  @override
  def _extract_result_metrics_table(self, metrics: JsonDict,
                                    table: dict[str, list[str]]) -> None:
    for metric_key, metric in metrics.items():
      if isinstance(metric,
                    dict) and "average" in metric and "stddev" in metric:
        table[metric_key].append(
            Metric.format(metric["average"], metric["stddev"]))
      elif isinstance(metric, (int, float)):
        table[metric_key].append(str(metric))


class WebXPRT5ProbeContext(
    JsonResultProbeContext[WebXPRTProbeT],
    Generic[WebXPRTProbeT],
    metaclass=abc.ABCMeta):

  def __init__(self, probe: WebXPRTProbeT, run: Run) -> None:
    super().__init__(probe, run)
    self._script: Final[str] = ObjectParser.str_or_file_contents(
        pth.LocalPath(__file__).parent / "script.js",
        name=f"{self.probe.name} script",
    )

  @override
  def to_json(self, actions: Actions) -> Json:
    raw_data = json.loads(actions.js(self._script))
    return ObjectParser.non_empty_dict(raw_data, f"{self.probe.name} raw json")

  @override
  def flatten_json_data(self, json_data: Json) -> Json:
    """
    Example data from JS:
    json_data: dict{
      "tests": list[{
        "mode": str,
        "testType": str,
        "numWorkloads": int,
        "iters": int,
        "additionalInfo": dict{
          "scoreCalculated": 0 | 1,
          "score": int,
          "geomean": float,
          "variance": int,
        }
      }]
      "workloads": list[{
        "testname": str,
        "workloadID": int,
        "workload": str,
        "iter": int,
        "dur": float,
        "info": [],
      }]
    }
    """
    json_data = ObjectParser.non_empty_dict(json_data,
                                            f"{self.probe.name} flatten json")
    if "tests" not in json_data and "workloads" not in json_data:
      return json_data
    result: dict[str, float] = {}
    self._extract_workload_metrics(json_data, result)
    self._extract_summary_metrics(json_data, result)
    return result

  def _extract_summary_metrics(self, json_data: Mapping[str, object],
                               result: dict[str, float]) -> None:
    test_info = self._get_test_info(json_data)
    info = ObjectParser.non_empty_dict(test_info["additionalInfo"],
                                       "additionalInfo")
    # scoreCalculated is 0 indicates that no score is expected for test.
    # For single workload, scoreCalculated will be 0 and we skip metric
    # extraction. For all workloads (testType is "all"), if scoreCalculated is
    # 0, raise exception.
    if info.get("scoreCalculated", 1) == 0:
      if test_info["testType"] == "all":
        raise ValueError(
            f"{self.probe.name}: Score not calculated for all tests")
      return

    score = self._extract_metric_value(info, "score", min_value=0)
    if score is not None:
      result["Score"] = score
    geomean = self._extract_metric_value(info, "geomean", min_value=0)
    if geomean is not None:
      result["Geomean"] = geomean
    variance = self._extract_metric_value(info, "variance")
    if variance is not None:
      result["Variance"] = variance

  def _extract_workload_metrics(self, json_data: Mapping[str, object],
                                result: dict[str, float]) -> None:
    workloads = json_data["workloads"]
    workloads_seq = ObjectParser.non_empty_sequence(workloads, "workloads")

    workload_durations: dict[str, list[float]] = defaultdict(list)
    for i, item in enumerate(workloads_seq):
      workload_dict = ObjectParser.non_empty_dict(item, f"workload item {i}")
      workload_name = self._get_workload_name(workload_dict)
      dur_value = workload_dict.get("dur")
      duration = NumberParser.positive_zero_float(dur_value,
                                                  f"{workload_name} duration")
      workload_durations[workload_name].append(duration)

    expected_iters = self._get_expected_iters(json_data)
    for workload_name, durations in workload_durations.items():
      if len(durations) != expected_iters:
        raise ValueError(f"Expected {expected_iters} iterations for workload "
                         f"{workload_name}, but got {len(durations)}")
      result[workload_name] = Metric(durations).average

  def _get_test_info(self, json_data: Mapping[str,
                                              object]) -> dict[str, object]:
    tests = json_data["tests"]
    tests_seq = ObjectParser.non_empty_sequence(tests, "tests")
    return ObjectParser.non_empty_dict(tests_seq[0], "test")

  def _get_expected_iters(self, json_data: Mapping[str, object]) -> int:
    test_info = self._get_test_info(json_data)
    return NumberParser.positive_int(test_info["iters"], "expected iterations")

  def _get_workload_name(self, item: Mapping[str, object]) -> str:
    workload_id = NumberParser.int_range(0, len(WebXPRT5Story.SUBSTORIES))(
        item["workloadID"])
    workload_key = WebXPRT5Story.SUBSTORIES[workload_id]
    return WebXPRT5Story.WORKLOADS[workload_key]

  def _extract_metric_value(self,
                            data: Mapping[str, object],
                            key: str,
                            min_value: float | None = None) -> float | None:
    if key not in data:
      return None
    value = data[key]
    float_val = NumberParser.any_float(value, key)
    if min_value is not None and float_val <= min_value:
      return None
    return float_val


class WebXPRT5Story(PressBenchmarkStory, metaclass=abc.ABCMeta):
  NAME: ClassVar[str] = "webxprt5"
  URL: ClassVar[str] = "https://www.principledtechnologies.com/wx5/index.html"
  URL_OFFICIAL: ClassVar[
      str] = "https://www.principledtechnologies.com/wx5/index.html"
  URL_LOCAL: ClassVar[str] = "http://localhost:8000/wx5/index.html"
  WORKLOADS: ClassVar[dict[str, str]] = {
      "video-effects": "Video_Effects",
      "face-detection": "Detect_Faces",
      "image-classification": "Image_Classification",
      "document-scanning": "Document_Scanning",
      "photo-effects": "Photo_Effects",
      "school-science-project": "School_Science_Project",
      "homework-spellcheck": "Homework_Spellcheck",
  }
  SUBSTORIES: ClassVar[tuple[str, ...]] = tuple(WORKLOADS.keys())

  @property
  @override
  def substory_duration(self) -> dt.timedelta:
    return dt.timedelta(seconds=30)

  @override
  def setup(self, run: Run) -> None:
    with run.actions("Setup", performance_mark="benchmark-setup") as actions:
      actions.show_url(
          self.url,
          timeout=self.substory_duration,
          ready_state=ReadyState.COMPLETE)
      self.setup_stories(actions)
      actions.wait_js_condition(
          f"""
          const checkedWorkloads = [...document.querySelectorAll(
            'input[data-workload-id]')].filter(e => e.checked === true);
          return checkedWorkloads.length === {len(self.substories)};
          """,
          min_interval=dt.timedelta(seconds=0.5),
          timeout=self.substory_duration)

  def setup_stories(self, actions: Actions) -> None:
    if self.substories == self.SUBSTORIES:
      return
    selected_stories = set(self.substories)
    for index, story in enumerate(self.SUBSTORIES):
      if story not in selected_stories:
        actions.js(f"""document
            .querySelector('input[data-workload-id="{index}"]').click()""")

  @override
  def run(self, run: Run) -> None:
    with run.actions("Running") as actions:
      actions.js(
          "document.querySelector('#startBtn').click()",
          timeout=self.substory_duration / 2)
    with run.actions(
        "Waiting for completion", performance_mark="benchmark-run") as actions:
      actions.wait_for_url_matches(
          re.compile(r"results\.html"),
          min_interval=dt.timedelta(seconds=5),
          timeout=self.slow_duration,
          delay=self.fast_duration)

  @override
  def teardown(self, run: Run) -> None:
    with run.actions("Finalizing") as actions:
      actions.wait_js_condition(
          "return document"
          ".querySelector('#resultsContent #results-details') !== null",
          min_interval=dt.timedelta(seconds=0.5),
          timeout=self.substory_duration,
          delay=dt.timedelta(seconds=5))


class WebXPRT5StoryFilter(PressBenchmarkStoryFilter[WebXPRT5Story]):
  """
  Filter WebXPRT benchmarks by story names.
  Supports either all stories (default) or any one.
  """

  def __init__(self,
               story_cls: type[WebXPRT5Story],
               patterns: Sequence[str],
               args: argparse.Namespace,
               separate: bool = False,
               url: str | None = None,
               tags: Iterable[str] = ()) -> None:
    assert issubclass(story_cls, WebXPRT5Story)
    super().__init__(story_cls, patterns, args, separate, url, tags)

  @override
  def stories_from_names(self,
                         names: Sequence[str]) -> tuple[WebXPRT5Story, ...]:
    if not self.separate and 1 < len(names) < len(self.story_cls.SUBSTORIES):
      raise argparse.ArgumentTypeError(
          f"WebXPRT 5 only supports running either a single workload or all "
          f"workloads, got {len(names)} workloads: {names}. "
          "Use --separate to run multiple workloads as separate stories.")
    return self.story_cls.from_names(
        names, separate=self.separate, url=self.url)


class WebXPRT5Benchmark(PressBenchmark, metaclass=abc.ABCMeta):
  """Benchmark runner for WebXPRT 5"""

  NAME: ClassVar[str] = "webxprt5"
  DEFAULT_STORY_CLS: ClassVar = WebXPRT5Story
  STORY_FILTER_CLS: ClassVar = WebXPRT5StoryFilter
  PROBES: ClassVar[tuple[type[WebXPRT5Probe], ...]] = (WebXPRT5Probe,)

  @classmethod
  @override
  def short_base_name(cls) -> str:
    return "wx5"

  @classmethod
  @override
  def base_name(cls) -> str:
    return "webxprt5"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("wx5",)

  @classmethod
  @override
  def version(cls) -> VersionParts:
    return (5,)
