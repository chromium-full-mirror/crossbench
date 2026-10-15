# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import datetime as dt
import functools
import json
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast

from typing_extensions import override

from crossbench import exception
from crossbench.action_runner.action.action_type import ActionType
from crossbench.config import ConfigObject, ConfigParser, UnusedPropertiesMode
from crossbench.parse import DurationParser, NumberParser

if TYPE_CHECKING:
  import urllib.parse as urlparse

  from crossbench.action_runner.base import ActionRunner
  from crossbench.types import JsonDict


class ActionTypeConfigParser(ConfigParser[ActionType]):
  """Special parser that does not warn about unused properties for generic
  Action Configs. This way we can pop the 'value' or 'type' key from the
  config dict."""

  def __init__(self) -> None:
    super().__init__(
        ActionType, unused_properties_mode=UnusedPropertiesMode.IGNORE)
    self.add_argument(
        "action", aliases=("type",), type=ActionType.parse, required=True)

  def new_instance_from_kwargs(self, kwargs: dict[str, object]) -> ActionType:
    action = kwargs["action"]
    assert isinstance(action, ActionType)
    return action


_ACTION_TYPE_CONFIG_PARSER: Final = ActionTypeConfigParser()

ACTION_TIMEOUT: Final = dt.timedelta(seconds=20)

# Lazily initialized Action class lookup.
ACTIONS: dict[ActionType, type[Action]] = {}


@dataclasses.dataclass(frozen=True, kw_only=True, eq=False)
class Action(ConfigObject, metaclass=abc.ABCMeta):
  TYPE: ClassVar[ActionType]

  timeout: dt.timedelta = ACTION_TIMEOUT
  index: int = 0

  @classmethod
  @override
  def parse_str(cls, value: str) -> Action:
    return ACTIONS[ActionType.GET].parse_str(value)

  @classmethod
  @override
  def parse_any_url(cls, url: urlparse.ParseResult, **kwargs) -> Action:
    cls.expect_no_extra_kwargs(kwargs)
    return ACTIONS[ActionType.GET].parse_any_url(url)

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    action_type: ActionType = _ACTION_TYPE_CONFIG_PARSER.parse(config)
    action_cls: type[Action] = ACTIONS[action_type]
    # Drop _ACTION_TYPE_CONFIG_PARSER arguments/aliases and avoid warnings
    config = dict(config)
    config.pop("action", None)
    config.pop("type", None)

    with exception.annotate_argparsing(
        f'Parsing Action details  ...{{ action: "{action_type}", ...}}:'):
      action = action_cls.config_parser().parse(config, **kwargs)
    assert isinstance(action, cls), f"Expected {cls} but got {type(action)}"
    return cast(Self, action)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("index", type=NumberParser.positive_zero_int, default=0)
    parser.add_argument(
        "timeout",
        type=DurationParser.positive_duration,
        default=ACTION_TIMEOUT)
    return parser

  @property
  def has_timeout(self) -> bool:
    return self.timeout != dt.timedelta.max

  @property
  def duration(self) -> dt.timedelta:
    return dt.timedelta()

  @abc.abstractmethod
  def run_with(self, action_runner: ActionRunner) -> None:
    pass

  @override
  def validate(self) -> None:
    super().validate()
    if self.timeout.total_seconds() < 0:
      raise ValueError(
          f"{self}.timeout should be positive, but got {self.timeout}")
    NumberParser.positive_zero_int(self.index, f"{self}.index")

  def to_json(self) -> JsonDict:
    return {"type": str(self.TYPE), "timeout": self.timeout.total_seconds()}

  def __str__(self) -> str:
    return type(self).__name__

  def __eq__(self, other: object) -> bool:
    if isinstance(other, Action):
      return self.to_json() == other.to_json()
    return False

  def __hash__(self) -> int:
    return hash(json.dumps(self.to_json()))
