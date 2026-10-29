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
class LaunchAppAction(Action):
  """Launches a native application or activity on the target platform.

  Currently supported on Android ADB platforms via `am start -W -n <component>`.
  """

  TYPE: ClassVar[ActionType] = ActionType.LAUNCH_APP

  component: str = ""

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "component",
        aliases=("app", "activity"),
        type=ObjectParser.non_empty_str,
        required=True,
        help="Application component or activity to launch "
        "(e.g. 'com.android.settings/.Settings').")
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.launch_app(self)

  @override
  def validate(self) -> None:
    super().validate()
    ObjectParser.non_empty_str(self.component, f"{self}.component")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["component"] = self.component
    return details
