# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_input_source import InputSourceAction
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import DurationParser, NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.base import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class ScrollAction(InputSourceAction):
  DEFAULT_DURATION: ClassVar[dt.timedelta] = dt.timedelta(seconds=1)
  TYPE: ClassVar[ActionType] = ActionType.SCROLL

  distance: float = 500.0
  selector: str | None = None
  required: bool = False
  # Overrides BaseDurationAction.duration:
  duration: dt.timedelta = dataclasses.field(
      default=DEFAULT_DURATION, kw_only=True)

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("distance", type=NumberParser.any_float, default=500)
    parser.add_argument(
        "duration",
        type=DurationParser.positive_duration,
        default=cls.DEFAULT_DURATION)
    parser.add_argument("selector", type=ObjectParser.non_empty_str)
    parser.add_argument("required", type=ObjectParser.bool, default=False)
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.scroll(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.distance:
      raise ValueError(f"{self}.distance is not provided")

    if self.required and not self.selector:
      raise ValueError(
          "'required' can only be used when a selector is specified")

  @override
  def supported_input_sources(self) -> tuple[InputSource, ...]:
    return (InputSource.JS, InputSource.TOUCH)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["distance"] = self.distance
    if self.selector:
      details["selector"] = self.selector
    if self.required:
      details["required"] = self.required
    return details
