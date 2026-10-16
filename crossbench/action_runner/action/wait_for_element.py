# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action import Action
from crossbench.action_runner.action.action_type import ActionType
from crossbench.parse import NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class WaitForElementAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.WAIT_FOR_ELEMENT

  selector: str = ""
  expected_count: int = 1
  check_rect: bool = False
  or_more: bool = False

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "selector", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "expected_count",
        type=NumberParser.positive_int,
        required=False,
        default=1)
    parser.add_argument(
        "check_rect", type=ObjectParser.bool, required=False, default=False)
    parser.add_argument(
        "or_more", type=ObjectParser.bool, required=False, default=False)
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.wait_for_element(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.selector:
      raise ValueError(f"{self}.selector is missing.")
    NumberParser.positive_int(self.expected_count, "expected_count")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["selector"] = self.selector
    details["expected_count"] = self.expected_count
    details["or_more"] = self.or_more
    details["check_rect"] = self.check_rect
    return details
