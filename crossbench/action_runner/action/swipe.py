# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from typing import TYPE_CHECKING, Any, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_duration import BaseDurationAction
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import DurationParser, NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.base import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class SwipeAction(BaseDurationAction):
  DEFAULT_DURATION: ClassVar[dt.timedelta] = dt.timedelta(seconds=1)
  TYPE: ClassVar[ActionType] = ActionType.SWIPE

  start_x: int = 0
  start_y: int = 0
  end_x: int = 0
  end_y: int = 0
  source_device: str = dataclasses.field(
      default=DEFAULT_VIRTUAL_DEVICES[InputSource.TOUCH].name, kw_only=True)

  @classmethod
  @override
  def create(cls: type[Self], *args: Any, **kwargs: Any) -> Self:
    kwargs.setdefault("duration", cls.DEFAULT_DURATION)
    return super().create(*args, **kwargs)

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "start_x",
        aliases=("startx",),
        type=NumberParser.any_int,
        required=True)
    parser.add_argument(
        "start_y",
        aliases=("starty",),
        type=NumberParser.any_int,
        required=True)
    parser.add_argument(
        "end_x", aliases=("endx",), type=NumberParser.any_int, required=True)
    parser.add_argument(
        "end_y", aliases=("endy",), type=NumberParser.any_int, required=True)
    parser.add_argument(
        "source_device",
        type=ObjectParser.non_empty_str,
        required=False,
        default=DEFAULT_VIRTUAL_DEVICES[InputSource.TOUCH].name)
    parser.add_argument(
        "duration",
        type=DurationParser.positive_duration,
        default=cls.DEFAULT_DURATION)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    NumberParser.any_int(self.start_x, f"{self}.start_x")
    NumberParser.any_int(self.start_y, f"{self}.start_y")
    NumberParser.any_int(self.end_x, f"{self}.end_x")
    NumberParser.any_int(self.end_y, f"{self}.end_y")
    ObjectParser.non_empty_str(self.source_device, f"{self}.source_device")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.swipe(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["start_x"] = self.start_x
    details["start_y"] = self.start_y
    details["end_x"] = self.end_x
    details["end_y"] = self.end_y
    details["source_device"] = self.source_device
    return details
