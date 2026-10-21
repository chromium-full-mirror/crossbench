# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import Final

from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.benchmarks.loading.point import Point


class ViewportInfo:
  """Translates browser DOM and window metrics into native display pixels.

  Translates coordinates from web page JavaScript (DOM bounding client rects,
  inner/outer window metrics, and screen metrics) into native physical screen
  pixels across various platforms and windowing modes (ChromeOS, Desktop, and
  Android in both fullscreen and desktop windowing mode).

  Handles the distinction between:
  1. System DIPs (Device-Independent Pixels): Used for outer window bounds and
     screen positions (e.g. window.outerWidth, window.screenX, screen.width).
  2. CSS Pixels: Used for web content layout and DOM element rectangles (e.g.
     window.visualViewport.width, element.getBoundingClientRect()).

  Coordinate layout (after scaling DIPs and CSS px to physical screen pixels):

    (0, 0)                        screen_width
      +-------------------------------------------------------------------+
      | (window_offset_x, window_offset_y)                                |
      |   +-----------------------------------------------+  ^            |
      |   | Browser Top Chrome (tabs, omnibox, title bar) |  |            |
      |   |   height = outer_height - inner_height        |  |            |
      |   +-----------------------------------------------+  | window_    |
      |   | Web Viewport (browser_viewable)               |  | outer_     |
      |   |   (inner_width x inner_height)                |  | height     |
      |   |                                               |  |            |
      |   |     (element_rect.left, element_rect.top)     |  |            |
      |   |       +------------------+                    |  |            |
      |   |       |  DOM Element     |                    |  |            |
      |   |       +------------------+                    |  |            |
      |   +-----------------------------------------------+  v            |
      |   <------------- window_outer_width -------------->               |
      |                                                                   |
      +-------------------------------------------------------------------+
      | System Shelf / Taskbar / Navigation Bar                           |
      |   (screen_height - screen_avail_height)                           |
      +-------------------------------------------------------------------+
  """

  def __init__(self, device_pixel_ratio: float, window_outer_width: int,
               window_outer_height: int, window_inner_width: float,
               window_inner_height: float, screen_width: int,
               screen_height: int, screen_avail_width: int,
               screen_avail_height: int, window_offset_x: int,
               window_offset_y: int,
               element_rect: DisplayRectangle | None) -> None:
    # When page zoom or mobile viewport scaling is active, the ratio between
    # the outer window width (in DIPs) and the inner webview width (in CSS px)
    # reflects the scaling factor between DIPs and CSS pixels:
    #   zoom_ratio = window_outer_width (DIP) / window_inner_width (CSS px)
    zoom_ratio = ((window_outer_width / window_inner_width)
                  if window_inner_width and window_outer_width else 1.0)

    if zoom_ratio < 1.0:
      # On mobile viewports (e.g. Android Clank when a page is zoomed out to fit
      # a wider layout viewport such as 980 CSS px into 360 DIPs),
      # window.devicePixelRatio reports the hardware display density (pixels per
      # DIP) and does not scale down by the mobile viewport scale factor.
      screen_dpr = device_pixel_ratio
      self._actual_pixel_ratio: float = device_pixel_ratio * zoom_ratio
    else:
      # When desktop page zoom is active (zoom_ratio >= 1.0),
      # window.devicePixelRatio already includes the zoom factor (pixels per CSS
      # pixel), so divide by zoom_ratio to recover display density (pixels/DIP).
      screen_dpr = (
          device_pixel_ratio / zoom_ratio if zoom_ratio else device_pixel_ratio)
      self._actual_pixel_ratio = device_pixel_ratio

    # Calculate native display resolution in physical pixels from DIPs.
    screen_width_pixels = round(screen_width * screen_dpr)
    screen_height_pixels = round(screen_height * screen_dpr)

    # Available screen area in physical pixels.
    screen_avail_width_px = round(screen_avail_width * screen_dpr)
    screen_avail_height_px = round(screen_avail_height * screen_dpr)

    # Outer window frame dimensions in physical pixels (scaled from DIPs).
    window_outer_width_px = round(window_outer_width * screen_dpr)
    window_outer_height_px = round(window_outer_height * screen_dpr)

    # Inner webview content area in physical pixels (scaled from CSS pixels).
    window_inner_width_px = round(window_inner_width * self._actual_pixel_ratio)
    window_inner_height_px = round(window_inner_height *
                                   self._actual_pixel_ratio)

    # Top-left origin of the window on the physical display (scaled from DIPs).
    window_offset_x_px = round(window_offset_x * screen_dpr)
    window_offset_y_px = round(window_offset_y * screen_dpr)

    # In windowed/desktop mode, window frames may have side borders.
    # Distribute the excess width equally between left and right borders.
    if window_outer_width_px > window_inner_width_px:
      window_offset_x_px += round(
          (window_outer_width_px - window_inner_width_px) / 2)

    # Account for top UI decorations (omnibox, tab strip, window title bar)
    # by taking the difference between outer window height and inner webview.
    top_toolbar_height = max(0, window_outer_height_px - window_inner_height_px)
    window_offset_y_px += top_toolbar_height

    # Calculate the visible viewport dimensions bounded by the display.
    visible_width = min(window_inner_width_px,
                        screen_avail_width_px - window_offset_x_px)
    visible_height = min(window_inner_height_px,
                         screen_avail_height_px - window_offset_y_px)

    self._native_screen: Final[DisplayRectangle] = DisplayRectangle(
        Point(0, 0), screen_width_pixels, screen_height_pixels)

    self._browser_viewable: Final[DisplayRectangle] = DisplayRectangle(
        Point(window_offset_x_px, window_offset_y_px), visible_width,
        visible_height)

    self._element_rect: DisplayRectangle | None = None
    if element_rect:
      self._element_rect = self._dom_rect_to_native_rect(element_rect)

  @property
  def actual_pixel_ratio(self) -> float:
    return self._actual_pixel_ratio

  @property
  def browser_viewable(self) -> DisplayRectangle:
    return self._browser_viewable

  @property
  def native_screen(self) -> DisplayRectangle:
    return self._native_screen

  @property
  def element_rect(self) -> DisplayRectangle | None:
    return self._element_rect

  def _dom_rect_to_native_rect(self,
                               dom_rect: DisplayRectangle) -> DisplayRectangle:
    # Converts a DOM element rectangle from viewport-relative CSS pixels to
    # absolute physical screen coordinates.
    browser_viewable = self.browser_viewable
    correct_ratio_rect = dom_rect * self._actual_pixel_ratio

    adjusted_left = correct_ratio_rect.left + browser_viewable.left
    adjusted_top = correct_ratio_rect.top + browser_viewable.top
    adjusted_width = min(correct_ratio_rect.width,
                         self._native_screen.width - adjusted_left)
    adjusted_height = min(correct_ratio_rect.height,
                          self._native_screen.height - adjusted_top)

    return DisplayRectangle(
        Point(adjusted_left, adjusted_top), adjusted_width, adjusted_height)

  def css_to_native_distance(self, distance: float) -> float:
    # Converts a distance measurement in CSS pixels to native screen pixels.
    return distance * self._actual_pixel_ratio
