# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
  from crossbench.plt.display_info import DisplayResolution

__all__ = ["GeneratorConfig", "generate_scroll_commands"]


@dataclasses.dataclass(frozen=True)
class GeneratorConfig:
  """Configuration for physical touch scroll generation.

  The session performs `scroll_count` iterations of scrolling down then up.
  Each iteration consists of `swipes_per_direction` swipes down, followed
  by the inverse swipes back up.
  """
  input_rate: int = 240
  scroll_count: int = 5
  swipes_per_direction: int = 5
  swipe_duration: dt.timedelta = dt.timedelta(milliseconds=750)
  settle_duration: dt.timedelta = dt.timedelta(milliseconds=150)
  lift_duration: dt.timedelta = dt.timedelta(milliseconds=100)

  def __post_init__(self) -> None:
    assert self.input_rate > 0
    assert self.scroll_count > 0
    assert self.swipes_per_direction > 0

  @property
  def single_cycle(self) -> dt.timedelta:
    return self.swipe_duration + self.settle_duration + self.lift_duration

  @property
  def single_sequence(self) -> dt.timedelta:
    return 2 * self.swipes_per_direction * self.single_cycle

  def sequence_duration(self) -> dt.timedelta:
    return self.scroll_count * self.single_sequence


class EvemuEvent:
  """Helper to construct and emit EVEMU synthetic touch events."""
  PRESSURE: ClassVar[int] = 50
  TOUCH_MAJOR: ClassVar[int] = 30

  EV_SYN: ClassVar[int] = 0x0000
  EV_KEY: ClassVar[int] = 0x0001
  EV_ABS: ClassVar[int] = 0x0003

  SYN_REPORT: ClassVar[int] = 0x0000
  BTN_TOUCH: ClassVar[int] = 0x014a

  ABS_MT_SLOT: ClassVar[int] = 0x002f
  ABS_MT_TOUCH_MAJOR: ClassVar[int] = 0x0030
  ABS_MT_POSITION_X: ClassVar[int] = 0x0035
  ABS_MT_POSITION_Y: ClassVar[int] = 0x0036
  ABS_MT_TRACKING_ID: ClassVar[int] = 0x0039
  ABS_MT_PRESSURE: ClassVar[int] = 0x003a

  def __init__(self, timestamp: float) -> None:
    self.time: float = timestamp
    self.events: list[tuple[int, int, int]] = []

  def _add(self, etype: int, code: int, value: int) -> None:
    self.events.append((etype, code, value))

  def set_btn_touch(self, value: int) -> None:
    self._add(self.EV_KEY, self.BTN_TOUCH, value)

  def set_tracking_id(self, value: int) -> None:
    self._add(self.EV_ABS, self.ABS_MT_TRACKING_ID, value)

  def set_x(self, value: int) -> None:
    self._add(self.EV_ABS, self.ABS_MT_POSITION_X, value)

  def set_y(self, value: int) -> None:
    self._add(self.EV_ABS, self.ABS_MT_POSITION_Y, value)

  def set_pressure(self, value: int) -> None:
    self._add(self.EV_ABS, self.ABS_MT_PRESSURE, value)

  def set_touch_major(self, value: int) -> None:
    self._add(self.EV_ABS, self.ABS_MT_TOUCH_MAJOR, value)

  def emit(self, out: list[str]) -> None:
    for etype, code, value in self.events:
      out.append(f"E: {self.time:.6f} {etype:04x} {code:04x} {value:04d}")
    out.append(
        f"E: {self.time:.6f} {self.EV_SYN:04x} {self.SYN_REPORT:04x} 0000")


def emit_header(max_x: int, max_y: int, out: list[str]) -> None:
  header = f"""# EVEMU 1.2
N: synaptics_tcm_touch
I: 0000 0000 0001 0001
P: 02 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 80 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 20 04 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 02 00 00 00 00 00 00 00 00
B: 03 03 00 00 01 00 80 f3 06
B: 04 00 00 00 00 00 00 00 00
B: 05 00 00 00 00 00 00 00 00
B: 11 00 00 00 00 00 00 00 00
B: 12 00 00 00 00 00 00 00 00
A: 00 0 {max_x} 0 0 0
A: 01 0 {max_y} 0 0 0
A: 18 0 255 0 0 0
A: 2f 0 9 0 0 0
A: 30 0 {max_y} 0 0 0
A: 31 0 {max_x} 0 0 0
A: 34 -4096 4096 0 0 0
A: 35 0 {max_x} 0 0 0
A: 36 0 {max_y} 0 0 0
A: 37 0 2 0 0 0
A: 39 0 65535 0 0 0
A: 3a 0 255 0 0 0"""
  out.append(header)


def generate_event(time: float, x: int, y: int, finger_down: bool,
                   out: list[str]) -> None:
  event = EvemuEvent(time)
  event.set_btn_touch(1 if finger_down else 0)
  event.set_tracking_id(0 if finger_down else -1)
  event.set_x(x)
  event.set_y(y)
  if finger_down:
    event.set_pressure(EvemuEvent.PRESSURE)
    event.set_touch_major(EvemuEvent.TOUCH_MAJOR)
  event.emit(out)


def generate_swipes(
    time: float,
    start_y: int,
    end_y: int,
    fixed_x: int,
    config: GeneratorConfig,
    out: list[str],
) -> float:
  period = 1.0 / config.input_rate
  input_frames = int(config.swipe_duration.total_seconds() * config.input_rate)
  settle_frames = int(config.settle_duration.total_seconds() *
                      config.input_rate)

  for _ in range(config.swipes_per_direction):
    cycle_start_time = time

    # 1. Touch down (1 frame)
    generate_event(time, fixed_x, start_y, finger_down=True, out=out)
    time += period

    # 2. Move (sinusoidal y-axis, no x-axis) (input_frames - 1)
    for i in range(1, input_frames):
      progress = i / input_frames
      # Sine easing: starts slow, peaks in middle, ends slow.
      multiplier = (1 - math.cos(math.pi * progress)) / 2
      current_y_pos = start_y + (end_y - start_y) * multiplier
      generate_event(
          time, fixed_x, int(current_y_pos), finger_down=True, out=out)
      time += period

    # Frames generated: 1 Touch Down Frame + (input_frames - 1) = input_frames
    # 3. Settle Time (Idle with finger on screen to prevent fling effect)
    for _ in range(settle_frames):
      generate_event(time, fixed_x, end_y, finger_down=True, out=out)
      time += period

    # 4. Lift finger (Idle with finger off screen)
    generate_event(time, fixed_x, end_y, finger_down=False, out=out)

    # 5. User's finger moves while NOT touching the screen,
    # reaching its new location, from which it will swipe again.
    time = cycle_start_time + config.single_cycle.total_seconds()

  return time


def generate_scroll_commands(config: GeneratorConfig,
                             display_resolution: DisplayResolution) -> str:
  max_x = display_resolution.width
  max_y = display_resolution.height
  assert max_x > 0
  assert max_y > 0

  fixed_x = int(0.5 * max_x)
  y_top = int(0.2 * max_y)
  y_bottom = int(0.8 * max_y)

  out: list[str] = []
  emit_header(max_x, max_y, out)
  time = 0.0
  for _ in range(config.scroll_count):
    # Scroll Down (swipe starts at y_bottom and moves to y_top)
    time = generate_swipes(time, y_bottom, y_top, fixed_x, config, out)
    # Scroll Up (swipe starts at y_top and moves to y_bottom)
    time = generate_swipes(time, y_top, y_bottom, fixed_x, config, out)

  return "\n".join(out) + "\n"
