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
class CloseAppAction(Action):
  """Closes an application by package name."""

  TYPE: ClassVar[ActionType] = ActionType.CLOSE_APP

  package: str = ""

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "package",
        aliases=("app", "package_name"),
        type=ObjectParser.non_empty_str,
        required=True,
        help="Application package name to close "
        "(e.g. 'com.android.settings').")
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.close_app(self)

  @override
  def validate(self) -> None:
    super().validate()
    ObjectParser.non_empty_str(self.package, f"{self}.package")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["package"] = self.package
    return details
