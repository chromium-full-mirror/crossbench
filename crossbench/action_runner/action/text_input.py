# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_input_source import InputSourceAction
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import DurationParser, NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class TextInputAction(InputSourceAction):
  TYPE: ClassVar[ActionType] = ActionType.TEXT_INPUT

  text: str | None = None
  keyevent: str | None = None
  repeat: int = 1

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("text", type=ObjectParser.non_empty_str, required=False)
    parser.add_argument(
        "keyevent",
        type=ObjectParser.non_empty_str,
        required=False,
        help="Keyevent code name to trigger on Android, instead of text. "
        "See https://developer.android.com/reference/android/view/KeyEvent")
    parser.add_argument(
        "repeat",
        type=NumberParser.positive_int,
        default=1,
        help="Number of times to repeat the text input or keyevent.")
    parser.add_argument(
        "duration",
        type=DurationParser.positive_or_zero_duration,
        default=dt.timedelta())
    return parser

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.text_input(self)

  @override
  def validate(self) -> None:
    super().validate()
    if bool(self.text) + bool(self.keyevent) != 1:
      raise ValueError(
          f"Exactly one of {self}.text or {self}.keyevent can be specified.")
    if self.input_source is InputSource.JS:
      if self.keyevent:
        raise ValueError("keyevent cannot be used with JS text_input source.")
      if not self.text:
        raise ValueError("text must be provided with JS text_input source.")

  @override
  def validate_duration(self) -> None:
    # A text input action is allowed to have a zero duration.
    return

  @override
  def supported_input_sources(self) -> tuple[InputSource, ...]:
    return (InputSource.JS, InputSource.KEYBOARD)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    if text := self.text:
      details["text"] = text
    if keyevent := self.keyevent:
      details["keyevent"] = keyevent
    if self.repeat != 1:
      details["repeat"] = self.repeat
    return details
