# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT, Action
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.input_events import EVENT_INPUT_SOURCES, \
    InputEvent, WaitEvent
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from collections.abc import Iterable

  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class RawInputAction(Action):
  """Action that dispatches a sequence of low-level `InputEvent` instances.

  Configures and executes a list of `events` (`WaitEvent`, `KeyEvent`,
  `TouchEvent`, `MouseButtonEvent`, `MouseMoveEvent`) on a single input
  `source` (`"keyboard"`, `"touch"`, or `"mouse"`, inferred automatically from
  `events` when omitted) and virtual `source_device`.
  """

  TYPE: ClassVar[ActionType] = ActionType.RAW_INPUT
  SUPPORTED_INPUT_SOURCES: ClassVar[tuple[InputSource, ...]] = (
      InputSource.KEYBOARD,
      InputSource.TOUCH,
      InputSource.MOUSE,
  )

  events: tuple[InputEvent, ...] = ()
  source: InputSource = InputSource.KEYBOARD
  source_device: str = dataclasses.field(
      default=DEFAULT_VIRTUAL_DEVICES[InputSource.KEYBOARD].name, kw_only=True)

  @classmethod
  def _infer_input_source(cls, events: Iterable[InputEvent]) -> InputSource:
    inferred_source: InputSource | None = None
    for event in events:
      if event_source := EVENT_INPUT_SOURCES.get(type(event)):
        if inferred_source is not None and event_source != inferred_source:
          raise ValueError("Events have conflicting input sources: "
                           f"{inferred_source} and {event_source}")
        inferred_source = event_source
    return inferred_source or InputSource.KEYBOARD

  @classmethod
  @override
  def create(cls: type[Self],
             events: Iterable[InputEvent] = (),
             source: InputSource | None = None,
             source_device: str | None = None,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    events = tuple(events)
    if source is None:
      source = cls._infer_input_source(events)
    if source_device is None:
      if default_device := DEFAULT_VIRTUAL_DEVICES.get(source):
        source_device = default_device.name
    return cls(
        events=events,
        source=source,
        source_device=source_device or "",
        timeout=timeout,
        index=index)

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("events", type=InputEvent, is_list=True, required=True)
    parser.add_argument(
        "source", type=InputSource.parse, required=False, default=None)
    parser.add_argument(
        "source_device",
        type=ObjectParser.non_empty_str,
        required=False,
        default=None)
    return parser

  @property
  def input_source(self) -> InputSource:
    return self.source

  @property
  @override
  def duration(self) -> dt.timedelta:
    return sum((event.duration
                for event in self.events
                if isinstance(event, WaitEvent)), dt.timedelta())

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.raw_input(self)

  @override
  def validate(self) -> None:
    super().validate()
    if not self.events:
      raise ValueError(f"{self}.events cannot be empty")
    if self.source not in self.SUPPORTED_INPUT_SOURCES:
      raise ValueError(
          f"Unsupported input source for {self.__class__.__name__}: "
          f"{self.source}")
    inferred_source = self._infer_input_source(self.events)
    if inferred_source != self.source:
      raise ValueError(f"Events input source {inferred_source} is incompatible "
                       f"with {self}.source={self.source}")
    ObjectParser.non_empty_str(self.source_device, f"{self}.source_device")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["source"] = str(self.source)
    details["source_device"] = self.source_device
    details["events"] = [event.to_json() for event in self.events]
    return details
