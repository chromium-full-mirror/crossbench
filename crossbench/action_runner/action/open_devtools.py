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
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class OpenDevToolsAction(BaseTabAction):
  TYPE: ClassVar[ActionType] = ActionType.OPEN_DEVTOOLS

  panel_name: str = "elements"

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "panel_name", type=ObjectParser.non_empty_str, default="elements")
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if not self.panel_name:
      raise ValueError(f"{self}.panel_name is missing")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.open_devtools(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    if self.panel_name:
      details["panel_name"] = self.panel_name
    return details
