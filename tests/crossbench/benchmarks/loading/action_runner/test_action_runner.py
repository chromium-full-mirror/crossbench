# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import pathlib
import unittest
from typing import TYPE_CHECKING, Any, cast, get_type_hints
from unittest import mock
from unittest.mock import MagicMock, call

from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.action.position import PositionConfig
from crossbench.action_runner.action.probe import ProbeAction
from crossbench.action_runner.action.scroll import ScrollAction
from crossbench.action_runner.action.swipe import SwipeAction
from crossbench.action_runner.action.text_input import TextInputAction
from crossbench.action_runner.action_runner import SCRIPTS_DIR, ActionRunner, \
    ElementRectResult, SelectElementResult
from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.element_not_found_error import \
    ElementNotFoundError
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.virtual_device.touchscreen import \
    TouchscreenVirtualDeviceConfig
from crossbench.benchmarks.loading.config.blocks import ActionBlock
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.benchmarks.loading.point import Point
from crossbench.browsers.settings import Settings
from crossbench.exception import MultiException
from crossbench.flags.base import Flags
from crossbench.probes.downloads import DownloadsProbe, \
    FileWatchDownloadsProbeContext
from crossbench.probes.dump_html import DumpHtmlProbe
from crossbench.probes.meminfo import MeminfoProbe
from crossbench.probes.screenshot import ScreenshotProbe
from crossbench.probes.shell import ShellProbe
from crossbench.runner.groups.session import BrowserSessionRunGroup
from crossbench.runner.run import Run
from tests import test_helper
from tests.crossbench.action_runner.action_runner_test_case import \
    ActionRunnerTestCase
from tests.crossbench.mock_browser import JsInvocation, MockChromeStable
from tests.crossbench.mock_helper import LinuxMockPlatform
from tests.crossbench.runner.helper import MockRun, MockRunner

if TYPE_CHECKING:
  from collections.abc import Iterator

  from crossbench.probes.probe import Probe, ProbeContext


class MockActionRunner(ActionRunner):

  def __init__(self, run: Run) -> None:
    super().__init__(run)
    self.click_js = MagicMock(name="Mock click_js")


class BaseActionRunnerTestCase(unittest.TestCase):

  def test_click_attempts_first_success(self):
    mock_run = MagicMock(name="Mock Run")
    mock_action_runner = MockActionRunner(mock_run)

    config_dict = {"action": "click", "selector": "#button", "attempts": 3}
    action = ClickAction.config_parser().parse(config_dict)

    mock_action_runner.click_js.side_effect = [None]

    mock_action_runner.click(action)

    mock_action_runner.click_js.assert_called_once_with(action)

  def test_click_attempts_last_success(self):
    mock_run = MagicMock(name="Mock Run")
    mock_action_runner = MockActionRunner(mock_run)

    config_dict = {"action": "click", "selector": "#button", "attempts": 3}
    action = ClickAction.config_parser().parse(config_dict)

    mock_action_runner.click_js.side_effect = [
        Exception("fail first"),
        Exception("and second"),
        None,
    ]

    mock_action_runner.click(action)

    mock_action_runner.click_js.assert_has_calls([
        call(action),
        call(action),
        call(action),
    ])

  def test_click_attempts_fail(self):
    mock_run = MagicMock(name="Mock Run")
    mock_action_runner = MockActionRunner(mock_run)

    config_dict = {"action": "click", "selector": "#button", "attempts": 3}
    action = ClickAction.config_parser().parse(config_dict)

    class TestException(Exception):
      pass

    mock_action_runner.click_js.side_effect = [
        TestException("fail first"),
        TestException("and second"),
        TestException("and third"),
    ]

    with self.assertRaises(TestException):
      mock_action_runner.click(action)

    mock_action_runner.click_js.assert_has_calls([
        call(action),
        call(action),
        call(action),
    ])


