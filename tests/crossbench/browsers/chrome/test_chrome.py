# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
from unittest import mock

import selenium.common.exceptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from typing_extensions import override

from crossbench import path as pth
from crossbench.browsers.chrome.version import ChromeVersion
from crossbench.browsers.chrome.webdriver import ChromeWebDriver, \
    LocalChromeWebDriverAndroid
from crossbench.browsers.settings import Settings
from crossbench.browsers.viewport import Viewport
from crossbench.browsers.webdriver import DriverException
from crossbench.flags.chrome import ChromeFlags
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.mock_helper import MacOsMockPlatform


class ChromeWebDriverForTesting(ChromeWebDriver):

  @override
  def _extract_version(self) -> ChromeVersion:
    return ChromeVersion.parse(mock_browser.MockChromeStable.VERSION)


class ChromeWebdriverTestCase(BaseCrossbenchTestCase):

  def test_conflicting_finch_flags(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ChromeWebDriverForTesting(
          label="browser-label",
          path=mock_browser.MockChromeStable.mock_app_path(),
          settings=Settings(
              js_flags=[],
              flags=[
                  "--disable-field-trial-config",
                  "--enable-field-trial-config",
              ],
              platform=self.platform))
    msg = str(cm.exception)
    self.assertIn("--enable-field-trial-config", msg)
    self.assertIn("--disable-field-trial-config", msg)

  def test_auto_disabling_field_trials(self):
    browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(platform=self.platform))
    self.assertIn("--disable-field-trial-config", browser.flags)

    browser_field_trial = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(
            flags=["--force-fieldtrials"], platform=self.platform))
    self.assertIn("--force-fieldtrials", browser_field_trial.flags)
    self.assertNotIn("--disable-field-trial-config", browser_field_trial.flags)

  def test_auto_disabling_field_trials_all(self):
    for field_trial_flag in ChromeFlags.FIELD_TRIAL_ENABLE_FLAGS:
      if field_trial_flag == "--enable-benchmarking":
        continue
      browser = ChromeWebDriverForTesting(
          label="browser-label",
          path=mock_browser.MockChromeStable.mock_app_path(),
          settings=Settings(flags=[field_trial_flag], platform=self.platform))
      flags: ChromeFlags = browser.flags
      self.assertIn(field_trial_flag, flags)
      self.assertFalse(flags.field_trial_disable_flags)

  def test_is_local_build_mock_browser(self):
    self.assertTrue(self.browsers)
    for browser in self.browsers:
      self.assertFalse(browser.is_local_build)

  def test_startup_error_headless_platform(self) -> None:
    browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(platform=self.platform))
    with mock.patch(
        "selenium.webdriver.Chrome",
        side_effect=selenium.common.exceptions.WebDriverException(
            "session not created")), mock.patch.object(
                type(self.platform),
                "has_display",
                new_callable=mock.PropertyMock,
                return_value=False):
      with self.assertRaises(DriverException) as cm:
        browser._create_driver(ChromeOptions(), ChromeService())
      self.assertIn("Try running with --headless", str(cm.exception))

    headless_browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(
            platform=self.platform, viewport=Viewport.HEADLESS))
    with mock.patch(
        "selenium.webdriver.Chrome",
        side_effect=selenium.common.exceptions.WebDriverException(
            "session not created")), mock.patch.object(
                type(self.platform),
                "has_display",
                new_callable=mock.PropertyMock,
                return_value=False):
      with self.assertRaises(DriverException) as cm:
        headless_browser._create_driver(ChromeOptions(), ChromeService())
      self.assertNotIn("Try running with --headless", str(cm.exception))


class LocalChromeWebDriverAndroidTestCase(BaseCrossbenchTestCase):

  def test_is_apk_helper(self):
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/chrome_public_apk")))
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/chrome_bundle")))
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath(
                "/home/user/Documents/chrome/src/"
                "out/arm64.apk/bin/trichrome_chrome_google_64_32_bundle")))
    self.assertFalse(LocalChromeWebDriverAndroid.is_apk_helper(None))
    self.assertFalse(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("org.chromium.chrome")))
    self.assertFalse(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/out/arm64/chrome")))


class ChromePathMacOsTestCase(BaseCrossbenchTestCase):

  @override
  def setup_platform(self):
    return MacOsMockPlatform()

  def test_chrome_path_macos(self):
    app_path = self.platform.path("/Users/user/chrome/src/out/mac/Chrome.app")
    binary_path = app_path / "Contents" / "MacOS" / "Chrome"
    self.fs.create_file(binary_path, st_size=100)

    # Test 1: Initialize with app bundle path
    browser_app = ChromeWebDriverForTesting(
        label="browser-app",
        path=app_path,
        settings=Settings(platform=self.platform))
    self.assertEqual(browser_app.path, binary_path)
    self.assertEqual(browser_app.app_path, app_path)

    # Test 2: Initialize with direct binary path
    browser_bin = ChromeWebDriverForTesting(
        label="browser-bin",
        path=binary_path,
        settings=Settings(platform=self.platform))
    self.assertEqual(browser_bin.path, binary_path)
    self.assertEqual(browser_bin.app_path, app_path)

    # Both should be identical in terms of paths
    self.assertEqual(browser_app.path, browser_bin.path)
    self.assertEqual(browser_app.app_path, browser_bin.app_path)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
