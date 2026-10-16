# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action import Action
from crossbench.action_runner.action.action_type import ActionType
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class WaitForConditionAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.WAIT_FOR_CONDITION

  condition: str = ""

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "condition", type=ObjectParser.non_empty_str, required=True)
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.wait_for_condition(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.condition:
      raise ValueError(f"{self}.condition is missing.")
    if "return" not in self.condition:
      raise ValueError(
          f"Missing return statement in condition: {self.condition}")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["condition"] = self.condition
    return details