class DefaultActionRunnerTestCase(ActionRunnerTestCase):

  def set_up_with_probe(
      self,
      probe: Probe,
      probe_context_cls: type[ProbeContext] | None = None,
      probe_context_args: dict[str, Any] | None = None,
  ) -> None:
    self.fs.create_file(
        "/usr/bin/google-chrome", contents="definitely a browser")

    self.root_dir = pathlib.Path()
    self.platform = LinuxMockPlatform()
    self.browser = MockChromeStable(
        "mock browser", settings=Settings(platform=self.platform))
    self.probe = probe
    self.runner = MockRunner(probes=[self.probe])
    self.root_dir = pathlib.Path()
    self.session = BrowserSessionRunGroup(
        self.runner.env,
        self.runner.probes,
        self.browser,
        Flags(),
        1,
        self.root_dir,
        True,
        True,
    )
    self.mock_run: Any = MockRun(
        self.runner,
        self.session,
        "run 1",
        probe=self.probe,
    )
    self.action_runner = ActionRunner(self.mock_run)
    self.mock_run.action_runner = self.action_runner

    if not probe_context_cls:
      self.probe_context = self.probe.create_context(cast(Run, self.mock_run))
    else:
      self.probe_context = probe_context_cls(
          self.probe,
          cast(Run, self.mock_run),
          **(probe_context_args if probe_context_args else {}),
      )

    self.mock_run.set_probe_context(self.probe_context)

  def test_probe_action_unsupported_probe(self):
    self.set_up_with_probe(ShellProbe(""))
    action_block = ActionBlock(actions=(ProbeAction.create(probe="shell"),))

    with self.assertRaisesRegex(MultiException,
                                "Invoke not implemented for probe"):
      self.action_runner.run_block(self.mock_run, action_block)

  def test_probe_action_screenshot(self):
    self.set_up_with_probe(ScreenshotProbe())
    action_block = ActionBlock(
        actions=(ProbeAction.create(probe="screenshot"),))
    self.action_runner.run_block(self.mock_run, action_block)
    self.assertEqual(len(self.platform.screenshots), 1)

  def test_probe_action_wait_for_download_missing_pattern(self):
    self.set_up_with_probe(
        DownloadsProbe(),
        FileWatchDownloadsProbeContext,
        {"downloads_dir": "/Downloads"},
    )
    action_block = ActionBlock(actions=(ProbeAction.create(probe="downloads"),))

    with self.assertRaisesRegex(MultiException, "pattern"):
      self.action_runner.run_block(self.mock_run, action_block)

  def test_probe_action_wait_for_download(self):
    downloads_dir = pathlib.Path("/Downloads")
    downloads_dir.mkdir()
    self.set_up_with_probe(
        DownloadsProbe(),
        FileWatchDownloadsProbeContext,
        {"downloads_dir": downloads_dir},
    )
    action_block = ActionBlock(
        actions=(ProbeAction.create(
            probe="downloads", kwargs={"pattern": "a_download"}),))

    with self.assertRaisesRegex(MultiException, "Waited for"):
      self.action_runner.run_block(self.mock_run, action_block)

  def test_probe_action_meminfo_no_kwargs(self):
    self.set_up_with_probe(MeminfoProbe())
    action_block = ActionBlock(actions=(ProbeAction.create(probe="meminfo"),))

    self.action_runner.run_block(self.mock_run, action_block)
    self.assertEqual(self.browser.performance_marks[-1], "crossbench-meminfo")

  def test_probe_action_meminfo_all_kwargs(self):
    self.set_up_with_probe(MeminfoProbe())
    action_block = ActionBlock(
        actions=(ProbeAction.create(
            probe="meminfo",
            kwargs={
                "browser": False,
                "system": False,
                "packages": [],
                "title": "",
            },
        ),))

    self.action_runner.run_block(self.mock_run, action_block)
    self.assertEqual(self.browser.performance_marks[-1], "crossbench-meminfo")

  def test_probe_action_dump_html(self):
    self.set_up_with_probe(DumpHtmlProbe())
    action_block = ActionBlock(actions=(ProbeAction.create(probe="dump_html"),))
    self.browser.set_default_js_return(True)
    self.action_runner.run_block(self.mock_run, action_block)
    self.assertEqual(
        self.browser.invoked_js[-1].script,
        "return document.children[0].outerHTML",
    )


