# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, ClassVar, Final

from typing_extensions import override

from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase, \
    WebPowerSiteConfig, WebPowerStory, WebPowerStoryFilter, _value_or
from crossbench.parse import DurationParser

if TYPE_CHECKING:
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.runner.run import Run


class WebPowerIdleStory(WebPowerStory):
  IS_SCENARIO_CLASS = True
  DEFAULT_DURATION: ClassVar[dt.timedelta] = dt.timedelta(seconds=80)

  @classmethod
  @override
  def story_name_cls(cls) -> str:
    return "idle"

  def __init__(self,
               name_suffix: str,
               site_config: WebPowerSiteConfig,
               duration: dt.timedelta | None = None,
               stabilization_time: dt.timedelta | None = None) -> None:
    stabilization_time = _value_or(stabilization_time,
                                   site_config.default_stabilization_time)
    duration = _value_or(duration, self.DEFAULT_DURATION)

    if duration.total_seconds() == 0:
      # Indefinite idling. (Mapped to 1 year to avoid overflow.)
      duration = dt.timedelta(days=365)
      total_duration = dt.timedelta(days=365)
    else:
      total_duration = (
          duration + stabilization_time + WebPowerStory.DEFAULT_GRACE_PERIOD)

    self._idle_duration: Final[dt.timedelta] = duration
    super().__init__(name_suffix, site_config, total_duration,
                     stabilization_time)

  @property
  def idle_duration(self) -> dt.timedelta:
    return self._idle_duration

  @override
  def run(self, run: Run) -> None:
    with run.actions(
        "Idle", verbose=True,
        performance_mark=WebPowerStory.MEASUREMENT_MARK) as actions:
      actions.wait(self._idle_duration)


class WebPowerIdleStoryFilter(WebPowerStoryFilter[WebPowerIdleStory]):
  """Story filter for Web Power idle stories."""

  IS_SCENARIO_CLASS = True
  STORY_CLS = WebPowerIdleStory


class WebPowerIdleBenchmark(WebPowerBenchmarkBase):
  """Benchmark runner for Power Idle scenario."""

  IS_SCENARIO_CLASS = True
  NAME: ClassVar = f"{WebPowerBenchmarkBase.NAME}-idle"
  DEFAULT_STORY_CLS: ClassVar[type[WebPowerIdleStory]] = WebPowerIdleStory
  STORY_FILTER_CLS: ClassVar = WebPowerIdleStoryFilter

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    parser = super().add_cli_arguments(parser)
    parser.set_defaults(duration=cls.DEFAULT_STORY_CLS.DEFAULT_DURATION)
    return parser

  @classmethod
  @override
  def add_scenario_cli_arguments(cls,
                                 parser: CBArgumentParser) -> CBArgumentParser:
    # TODO(eladalon): Avoid accessing private _option_string_actions.
    actions = parser._option_string_actions  # noqa: SLF001
    if "--duration" not in actions:
      parser.add_argument(
          "--duration",
          type=DurationParser.positive_or_zero_duration,
          help="How long to run the idle phase for. (0 indicates forever.)",
      )
    return parser
