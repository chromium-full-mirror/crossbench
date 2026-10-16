# Copyright 2024 The Chromium Authors
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
class SwitchTabAction(BaseTabAction):
  TYPE: ClassVar[ActionType] = ActionType.SWITCH_TAB

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.switch_tab(self)

  @override
  def validate(self) -> None:
    super().validate()

    if (not self.title and not self.url and self.tab_index is None and
        self.relative_tab_index is None):
      raise ValueError("One of tab_index, title, or url is required.")

    if self.relative_tab_index is not None and self.tab_index is not None:
      raise ValueError("relative_tab_index and tab_index can not both be set")
