# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
import logging
from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT, Action, Self
from crossbench.action_runner.action.action_type import ActionType
from crossbench.parse import ObjectParser, PathParser
from crossbench.replacements import Replacements

if TYPE_CHECKING:
  import datetime as dt

  from crossbench import path as pth
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class JsAction(Action):
  TYPE: ClassVar[ActionType] = ActionType.JS

  script: str = ""
  script_path: pth.LocalPath | None = None
  replacements: Replacements | None = None

  @classmethod
  @override
  def create(cls: type[Self],
             script: str | None = None,
             script_path: pth.LocalPath | None = None,
             replacements: Replacements | None = None,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    if bool(script) == bool(script_path):
      raise ValueError(
          f"One of {cls.__name__}.script or {cls.__name__}.script_path, "
          "but not both, have to be specified.")
    compiled: str = ""
    if script:
      compiled = script
    elif script_path:
      compiled = script_path.read_text()
      logging.debug("Loading script from %s: %s", script_path, compiled)
    if replacements:
      compiled = replacements.apply(compiled)
    return cls(
        script=compiled,
        script_path=script_path,
        replacements=replacements,
        timeout=timeout,
        index=index)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("script", type=ObjectParser.non_empty_str)
    parser.add_argument(
        "script_path", aliases=("path",), type=PathParser.existing_file_path)
    parser.add_argument("replacements", aliases=("replace",), type=Replacements)
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.js(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.script:
      raise ValueError(
          f"{self}.script is missing or the provided script file is empty.")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    if self.script_path:
      details["script_path"] = str(self.script_path)
    elif self.script:
      details["script"] = self.script
    if self.replacements:
      details["replacements"] = self.replacements.to_json()
    return details
