# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import enum
import functools
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import exception
from crossbench.action_runner.action.enums import ButtonClick
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.benchmarks.loading.point import Point
from crossbench.config import ConfigEnum, ConfigObject, ConfigParser, \
    UnusedPropertiesMode
from crossbench.parse import DurationParser, NumberParser, ObjectParser

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.types import JsonDict


@enum.unique
class InputEventType(ConfigEnum):
  WAIT = ("wait", "Wait for a given duration")
  KEY = ("key", "Press or release a keyboard key")
  TOUCH = ("touch", "Touch down, move, or release on a touchscreen")
  MOUSE_BUTTON = ("mouse_button", "Press or release a mouse button")
  MOUSE_MOVE = ("mouse_move", "Move the mouse cursor to a position")


class InputEventTypeConfigParser(ConfigParser[InputEventType]):

  def __init__(self) -> None:
    super().__init__(
        InputEventType, unused_properties_mode=UnusedPropertiesMode.IGNORE)
    self.add_argument(
        "event", aliases=("type",), type=InputEventType.parse, required=True)

  def new_instance_from_kwargs(self, kwargs: dict[str,
                                                  object]) -> InputEventType:
    event_type = kwargs["event"]
    assert isinstance(event_type, InputEventType)
    return event_type


_INPUT_EVENT_TYPE_CONFIG_PARSER: Final = InputEventTypeConfigParser()

INPUT_EVENTS: Final[dict[InputEventType, type[InputEvent]]] = {}


@dataclasses.dataclass(frozen=True)
class InputEvent(ConfigObject, metaclass=abc.ABCMeta):
  """Base configuration object for a single low-level input event.

  Parsed from a dictionary containing an `event` (or `type`) field matching
  an `InputEventType` (`"wait"`, `"key"`, `"touch"`, `"mouse_button"`, or
  `"mouse_move"`) along with the event-specific parameters for that subclass.
  """

  TYPE: ClassVar[InputEventType]

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    del value
    raise ValueError(f"{cls.__name__} must be parsed from a dictionary")

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs: object) -> Self:
    event_type: InputEventType = _INPUT_EVENT_TYPE_CONFIG_PARSER.parse(config)
    event_cls: type[InputEvent] = INPUT_EVENTS[event_type]
    config = dict(config)
    config.pop("event", None)
    config.pop("type", None)

    with exception.annotate_argparsing(
        f'Parsing InputEvent details  ...{{ event: "{event_type}", ...}}:'):
      event = event_cls.config_parser().parse(config, **kwargs)
    assert isinstance(event, cls), f"Expected {cls} but got {type(event)}"
    return cast(Self, event)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    return ConfigParser(cls)

  def to_json(self) -> JsonDict:
    return {"type": str(self.TYPE)}

  def __str__(self) -> str:
    return type(self).__name__


@dataclasses.dataclass(frozen=True)
class WaitEvent(InputEvent):
  """Input event that pauses execution for a positive `duration`."""

  TYPE: ClassVar[InputEventType] = InputEventType.WAIT

  duration: dt.timedelta

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "duration", type=DurationParser.positive_duration, required=True)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if self.duration.total_seconds() <= 0:
      raise ValueError(
          f"{self}.duration should be positive, but got {self.duration}")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["duration"] = self.duration.total_seconds()
    return details


@dataclasses.dataclass(frozen=True)
class KeyEvent(InputEvent):
  """Input event that presses or releases a physical keyboard key.

  Attributes:
    key_code: Physical key using the W3C KeyboardEvent.code specification
      (e.g. "KeyA", "Space", "ShiftLeft") or a platform-specific keycode
      supported by the target platform (e.g. "KEYCODE_HOME" on Android).
    is_down: True for a key press, False for a key release.
  """

  TYPE: ClassVar[InputEventType] = InputEventType.KEY

  key_code: str
  is_down: bool

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "key_code",
        aliases=("key", "code"),
        type=ObjectParser.non_empty_str,
        required=True)
    parser.add_argument(
        "is_down", aliases=("down",), type=ObjectParser.bool, required=True)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    ObjectParser.non_empty_str(self.key_code, f"{self}.key_code")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["key_code"] = self.key_code
    details["is_down"] = self.is_down
    return details


@dataclasses.dataclass(frozen=True)
class TouchEvent(InputEvent):
  """Input event representing a touch press, move, or release on a screen.

  Attributes:
    position: Screen coordinates of the touch contact point.
    is_down: True when the touch contact is active, False when released.
    slot: Multi-touch tracking channel index (default 0).
  """

  TYPE: ClassVar[InputEventType] = InputEventType.TOUCH

  position: Point
  is_down: bool
  slot: int = 0

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("position", aliases=("pos",), type=Point, required=True)
    parser.add_argument(
        "is_down", aliases=("down",), type=ObjectParser.bool, required=True)
    parser.add_argument("slot", type=NumberParser.positive_zero_int, default=0)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    NumberParser.positive_zero_int(self.slot, f"{self}.slot")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["position"] = self.position.to_json()
    details["is_down"] = self.is_down
    details["slot"] = self.slot
    return details


@dataclasses.dataclass(frozen=True)
class MouseButtonEvent(InputEvent):
  """Input event that presses or releases a mouse button."""

  TYPE: ClassVar[InputEventType] = InputEventType.MOUSE_BUTTON

  button: ButtonClick
  is_down: bool

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("button", type=ButtonClick.parse, required=True)
    parser.add_argument(
        "is_down", aliases=("down",), type=ObjectParser.bool, required=True)
    return parser

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["button"] = str(self.button)
    details["is_down"] = self.is_down
    return details


@dataclasses.dataclass(frozen=True)
class MouseMoveEvent(InputEvent):
  """Input event that moves the mouse cursor to a target screen `position`."""

  TYPE: ClassVar[InputEventType] = InputEventType.MOUSE_MOVE

  position: Point

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("position", aliases=("pos",), type=Point, required=True)
    return parser

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["position"] = self.position.to_json()
    return details


EVENT_INPUT_SOURCES: Final[immutabledict[type[InputEvent],
                                         InputSource]] = immutabledict({
                                             KeyEvent:
                                                 InputSource.KEYBOARD,
                                             TouchEvent:
                                                 InputSource.TOUCH,
                                             MouseButtonEvent:
                                                 InputSource.MOUSE,
                                             MouseMoveEvent:
                                                 InputSource.MOUSE,
                                         })

INPUT_EVENTS_TUPLE: Final[tuple[type[InputEvent], ...]] = (
    WaitEvent,
    KeyEvent,
    TouchEvent,
    MouseButtonEvent,
    MouseMoveEvent,
)
for event_cls in INPUT_EVENTS_TUPLE:
  INPUT_EVENTS[event_cls.TYPE] = event_cls

assert len(INPUT_EVENTS_TUPLE) == len(INPUT_EVENTS), (
    "Non unique InputEvent.TYPE present")
