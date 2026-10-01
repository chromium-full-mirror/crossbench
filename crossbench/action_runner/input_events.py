# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.action_runner.action.enums import ButtonClick
  from crossbench.benchmarks.loading.point import Point


@dataclasses.dataclass(frozen=True)
class InputEvent:
  pass


@dataclasses.dataclass(frozen=True)
class WaitEvent(InputEvent):
  duration: dt.timedelta


@dataclasses.dataclass(frozen=True)
class KeyEvent(InputEvent):
  # key_code represents the physical key using the W3C KeyboardEvent.code
  # specification (e.g. "KeyA", "Space", "ShiftLeft").
  key_code: str
  is_down: bool


@dataclasses.dataclass(frozen=True)
class TouchEvent(InputEvent):
  position: Point
  is_down: bool
  # The 'slot' of a touch event is the tracking channel of this
  # touch event during a multi-touch interaction.
  slot: int = 0


@dataclasses.dataclass(frozen=True)
class MouseButtonEvent(InputEvent):
  button: ButtonClick
  is_down: bool


@dataclasses.dataclass(frozen=True)
class MouseMoveEvent(InputEvent):
  position: Point
