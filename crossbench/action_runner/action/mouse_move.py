# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_duration import DurationAction
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.benchmarks.loading.point import Point
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from collections.abc import Iterable

  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class MouseMoveAction(DurationAction):
  """Moves the mouse cursor along a sequence of waypoints over a duration."""

  TYPE: ClassVar[ActionType] = ActionType.MOUSE_MOVE

  waypoints: tuple[Point, ...] = ()
  source_device: str = dataclasses.field(
      default=DEFAULT_VIRTUAL_DEVICES[InputSource.MOUSE].name, kw_only=True)

  @classmethod
  @override
  def create(
      cls: type[Self],
      waypoints: Iterable[Point] = (),
      duration: dt.timedelta = dt.timedelta(),
      source_device: str = DEFAULT_VIRTUAL_DEVICES[InputSource.MOUSE].name,
      timeout: dt.timedelta = ACTION_TIMEOUT,
      index: int = 0,
  ) -> Self:
    return cls(
        waypoints=tuple(waypoints),
        duration=duration,
        source_device=source_device,
        timeout=timeout,
        index=index,
    )

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "waypoints",
        aliases=("points", "positions", "path", "coordinates"),
        type=Point,
        is_list=True,
        required=True)
    parser.add_argument(
        "source_device",
        type=ObjectParser.non_empty_str,
        required=False,
        default=DEFAULT_VIRTUAL_DEVICES[InputSource.MOUSE].name)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if len(self.waypoints) < 2:
      raise ValueError(f"{self}.waypoints must contain at least 2 points, "
                       f"got {len(self.waypoints)}")
    ObjectParser.non_empty_str(self.source_device, f"{self}.source_device")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.mouse_move(self)

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["waypoints"] = [point.to_json() for point in self.waypoints]
    details["source_device"] = self.source_device
    return details
