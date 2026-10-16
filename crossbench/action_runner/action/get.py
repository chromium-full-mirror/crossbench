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
from crossbench.action_runner.action.base_duration import BaseDurationAction
from crossbench.action_runner.action.enums import ReadyState, WindowTarget
from crossbench.parse import DurationParser, ObjectParser

if TYPE_CHECKING:
  from urllib.parse import ParseResult

  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class GetAction(BaseDurationAction):
  TYPE: ClassVar[ActionType] = ActionType.GET

  url: str = ""
  ready_state: ReadyState = ReadyState.ANY
  target: WindowTarget = WindowTarget.SELF

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    return cls(url=ObjectParser.fuzzy_url_str(value))

  @classmethod
  @override
  def parse_any_url(cls, url: ParseResult, **kwargs) -> Self:
    cls.expect_no_extra_kwargs(kwargs)
    return cls(url=url.geturl())

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("url", type=ObjectParser.fuzzy_url_str, required=True)
    parser.add_argument(
        "duration",
        type=DurationParser.positive_or_zero_duration,
        default=dt.timedelta())
    parser.add_argument(
        "ready_state", type=ReadyState.parse, default=ReadyState.ANY)
    parser.add_argument(
        "target", type=WindowTarget.parse, default=WindowTarget.SELF)
    return parser

  @override
  def validate(self) -> None:
    if not self.url:
      raise ValueError(f"{self}.url is missing")
    super().validate()

  @override
  def validate_duration(self) -> None:
    if self.ready_state != ReadyState.ANY and self.duration != dt.timedelta():
      raise ValueError(
          f"Expected empty duration with ReadyState {self.ready_state} "
          f"but got: {self.duration}")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.get(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["url"] = self.url
    details["ready_state"] = str(self.ready_state)
    details["target"] = str(self.target)
    return details
