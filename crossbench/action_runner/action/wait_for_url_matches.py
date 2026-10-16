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
  import re

  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class WaitForUrlMatchesAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.WAIT_FOR_URL_MATCHES

  url_pattern: re.Pattern[str]

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("url_pattern", type=ObjectParser.regexp, required=True)
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.wait_for_url_matches(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.url_pattern:
      raise ValueError(f"{self}.url_pattern is missing.")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["url_pattern"] = self.url_pattern.pattern
    return details
