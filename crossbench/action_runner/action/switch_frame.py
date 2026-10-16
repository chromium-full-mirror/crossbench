# Copyright 2026 The Chromium Authors
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
class SwitchFrameAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.SWITCH_FRAME

  selector: str = ""

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("selector", type=ObjectParser.any_str, default="")
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    ObjectParser.any_str(self.selector, f"{self}.selector")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.switch_frame(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["selector"] = self.selector
    return details