class ActionRunnerInputTestCase(ActionRunnerTestCase):

  _NO_ELEMENT_JS_RESULT: JsInvocation = JsInvocation(
      result={
          "count": 0,
          "scrollTop": 0,
          "device_pixel_ratio": 1,
          "window_outer_width": 1920,
          "window_outer_height": 1080,
          "window_inner_width": 1920,
          "window_inner_height": 1080,
          "screen_width": 1920,
          "screen_height": 1080,
          "screen_avail_width": 1920,
          "screen_avail_height": 1080,
          "window_offset_x": 0,
          "window_offset_y": 0,
          "element_rect": None,
      })

  _FOUND_ELEMENT_JS_RESULT: JsInvocation = JsInvocation(
      result={
          "count": 1,
          "scrollTop": 0,
          "device_pixel_ratio": 1,
          "window_outer_width": 1920,
          "window_outer_height": 1080,
          "window_inner_width": 1920,
          "window_inner_height": 1080,
          "screen_width": 1920,
          "screen_height": 1080,
          "screen_avail_width": 1920,
          "screen_avail_height": 1080,
          "window_offset_x": 0,
          "window_offset_y": 0,
          "element_rect": {
              "left": 100,
              "top": 200,
              "width": 50,
              "height": 40,
          },
      })

  def setUp(self) -> None:
    super().setUp()
    self.platform = LinuxMockPlatform()
    self.fs.create_file("/usr/bin/google-chrome", contents="chrome_mock")
    self.browser = MockChromeStable(
        "mock browser", settings=Settings(platform=self.platform))
    self.runner = MockRunner()
    self.session = BrowserSessionRunGroup(self.runner.env, self.runner.probes,
                                          self.browser, Flags(), 1,
                                          pathlib.Path(), True, True)
    self.mock_run = MockRun(self.runner, self.session, "run 1")
    self.action_runner = ActionRunner(self.mock_run)
    self.mock_run.action_runner = self.action_runner

    # Mock inject_input_events on the existing platform directly
    self.inject_events_mock = mock.MagicMock()
    self.action_runner.browser_platform.inject_input_events = \
      self.inject_events_mock

  def run_action(self, action) -> None:
    action.run_with(self.action_runner)

  def assert_input_events_injected(
      self,
      expected_events: list[InputEvent],
      expected_device_name: str | None = None,
  ) -> None:
    self.inject_events_mock.assert_called_once()
    actual_device_name = self.inject_events_mock.call_args[0][0]
    actual_events = self.inject_events_mock.call_args[0][1]
    if expected_device_name is None:
      if isinstance(expected_events[0], KeyEvent):
        expected_device_name = "default_keyboard"
      elif isinstance(expected_events[0], TouchEvent):
        expected_device_name = "default_touchscreen"
      else:
        expected_device_name = "default_mouse"
    self.assertEqual(actual_device_name, expected_device_name)
    self.assertSequenceEqual(actual_events, expected_events)

  def test_text_input_text_zero_duration(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD, text="a", duration=dt.timedelta())
    self.run_action(text_input_action)

    self.assert_input_events_injected(
        [KeyEvent("KeyA", is_down=True),
         KeyEvent("KeyA", is_down=False)])

  def test_text_input_text_shift_modifier(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD, text="A", duration=dt.timedelta())
    self.run_action(text_input_action)

    self.assert_input_events_injected([
        KeyEvent("ShiftLeft", is_down=True),
        KeyEvent("KeyA", is_down=True),
        KeyEvent("KeyA", is_down=False),
        KeyEvent("ShiftLeft", is_down=False),
    ])

  def test_text_input_text_with_duration(self) -> None:
    # 2 seconds total for an action of length 4 ("abcd").
    # Each char has weight 10 (4 hold, 6 gap) -> 200ms hold, 300ms gap.
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD, text="abcd", duration=dt.timedelta(seconds=2))
    self.run_action(text_input_action)

    self.assert_input_events_injected([
        KeyEvent("KeyA", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=200)),
        KeyEvent("KeyA", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=300)),
        KeyEvent("KeyB", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=200)),
        KeyEvent("KeyB", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=300)),
        KeyEvent("KeyC", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=200)),
        KeyEvent("KeyC", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=300)),
        KeyEvent("KeyD", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=200)),
        KeyEvent("KeyD", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=300)),
    ])

  def test_text_input_text_shift_with_duration(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD, text="A", duration=dt.timedelta(milliseconds=100))
    self.run_action(text_input_action)

    self.assert_input_events_injected([
        KeyEvent("ShiftLeft", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=10)),
        KeyEvent("KeyA", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=30)),
        KeyEvent("KeyA", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=10)),
        KeyEvent("ShiftLeft", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=50)),
    ])

  def test_text_input_keyevent_zero_duration(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD, keyevent="Enter", duration=dt.timedelta())
    self.run_action(text_input_action)

    self.assert_input_events_injected(
        [KeyEvent("Enter", is_down=True),
         KeyEvent("Enter", is_down=False)])

  def test_text_input_keyevent_with_duration(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD,
        keyevent="Enter",
        duration=dt.timedelta(seconds=1))
    self.run_action(text_input_action)

    self.assert_input_events_injected([
        KeyEvent("Enter", is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=400)),
        KeyEvent("Enter", is_down=False),
        WaitEvent(duration=dt.timedelta(milliseconds=600)),
    ])

  def test_text_input_with_source_device(self) -> None:
    text_input_action = TextInputAction.create(
        InputSource.KEYBOARD,
        duration=dt.timedelta(),
        text="a",
        source_device="my_custom_keyboard")
    self.run_action(text_input_action)

    self.assert_input_events_injected(
        [KeyEvent("KeyA", is_down=True),
         KeyEvent("KeyA", is_down=False)],
        expected_device_name="my_custom_keyboard")

  def test_click_touch_coordinates_default_duration(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH, position=PositionConfig.from_coordinates(x=50, y=60))
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(50, 60), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(50, 60), is_down=False),
    ])

  def test_click_touch_coordinates_with_duration(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_coordinates(x=50, y=60),
        duration=dt.timedelta(milliseconds=150))
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(50, 60), is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=150)),
        TouchEvent(Point(50, 60), is_down=False),
    ])

  def test_click_touch_coordinates_with_source_device(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_coordinates(x=50, y=60),
        source_device="my_touch_device")
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(50, 60), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(50, 60), is_down=False),
    ],
                                      expected_device_name="my_touch_device")

  def test_click_touch_selector_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_selector(
            selector="div#submit", required=True))
    self.browser.expect_js(expected_js=self._FOUND_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(125, 220), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(125, 220), is_down=False),
    ])

  def test_click_touch_selector_with_wait(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_selector(
            selector="div#submit", required=True, wait=True))
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    self.browser.expect_js(expected_js=self._FOUND_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(125, 220), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(125, 220), is_down=False),
    ])

  def test_click_touch_selector_non_existent_required_raises(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_selector(
            selector="div#missing", required=True))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)

    with self.assertRaisesRegex(ElementNotFoundError, "div#missing"):
      self.run_action(click_action)

    self.inject_events_mock.assert_not_called()

  def test_click_touch_selector_non_required_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_selector(
            selector="div#missing", required=False))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.inject_events_mock.assert_not_called()

  def test_click_touch_with_verify(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_coordinates(x=10, y=20),
        verify="#success")
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    self.run_action(click_action)

    self.assert_input_events_injected([
        TouchEvent(Point(10, 20), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(10, 20), is_down=False),
    ])

  def test_click_mouse_coordinates_default_duration(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE, position=PositionConfig.from_coordinates(x=50, y=60))
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(50, 60)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_mouse_coordinates_with_duration(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_coordinates(x=50, y=60),
        duration=dt.timedelta(milliseconds=150))
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(50, 60)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=dt.timedelta(milliseconds=150)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_mouse_coordinates_with_source_device(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_coordinates(x=50, y=60),
        source_device="my_mouse_device")
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(50, 60)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ],
                                      expected_device_name="my_mouse_device")

  def test_click_mouse_selector_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_selector(
            selector="div#submit", required=True))
    self.browser.expect_js(expected_js=self._FOUND_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(125, 220)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_mouse_selector_with_wait(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_selector(
            selector="div#submit", required=True, wait=True))
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    self.browser.expect_js(expected_js=self._FOUND_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(125, 220)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_mouse_selector_non_existent_required_raises(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_selector(
            selector="div#missing", required=True))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)

    with self.assertRaisesRegex(ElementNotFoundError, "div#missing"):
      self.run_action(click_action)

    self.inject_events_mock.assert_not_called()

  def test_click_mouse_selector_non_required_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_selector(
            selector="div#missing", required=False))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(click_action)

    self.inject_events_mock.assert_not_called()

  def test_click_mouse_with_verify(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_coordinates(x=10, y=20),
        verify="#success")
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    self.run_action(click_action)

    self.assert_input_events_injected([
        MouseMoveEvent(Point(10, 20)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  @contextlib.contextmanager
  def patch_get_ui_element_rect(
      self,
      return_value: DisplayRectangle | None = None,
      side_effect: Exception | None = None,
  ) -> Iterator[mock.MagicMock]:
    if return_value is None and side_effect is None:
      return_value = DisplayRectangle(Point(100, 200), 50, 40)
    with mock.patch.object(
        self.action_runner.browser_platform,
        "get_ui_element_rect",
        return_value=return_value,
        side_effect=side_effect) as mock_get_rect:
      yield mock_get_rect

  def test_click_touch_ui_selector_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_ui_selector(res="button_id"))
    with self.patch_get_ui_element_rect() as mock_get_rect:
      self.run_action(click_action)
      mock_get_rect.assert_called_once()

    self.assert_input_events_injected([
        TouchEvent(Point(125, 220), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(125, 220), is_down=False),
    ])

  def test_click_mouse_ui_selector_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_ui_selector(res="button_id"))
    with self.patch_get_ui_element_rect() as mock_get_rect:
      self.run_action(click_action)
      mock_get_rect.assert_called_once()

    self.assert_input_events_injected([
        MouseMoveEvent(Point(125, 220)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_touch_ui_selector_with_verify(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_ui_selector(res="button_id"),
        verify="#success")
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    with self.patch_get_ui_element_rect() as mock_get_rect:
      self.run_action(click_action)
      mock_get_rect.assert_called_once()

    self.assert_input_events_injected([
        TouchEvent(Point(125, 220), is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        TouchEvent(Point(125, 220), is_down=False),
    ])

  def test_click_mouse_ui_selector_with_verify(self) -> None:
    click_action = ClickAction.create(
        InputSource.MOUSE,
        position=PositionConfig.from_ui_selector(res="button_id"),
        verify="#success")
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 1}))
    with self.patch_get_ui_element_rect() as mock_get_rect:
      self.run_action(click_action)
      mock_get_rect.assert_called_once()

    self.assert_input_events_injected([
        MouseMoveEvent(Point(125, 220)),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=ActionRunner.DEFAULT_CLICK_DURATION),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    ])

  def test_click_ui_selector_not_found_required(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_ui_selector(
            res="button_id", required=True))
    with self.patch_get_ui_element_rect(
        side_effect=ElementNotFoundError("button_id")):
      with self.assertRaises(ElementNotFoundError):
        self.run_action(click_action)
    self.inject_events_mock.assert_not_called()

  def test_click_ui_selector_not_found_optional(self) -> None:
    click_action = ClickAction.create(
        InputSource.TOUCH,
        position=PositionConfig.from_ui_selector(
            res="button_id", required=False))
    with self.patch_get_ui_element_rect(
        side_effect=ElementNotFoundError("button_id")):
      self.run_action(click_action)
    self.inject_events_mock.assert_not_called()

  _EXPECTED_50MS_SWIPE_EVENTS: tuple[InputEvent, ...] = (
      TouchEvent(Point(0, 0), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8333)),
      TouchEvent(Point(5, 10), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8333)),
      TouchEvent(Point(10, 20), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8334)),
      TouchEvent(Point(15, 30), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8333)),
      TouchEvent(Point(20, 40), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8333)),
      TouchEvent(Point(25, 50), is_down=True),
      WaitEvent(duration=dt.timedelta(microseconds=8334)),
      TouchEvent(Point(30, 60), is_down=True),
      TouchEvent(Point(30, 60), is_down=False),
  )

  def test_swipe_minimal_duration(self) -> None:
    swipe_action = SwipeAction.create(
        10, 20, 30, 40, duration=dt.timedelta(milliseconds=1))
    self.run_action(swipe_action)

    self.assert_input_events_injected([
        TouchEvent(Point(10, 20), is_down=True),
        WaitEvent(duration=dt.timedelta(microseconds=1000)),
        TouchEvent(Point(30, 40), is_down=True),
        TouchEvent(Point(30, 40), is_down=False),
    ])

  def test_swipe_with_duration(self) -> None:
    # 50ms at 120Hz -> 6 steps
    swipe_action = SwipeAction.create(
        0, 0, 30, 60, duration=dt.timedelta(milliseconds=50))
    self.run_action(swipe_action)

    self.assert_input_events_injected(list(self._EXPECTED_50MS_SWIPE_EVENTS))

  def test_swipe_with_source_device(self) -> None:
    swipe_action = SwipeAction.create(
        0,
        0,
        30,
        60,
        duration=dt.timedelta(milliseconds=50),
        source_device="my_touch_device")
    self.run_action(swipe_action)

    self.assert_input_events_injected(
        list(self._EXPECTED_50MS_SWIPE_EVENTS),
        expected_device_name="my_touch_device")

  def test_swipe_custom_polling_rate(self) -> None:
    custom_ts = TouchscreenVirtualDeviceConfig(
        name="custom_ts", polling_rate_hz=40)
    self.action_runner = ActionRunner(
        self.mock_run, virtual_devices=(custom_ts,))
    self.mock_run.action_runner = self.action_runner

    swipe_action = SwipeAction.create(
        0,
        0,
        30,
        60,
        duration=dt.timedelta(milliseconds=50),
        source_device="custom_ts")
    self.run_action(swipe_action)

    self.assert_input_events_injected([
        TouchEvent(Point(0, 0), is_down=True),
        WaitEvent(duration=dt.timedelta(microseconds=25000)),
        TouchEvent(Point(15, 30), is_down=True),
        WaitEvent(duration=dt.timedelta(microseconds=25000)),
        TouchEvent(Point(30, 60), is_down=True),
        TouchEvent(Point(30, 60), is_down=False),
    ],
                                      expected_device_name="custom_ts")

  def test_scroll_touch_window_down(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH, distance=100, duration=dt.timedelta(milliseconds=50))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(scroll_action)

    self.inject_events_mock.assert_called_once()
    device_name, events = self.inject_events_mock.call_args[0]
    self.assertEqual(device_name, "default_touchscreen")
    self.assertEqual(events[0], TouchEvent(Point(960, 972), is_down=True))
    self.assertEqual(events[-1], TouchEvent(Point(960, 872), is_down=False))

  def test_scroll_touch_window_up(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH,
        distance=-100,
        duration=dt.timedelta(milliseconds=50))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(scroll_action)

    self.inject_events_mock.assert_called_once()
    device_name, events = self.inject_events_mock.call_args[0]
    self.assertEqual(device_name, "default_touchscreen")
    self.assertEqual(events[0], TouchEvent(Point(960, 108), is_down=True))
    self.assertEqual(events[-1], TouchEvent(Point(960, 208), is_down=False))

  def test_scroll_touch_scales_by_pixel_ratio(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH, distance=100, duration=dt.timedelta(milliseconds=50))
    self.browser.expect_js(
        expected_js=JsInvocation(
            result={
                "count": 0,
                "device_pixel_ratio": 2,
                "window_outer_width": 960,
                "window_outer_height": 540,
                "window_inner_width": 960,
                "window_inner_height": 540,
                "screen_width": 960,
                "screen_height": 540,
                "screen_avail_width": 960,
                "screen_avail_height": 540,
                "window_offset_x": 0,
                "window_offset_y": 0,
                "element_rect": None,
            },
            arguments=[{
                "selector": None,
                "scrollIntoView": False,
            }]))
    self.run_action(scroll_action)

    self.inject_events_mock.assert_called_once()
    device_name, events = self.inject_events_mock.call_args[0]
    self.assertEqual(device_name, "default_touchscreen")
    self.assertEqual(events[0], TouchEvent(Point(960, 972), is_down=True))
    self.assertEqual(events[-1], TouchEvent(Point(960, 772), is_down=False))

  def test_scroll_touch_selector_success(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH,
        distance=10,
        selector="div#scrollable",
        required=True,
        duration=dt.timedelta(milliseconds=50))
    self.browser.expect_js(
        expected_js=JsInvocation(
            result={
                "count": 1,
                "device_pixel_ratio": 1,
                "window_outer_width": 1920,
                "window_outer_height": 1080,
                "window_inner_width": 1920,
                "window_inner_height": 1080,
                "screen_width": 1920,
                "screen_height": 1080,
                "screen_avail_width": 1920,
                "screen_avail_height": 1080,
                "window_offset_x": 0,
                "window_offset_y": 0,
                "element_rect": {
                    "left": 10,
                    "top": 10,
                    "width": 80,
                    "height": 80,
                },
            },
            arguments=[{
                "selector": "div#scrollable",
                "scrollIntoView": False,
            }]))
    self.run_action(scroll_action)

    self.inject_events_mock.assert_called_once()
    device_name, events = self.inject_events_mock.call_args[0]
    self.assertEqual(device_name, "default_touchscreen")
    self.assertEqual(events[0], TouchEvent(Point(50, 82), is_down=True))
    self.assertEqual(events[-1], TouchEvent(Point(50, 72), is_down=False))

  def test_scroll_touch_selector_non_existent_required_raises(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH, distance=100, selector="div#missing", required=True)
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    with self.assertRaisesRegex(ElementNotFoundError, "div#missing"):
      self.run_action(scroll_action)

  def test_scroll_touch_selector_non_required_success(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH, distance=100, selector="div#missing", required=False)
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(scroll_action)
    self.inject_events_mock.assert_not_called()

  def test_scroll_touch_chunked(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH,
        distance=900,
        duration=dt.timedelta(milliseconds=100))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(scroll_action)

    self.assertEqual(self.inject_events_mock.call_count, 2)
    first_events = self.inject_events_mock.call_args_list[0][0][1]
    self.assertEqual(first_events[0], TouchEvent(Point(960, 972), is_down=True))
    self.assertEqual(first_events[-1],
                     TouchEvent(Point(960, 108), is_down=False))
    second_events = self.inject_events_mock.call_args_list[1][0][1]
    self.assertEqual(second_events[0],
                     TouchEvent(Point(960, 972), is_down=True))
    self.assertEqual(second_events[-1],
                     TouchEvent(Point(960, 936), is_down=False))

  def test_scroll_touch_with_source_device(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.TOUCH,
        distance=100,
        source_device="custom_ts",
        duration=dt.timedelta(milliseconds=50))
    self.browser.expect_js(expected_js=self._NO_ELEMENT_JS_RESULT)
    self.run_action(scroll_action)
    self.inject_events_mock.assert_called_once()
    device_name, _ = self.inject_events_mock.call_args[0]
    self.assertEqual(device_name, "custom_ts")

  def test_click_js_selector_success(self) -> None:
    click_action = ClickAction.create(
        InputSource.JS,
        position=PositionConfig.from_selector(
            selector="div#submit", required=True, scroll_into_view=True))
    self.browser.expect_js(
        expected_js=JsInvocation(
            result={"count": 1},
            arguments=[{
                "selector": "div#submit",
                "scrollIntoView": True,
                "click": True,
            }]))
    self.run_action(click_action)

  def test_click_js_selector_not_found_required_raises(self) -> None:
    click_action = ClickAction.create(
        InputSource.JS,
        position=PositionConfig.from_selector(
            selector="div#missing", required=True))
    self.browser.expect_js(expected_js=JsInvocation(result={"count": 0}))
    with self.assertRaisesRegex(ElementNotFoundError, "div#missing"):
      self.run_action(click_action)

  def test_scroll_js_window(self) -> None:
    scroll_action = ScrollAction.create(
        InputSource.JS, distance=100, duration=dt.timedelta(seconds=1))
    self.browser.expect_js(
        expected_js=JsInvocation(
            result={
                "count": 1,
                "scrollTop": 50,
            },
            arguments=[{
                "selector": None,
            }]))
    self.browser.expect_js(
        expected_js=JsInvocation(
            result={"count": 1},
            arguments=[{
                "selector": None,
                "scrollTo": 150,
            }]))
    with mock.patch("crossbench.action_runner.action_runner.time") as mock_time:
      mock_time.time.side_effect = [0.0, 1.0]
      self.run_action(scroll_action)


class ScriptsDirTestCase(unittest.TestCase):

  def test_scripts_dir_exists(self) -> None:
    self.assertTrue(SCRIPTS_DIR.is_dir())
    self.assertTrue(any(SCRIPTS_DIR.iterdir()))
    self.assertTrue((SCRIPTS_DIR / "select_element.js").is_file())

  def test_select_element_result_type_hints(self) -> None:
    expected_keys = set(get_type_hints(SelectElementResult).keys())
    self.assertEqual(
        set(ActionRunnerInputTestCase._NO_ELEMENT_JS_RESULT.result.keys()),
        expected_keys)
    self.assertEqual(
        set(ActionRunnerInputTestCase._FOUND_ELEMENT_JS_RESULT.result.keys()),
        expected_keys)
    expected_rect_keys = set(get_type_hints(ElementRectResult).keys())
    self.assertEqual(
        set(ActionRunnerInputTestCase._FOUND_ELEMENT_JS_RESULT
            .result["element_rect"].keys()), expected_rect_keys)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
