# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum


class BrowserAttributes(enum.IntFlag):
  SAFARI = enum.auto()
  WEBKIT = enum.auto()
  FIREFOX = enum.auto()
  CHROMIUM = enum.auto()
  CHROME = enum.auto()
  EDGE = enum.auto()
  WEBVIEW = enum.auto()
  WEBVIEW_EMBEDDER = enum.auto()

  CHROMIUM_BASED = enum.auto()

  D8 = enum.auto()

  WEBDRIVER = enum.auto()
  APPLESCRIPT = enum.auto()

  MOBILE = enum.auto()
  DESKTOP = enum.auto()

  REMOTE = enum.auto()

  def assert_chromium_based(self) -> None:
    assert self.is_chromium_based, (f"Got non chromium-based browser: {self}")

  def assert_is_local(self) -> None:
    assert self.is_local, (f"Got remote browser: {self}")

  @property
  def is_chromium_based(self) -> bool:
    return bool(self.CHROMIUM_BASED & self)

  @property
  def is_chromium(self) -> bool:
    return bool(self & self.CHROMIUM)

  @property
  def is_chrome(self) -> bool:
    return bool(self & self.CHROME)

  @property
  def is_safari(self) -> bool:
    return bool(self & self.SAFARI)

  @property
  def is_webkit(self) -> bool:
    return bool(self & self.WEBKIT)

  @property
  def is_edge(self) -> bool:
    return bool(self & self.EDGE)

  @property
  def is_firefox(self) -> bool:
    return bool(self & self.FIREFOX)

  @property
  def is_webview(self) -> bool:
    return bool(self & self.WEBVIEW)

  @property
  def is_webview_embedder(self) -> bool:
    return bool(self & self.WEBVIEW_EMBEDDER)

  @property
  def is_d8(self) -> bool:
    return bool(self & self.D8)

  @property
  def is_webdriver(self) -> bool:
    return bool(self & self.WEBDRIVER)

  @property
  def is_applescript(self) -> bool:
    return bool(self & self.APPLESCRIPT)

  @property
  def is_mobile(self) -> bool:
    return bool(self & self.MOBILE)

  @property
  def is_desktop(self) -> bool:
    return bool(self & self.DESKTOP)

  @property
  def is_remote(self) -> bool:
    return bool(self & self.REMOTE)

  @property
  def is_local(self) -> bool:
    return not self.is_remote
