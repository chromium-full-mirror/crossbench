# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, ClassVar, Final

from typing_extensions import override

from crossbench.action_runner.action.clear_cache import ClearCacheAction
from crossbench.action_runner.action.enums import WindowTarget
from crossbench.benchmarks.loading.playback_controller import \
    PeriodicPlaybackController
from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase, \
    WebPowerSiteConfig, WebPowerStory, WebPowerStoryFilter, _value_or
from crossbench.parse import DurationParser, NumberParser

if TYPE_CHECKING:
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.runner.run import Run


class WebPowerPageLoadStory(WebPowerStory):
  IS_SCENARIO_CLASS = True
  WINDOW_TARGET: ClassVar[WindowTarget] = WindowTarget.NEW_TAB
  DEFAULT_PAGE_LOAD_COUNT: ClassVar[int] = 40
  # TODO: Test all other sites with 10 page loads and converge on a single
  # default value once it's proven that the variance is low.
  DEFAULT_CNN_PAGE_LOAD_COUNT: ClassVar[int] = 10
  DEFAULT_INTERVAL: ClassVar[dt.timedelta] = dt.timedelta(seconds=3)

  @classmethod
  @override
  def story_name_cls(cls) -> str:
    return "page-load"

  def __init__(self,
               name_suffix: str,
               site_config: WebPowerSiteConfig,
               page_load_count: int | None = None,
               interval: dt.timedelta | None = None,
               stabilization_time: dt.timedelta | None = None) -> None:
    default_count = (
        self.DEFAULT_CNN_PAGE_LOAD_COUNT
        if name_suffix == "cnn" else self.DEFAULT_PAGE_LOAD_COUNT)
    self.page_load_count: Final[int] = _value_or(page_load_count, default_count)
    self.interval: Final[dt.timedelta] = _value_or(interval,
                                                   self.DEFAULT_INTERVAL)
    stabilization_time = _value_or(stabilization_time,
                                   site_config.default_stabilization_time)

    total_duration = (
        stabilization_time + self.page_load_count * self.interval +
        WebPowerStory.DEFAULT_GRACE_PERIOD)
    super().__init__(name_suffix, site_config, total_duration,
                     stabilization_time)

  @override
  def run(self, run: Run) -> None:
    logging.info("Starting page-load loop.")
    playback = PeriodicPlaybackController(self.page_load_count, self.interval)
    with run.actions(
        "Run", verbose=True, performance_mark=WebPowerStory.MEASUREMENT_MARK):
      for i in playback:
        # Clearing the cache from inside of the power-measured window is the
        # lesser evil given current technical difficulties with:
        #  1. Currently available cache-clearing mechanisms.
        #  2. The resolution of power-measuring instruments such as ODPM.
        with run.actions(f"Cache_Clear_{i}"):
          run.action_runner.clear_cache(ClearCacheAction.create())
        with run.actions(f"Close_Tab_{i}"):
          run.browser.close_tab(tab_index=0, timeout=dt.timedelta(seconds=1))
        with run.actions(f"Page_Load_{i}") as actions:
          actions.show_url(self.url, target=WindowTarget.NEW_TAB)


class WebPowerPageLoadStoryFilter(WebPowerStoryFilter[WebPowerPageLoadStory]):
  """Story filter for Web Power page-load stories."""

  IS_SCENARIO_CLASS = True
  STORY_CLS = WebPowerPageLoadStory


class WebPowerPageLoadBenchmark(WebPowerBenchmarkBase):
  """Benchmark runner for Power Page-Load scenario."""

  IS_SCENARIO_CLASS = True
  NAME: ClassVar = f"{WebPowerBenchmarkBase.NAME}-page-load"
  DEFAULT_STORY_CLS: ClassVar[
      type[WebPowerPageLoadStory]] = WebPowerPageLoadStory
  STORY_FILTER_CLS: ClassVar = WebPowerPageLoadStoryFilter

  @classmethod
  @override
  def fast_mode_default_overrides(cls) -> dict[str, object]:
    overrides = super().fast_mode_default_overrides()
    overrides["page_load_count"] = 2
    overrides["interval"] = dt.timedelta(seconds=1)
    return overrides

  @classmethod
  @override
  def add_scenario_cli_arguments(cls,
                                 parser: CBArgumentParser) -> CBArgumentParser:
    story_cls = cls.DEFAULT_STORY_CLS
    default_interval_s = story_cls.DEFAULT_INTERVAL.total_seconds()
    parser.add_argument(
        "--page-loads",
        "--page-load-count",
        dest="page_load_count",
        type=NumberParser.positive_int,
        default=None,
        help="Number of times to reload the page. "
        f"(Default: {story_cls.DEFAULT_PAGE_LOAD_COUNT}, "
        f"CNN default: {story_cls.DEFAULT_CNN_PAGE_LOAD_COUNT})")
    parser.add_argument(
        "--interval",
        type=DurationParser.positive_duration,
        default=story_cls.DEFAULT_INTERVAL,
        help="Wait time between page loads. "
        f"(Default: {default_interval_s:.0f}s)")
    return parser
