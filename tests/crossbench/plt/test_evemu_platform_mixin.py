# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import subprocess
import unittest
from typing import TYPE_CHECKING
from unittest import mock

from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.virtual_device.keyboard import \
    KeyboardVirtualDeviceConfig
from crossbench.action_runner.virtual_device.mouse import \
    MouseVirtualDeviceConfig
from crossbench.action_runner.virtual_device.touchscreen import \
    TouchscreenVirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_config import \
    VirtualDeviceConfig
from crossbench.benchmarks.loading.point import Point
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.evemu_platform_mixin import _INPUT_DRAIN_BUFFER, \
    _INPUT_LEAD_BUFFER, EvemuPlatformMixin
from tests import test_helper
from tests.crossbench.mock_helper import LinuxMockPlatform

if TYPE_CHECKING:
  from crossbench.action_runner.virtual_device.virtual_device_type import \
      VirtualDeviceType
  from crossbench.plt.types import TupleCmdArgs


class MockEvemuPlatform(EvemuPlatformMixin, LinuxMockPlatform):

  def __init__(self) -> None:
    super().__init__()
    self.mock_proc = mock.MagicMock()
    self.mock_proc.poll.return_value = None
    self.mock_proc.stdin = mock.MagicMock()
    self.popen_calls: list[tuple] = []
    self.sleep_calls: list[float | dt.timedelta] = []

  def display_resolution(self) -> DisplayResolution:
    return DisplayResolution(1080, 1920)

  def _get_evemu_device_cmd(self,
                            device_type: VirtualDeviceType) -> TupleCmdArgs:
    del device_type
    return ("mock-evemu", "-")

  def popen(self, *args, **kwargs) -> subprocess.Popen:
    self.popen_calls.append((args, kwargs))
    return self.mock_proc

  def sleep(self, seconds: float | dt.timedelta) -> None:
    self.sleep_calls.append(seconds)


