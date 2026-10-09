# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from collections import defaultdict
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final

import pandas as pd
from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loadline.loadline import LoadLineBenchmark, \
    LoadLineProbe
from crossbench.benchmarks.loadline.loadline_2 import N_EXPECTED_METRICS, \
    process_scores
from crossbench.probes.js import JSProbe
from crossbench.probes.probe_context import ProbeContext

if TYPE_CHECKING:
  import argparse

  from crossbench.benchmarks.loading.page.base import Page
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.flags.base import Flags
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.stories.story import Story as BaseStory

# We should increase the minor version number every time there are any changes
# that might affect the benchmark score.
VERSION_STRING: Final[str] = "2.4.0"


class Event(StrEnum):
  NAVIGATION_START = "navigation_start_ts"
  VISUAL_END = "visual_end_ts"
  INTERACTIVE_END = "interactive_end_ts"


class Metric(StrEnum):
  VISUAL = "visual"
  INTERACTIVE = "interactive"


def split_ts_per_story_and_event(
    j: dict[str, float]) -> dict[str, dict[Event, float]]:
  ts_per_story_and_event: dict[str, dict[Event, float]] = defaultdict(dict)
  for key, value in j.items():
    for event in Event:
      if key.endswith(event):
        story = key[:-len(event) - 1]
        ts_per_story_and_event[story][event] = value
        break
  return ts_per_story_and_event


def get_metric_name(story: str, metric: Metric) -> str:
  return f"{story}_{metric}"


class LoadLine2WebApiProbe(LoadLineProbe):
  NAME: ClassVar = "loadline2_webapi_probe"
  BENCHMARK_NAME: ClassVar = "LoadLine2_WebApi"
  BENCHMARK_VERSION: ClassVar[str] = VERSION_STRING

  @override
  def get_context_cls(self) -> type[LoadLine2WebApiProbeContext]:
    return LoadLine2WebApiProbeContext

  @override
  def _compute_score(self, group: BrowsersRunGroup) -> pd.DataFrame:
    timings: dict[str, list] = {
        "cb_browser": [],
        "metric": [],
        "cb_run": [],
        "value": [],
    }
    browsers = list(group.browsers)
    assert len(browsers) == 1, (
        "Attempting to use 2 different browsers currently fails when "
        "restarting WPR, so the score computation assumes a single browser.")
    for run_number, run in enumerate(group.runs):
      js_results = run.results.get_by_name(JSProbe.NAME)
      if not js_results:
        # No JSON file produced for this repetition, skip it entirely.
        # TODO: warn the user.
        continue

      j = {}
      with js_results.json.open() as file:
        j = json.load(file)

      assert j
      ts_per_story_and_event: dict[str, dict[Event, float]] = (
          split_ts_per_story_and_event(j))

      new_metrics = []
      new_values = []
      broken_metrics = False
      for story, ts_per_event in ts_per_story_and_event.items():
        if not all(e in ts_per_event for e in Event):
          broken_metrics = True
          break

        visual_delay = (
            ts_per_event[Event.VISUAL_END] -
            ts_per_event[Event.NAVIGATION_START])
        interactive_delay = (
            ts_per_event[Event.INTERACTIVE_END] -
            ts_per_event[Event.NAVIGATION_START])
        if visual_delay < 0 or interactive_delay < 0:
          broken_metrics = True
          break

        new_metrics.append(get_metric_name(story, Metric.VISUAL))
        new_values.append(60e3 / visual_delay)
        new_metrics.append(get_metric_name(story, Metric.INTERACTIVE))
        new_values.append(60e3 / interactive_delay)

      if broken_metrics:
        continue

      assert len(new_metrics) == len(new_values)
      # TODO(victorvianna): Show scores even when stories are filtered.
      if len(new_metrics) != N_EXPECTED_METRICS:
        continue

      timings["cb_browser"].extend([browsers[0].unique_name] * len(new_metrics))
      timings["cb_run"].extend([run_number] * len(new_metrics))
      timings["metric"].extend(new_metrics)
      timings["value"].extend(new_values)

    return process_scores(pd.DataFrame.from_dict(timings))

  @override
  def _compute_breakdown(self, group: BrowsersRunGroup) -> pd.DataFrame:
    return pd.DataFrame(index=pd.Index([], name="Not implemented"))


class LoadLine2WebApiProbeContext(ProbeContext[LoadLine2WebApiProbe]):

  def start(self) -> None:
    pass

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    return self.empty_result()


class LoadLine2WebApiBenchmark(LoadLineBenchmark):
  PROBES: ClassVar = (LoadLine2WebApiProbe,)
  DEFAULT_REPETITIONS: ClassVar = 50

  @classmethod
  def _base_dir(cls) -> pth.LocalPath:
    return config.config_dir() / "benchmark" / "loadline2"

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_webapi.hjson"

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    pages = super().stories_from_cli_args(args)
    return (CombinedPage(pages, playback=args.playback),)

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: BaseStory) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if browser_attributes.is_chromium_based:
      # Makes chrome more consistent regarding whether it creates a new
      # renderer process or uses an existing one.
      flags.set("--site-per-process")
    return flags


class LoadLine2WebApiPhoneBenchmark(LoadLine2WebApiBenchmark):
  """A version of LoadLine 2 benchmark that uses pure Web API (no Chromium-only
   features) to collect metrics.
  """
  NAME: ClassVar = "loadline2-webapi-phone"

  @classmethod
  @override
  def default_pages_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "page_config_webapi_phone.hjson"

  @classmethod
  @override
  def default_network_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "network_config_webapi_phone.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-webapi-phone",)


class LoadLine2WebApiPhoneDebugBenchmark(LoadLine2WebApiPhoneBenchmark):
  """LoadLine 2 WebAPI benchmark, with perfetto tracing for debugging.
  """
  NAME: ClassVar = "loadline2-webapi-phone-debug"
  DEFAULT_REPETITIONS: ClassVar = 1

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_webapi_debug.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-webapi-phone-debug",)
