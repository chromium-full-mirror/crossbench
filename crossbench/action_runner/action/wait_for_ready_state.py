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
from crossbench.action_runner.action.enums import ReadyState

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class WaitForReadyStateAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.WAIT_FOR_READY_STATE

  ready_state: ReadyState = ReadyState.COMPLETE

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "ready_state", type=ReadyState.parse, default=ReadyState.COMPLETE)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if not isinstance(self.ready_state, ReadyState):
      raise ValueError(f"Invalid ready_state: {self.ready_state}")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.wait_for_ready_state(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["ready_state"] = str(self.ready_state)
    return details
