# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.bond import BondAction
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser


# This action is different from the `JsAction` in that it is not executed on the
# client side, but rather on the server side. This allows for more complex
# interactions with the Meet API, such as directing bots to present, or pin a
# participant.
@dataclasses.dataclass(frozen=True, eq=False)
class MeetScriptAction(BondAction):
  TYPE: ClassVar[ActionType] = ActionType.MEET_SCRIPT

  script: str = ""

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "script", type=ObjectParser.non_empty_str, required=True)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if not self.script:
      raise ValueError(f"{self}.script is missing")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.bond.meet_script(self)
