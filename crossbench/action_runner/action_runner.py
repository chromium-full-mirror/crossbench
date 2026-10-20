# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import functools
import logging
import sys
import time
from typing import TYPE_CHECKING, Callable, Final, Iterable, Iterator, \
    Sequence, TypedDict

from crossbench import exception
from crossbench import path as pth
from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.action_runner_listener import \
    ActionRunnerListener
from crossbench.action_runner.bond_action_runner import BondActionRunner
from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.element_not_found_error import \
    ElementNotFoundError
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.keyboard_layout import US_KEYBOARD_LAYOUT
from crossbench.action_runner.screenshot_annotation import \
    ScreenshotPointAnnotation, ScreenshotRectAnnotation
from crossbench.action_runner.viewport_info import ViewportInfo
from crossbench.action_runner.virtual_device.pointing import \
    PointingVirtualDeviceConfig
from crossbench.action_runner.virtual_device.touchscreen import \
    DEFAULT_TOUCH_POLLING_RATE_HZ
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.benchmarks.loading.point import Point
from crossbench.browsers.chromium.devtools import \
    DevToolsInBrowserClient as DevToolsClient
from crossbench.cli.ui import ui
from crossbench.probes.screenshot import ScreenshotProbe, \
    ScreenshotProbeContext
from crossbench.runner.probe_context_lookup_error import \
    ProbeContextLookupError

if TYPE_CHECKING:
  from crossbench.action_runner.action import all as i_action
  from crossbench.action_runner.action.base_probe import BaseProbeAction
  from crossbench.action_runner.action.position import SelectorConfig, \
      UiSelectorConfig
  from crossbench.action_runner.screenshot_annotation import \
      ScreenshotAnnotation
  from crossbench.action_runner.virtual_device.virtual_device_config import \
      VirtualDeviceConfig
  from crossbench.benchmarks.loading.config.pages import ActionBlock
  from crossbench.benchmarks.loading.page.base import Page
  from crossbench.benchmarks.loading.page.combined import CombinedPage
  from crossbench.benchmarks.loading.page.interactive import InteractivePage
  from crossbench.benchmarks.loading.tab_controller import TabController
  from crossbench.browsers.browser import Browser
  from crossbench.plt.base import Platform
  from crossbench.runner.actions import Actions
  from crossbench.runner.run import Run

SCRIPTS_DIR: Final[pth.LocalPath] = (
    pth.ROOT_DIR / "crossbench" / "action_runner" / "scripts")


class ElementRectResult(TypedDict):
  left: int
  top: int
  width: int
  height: int


class SelectElementResult(TypedDict):
  count: int
  scrollTop: float
  device_pixel_ratio: float
  window_outer_width: int
  window_outer_height: int
  window_inner_width: float
  window_inner_height: float
  screen_width: int
  screen_height: int
  screen_avail_width: int
  screen_avail_height: int
  window_offset_x: int
  window_offset_y: int
  element_rect: ElementRectResult | None


class ActionNotImplementedError(NotImplementedError):

  def __init__(
      self,
      runner: ActionRunner,
      action: i_action.Action,
      msg_context: str = "",
  ) -> None:
    self.runner = runner
    self.action = action

    if msg_context:
      msg_context = f", context: {msg_context}"
    message = (f"{action.TYPE!s}-action "
               f"not implemented in {type(runner).__name__}{msg_context}")
    super().__init__(message)


class InputSourceNotImplementedError(ActionNotImplementedError):

  def __init__(
      self,
      runner: ActionRunner,
      action: i_action.Action,
      input_source: InputSource,
      msg_context: str = "",
  ) -> None:
    if msg_context:
      msg_context = f", context: {msg_context}"
    input_source_message = (
        f"Source {input_source!r} not implemented{msg_context}")
    super().__init__(runner, action, input_source_message)


