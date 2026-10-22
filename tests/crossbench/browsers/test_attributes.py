# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import inspect
import unittest
from typing import TYPE_CHECKING

from crossbench.browsers import all as all_browsers
from crossbench.browsers.applescript import AppleScriptBrowser
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.chromium_based.chromium_based import ChromiumBased
from crossbench.browsers.shell.shell_browser import ShellBrowser
from crossbench.browsers.webdriver import RemoteWebDriver, WebDriverBrowser
from crossbench.browsers.webview.embedder import WebviewEmbedder
from crossbench.browsers.webview.webview import Webview
from tests import test_helper
from tests.crossbench import mock_browser

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser


class BrowserAttributesTestCase(unittest.TestCase):

  def test_is_chromium_based(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_chromium_based, value
                       is BrowserAttributes.CHROMIUM_BASED)
    custom_chrome = (
        BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED)
    self.assertTrue(custom_chrome)
    self.assertFalse(custom_chrome & BrowserAttributes.SAFARI)
    self.assertTrue(custom_chrome & BrowserAttributes.CHROMIUM_BASED)
    self.assertIs(custom_chrome & BrowserAttributes.CHROMIUM_BASED,
                  BrowserAttributes.CHROMIUM_BASED)
    self.assertTrue(custom_chrome.is_chromium_based)

  def test_is_chromium(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_chromium, value is BrowserAttributes.CHROMIUM)
    custom = BrowserAttributes.CHROMIUM | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_chromium)
    self.assertTrue(BrowserAttributes.CHROMIUM.is_chromium)
    self.assertFalse(BrowserAttributes.CHROME.is_chromium)

  def test_is_chrome(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_chrome, value is BrowserAttributes.CHROME)
    custom = BrowserAttributes.CHROME | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_chrome)
    self.assertTrue(BrowserAttributes.CHROME.is_chrome)
    self.assertFalse(BrowserAttributes.SAFARI.is_chrome)

  def test_is_safari(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_safari, value is BrowserAttributes.SAFARI)
    custom = BrowserAttributes.SAFARI | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_safari)
    self.assertTrue(BrowserAttributes.SAFARI.is_safari)
    self.assertFalse(BrowserAttributes.CHROME.is_safari)

  def test_is_webkit(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_webkit, value is BrowserAttributes.WEBKIT)
    custom = BrowserAttributes.WEBKIT | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_webkit)
    self.assertTrue(BrowserAttributes.WEBKIT.is_webkit)
    self.assertFalse(BrowserAttributes.SAFARI.is_webkit)

  def test_is_edge(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_edge, value is BrowserAttributes.EDGE)
    custom = BrowserAttributes.EDGE | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_edge)
    self.assertTrue(BrowserAttributes.EDGE.is_edge)
    self.assertFalse(BrowserAttributes.CHROME.is_edge)

  def test_is_firefox(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_firefox, value is BrowserAttributes.FIREFOX)
    custom = BrowserAttributes.FIREFOX | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_firefox)
    self.assertTrue(BrowserAttributes.FIREFOX.is_firefox)
    self.assertFalse(BrowserAttributes.CHROME.is_firefox)

  def test_is_webview(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_webview, value is BrowserAttributes.WEBVIEW)
    custom = BrowserAttributes.WEBVIEW | BrowserAttributes.WEBDRIVER
    self.assertTrue(custom.is_webview)
    self.assertTrue(BrowserAttributes.WEBVIEW.is_webview)
    self.assertFalse(BrowserAttributes.CHROME.is_webview)

  def test_is_webview_embedder(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_webview_embedder, value
                       is BrowserAttributes.WEBVIEW_EMBEDDER)
    custom = (
        BrowserAttributes.WEBVIEW | BrowserAttributes.WEBVIEW_EMBEDDER
        | BrowserAttributes.WEBDRIVER)
    self.assertTrue(custom.is_webview_embedder)
    self.assertTrue(BrowserAttributes.WEBVIEW_EMBEDDER.is_webview_embedder)
    self.assertFalse(BrowserAttributes.WEBVIEW.is_webview_embedder)

  def test_is_d8(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_d8, value is BrowserAttributes.D8)
    custom = BrowserAttributes.D8 | BrowserAttributes.CHROMIUM_BASED
    self.assertTrue(custom.is_d8)

  def test_is_webdriver(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_webdriver, value is BrowserAttributes.WEBDRIVER)

  def test_is_applescript(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_applescript, value
                       is BrowserAttributes.APPLESCRIPT)

  def test_is_mobile_and_desktop(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_mobile, value is BrowserAttributes.MOBILE)
      self.assertEqual(value.is_desktop, value is BrowserAttributes.DESKTOP)

  def test_is_remote_and_local(self) -> None:
    for value in BrowserAttributes:
      self.assertEqual(value.is_remote, value is BrowserAttributes.REMOTE)
      self.assertEqual(value.is_local, value is not BrowserAttributes.REMOTE)

  def test_concrete_browser_attributes(self) -> None:
    expected_by_cls: dict[type[Browser], BrowserAttributes] = {
        all_browsers.CdpAndroidBrowser:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.MOBILE | BrowserAttributes.REMOTE),
        all_browsers.Chrome:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.DESKTOP),
        all_browsers.ChromeAppleScript:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.APPLESCRIPT | BrowserAttributes.DESKTOP),
        all_browsers.ChromeWebDriver:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP),
        all_browsers.ChromeWebDriverAndroid:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.MOBILE
             | BrowserAttributes.REMOTE),
        all_browsers.LocalChromeWebDriverAndroid:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.MOBILE
             | BrowserAttributes.REMOTE),
        all_browsers.ChromeWebDriverSsh:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP
             | BrowserAttributes.REMOTE),
        all_browsers.ChromeWebDriverChromeOsSsh:
            (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP
             | BrowserAttributes.REMOTE),
        all_browsers.Chromium:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.DESKTOP),
        all_browsers.ChromiumAppleScript:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.APPLESCRIPT | BrowserAttributes.DESKTOP),
        all_browsers.ChromiumWebDriver:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP),
        all_browsers.ChromiumWebDriverAndroid:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.MOBILE
             | BrowserAttributes.REMOTE),
        all_browsers.LocalChromiumWebDriverAndroid:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.MOBILE
             | BrowserAttributes.REMOTE),
        all_browsers.ChromiumWebDriverSsh:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP
             | BrowserAttributes.REMOTE),
        all_browsers.ChromiumWebDriverChromeOsSsh:
            (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP
             | BrowserAttributes.REMOTE),
        all_browsers.D8:
            (BrowserAttributes.D8 | BrowserAttributes.CHROMIUM_BASED),
        all_browsers.Edge:
            (BrowserAttributes.EDGE | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.DESKTOP),
        all_browsers.EdgeWebDriver:
            (BrowserAttributes.EDGE | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.DESKTOP),
        all_browsers.Firefox:
            (BrowserAttributes.FIREFOX | BrowserAttributes.DESKTOP),
        all_browsers.FirefoxWebDriver:
            (BrowserAttributes.FIREFOX | BrowserAttributes.WEBDRIVER
             | BrowserAttributes.DESKTOP),
        all_browsers.Safari:
            (BrowserAttributes.SAFARI | BrowserAttributes.DESKTOP),
        all_browsers.SafariAppleScript:
            (BrowserAttributes.SAFARI | BrowserAttributes.APPLESCRIPT
             | BrowserAttributes.DESKTOP),
        all_browsers.SafariWebDriver:
            (BrowserAttributes.SAFARI | BrowserAttributes.WEBDRIVER
             | BrowserAttributes.DESKTOP),
        all_browsers.SafariWebdriverIOS:
            (BrowserAttributes.SAFARI | BrowserAttributes.WEBDRIVER
             | BrowserAttributes.MOBILE | BrowserAttributes.REMOTE),
        all_browsers.WebKitWebDriver:
            (BrowserAttributes.WEBKIT | BrowserAttributes.WEBDRIVER
             | BrowserAttributes.DESKTOP),
        all_browsers.WebviewBrowser:
            (BrowserAttributes.WEBVIEW | BrowserAttributes.CHROMIUM_BASED
             | BrowserAttributes.WEBDRIVER | BrowserAttributes.MOBILE
             | BrowserAttributes.REMOTE),
        all_browsers.WebviewEmbedder:
            (BrowserAttributes.WEBVIEW | BrowserAttributes.WEBVIEW_EMBEDDER
             | BrowserAttributes.CHROMIUM_BASED | BrowserAttributes.WEBDRIVER
             | BrowserAttributes.MOBILE | BrowserAttributes.REMOTE),
        RemoteWebDriver:
            (BrowserAttributes.WEBDRIVER | BrowserAttributes.REMOTE),
    }

    primary_brands = (
        BrowserAttributes.SAFARI,
        BrowserAttributes.WEBKIT,
        BrowserAttributes.FIREFOX,
        BrowserAttributes.CHROMIUM,
        BrowserAttributes.CHROME,
        BrowserAttributes.EDGE,
        BrowserAttributes.WEBVIEW,
        BrowserAttributes.D8,
    )

    for browser_cls, expected in expected_by_cls.items():
      with self.subTest(browser_cls=browser_cls.__name__):
        attrs = browser_cls.attributes()
        self.assertEqual(attrs, expected)
        self.assertFalse(attrs.is_mobile and attrs.is_desktop)
        if attrs.is_mobile:
          self.assertTrue(attrs.is_remote)
        self.assertEqual(
            issubclass(browser_cls, WebDriverBrowser), attrs.is_webdriver)
        self.assertEqual(
            issubclass(browser_cls, AppleScriptBrowser), attrs.is_applescript)
        self.assertEqual(
            issubclass(browser_cls, (ChromiumBased, all_browsers.D8)),
            attrs.is_chromium_based)
        self.assertEqual(issubclass(browser_cls, Webview), attrs.is_webview)
        self.assertEqual(
            issubclass(browser_cls, WebviewEmbedder), attrs.is_webview_embedder)
        if browser_cls is not RemoteWebDriver:
          if not issubclass(browser_cls, ShellBrowser):
            self.assertTrue(attrs.is_mobile or attrs.is_desktop)
          matched_brands = [b for b in primary_brands if b in attrs]
          self.assertEqual(len(matched_brands), 1)

  def test_mock_browsers_attributes(self) -> None:
    mock_classes: tuple[type[mock_browser.MockBrowser], ...] = (
        *mock_browser.ALL,
        mock_browser.MockChromium,
        mock_browser.MockChromeAndroidStable,
    )
    for browser_cls in mock_classes:
      with self.subTest(browser_cls=browser_cls.__name__):
        self.assertFalse(inspect.isabstract(browser_cls))
        attrs = browser_cls.attributes()
        self.assertTrue(attrs.is_mobile ^ attrs.is_desktop)
        if attrs.is_mobile:
          self.assertTrue(attrs.is_remote)
        else:
          self.assertTrue(attrs.is_local)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