class EvemuPlatformMixinTestCase(unittest.TestCase):

  def setUp(self) -> None:
    super().setUp()
    self.platform = MockEvemuPlatform()
    with mock.patch("time.monotonic", return_value=100.0):
      self.platform.setup_virtual_devices((
          KeyboardVirtualDeviceConfig(name="test_kb"),
          TouchscreenVirtualDeviceConfig(
              name="test_touch", width=1080, height=2400),
          MouseVirtualDeviceConfig(name="test_mouse", width=1920, height=1080),
      ))
    self.platform.sleep_calls.clear()

  def test_setup_virtual_devices(self) -> None:
    platform = MockEvemuPlatform()
    kb_config = KeyboardVirtualDeviceConfig(name="kb1")
    platform.setup_virtual_devices((kb_config,))
    self.assertEqual(len(platform.popen_calls), 1)
    args, kwargs = platform.popen_calls[0]
    self.assertEqual(args, ("mock-evemu", "-"))
    self.assertEqual(kwargs, {"stdin": subprocess.PIPE})
    self.assertIn("kb1", platform._virtual_devices)
    self.assertIs(platform._virtual_devices["kb1"].proc, platform.mock_proc)
    self.assertEqual(platform.virtual_devices, {"kb1": kb_config})
    platform.mock_proc.stdin.write.assert_called_once()
    platform.mock_proc.stdin.flush.assert_called_once()

  def test_teardown_virtual_devices(self) -> None:
    self.assertIn("test_kb", self.platform._virtual_devices)
    self.assertIn("test_touch", self.platform._virtual_devices)
    self.assertIn("test_mouse", self.platform._virtual_devices)
    self.assertEqual(
        set(self.platform.virtual_devices.keys()),
        {"test_kb", "test_touch", "test_mouse"})
    self.platform.teardown_virtual_devices()
    self.assertEqual(self.platform._virtual_devices, {})
    self.assertEqual(self.platform.virtual_devices, {})
    self.assertEqual(self.platform.mock_proc.stdin.close.call_count, 3)
    self.platform.mock_proc.wait.assert_has_calls(
        [mock.call(timeout=2),
         mock.call(timeout=2),
         mock.call(timeout=2)])

  def test_setup_virtual_devices_touchscreen(self) -> None:
    platform = MockEvemuPlatform()
    platform.setup_virtual_devices(
        (TouchscreenVirtualDeviceConfig(name="touch1", width=1080,
                                        height=2400),))
    self.assertEqual(len(platform.popen_calls), 1)
    args, kwargs = platform.popen_calls[0]
    self.assertEqual(args, ("mock-evemu", "-"))
    self.assertEqual(kwargs, {"stdin": subprocess.PIPE})
    self.assertIn("touch1", platform._virtual_devices)
    self.assertIs(platform._virtual_devices["touch1"].proc, platform.mock_proc)
    written_header = platform.mock_proc.stdin.write.call_args[0][0].decode(
        "utf-8")
    self.assertIn("N: touch1", written_header)
    self.assertIn("A: 35 0 1080 0 0 12", written_header)
    self.assertIn("A: 36 0 2400 0 0 12", written_header)
    platform.mock_proc.stdin.flush.assert_called_once()

  def test_setup_virtual_devices_touchscreen_fallback_resolution(self) -> None:
    platform = MockEvemuPlatform()
    with mock.patch.object(
        platform,
        "display_resolution",
        return_value=DisplayResolution(1440, 3120)) as mock_res:
      platform.setup_virtual_devices(
          (TouchscreenVirtualDeviceConfig(name="touch1"),))
      mock_res.assert_called_once()
      self.assertIn("touch1", platform._virtual_devices)
      written_header = platform.mock_proc.stdin.write.call_args[0][0].decode(
          "utf-8")
      self.assertIn("N: touch1", written_header)
      self.assertIn("A: 35 0 1440 0 0 12", written_header)
      self.assertIn("A: 36 0 3120 0 0 12", written_header)

  def test_setup_virtual_devices_mouse(self) -> None:
    platform = MockEvemuPlatform()
    platform.setup_virtual_devices(
        (MouseVirtualDeviceConfig(name="mouse1", width=1920, height=1080),))
    self.assertEqual(len(platform.popen_calls), 1)
    args, kwargs = platform.popen_calls[0]
    self.assertEqual(args, ("mock-evemu", "-"))
    self.assertEqual(kwargs, {"stdin": subprocess.PIPE})
    self.assertIn("mouse1", platform._virtual_devices)
    self.assertIs(platform._virtual_devices["mouse1"].proc, platform.mock_proc)
    written_header = platform.mock_proc.stdin.write.call_args[0][0].decode(
        "utf-8")
    self.assertIn("N: mouse1", written_header)
    self.assertIn("A: 35 0 1920 0 0 0", written_header)
    self.assertIn("A: 36 0 1080 0 0 0", written_header)
    platform.mock_proc.stdin.flush.assert_called_once()

  def test_setup_virtual_devices_mouse_fallback_resolution(self) -> None:
    platform = MockEvemuPlatform()
    with mock.patch.object(
        platform,
        "display_resolution",
        return_value=DisplayResolution(1440, 3120)) as mock_res:
      platform.setup_virtual_devices((MouseVirtualDeviceConfig(name="mouse1"),))
      mock_res.assert_called_once()
      self.assertIn("mouse1", platform._virtual_devices)
      written_header = platform.mock_proc.stdin.write.call_args[0][0].decode(
          "utf-8")
      self.assertIn("N: mouse1", written_header)
      self.assertIn("A: 35 0 1440 0 0 0", written_header)
      self.assertIn("A: 36 0 3120 0 0 0", written_header)

  def test_setup_virtual_devices_unsupported(self) -> None:
    platform = MockEvemuPlatform()
    unsupported_config = mock.MagicMock(spec=VirtualDeviceConfig)
    unsupported_config.device_type = "unsupported_device_type"
    unsupported_config.name = "touch1"

    with self.assertRaisesRegex(ValueError, "Unsupported virtual device type"):
      platform.setup_virtual_devices((unsupported_config,))

  def test_execute_evemu_script(self) -> None:
    self.platform._execute_evemu_script("test_kb",
                                        "E: 0.000000 0001 001e 0001\n")
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.000000 0001 001e 0001\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  def test_execute_evemu_script_uninitialized(self) -> None:
    with self.assertRaisesRegex(RuntimeError,
                                "Virtual device 'unknown' was not initialized"):
      self.platform._execute_evemu_script("unknown", "E: ...")

  @mock.patch("time.monotonic", return_value=100.5)
  def test_single_key(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_kb", [
        KeyEvent("KeyA", is_down=True),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 001e 0001\nE: 0.200000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_key_with_wait(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events(
        "test_kb",
        [
            KeyEvent("KeyA", is_down=True),
            WaitEvent(dt.timedelta(milliseconds=1500)),  # 1.5 seconds wait
            KeyEvent("KeyA", is_down=False),
        ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 001e 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 1.700000 0001 001e 0000\n"
        b"E: 1.700000 0000 0000 0000\n")

  @mock.patch("time.monotonic")
  def test_consecutive_injections_monotonic_timestamps(self,
                                                       mock_monotonic) -> None:
    mock_monotonic.return_value = 100.5
    self.platform.inject_input_events("test_kb", [
        KeyEvent("KeyA", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=500)),
        KeyEvent("KeyA", is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 001e 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.700000 0001 001e 0000\n"
        b"E: 0.700000 0000 0000 0000\n")
    self.assertEqual(self.platform.sleep_calls, [
        dt.timedelta(milliseconds=500) + _INPUT_LEAD_BUFFER +
        _INPUT_DRAIN_BUFFER,
    ])

    mock_monotonic.return_value = 101.0
    self.platform.inject_input_events("test_kb", [
        KeyEvent("KeyB", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=200)),
        KeyEvent("KeyB", is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.700000 0001 0030 0001\n"
        b"E: 0.700000 0000 0000 0000\n"
        b"E: 0.900000 0001 0030 0000\n"
        b"E: 0.900000 0000 0000 0000\n")
    self.assertEqual(self.platform.sleep_calls, [
        dt.timedelta(milliseconds=500) + _INPUT_LEAD_BUFFER +
        _INPUT_DRAIN_BUFFER,
        (dt.timedelta(milliseconds=200) + _INPUT_LEAD_BUFFER +
         _INPUT_DRAIN_BUFFER),
    ])

  @mock.patch("time.monotonic")
  def test_consecutive_injections_with_delay(self, mock_monotonic) -> None:
    mock_monotonic.return_value = 100.5
    self.platform.inject_input_events("test_kb", [
        KeyEvent("KeyA", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=500)),
        KeyEvent("KeyA", is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 001e 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.700000 0001 001e 0000\n"
        b"E: 0.700000 0000 0000 0000\n")

    # Simulate 5 seconds elapsed between injections
    mock_monotonic.return_value = 105.5
    self.platform.inject_input_events("test_kb", [
        KeyEvent("KeyB", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=200)),
        KeyEvent("KeyB", is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 5.200000 0001 0030 0001\n"
        b"E: 5.200000 0000 0000 0000\n"
        b"E: 5.400000 0001 0030 0000\n"
        b"E: 5.400000 0000 0000 0000\n")
    self.assertEqual(self.platform.sleep_calls, [
        dt.timedelta(milliseconds=500) + _INPUT_LEAD_BUFFER +
        _INPUT_DRAIN_BUFFER,
        (dt.timedelta(milliseconds=200) + _INPUT_LEAD_BUFFER +
         _INPUT_DRAIN_BUFFER),
    ])

  @mock.patch("time.monotonic", return_value=100.5)
  def test_touch_down_and_up(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_touch", [
        TouchEvent(Point(100, 200), is_down=True),
        TouchEvent(Point(100, 200), is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0003 002f 0000\n"
        b"E: 0.200000 0003 0039 0000\n"
        b"E: 0.200000 0003 0035 0100\n"
        b"E: 0.200000 0003 0036 0200\n"
        b"E: 0.200000 0003 003a 0050\n"
        b"E: 0.200000 0003 0030 0005\n"
        b"E: 0.200000 0003 0031 0005\n"
        b"E: 0.200000 0001 014a 0001\n"
        b"E: 0.200000 0003 0000 0100\n"
        b"E: 0.200000 0003 0001 0200\n"
        b"E: 0.200000 0003 0018 0050\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.200000 0003 002f 0000\n"
        b"E: 0.200000 0003 0039 -001\n"
        b"E: 0.200000 0001 014a 0000\n"
        b"E: 0.200000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_touch_with_wait(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_touch", [
        TouchEvent(Point(10, 20), is_down=True, slot=1),
        WaitEvent(dt.timedelta(milliseconds=500)),
        TouchEvent(Point(10, 20), is_down=False, slot=1),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0003 002f 0001\n"
        b"E: 0.200000 0003 0039 0001\n"
        b"E: 0.200000 0003 0035 0010\n"
        b"E: 0.200000 0003 0036 0020\n"
        b"E: 0.200000 0003 003a 0050\n"
        b"E: 0.200000 0003 0030 0005\n"
        b"E: 0.200000 0003 0031 0005\n"
        b"E: 0.200000 0001 014a 0001\n"
        b"E: 0.200000 0003 0000 0010\n"
        b"E: 0.200000 0003 0001 0020\n"
        b"E: 0.200000 0003 0018 0050\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.700000 0003 002f 0001\n"
        b"E: 0.700000 0003 0039 -001\n"
        b"E: 0.700000 0001 014a 0000\n"
        b"E: 0.700000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_mouse_move(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_mouse", [
        MouseMoveEvent(Point(100, 200)),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 0146 0001\n"
        b"E: 0.200000 0001 014a 0001\n"
        b"E: 0.200000 0003 002f 0000\n"
        b"E: 0.200000 0003 0039 0000\n"
        b"E: 0.200000 0003 0035 0100\n"
        b"E: 0.200000 0003 0036 0200\n"
        b"E: 0.200000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_mouse_button_down_and_up(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_mouse", [
        MouseButtonEvent(ButtonClick.LEFT, is_down=True),
        MouseButtonEvent(ButtonClick.LEFT, is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 0110 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.200000 0001 0110 0000\n"
        b"E: 0.200000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_mouse_other_buttons(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_mouse", [
        MouseButtonEvent(ButtonClick.RIGHT, is_down=True),
        MouseButtonEvent(ButtonClick.MIDDLE, is_down=True),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 0111 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.200000 0001 0112 0001\n"
        b"E: 0.200000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  @mock.patch("time.monotonic", return_value=100.5)
  def test_mouse_with_wait(self, mock_monotonic) -> None:
    del mock_monotonic
    self.platform.inject_input_events("test_mouse", [
        MouseMoveEvent(Point(50, 60)),
        MouseButtonEvent(ButtonClick.LEFT, is_down=True),
        WaitEvent(dt.timedelta(milliseconds=500)),
        MouseButtonEvent(ButtonClick.LEFT, is_down=False),
    ])
    self.platform.mock_proc.stdin.write.assert_called_with(
        b"E: 0.200000 0001 0146 0001\n"
        b"E: 0.200000 0001 014a 0001\n"
        b"E: 0.200000 0003 002f 0000\n"
        b"E: 0.200000 0003 0039 0000\n"
        b"E: 0.200000 0003 0035 0050\n"
        b"E: 0.200000 0003 0036 0060\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.200000 0001 0110 0001\n"
        b"E: 0.200000 0000 0000 0000\n"
        b"E: 0.700000 0001 0110 0000\n"
        b"E: 0.700000 0000 0000 0000\n")
    self.platform.mock_proc.stdin.flush.assert_called()

  def test_unsupported_key(self) -> None:
    with self.assertRaises(ValueError):
      self.platform.inject_input_events("test_kb", [
          KeyEvent("UnsupportedKey", is_down=True),
      ])

  def test_unsupported_mouse_button(self) -> None:
    with self.assertRaises(ValueError):
      self.platform.inject_input_events(
          "test_mouse",
          [
              MouseButtonEvent("unsupported", is_down=True),  # type: ignore
          ])

  def test_unsupported_event_type(self) -> None:
    with self.assertRaisesRegex(ValueError,
                                "Unsupported event type: InputEvent"):
      self.platform.inject_input_events("test_kb", [InputEvent()])

  def test_lazy_init_keyboard_on_demand(self) -> None:
    platform = MockEvemuPlatform()
    self.assertEqual(platform._virtual_devices, {})

    with mock.patch("time.monotonic", side_effect=[100.0, 100.5, 101.0]):
      with self.assertLogs(level="WARNING") as cm:
        platform.inject_input_events("default_keyboard",
                                     [KeyEvent("KeyA", is_down=True)])
      self.assertIn("ActionRunnerConfig", cm.output[0])
      self.assertIn("default_keyboard", platform._virtual_devices)
      self.assertEqual(len(platform.popen_calls), 1)
      platform.mock_proc.stdin.write.assert_called_with(
          b"E: 0.200000 0001 001e 0001\nE: 0.200000 0000 0000 0000\n")

      # Subsequent injection reuses the initialized default_keyboard.
      platform.inject_input_events("default_keyboard",
                                   [KeyEvent("KeyA", is_down=False)])
      self.assertEqual(len(platform.popen_calls), 1)

  def test_lazy_init_touchscreen_on_demand(self) -> None:
    platform = MockEvemuPlatform()
    self.assertEqual(platform._virtual_devices, {})

    platform.inject_input_events("default_touchscreen",
                                 [TouchEvent(Point(100, 200), is_down=True)])
    self.assertIn("default_touchscreen", platform._virtual_devices)
    self.assertEqual(len(platform.popen_calls), 1)

  def test_lazy_init_mouse_on_demand(self) -> None:
    platform = MockEvemuPlatform()
    self.assertEqual(platform._virtual_devices, {})

    platform.inject_input_events("default_mouse",
                                 [MouseMoveEvent(Point(100, 200))])
    self.assertIn("default_mouse", platform._virtual_devices)
    self.assertEqual(len(platform.popen_calls), 1)

  def test_lazy_init_missing_device_when_others_configured(self) -> None:
    platform = MockEvemuPlatform()
    platform.setup_virtual_devices(
        (KeyboardVirtualDeviceConfig(name="custom_kb"),))
    self.assertEqual(list(platform._virtual_devices.keys()), ["custom_kb"])

    # Keyboard events on custom_kb reuse the already-initialized custom_kb.
    platform.inject_input_events("custom_kb", [KeyEvent("KeyA", is_down=True)])
    self.assertEqual(list(platform._virtual_devices.keys()), ["custom_kb"])
    self.assertEqual(len(platform.popen_calls), 1)

    # Touch events on default_touchscreen lazily initialize it from
    # DEFAULT_VIRTUAL_DEVICES.
    platform.inject_input_events("default_touchscreen",
                                 [TouchEvent(Point(100, 200), is_down=True)])
    self.assertEqual(
        list(platform._virtual_devices.keys()),
        ["custom_kb", "default_touchscreen"])
    self.assertEqual(len(platform.popen_calls), 2)

  def test_inject_uninitialized_custom_device_raises(self) -> None:
    platform = MockEvemuPlatform()
    with self.assertRaisesRegex(
        RuntimeError, "Virtual device 'unknown_device' was not initialized"):
      platform.inject_input_events("unknown_device",
                                   [KeyEvent("KeyA", is_down=True)])


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