class ActionRunner:
  """Executes interactive page actions via JavaScript, WebDriver, or
  platform-level input event injection.
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

  _bond: BondActionRunner | None = None

  def __init__(self,
               run: Run,
               virtual_devices: tuple[VirtualDeviceConfig, ...] = (),
               step_by_step_mode: bool = False) -> None:
    self._run = run
    self._listener = ActionRunnerListener()
    # TODO: Don't share state across runs
    self._info_stack: exception.TInfoStack | None = None
    self._step_by_step_mode = step_by_step_mode
    self._failure_screenshot_annotations: list[ScreenshotAnnotation] = []
    self.browser_platform.setup_virtual_devices(virtual_devices)

  @functools.cached_property
  def _select_element_script(self) -> str:
    return (SCRIPTS_DIR / "select_element.js").read_text()

  @property
  def run(self) -> Run:
    return self._run

  @run.setter
  def run(self, value: Run) -> None:
    self._run = value

  @property
  def browser(self) -> Browser:
    return self.run.browser

  @property
  def host_platform(self) -> Platform:
    return self.run.host_platform

  @property
  def browser_platform(self) -> Platform:
    return self.run.browser_platform

  def actions(self,
              name: str,
              verbose: bool = False,
              measure: bool = True) -> Actions:
    return self.run.actions(name, verbose=verbose, measure=measure)

  def set_listener(self, listener: ActionRunnerListener) -> None:
    self._listener = listener

  # info_stack is a unique identifier for the currently running or most recently
  # run action.
  @property
  def info_stack(self) -> exception.TInfoStack:
    if not self._info_stack:
      raise RuntimeError("info_stack can not be called before run_blocks")
    return self._info_stack

  @property
  def bond(self) -> BondActionRunner:
    if not self._bond:
      self._bond = BondActionRunner(self, self.run)
    return self._bond

  def teardown(self) -> None:
    if self._bond:
      self._bond.teardown()

  def run_blocks(self, run: Run, page: InteractivePage,
                 blocks: Iterable[ActionBlock]) -> None:
    for block in blocks:
      block.run_with(self, run, page)

  def run_block(self, run: Run, block: ActionBlock) -> None:
    block_index = block.index
    # TODO: Instead maybe just pass context down.
    # Or pass unique path to every action __init__
    with exception.annotate(f"block {block_index}: {block.label}"):
      with self._info_stack_annotate(f"block_{block_index}"):
        for action_index, action in enumerate(block, start=1):
          with self._info_stack_annotate(f"action_{action_index}"):
            with exception.annotate(f"action {action_index}: {action!s}"):
              self._run_action_step(run, action)

  def _run_action_step(self, run: Run, action: i_action.Action) -> None:
    if self._step_by_step_mode:
      logging.critical("[STEP-BY-STEP MODE] Next step: %s", action.to_json())
      ui.prompt("[STEP-BY-STEP MODE] Press Enter to continue")
    self._failure_screenshot_annotations = []
    self.run_action(run, action)

  def run_action(self, run: Run, action: i_action.Action) -> None:
    message: str = action.TYPE.name
    with run.exceptions.annotate(message):
      sys.stdout.write(f"   {message.ljust(30)}\r")
      action.run_with(self)

  def wait(self, action: i_action.WaitAction) -> None:
    with self.actions("WaitAction", measure=False) as actions:
      actions.wait(action.duration)

  def js(self, action: i_action.JsAction) -> None:
    with self.actions("JS", measure=False) as actions:
      actions.js(action.script, action.timeout)

  def click(self, action: i_action.ClickAction) -> None:
    input_source = action.input_source
    if input_source is InputSource.JS:
      do_click = self.click_js
    elif input_source is InputSource.TOUCH:
      do_click = self.click_touch
    elif input_source is InputSource.MOUSE:
      do_click = self.click_mouse
    elif input_source is InputSource.DRIVER:
      do_click = self.click_driver
    else:
      raise RuntimeError(f"Unsupported input source: '{input_source}'")

    for i in range(action.attempts):
      try:
        do_click(action)
        return
      except Exception as e:
        if i + 1 < action.attempts:
          logging.warning("Click failed with %d attempts left: %s",
                          action.attempts - i, e)
          continue
        raise e

  def scroll(self, action: i_action.ScrollAction) -> None:
    input_source = action.input_source
    if input_source is InputSource.JS:
      self.scroll_js(action)
    elif input_source is InputSource.TOUCH:
      self.scroll_touch(action)
    elif input_source is InputSource.MOUSE:
      self.scroll_mouse(action)
    else:
      raise RuntimeError(f"Unsupported input source: '{input_source}'")

  def get(self, action: i_action.GetAction) -> None:
    with self.actions(f"Get {action.url}", measure=False) as actions:
      with actions.wait_until(action.duration):
        actions.show_url(action.url, action.target, action.ready_state,
                         action.timeout)

  def clear_cache(self, action: i_action.ClearCacheAction) -> None:
    del action
    with self.actions("ClearCacheAction", measure=False):
      self.browser.clear_cache()

  def text_input(self, action: i_action.TextInputAction) -> None:
    input_source = action.input_source
    if input_source is InputSource.KEYBOARD:
      self.text_input_keyboard(action)
    elif input_source is InputSource.JS and not action.keyevent:
      self.text_input_js(action)
    else:
      raise RuntimeError(f"Unsupported input source: '{input_source}'")

  def click_js(self, action: i_action.ClickAction) -> None:
    if action.duration > dt.timedelta():
      raise InputSourceNotImplementedError(
          self,
          action,
          action.input_source,
          "Non-zero duration not implemented",
      )
    selector_config = action.position.selector
    if not selector_config:
      raise RuntimeError("Missing selector")

    with self.actions("ClickAction", measure=False) as actions:
      if selector_config.wait:
        self.wait_for_element_impl(
            actions,
            selector=selector_config.selector,
            timeout=action.timeout,
            required=selector_config.required,
        )
      res: SelectElementResult = actions.js(
          self._select_element_script,
          arguments=[{
              "selector": selector_config.selector,
              "scrollIntoView": selector_config.scroll_into_view,
              "click": True,
          }],
      )
      if not res["count"] and selector_config.required:
        raise ElementNotFoundError(selector_config.selector)

      if action.verify:
        self.wait_for_element_impl(
            actions, selector=action.verify, timeout=action.timeout)

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
    res: SelectElementResult = actions.js(
        self._select_element_script,
        arguments=[{
            "selector": selector,
            "scrollIntoView": scroll_into_view,
        }],
    )
    element_rect: DisplayRectangle | None = None
    if rect := res["element_rect"]:
      element_rect = DisplayRectangle(
          Point(rect["left"], rect["top"]), rect["width"], rect["height"])
    return ViewportInfo(
        device_pixel_ratio=res["device_pixel_ratio"],
        window_outer_width=res["window_outer_width"],
        window_outer_height=res["window_outer_height"],
        window_inner_width=res["window_inner_width"],
        window_inner_height=res["window_inner_height"],
        screen_width=res["screen_width"],
        screen_height=res["screen_height"],
        screen_avail_width=res["screen_avail_width"],
        screen_avail_height=res["screen_avail_height"],
        window_offset_x=res["window_offset_x"],
        window_offset_y=res["window_offset_y"],
        element_rect=element_rect,
    )

  def click_driver(self, action: i_action.ClickAction) -> None:
    if action.duration > dt.timedelta():
      raise InputSourceNotImplementedError(self, action, action.input_source,
                                           "Non-zero duration not implemented")
    selector_config = action.position.selector
    if not selector_config:
      raise RuntimeError("Missing selector")

    with self.actions("ClickAction (Driver)", measure=False) as actions:
      if selector_config.wait:
        self.wait_for_element_impl(
            actions,
            selector=selector_config.selector,
            timeout=action.timeout,
            required=selector_config.required)

      self.browser.trusted_click(selector_config.selector)

      if action.verify:
        self.wait_for_element_impl(
            actions, selector=action.verify, timeout=action.timeout)

  def scroll_js(self, action: i_action.ScrollAction) -> None:
    with self.actions("ScrollAction", measure=False) as actions:
      res: SelectElementResult = actions.js(
          self._select_element_script,
          arguments=[{
              "selector": action.selector,
          }],
      )

      if not res["count"]:
        if action.required:
          raise ElementNotFoundError(action.selector or "")
        return

      initial_scroll_y = res["scrollTop"]

      duration_s = action.duration.total_seconds()
      distance = action.distance

      start_time = time.time()
      # TODO: use the chrome.gpuBenchmarking.smoothScrollBy extension
      # if available.
      while True:
        time_delta = time.time() - start_time
        if time_delta >= duration_s:
          break
        scroll_y = initial_scroll_y + time_delta / duration_s * distance
        actions.js(
            self._select_element_script,
            arguments=[{
                "selector": action.selector,
                "scrollTo": scroll_y,
            }],
        )
        actions.wait(0.2)
      scroll_y = initial_scroll_y + distance
      actions.js(
          self._select_element_script,
          arguments=[{
              "selector": action.selector,
              "scrollTo": scroll_y,
          }],
      )

  def scroll_touch(self, action: i_action.ScrollAction) -> None:
    with self.actions("ScrollAction", measure=False) as actions:
      viewport_info = self._get_viewport_info(actions, action.selector)
      scroll_area = self._get_scroll_area(viewport_info, action)
      if not scroll_area:
        return

      assert action.source_device
      total_scroll_distance = viewport_info.css_to_native_distance(
          action.distance)
      self._inject_scroll_swipes(scroll_area, total_scroll_distance,
                                 action.duration, action.source_device)

  def _inject_scroll_swipes(self, scroll_area: DisplayRectangle,
                            total_scroll_distance: float,
                            total_duration: dt.timedelta,
                            source_device: str) -> None:
    # get_scrollable_area will apply a non-scrollable border around the
    # rectangle to avoid issues with swiping on the very edge of windows.
    (scrollable_top, scrollable_bottom,
     max_swipe_distance) = scroll_area.get_scrollable_area()
    mid_x = scroll_area.mid_x
    total_distance = abs(total_scroll_distance)
    remaining_distance = total_distance

    while remaining_distance > 0:
      current_distance = min(max_swipe_distance, remaining_distance)
      current_duration = (current_distance / total_distance) * total_duration
      y_start, y_end = self._get_scroll_swipe_y_range(total_scroll_distance,
                                                      current_distance,
                                                      scrollable_top,
                                                      scrollable_bottom)
      self._inject_swipe(
          start_x=mid_x,
          start_y=y_start,
          end_x=mid_x,
          end_y=y_end,
          duration=current_duration,
          source_device=source_device)
      remaining_distance -= current_distance

  def _get_scroll_swipe_y_range(self, total_scroll_distance: float,
                                current_distance: float, scrollable_top: int,
                                scrollable_bottom: int) -> tuple[int, int]:
    if total_scroll_distance < 0:
      return scrollable_top, round(scrollable_top + current_distance)
    return scrollable_bottom, round(scrollable_bottom - current_distance)

  def _get_scroll_area(
      self, viewport_info: ViewportInfo,
      action: i_action.ScrollAction) -> DisplayRectangle | None:
    if not action.selector:
      return viewport_info.browser_viewable
    if element_rect := viewport_info.element_rect:
      return element_rect
    if action.required:
      raise ElementNotFoundError(action.selector)
    return None

  def scroll_mouse(self, action: i_action.ScrollAction) -> None:
    raise InputSourceNotImplementedError(self, action, action.input_source)

  def text_input_js(self, action: i_action.TextInputAction) -> None:
    with self.actions("TextInput", measure=False) as actions:
      if text := action.text:
        actions.js(
            "document.activeElement.value = arguments[0]", arguments=[text])
      else:
        raise InputSourceNotImplementedError(self, action, action.input_source)

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

  def swipe(self, action: i_action.SwipeAction) -> None:
    with self.actions("SwipeAction", measure=False):
      self._inject_swipe(
          start_x=action.start_x,
          start_y=action.start_y,
          end_x=action.end_x,
          end_y=action.end_y,
          duration=action.duration,
          source_device=action.source_device)

  def _inject_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int,
                    duration: dt.timedelta, source_device: str) -> None:
    polling_rate_hz = self._get_polling_rate_hz(source_device)
    events = self._get_swipe_events(start_x, start_y, end_x, end_y, duration,
                                    polling_rate_hz)
    self.browser_platform.inject_input_events(source_device, events)

  def _get_polling_rate_hz(self, source_device: str) -> int:
    device = self.browser_platform.virtual_devices.get(source_device)
    if isinstance(device, PointingVirtualDeviceConfig):
      return device.polling_rate_hz
    return DEFAULT_TOUCH_POLLING_RATE_HZ

  def _get_swipe_events(self, start_x: int, start_y: int, end_x: int,
                        end_y: int, duration: dt.timedelta,
                        polling_rate_hz: int) -> list[InputEvent]:
    start_point = Point(start_x, start_y)
    end_point = Point(end_x, end_y)
    num_steps = max(1, round(duration.total_seconds() * polling_rate_hz))
    total_duration_us = int(duration.total_seconds() * 1_000_000)
    previous_cumulative_us = 0

    events: list[InputEvent] = [TouchEvent(position=start_point, is_down=True)]
    for step in range(1, num_steps + 1):
      target_cumulative_us = (total_duration_us * step) // num_steps
      if (wait_us := target_cumulative_us - previous_cumulative_us) > 0:
        events.append(WaitEvent(duration=dt.timedelta(microseconds=wait_us)))
      previous_cumulative_us = target_cumulative_us

      fraction = step / num_steps
      cur_x = self._interpolate(start_x, end_x, fraction)
      cur_y = self._interpolate(start_y, end_y, fraction)
      events.append(TouchEvent(position=Point(cur_x, cur_y), is_down=True))

    events.append(TouchEvent(position=end_point, is_down=False))
    return events

  def _interpolate(self, start: int, end: int, fraction: float) -> int:
    return round(start + (end - start) * fraction)

  def wait_for_condition(self, action: i_action.WaitForConditionAction) -> None:
    with self.actions("WaitForConditionAction", measure=False) as actions:
      actions.wait_js_condition(
          action.condition, min_interval=0.1, timeout=action.timeout)

  def wait_for_url_matches(self,
                           action: i_action.WaitForUrlMatchesAction) -> None:
    with self.actions("WaitForUrlMatchesAction", measure=False) as actions:
      actions.wait_for_url_matches(
          action.url_pattern, min_interval=0.1, timeout=action.timeout)

  def wait_for_element_impl(
      self,
      actions: Actions,
      selector: str,
      timeout: dt.timedelta,
      expected_count: int = 1,
      or_more: bool = False,
      scroll_into_view: bool = False,
      check_element_rect: bool = False,
      required: bool = True,
  ) -> None:
    # TODO: if check_element_rect, we should wait for the position to be the
    # same

    def _exact_match(js_result: SelectElementResult) -> bool:
      return js_result["count"] == expected_count

    def _or_more_match(js_result: SelectElementResult) -> bool:
      return js_result["count"] >= expected_count

    success_condition = _exact_match

    if or_more:
      success_condition = _or_more_match

    try:
      actions.wait_js_condition(
          self._select_element_script,
          min_interval=0.2,
          timeout=timeout,
          arguments=({
              "selector": selector,
              "scrollIntoView": scroll_into_view,
              "checkRect": check_element_rect,
          },),
          success_condition=success_condition,
      )
    except (TimeoutError, ValueError) as e:
      if required:
        raise
      logging.debug("Element %s not found: %s", selector, e)

  def wait_for_element(self, action: i_action.WaitForElementAction) -> None:
    with self.actions("WaitForElementAction", measure=False) as actions:
      self.wait_for_element_impl(
          actions=actions,
          selector=action.selector,
          expected_count=action.expected_count,
          or_more=action.or_more,
          timeout=action.timeout,
          check_element_rect=action.check_rect,
      )

  def wait_for_ready_state(self,
                           action: i_action.WaitForReadyStateAction) -> None:
    with self.actions(
        f"Wait for ready state {action.ready_state}", measure=False) as actions:
      actions.wait_for_ready_state(action.ready_state, action.timeout)

  def inject_new_document_script(
      self, action: i_action.InjectNewDocumentScriptAction) -> None:
    self.browser.run_script_on_new_document(action.script)

  def invoke_probe(self, action: BaseProbeAction) -> None:
    ctx = self.run.get_probe_context(action.probe_cls)
    if ctx is None:
      raise ProbeContextLookupError(action.probe_cls)

    with self.actions(f"Invoke Probe ({action.probe_cls.NAME})", measure=False):
      ctx.invoke(
          info_stack=self.info_stack, timeout=action.timeout, **action.kwargs)

  def open_devtools(self, action: i_action.OpenDevToolsAction) -> None:
    logging.info("Opening DevTools panel '%s'...", action.panel_name)
    DevToolsClient().open_frontend(self.browser, action.panel_name)

  def screenshot_impl(
      self,
      run: Run,
      suffix: str,
      annotations: Sequence[ScreenshotAnnotation] | None = None,
  ) -> None:
    ctx = run.get_probe_context(ScreenshotProbe)
    if not ctx:
      logging.debug("No screenshot probe for screenshot on %s",
                    repr(self.info_stack))
      return
    assert isinstance(ctx, ScreenshotProbeContext)
    ctx.screenshot("_".join(self.info_stack) + f"_{suffix}", annotations)

  def add_failure_screenshot_annotation(
      self, annotation: ScreenshotAnnotation) -> None:
    self._failure_screenshot_annotations.append(annotation)

  def failure_screenshot(self, run: Run, suffix: str) -> None:
    self.screenshot_impl(run, suffix, self._failure_screenshot_annotations)

  def _maybe_navigate_to_about_blank(self, run: Run, page: Page) -> None:
    if duration := page.about_blank_duration:
      run.browser.show_url("about:blank")
      run.runner.wait(duration)

  def run_page_multiple_tabs(self, run: Run, tabs: TabController,
                             pages: Iterable[Page]) -> None:
    # TODO: refactor possible logics to TabController.
    browser = run.browser
    for _ in tabs:
      try:
        for i, page in enumerate(pages):
          # Create a new tab for the multiple_tab case.
          if i > 0:
            browser.switch_to_new_tab()
            self._listener.handle_new_tab(run)
          page.run_with(run, self, False)
          self._listener.handle_page_run(run)
        browser.switch_to_new_tab()
        self._listener.handle_new_tab(run)
      except Exception as e:
        self._listener.handle_error(run, e)
        raise

  def run_combined_page(self, run: Run, page: CombinedPage,
                        multiple_tabs: bool) -> None:
    if multiple_tabs:
      self.run_page_multiple_tabs(run, page.tabs, page.pages)
    else:
      for sub_page in page.pages:
        sub_page.run_with(run, self, False)

  def run_interactive_page_once(self, run: Run, page: InteractivePage) -> None:
    try:
      self.run_blocks(run, page, page.blocks)
      self._maybe_navigate_to_about_blank(run, page)
    except Exception:
      with self._info_stack_annotate("failure"):
        page.create_failure_artifacts(run)
      raise

  def run_interactive_page(self, run: Run, page: InteractivePage,
                           multiple_tabs: bool) -> None:
    if multiple_tabs:
      self.run_page_multiple_tabs(run, page.tabs, [page])
    else:
      self.run_interactive_page_once(run, page)

  def run_login(self, run: Run, page: InteractivePage,
                login: ActionBlock) -> None:
    with self._management_block_scope(run, page, "login"):
      with run.browser.network.traffic_shaper.pause():
        login.run_with(self, run, page)

  def run_setup(self, run: Run, page: InteractivePage,
                setup: ActionBlock) -> None:
    with self._management_block_scope(run, page, "setup"):
      setup.run_with(self, run, page)

  def run_teardown(self, run: Run, page: InteractivePage,
                   teardown: ActionBlock) -> None:
    with self._management_block_scope(run, page, "teardown"):
      teardown.run_with(self, run, page)

  @contextlib.contextmanager
  def playback_iteration(self, i: int) -> Iterator[None]:
    assert self._info_stack is None, (
        f"Got unexpected info stack {self._info_stack}")
    with self._info_stack_annotate(f"playback_{i}"):
      yield

  @contextlib.contextmanager
  def _info_stack_annotate(self, name: str) -> Iterator[None]:
    parent_info_stack = self._info_stack
    try:
      if self._info_stack is not None:
        self._info_stack = (*self._info_stack, name)
      else:
        self._info_stack = (name,)
      yield
    finally:
      self._info_stack = parent_info_stack

  @contextlib.contextmanager
  def _management_block_scope(self, run: Run, page: InteractivePage,
                              name: str) -> Iterator[None]:
    try:
      with exception.annotate(name):
        with self._info_stack_annotate(name):
          yield
    except Exception:
      with self._info_stack_annotate("failure"):
        page.create_failure_artifacts(run, "failure")
      raise

  def switch_tab(self, action: i_action.SwitchTabAction) -> None:
    with self.actions("SwitchTabAction", measure=False):
      self.browser.switch_tab(
          action.title,
          action.url,
          action.tab_index,
          action.relative_tab_index,
          action.timeout,
      )

  def switch_frame(self, action: i_action.SwitchFrameAction) -> None:
    with self.actions("SwitchFrameAction", measure=False):
      self.browser.switch_frame(action.selector)

  def close_tab(self, action: i_action.CloseTabAction) -> None:
    with self.actions("CloseTabAction", measure=False):
      self.browser.close_tab(
          action.title,
          action.url,
          action.tab_index,
          action.relative_tab_index,
          action.timeout,
      )

  def close_all_tabs(self, action: i_action.CloseAllTabsAction) -> None:
    del action
    with self.actions("CloseAllTabsAction", measure=False):
      self.browser.close_all_tabs()
