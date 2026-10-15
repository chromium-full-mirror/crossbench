# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import datetime as dt
import logging
import subprocess
import time
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final, Iterable

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.action_runner.virtual_device.pointing import \
    PointingVirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.plt.base import Platform

if TYPE_CHECKING:
  from crossbench.action_runner.config import VirtualDeviceConfig

# Simplified mapping for common W3C to Linux EV_KEY codes
# See linux/input-event-codes.h
W3C_TO_LINUX: Final[immutabledict[str, int]] = immutabledict({
    "KeyA": 30,
    "KeyB": 48,
    "KeyC": 46,
    "KeyD": 32,
    "KeyE": 18,
    "KeyF": 33,
    "KeyG": 34,
    "KeyH": 35,
    "KeyI": 23,
    "KeyJ": 36,
    "KeyK": 37,
    "KeyL": 38,
    "KeyM": 50,
    "KeyN": 49,
    "KeyO": 24,
    "KeyP": 25,
    "KeyQ": 16,
    "KeyR": 19,
    "KeyS": 31,
    "KeyT": 20,
    "KeyU": 22,
    "KeyV": 47,
    "KeyW": 17,
    "KeyX": 45,
    "KeyY": 21,
    "KeyZ": 44,
    "Digit1": 2,
    "Digit2": 3,
    "Digit3": 4,
    "Digit4": 5,
    "Digit5": 6,
    "Digit6": 7,
    "Digit7": 8,
    "Digit8": 9,
    "Digit9": 10,
    "Digit0": 11,
    "Enter": 28,
    "Escape": 1,
    "Backspace": 14,
    "Tab": 15,
    "Space": 57,
    "Minus": 12,
    "Equal": 13,
    "BracketLeft": 26,
    "BracketRight": 27,
    "Backslash": 43,
    "Semicolon": 39,
    "Quote": 40,
    "Backquote": 41,
    "Comma": 51,
    "Period": 52,
    "Slash": 53,
    "ShiftLeft": 42,
    "ShiftRight": 54,
    "ControlLeft": 29,
    "ControlRight": 97,
    "AltLeft": 56,
    "AltRight": 100,
    "MetaLeft": 125,
    "MetaRight": 126,
})

EV_SYN: Final[int] = 0x0000
EV_KEY: Final[int] = 0x0001
EV_ABS: Final[int] = 0x0003

SYN_REPORT: Final[int] = 0x0000
BTN_TOUCH: Final[int] = 0x014a
BTN_TOOL_MOUSE: Final[int] = 0x0146
BTN_LEFT: Final[int] = 0x0110
BTN_RIGHT: Final[int] = 0x0111
BTN_MIDDLE: Final[int] = 0x0112

BUTTON_CLICK_TO_LINUX: Final[immutabledict[ButtonClick, int]] = (
    immutabledict({
        ButtonClick.LEFT: BTN_LEFT,
        ButtonClick.RIGHT: BTN_RIGHT,
        ButtonClick.MIDDLE: BTN_MIDDLE,
    }))

ABS_X: Final[int] = 0x0000
ABS_Y: Final[int] = 0x0001
ABS_PRESSURE: Final[int] = 0x0018
ABS_MT_SLOT: Final[int] = 0x002f
ABS_MT_TOUCH_MAJOR: Final[int] = 0x0030
ABS_MT_TOUCH_MINOR: Final[int] = 0x0031
ABS_MT_POSITION_X: Final[int] = 0x0035
ABS_MT_POSITION_Y: Final[int] = 0x0036
ABS_MT_TRACKING_ID: Final[int] = 0x0039
ABS_MT_PRESSURE: Final[int] = 0x003a

# Note: Do not include '#' comment lines (such as '# EVEMU 1.2') in these
# headers. ChromeOS's libutouch-evemu parses device descriptors via fscanf()
# without skipping comments and fails if the file does not start with 'N:'.
_EVEMU_KEYBOARD_HEADER: Final[bytes] = b"""N: Virtual Keyboard (Crossbench)
I: 0003 18d2 2c42 0111
P: 00 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 fe ff ff ff ff ff 7f ff
B: 01 1f 00 c0 53 da bf 0e 31
B: 01 00 40 00 40 00 10 80 00
B: 01 00 00 00 00 13 00 00 01
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 10 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 01 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 80 04 20 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 02 00 00 00 00 00 00 00 00
B: 03 00 00 00 00 00 00 00 00
B: 04 10 00 00 00 00 00 00 00
B: 05 00 00 00 00 00 00 00 00
B: 11 00 00 00 00 00 00 00 00
B: 12 00 00 00 00 00 00 00 00
"""

