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
from crossbench.action_runner.action.position import PositionConfig, \
    SelectorConfig
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import DurationParser, NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class ClickAction(InputSourceAction):
  TYPE: ClassVar[ActionType] = ActionType.CLICK

  position: PositionConfig = dataclasses.field(default_factory=PositionConfig)
  attempts: int = 1
  verify: str | None = None

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "position",
        aliases=("pos", "selector"),
        type=PositionConfig,
        required=True)
    parser.add_argument(
        "duration",
        type=DurationParser.positive_or_zero_duration,
        default=dt.timedelta())
    parser.add_argument("attempts", type=NumberParser.positive_int, default=1)
    parser.add_argument("verify", type=ObjectParser.non_empty_str)

    return parser

  @property
  def selector(self) -> SelectorConfig:
    if selector := self.position.selector:
      return selector
    raise ValueError(f"{self.position} has no selector")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.click(self)

  @override
  def validate(self) -> None:
    super().validate()

    if not self.position:
      raise ValueError(f"{self}.position is missing")

    if (self.input_source in (InputSource.JS, InputSource.DRIVER) and
        not self.position.selector):
      raise ValueError(f"{self.input_source.name} click source requires a "
                       "selector position.")

    if self.attempts != 1:
      if not self.position.selector:
        raise ValueError(
            "multiple attempts can only be used with a selector position.")
      if not self.position.selector.required:
        raise ValueError("non-required clicks can not have multiple attempts.")

  @override
  def validate_duration(self) -> None:
    # A click action is allowed to have a zero duration.
    return

  @override
  def supported_input_sources(self) -> tuple[InputSource, ...]:
    return (InputSource.JS, InputSource.TOUCH, InputSource.MOUSE,
            InputSource.DRIVER)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["position"] = self.position.to_json()
    if self.verify:
      details["verify"] = self.verify
    details["attempts"] = self.attempts
    return details
