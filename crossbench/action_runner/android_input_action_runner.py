# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Final

from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.element_not_found_error import \
    ElementNotFoundError
from crossbench.action_runner.unified_input_action_runner import \
    UnifiedInputActionRunner
from crossbench.benchmarks.loading.point import Point

if TYPE_CHECKING:
  from crossbench.action_runner.action import all as i_action
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.runner.actions import Actions


class ViewportInfo:

  def __init__(self,
               raw_chrome_window_bounds: DisplayRectangle,
               window_inner_height: int,
               window_inner_width: int,
               element_rect: DisplayRectangle | None = None) -> None:
    self._element_rect: DisplayRectangle | None = None

    # On android, clank does not report the correct window.devicePixelRatio
    # when a page is zoomed.
    # Zoom can happen automatically on load with pages that force a certain
    # viewport width (such as speedometer), so calculate the ratio manually.
    # Note: this calculation assumes there are no system borders on the side of
    # the chrome window.
    self._actual_pixel_ratio: float = float(raw_chrome_window_bounds.width /
                                            window_inner_width)

    window_inner_height = int(
        round(self.actual_pixel_ratio * window_inner_height))
    window_inner_width = int(
        round(self.actual_pixel_ratio * window_inner_width))

    # On Android there may be a system added border from the top of the app view
    # that is included in the mAppBounds rectangle dimensions. Calculate the
    # height of this border using the difference between the height reported by
    # chrome and the height reported by android.
    top_border_height = raw_chrome_window_bounds.height - window_inner_height

    self._chrome_window: DisplayRectangle = DisplayRectangle(
        Point(raw_chrome_window_bounds.origin.x,
              raw_chrome_window_bounds.origin.y + top_border_height),
        raw_chrome_window_bounds.width,
        raw_chrome_window_bounds.height - top_border_height)

    if element_rect:
      self._element_rect = (element_rect * self.actual_pixel_ratio).shift_by(
          self._chrome_window)
      self._element_rect = self.chrome_window.intersection(self._element_rect)

  @property
  def chrome_window(self) -> DisplayRectangle:
    return self._chrome_window

  @property
  def actual_pixel_ratio(self) -> float:
    return self._actual_pixel_ratio

  def element_rect(self) -> DisplayRectangle | None:
    return self._element_rect

  def element_center(self) -> Point | None:
    if not self._element_rect:
      return None
    return self._element_rect.middle

  def css_to_native_distance(self, distance: float) -> float:
    return distance * self.actual_pixel_ratio


class AndroidInputActionRunner(UnifiedInputActionRunner):
  """Custom ActionRunner for Android."""

  _BOUNDS_RE: Final[re.Pattern] = re.compile(
      r"mAppBounds=Rect\((?P<left>\d+), (?P<top>\d+) - (?P<right>\d+),"
      r" (?P<bottom>\d+)\)")

  _GET_JS_VALUES: Final[str] = """
const found_element = arguments[0] && element;
if(found_element && arguments[1]) element.scrollIntoView({ block: 'nearest' });
rect = found_element ? element.getBoundingClientRect() : new DOMRect();
return [
  found_element,
  window.visualViewport.height,
  window.visualViewport.width,
  rect.left,
  rect.top,
  rect.width,
  rect.height
];"""

  def scroll_touch(self, action: i_action.ScrollAction) -> None:
    with self.actions("ScrollAction", measure=False) as actions:

      viewport_info = self._get_android_viewport_info(actions, action.selector)

      # The scroll distance is specified in terms of css pixels so adjust to the
      # native pixel density.
      total_scroll_distance = (
          viewport_info.css_to_native_distance(action.distance))

      # Default to scrolling within the entire chrome window.
      scroll_area: DisplayRectangle = viewport_info.chrome_window

      if action.selector:
        if element_rect := viewport_info.element_rect():
          scroll_area = element_rect
        else:
          if action.required:
            raise ElementNotFoundError(action.selector)
          return

      (scrollable_top, scrollable_bottom,
       max_swipe_distance) = scroll_area.get_scrollable_area()

      remaining_distance = abs(total_scroll_distance)

      while remaining_distance > 0:

        current_distance = min(max_swipe_distance, remaining_distance)

        # The duration for this swipe should be only a fraction of the total
        # duration since the entire distance may not be covered in one swipe.
        current_duration = (current_distance /
                            abs(total_scroll_distance)) * action.duration

        # If scrolling down, the swipe should start at the bottom and end above.
        y_start = scrollable_bottom
        y_end = scrollable_bottom - current_distance

        # If scrolling up, the swipe should start at the top and end below.
        if total_scroll_distance < 0:
          y_start = scrollable_top
          y_end = scrollable_top + current_distance

        self._swipe_impl(
            round(scroll_area.mid_x), round(y_start), round(scroll_area.mid_x),
            round(y_end), current_duration)

        remaining_distance -= current_distance

  def _swipe_impl(self, start_x: int, start_y: int, end_x: int, end_y: int,
                  duration: dt.timedelta) -> None:

    duration_millis = round(duration // dt.timedelta(milliseconds=1))

    self.browser_platform.sh("input", "swipe", str(start_x), str(start_y),
                             str(end_x), str(end_y), str(duration_millis))

  def _get_android_viewport_info(
      self,
      actions: Actions,
      selector: str | None = None,
      scroll_into_view: bool = False) -> ViewportInfo:

    script = ""

    if selector:
      selector, script = self.get_selector_script(selector)

    script += self._GET_JS_VALUES

    (found_element, inner_height, inner_width, left, top, width,
     height) = actions.js(
         script, arguments=[selector, scroll_into_view])

    raw_chrome_window_bounds: DisplayRectangle = self._find_chrome_window_size()

    element_rect: DisplayRectangle | None = None
    if found_element:
      element_rect = DisplayRectangle(Point(left, top), width, height)

    return ViewportInfo(raw_chrome_window_bounds, inner_height, inner_width,
                        element_rect)

  # Returns the name of the browser's main window as reported by android's
  # window manager.
  def _get_browser_window_name(self,
                               browser_attributes: BrowserAttributes) -> str:
    if browser_attributes.is_chrome:
      return "chrome"

    raise RuntimeError("Unsupported browser for android action runner.")

  def _find_chrome_window_size(self) -> DisplayRectangle:
    # Find the chrome app window position by dumping the android app window
    # list. The list is sorted from highest to lowest z-order, so the first
    # Chrome window is the focused window.
    #
    # Chrome's main view always contains 'chrome' and is followed by the
    # configuration for that window.
    #
    # The mAppBounds config of the chrome window contains the dimensions
    # for the visible part of the current chrome window formatted like this for
    # a 800 height by 480 width window:
    #
    # mAppBounds=Rect(0, 0 - 480, 800)
    browser_main_window_name = self._get_browser_window_name(
        self.browser.attributes())

    return self.browser_platform.get_window_rect(browser_main_window_name)