# Additional time for the OS input pipeline and WindowManager configuration
# changes to settle after a virtual input device is hot-plugged during setup.
DEVICE_SETTLE_DELAY: Final[dt.timedelta] = dt.timedelta(milliseconds=500)

# Buffer added to timestamps on consecutive injections to ensure events arrive
# on the device ahead of their target playback time, preventing uinput/evemu
# from discarding inter-event delays in "catch-up" mode due to transport latency
# or clock drift.
INPUT_LEAD_BUFFER: Final[dt.timedelta] = dt.timedelta(milliseconds=200)
# Buffer added to the sleep duration after injection to allow the virtual
# device process and OS input pipeline to fully drain and dispatch queued
# events before Crossbench proceeds.
INPUT_DRAIN_BUFFER: Final[dt.timedelta] = dt.timedelta(milliseconds=300)
# Initial non-zero timestamp used for relative-delta players (like evemu-play),
# which treat {tv_sec=0, tv_usec=0} as an uninitialized sentinel and would
# otherwise skip the delay between the first and second events.
INITIAL_RELATIVE_TIMESTAMP: Final[dt.timedelta] = dt.timedelta(seconds=1)


@dataclasses.dataclass
class VirtualDeviceState:
  proc: subprocess.Popen
  device_type: VirtualDeviceType = VirtualDeviceType.KEYBOARD
  start_time: dt.timedelta | None = None
  last_timestamp: dt.timedelta = INITIAL_RELATIVE_TIMESTAMP


_EVEMU_TOUCHSCREEN_HEADER: Final[str] = """N: {name}
I: 0018 04f3 4835 0100
P: 02 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 04 00 00 00 00 00 00
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
A: 00 0 {max_x} 0 0 12
A: 01 0 {max_y} 0 0 12
A: 18 0 255 0 0 0
A: 2f 0 9 0 0 0
A: 30 0 255 0 0 1
A: 31 0 255 0 0 1
A: 34 0 1 0 0 0
A: 35 0 {max_x} 0 0 12
A: 36 0 {max_y} 0 0 12
A: 37 0 2 0 0 0
A: 39 0 65535 0 0 0
A: 3a 0 255 0 0 0
"""

_EVEMU_MOUSE_HEADER: Final[str] = """N: {name}
I: 0003 18d1 0003 0100
P: 00 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 07 00 00 00 00 00
B: 01 40 04 00 00 00 00 00 00
B: 03 00 00 00 00 00 80 60 02
A: 2f 0 9 0 0 0
A: 35 0 {max_x} 0 0 0
A: 36 0 {max_y} 0 0 0
A: 39 0 9 0 0 0
"""


