# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import functools
from typing import TYPE_CHECKING, Callable, Final, NamedTuple, Sequence

import crossbench.path as pth
from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.base import ActionRunner
from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.element_not_found_error import \
    ElementNotFoundError
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.keyboard_layout import US_KEYBOARD_LAYOUT
from crossbench.action_runner.screenshot_annotation import \
    ScreenshotPointAnnotation, ScreenshotRectAnnotation
from crossbench.action_runner.viewport_info import ViewportInfo
from crossbench.benchmarks.loading.point import Point

if TYPE_CHECKING:
  from crossbench.action_runner.action import all as i_action
  from crossbench.action_runner.action.position import SelectorConfig, \
      UiSelectorConfig
  from crossbench.runner.actions import Actions

SCRIPTS_DIR: Final[pth.LocalPath] = (
    pth.ROOT_DIR / "crossbench" / "action_runner" / "scripts")


class WindowPositions(NamedTuple):
  found_element: bool
  pixel_ratio: float
  outer_width: int
  outer_height: int
  inner_width: float
  inner_height: float
  screen_width: int
  screen_height: int
  avail_width: int
  avail_height: int
  screen_x: int
  screen_y: int
  element_left: int
  element_top: int
  element_width: int
  element_height: int


class UnifiedInputActionRunner(ActionRunner):
  """ActionRunner implementation that translates abstract actions
  into sequences of InputEvent objects, and injects them via the
  platform level.
  """

  # Relative timing weights used to distribute `action.duration` across the
  # various phases of keyboard input. Each character receives a total weight of
  # 10 units, ensuring uniform typing speed across characters.
  #
  # Example: For a typing rate of 200ms per character (5 chars in 1 second):
  #   - Unshifted character ('a'):
  #       KeyDown(KeyA) -> 80ms (40%) -> KeyUp(KeyA) -> 120ms (60%)
  #   - Shifted character ('A'):
  #       KeyDown(ShiftLeft) -> 20ms (10%)
  #       KeyDown(KeyA)      -> 60ms (30%)
  #       KeyUp(KeyA)        -> 20ms (10%)
  #       KeyUp(ShiftLeft)   -> 100ms (50%)
  KEY_HOLD_WEIGHT: Final[int] = 4
  KEY_GAP_WEIGHT: Final[int] = 6

  SHIFT_PRE_DWELL_WEIGHT: Final[int] = 1
  SHIFT_KEY_HOLD_WEIGHT: Final[int] = 3
  SHIFT_POST_DWELL_WEIGHT: Final[int] = 1
  SHIFT_GAP_WEIGHT: Final[int] = 5

  DEFAULT_CLICK_DURATION: Final[dt.timedelta] = dt.timedelta(milliseconds=50)

  @functools.cached_property
  def _get_window_positions_script(self) -> str:
    return (SCRIPTS_DIR / "get_window_positions.js").read_text()

  def click_touch(self, action: i_action.ClickAction) -> None:
    self._inject_click(action, self._get_touch_click_events)

  def click_mouse(self, action: i_action.ClickAction) -> None:
    self._inject_click(action, self._get_mouse_click_events)

  def _get_touch_click_events(self, click_location: Point,
                              duration: dt.timedelta) -> tuple[InputEvent, ...]:
    return (
        TouchEvent(position=click_location, is_down=True),
        WaitEvent(duration=duration),
        TouchEvent(position=click_location, is_down=False),
    )

  def _get_mouse_click_events(self, click_location: Point,
                              duration: dt.timedelta) -> tuple[InputEvent, ...]:
    return (
        MouseMoveEvent(position=click_location),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=True),
        WaitEvent(duration=duration),
        MouseButtonEvent(button=ButtonClick.LEFT, is_down=False),
    )

  def _inject_click(
      self, action: i_action.ClickAction,
      events_fn: Callable[[Point, dt.timedelta], Sequence[InputEvent]]) -> None:
    with self.actions("ClickAction", measure=False) as actions:
      click_location = self._get_click_location(actions, action)
      if not click_location:
        return

      duration = action.duration or self.DEFAULT_CLICK_DURATION
      events = events_fn(click_location, duration)

      assert action.source_device
      self.browser_platform.inject_input_events(action.source_device, events)

      if action.verify:
        self.wait_for_element_impl(
            actions,
            selector=action.verify,
            timeout=action.timeout,
            check_element_rect=True)

  def _get_click_location(self, actions: Actions,
                          action: i_action.ClickAction) -> Point | None:
    if selector_config := action.position.selector:
      click_location = self._get_selector_click_location(
          actions, action, selector_config)
    elif coordinates_config := action.position.coordinates:
      click_location = coordinates_config.point()
    elif ui_selector := action.position.ui_selector:
      click_location = self._get_ui_selector_click_location(action, ui_selector)
    else:
      raise RuntimeError("Missing coordinates")

    if click_location:
      self.add_failure_screenshot_annotation(
          ScreenshotPointAnnotation(label="click", point=click_location))
    return click_location

  def _get_selector_click_location(
      self, actions: Actions, action: i_action.ClickAction,
      selector_config: SelectorConfig) -> Point | None:
    if selector_config.wait:
      self.wait_for_element_impl(
          actions,
          selector=selector_config.selector,
          timeout=action.timeout,
          scroll_into_view=selector_config.scroll_into_view,
          check_element_rect=True,
          required=selector_config.required)

    viewport_info = self._get_viewport_info(actions, selector_config.selector,
                                            selector_config.scroll_into_view)
    element_rect = viewport_info.element_rect
    if not element_rect:
      if selector_config.required:
        raise ElementNotFoundError(selector_config.selector)
      return None
    self.add_failure_screenshot_annotation(
        ScreenshotRectAnnotation(
            label=selector_config.selector, rect=element_rect))
    return element_rect.middle

  def _get_ui_selector_click_location(
      self, action: i_action.ClickAction,
      ui_selector: UiSelectorConfig) -> Point | None:
    try:
      element_rect = self.browser_platform.get_ui_element_rect(
          ui_selector, action.timeout)
    except ElementNotFoundError:
      if ui_selector.required:
        raise
      return None
    self.add_failure_screenshot_annotation(
        ScreenshotRectAnnotation(
            label=str(ui_selector.to_json()), rect=element_rect))
    return element_rect.middle

  def _get_viewport_info(self,
                         actions: Actions,
                         selector: str | None,
                         scroll_into_view: bool = False) -> ViewportInfo:
    script = ""
    if selector:
      selector, script = self.get_selector_script(selector)

    script += self._get_window_positions_script

    pos = WindowPositions(
        *actions.js(script, arguments=[selector, scroll_into_view]))

    element_rect: DisplayRectangle | None = None
    if pos.found_element:
      element_rect = DisplayRectangle(
          Point(pos.element_left, pos.element_top), pos.element_width,
          pos.element_height)

    return ViewportInfo(
        device_pixel_ratio=pos.pixel_ratio,
        window_outer_width=pos.outer_width,
        window_outer_height=pos.outer_height,
        window_inner_width=pos.inner_width,
        window_inner_height=pos.inner_height,
        screen_width=pos.screen_width,
        screen_height=pos.screen_height,
        screen_avail_width=pos.avail_width,
        screen_avail_height=pos.avail_height,
        window_offset_x=pos.screen_x,
        window_offset_y=pos.screen_y,
        element_rect=element_rect)

  def scroll_touch(self, action: i_action.ScrollAction) -> None:
    # TODO(b/553272919): implement
    del action

  def swipe(self, action: i_action.SwipeAction) -> None:
    # TODO(b/553272919): implement
    del action

  def _text_to_weighted_events(self, text: str) -> list[KeyEvent | int]:
    events: list[KeyEvent | int] = []
    for char in text:
      mapping = US_KEYBOARD_LAYOUT.get(char)
      if not mapping:
        raise ValueError(f"Character {char!r} is not supported "
                         "in the standard US keyboard layout.")

      if mapping.has_shift:
        events.append(KeyEvent("ShiftLeft", is_down=True))
        events.append(self.SHIFT_PRE_DWELL_WEIGHT)
        events.append(KeyEvent(mapping.code, is_down=True))
        events.append(self.SHIFT_KEY_HOLD_WEIGHT)
        events.append(KeyEvent(mapping.code, is_down=False))
        events.append(self.SHIFT_POST_DWELL_WEIGHT)
        events.append(KeyEvent("ShiftLeft", is_down=False))
        events.append(self.SHIFT_GAP_WEIGHT)
      else:
        events.append(KeyEvent(mapping.code, is_down=True))
        events.append(self.KEY_HOLD_WEIGHT)
        events.append(KeyEvent(mapping.code, is_down=False))
        events.append(self.KEY_GAP_WEIGHT)

    return events

  def text_input_keyboard(self, action: i_action.TextInputAction) -> None:
    events_with_weights: list[KeyEvent | int] = []
    if action.text:
      events_with_weights.extend(self._text_to_weighted_events(action.text))
    elif action.keyevent:
      events_with_weights.extend([
          KeyEvent(key_code=action.keyevent, is_down=True),
          self.KEY_HOLD_WEIGHT,
          KeyEvent(key_code=action.keyevent, is_down=False),
          self.KEY_GAP_WEIGHT,
      ])

    if not events_with_weights:
      return

    assert action.source_device

    if not action.duration:
      input_events = [e for e in events_with_weights if isinstance(e, KeyEvent)]
      self.browser_platform.inject_input_events(action.source_device,
                                                input_events)
      return

    total_weight = sum(w for w in events_with_weights if isinstance(w, int))
    total_duration_us = int(action.duration.total_seconds() * 1_000_000)
    cumulative_weight = 0
    previous_cumulative_us = 0

    timed_events: list[InputEvent] = []
    for item in events_with_weights:
      if isinstance(item, KeyEvent):
        timed_events.append(item)
      else:
        cumulative_weight += item
        target_cumulative_us = (total_duration_us *
                                cumulative_weight) // total_weight
        wait_us = target_cumulative_us - previous_cumulative_us
        previous_cumulative_us = target_cumulative_us
        if wait_us > 0:
          timed_events.append(
              WaitEvent(duration=dt.timedelta(microseconds=wait_us)))

    self.browser_platform.inject_input_events(action.source_device,
                                              timed_events)
