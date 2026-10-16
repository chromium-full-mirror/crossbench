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
from crossbench.action_runner.action.enums import WindowTarget
from crossbench.bond.bond import AddBotsConfig

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser


@dataclasses.dataclass(frozen=True, eq=False)
class MeetCreateAction(BondAction):
  TYPE: ClassVar[ActionType] = ActionType.MEET_CREATE

  bots: AddBotsConfig | None = None
  target: WindowTarget = WindowTarget.SELF

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("bots", type=AddBotsConfig)
    parser.add_argument(
        "target", type=WindowTarget.parse, default=WindowTarget.SELF)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if self.bots is not None:
      self.bots.validate()

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.bond.meet_create(self)