class EvemuPlatformMixin(Platform, metaclass=abc.ABCMeta):
  """
  Mixin for Platforms that support executing standard
  Linux (evemu) strings.
  """

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._virtual_devices: dict[str, VirtualDeviceState] = {}

  @abc.abstractmethod
  def _start_virtual_device(self, device_name: str,
                            device_type: VirtualDeviceType,
                            header: bytes) -> None:
    pass

  @override
  def setup_virtual_devices(
      self, virtual_devices: tuple[VirtualDeviceConfig, ...]) -> None:
    for device_config in virtual_devices:
      if device_config.device_type == VirtualDeviceType.KEYBOARD:
        self._init_virtual_keyboard(device_config.name)
      elif device_config.device_type == VirtualDeviceType.TOUCHSCREEN:
        assert isinstance(device_config, PointingVirtualDeviceConfig)
        self._init_pointing_virtual_device(device_config,
                                           _EVEMU_TOUCHSCREEN_HEADER)
      elif device_config.device_type == VirtualDeviceType.MOUSE:
        assert isinstance(device_config, PointingVirtualDeviceConfig)
        self._init_pointing_virtual_device(device_config, _EVEMU_MOUSE_HEADER)
      else:
        raise ValueError(
            f"Unsupported virtual device type: {device_config.device_type}")
    super().setup_virtual_devices(virtual_devices)

  def _stop_process(self, proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
      return
    if stdin := proc.stdin:
      stdin.close()
    if stdout := proc.stdout:
      stdout.close()
    try:
      proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
      proc.terminate()

  @override
  def teardown_virtual_devices(self) -> None:
    for state in self._virtual_devices.values():
      self._stop_process(state.proc)
    self._virtual_devices.clear()
    super().teardown_virtual_devices()

  def _is_device_running(self, device_name: str) -> bool:
    state = self._virtual_devices.get(device_name)
    return state is not None and state.proc.poll() is None

  def _resolve_dimensions(self, width: int | None,
                          height: int | None) -> tuple[int, int]:
    if width is not None and height is not None:
      return width, height
    resolution = self.display_resolution()
    return (
        width if width is not None else resolution.width,
        height if height is not None else resolution.height,
    )

  def _init_virtual_keyboard(self, device_name: str) -> None:
    if self._is_device_running(device_name):
      return
    self._start_virtual_device(device_name, VirtualDeviceType.KEYBOARD,
                               _EVEMU_KEYBOARD_HEADER)

  def _init_pointing_virtual_device(self,
                                    device_config: PointingVirtualDeviceConfig,
                                    header_template: str) -> None:
    device_name = device_config.name
    if self._is_device_running(device_name):
      return
    width, height = self._resolve_dimensions(device_config.width,
                                             device_config.height)
    header = header_template.format(
        name=device_name, max_x=width, max_y=height).encode("utf-8")
    logging.debug("Initializing virtual %s '%s' (%dx%d)",
                  device_config.device_type.value, device_name, width, height)
    self._start_virtual_device(device_name, device_config.device_type, header)

  def _execute_evemu_script(self, device_name: str, script: str) -> None:
    state = self._virtual_devices.get(device_name)
    if state is None:
      raise RuntimeError(f"Virtual device '{device_name}' was not initialized. "
                         "Call setup_virtual_devices() first.")
    if (exit_code := state.proc.poll()) is not None:
      raise RuntimeError(
          f"Virtual device '{device_name}' process terminated unexpectedly "
          f"with exit code {exit_code}.")
    logging.debug("EVEMU [%s]:\n%s", device_name, script)
    assert state.proc.stdin is not None
    try:
      state.proc.stdin.write(script.encode("utf-8"))
      state.proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
      exit_code = state.proc.poll()
      raise RuntimeError(
          f"Failed to write evemu script to virtual device '{device_name}' "
          f"(exit code: {exit_code}):\n{script}") from e

  def _get_or_init_virtual_device(self, device_name: str) -> VirtualDeviceState:
    if state := self._virtual_devices.get(device_name):
      return state
    for default_device in DEFAULT_VIRTUAL_DEVICES.values():
      if default_device.name == device_name:
        logging.warning(
            "Lazily initializing virtual device '%s' during test execution. "
            "Consider defining virtual devices in ActionRunnerConfig so they "
            "are initialized during test setup.", device_name)
        self.setup_virtual_devices((default_device,))
        return self._virtual_devices[device_name]
    raise RuntimeError(f"Virtual device '{device_name}' was not initialized. "
                       "Call setup_virtual_devices() first.")

  def inject_input_events(self, device_name: str,
                          events: Iterable[InputEvent]) -> None:
    """Injects abstract input events by translating them into an evemu script.

    Blocks until all events are processed. Applies a lead buffer on consecutive
    injections when using wall-clock playback (Android uinput) or continues
    from the last timestamp when using relative-delta playback (evemu-play),
    and applies a drain buffer to ensure all dispatched events finish
    processing.
    """
    state = self._get_or_init_virtual_device(device_name)
    if state.start_time is not None:
      # Wall-clock mode (e.g. Android `uinput -`): pad injections with a lead
      # buffer so timestamps are in the future relative to the device playback
      # clock, preventing catch-up mode.
      now = dt.timedelta(seconds=time.monotonic())
      lead_buffer = INPUT_LEAD_BUFFER
      start_time = (now - state.start_time) + lead_buffer
    else:
      # Relative-delta mode (e.g. Linux/ChromeOS `evemu-play`): `evemu-play`
      # sleeps for the delta between consecutive event timestamps rather than
      # wall-clock time since registration, so continue directly from the last
      # emitted timestamp.
      lead_buffer = dt.timedelta()
      start_time = state.last_timestamp

    script, end_time = self._generate_evemu_events_string(events, start_time)
    state.last_timestamp = end_time

    if not script:
      return

    if state.start_time is None:
      # ChromeOS's libutouch-evemu parses events with
      # fscanf(fp, "E: %lu.%06u %04x %04x %d\n", ...). The trailing '\n' in the
      # format string causes fscanf to block on a pipe until it peeks the first
      # non-whitespace character of the next line (or EOF). Append an extra
      # SYN_REPORT at end_time so the actual final SYN_REPORT of this batch is
      # flushed to the kernel immediately.
      end_ts = self._format_evemu_timestamp(end_time)
      script += f"E: {end_ts} {EV_SYN:04x} {SYN_REPORT:04x} 0000\n"

    duration = end_time - start_time
    self._execute_evemu_script(device_name, script)
    # Block for the playback duration plus lead and drain buffers so the host
    # waits until the device completes event playback and pipeline dispatch.
    self.sleep(duration + lead_buffer + INPUT_DRAIN_BUFFER)

  def _generate_evemu_events_string(
      self,
      events: Iterable[InputEvent],
      start_time: dt.timedelta = dt.timedelta(),
  ) -> tuple[str, dt.timedelta]:
    lines: list[str] = []
    current_time = start_time

    for event in events:
      if isinstance(event, WaitEvent):
        current_time += event.duration
        continue
      generator = self._EVENT_GENERATORS.get(type(event))
      if generator is None:
        raise ValueError(f"Unsupported event type: {type(event).__name__}")
      generator(self, lines, event, current_time)

    return ("\n".join(lines) + "\n" if lines else ""), current_time

  def _format_evemu_timestamp(self, current_time: dt.timedelta) -> str:
    sec = int(current_time.total_seconds())
    usec = current_time.microseconds
    return f"{sec}.{usec:06d}"

  def _add_line(self, lines: list[str], current_time: dt.timedelta,
                event_type: int, code: int, value: int) -> None:
    timestamp = self._format_evemu_timestamp(current_time)
    lines.append(f"E: {timestamp} {event_type:04x} {code:04x} {value:04d}")

  def _generate_key_event(self, lines: list[str], event: KeyEvent,
                          current_time: dt.timedelta) -> None:
    linux_code = W3C_TO_LINUX.get(event.key_code)
    if linux_code is None:
      raise ValueError(f"W3C key code '{event.key_code}' is not supported.")

    value = 1 if event.is_down else 0
    self._add_line(lines, current_time, EV_KEY, linux_code, value)
    self._add_line(lines, current_time, EV_SYN, SYN_REPORT, 0)

  def _generate_touch_event(self, lines: list[str], event: TouchEvent,
                            current_time: dt.timedelta) -> None:
    if event.is_down:
      self._add_line(lines, current_time, EV_ABS, ABS_MT_SLOT, event.slot)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_TRACKING_ID,
                     event.slot)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_POSITION_X,
                     event.position.x)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_POSITION_Y,
                     event.position.y)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_PRESSURE, 50)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_TOUCH_MAJOR, 5)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_TOUCH_MINOR, 5)
      self._add_line(lines, current_time, EV_KEY, BTN_TOUCH, 1)
      self._add_line(lines, current_time, EV_ABS, ABS_X, event.position.x)
      self._add_line(lines, current_time, EV_ABS, ABS_Y, event.position.y)
      self._add_line(lines, current_time, EV_ABS, ABS_PRESSURE, 50)
      self._add_line(lines, current_time, EV_SYN, SYN_REPORT, 0)
    else:
      self._add_line(lines, current_time, EV_ABS, ABS_MT_SLOT, event.slot)
      self._add_line(lines, current_time, EV_ABS, ABS_MT_TRACKING_ID, -1)
      self._add_line(lines, current_time, EV_KEY, BTN_TOUCH, 0)
      self._add_line(lines, current_time, EV_SYN, SYN_REPORT, 0)

  def _generate_mouse_button_event(self, lines: list[str],
                                   event: MouseButtonEvent,
                                   current_time: dt.timedelta) -> None:
    linux_code = BUTTON_CLICK_TO_LINUX.get(event.button)
    if linux_code is None:
      raise ValueError(f"Button click '{event.button}' is not supported.")

    value = 1 if event.is_down else 0
    self._add_line(lines, current_time, EV_KEY, linux_code, value)
    self._add_line(lines, current_time, EV_SYN, SYN_REPORT, 0)

  def _generate_mouse_move_event(self, lines: list[str], event: MouseMoveEvent,
                                 current_time: dt.timedelta) -> None:
    self._add_line(lines, current_time, EV_KEY, BTN_TOOL_MOUSE, 1)
    self._add_line(lines, current_time, EV_KEY, BTN_TOUCH, 1)
    self._add_line(lines, current_time, EV_ABS, ABS_MT_SLOT, 0)
    self._add_line(lines, current_time, EV_ABS, ABS_MT_TRACKING_ID, 0)
    self._add_line(lines, current_time, EV_ABS, ABS_MT_POSITION_X,
                   event.position.x)
    self._add_line(lines, current_time, EV_ABS, ABS_MT_POSITION_Y,
                   event.position.y)
    self._add_line(lines, current_time, EV_SYN, SYN_REPORT, 0)

  _EVENT_GENERATORS: ClassVar[immutabledict[
      type[InputEvent],
      Callable[[Any, list[str], Any, dt.timedelta], None],
  ]] = immutabledict({
      KeyEvent: _generate_key_event,
      TouchEvent: _generate_touch_event,
      MouseButtonEvent: _generate_mouse_button_event,
      MouseMoveEvent: _generate_mouse_move_event,
  })
