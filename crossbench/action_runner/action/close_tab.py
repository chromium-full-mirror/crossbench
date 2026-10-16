# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_tab_action import BaseTabAction

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser


@dataclasses.dataclass(frozen=True, eq=False)
class CloseTabAction(BaseTabAction):
  TYPE: ClassVar[ActionType] = ActionType.CLOSE_TAB

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.close_tab(self)
