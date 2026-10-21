# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import unittest
from typing import Any

from crossbench.cli.config.driver_type import BrowserDriverType
from tests import test_helper


class BrowserDriverTypeTestCase(unittest.TestCase):

  def test_default(self):
    self.assertEqual(BrowserDriverType.default(), BrowserDriverType.WEB_DRIVER)

  def test_parse_invalid(self):
    invalid: Any
    for invalid in ["invalid", None, [], (), {}]:
      with self.assertRaises(argparse.ArgumentTypeError):
        BrowserDriverType.parse(invalid)

  def test_parse_str(self):
    test_data = {
        "": BrowserDriverType.default(),
        "selenium": BrowserDriverType.WEB_DRIVER,
        "webdriver": BrowserDriverType.WEB_DRIVER,
        "applescript": BrowserDriverType.APPLE_SCRIPT,
        "osa": BrowserDriverType.APPLE_SCRIPT,
        "android": BrowserDriverType.ANDROID,
        "adb": BrowserDriverType.ANDROID,
        "cdp": BrowserDriverType.ANDROID_CDP,
        "android-cdp": BrowserDriverType.ANDROID_CDP,
        "iphone": BrowserDriverType.IOS,
        "ios": BrowserDriverType.IOS,
        "ios-wda": BrowserDriverType.IOS_WDA,
        "wda": BrowserDriverType.IOS_WDA,
        "ssh": BrowserDriverType.LINUX_SSH,
        "chromeos-ssh": BrowserDriverType.CHROMEOS_SSH,
    }
    for value, result in test_data.items():
      self.assertEqual(BrowserDriverType.parse(value), result)

  def test_parse_enum(self):
    for driver_type in BrowserDriverType:
      self.assertEqual(BrowserDriverType.parse(driver_type), driver_type)

  def test_is_remote_browser_generic(self):
    for driver_type in BrowserDriverType:
      self.assertNotEqual(driver_type.is_local_browser,
                          driver_type.is_remote_browser)

  def test_is_remote_driver_generic(self):
    for driver_type in BrowserDriverType:
      self.assertNotEqual(driver_type.is_local_driver,
                          driver_type.is_remote_driver)

  def test_is_remote_driver_implication(self):
    for driver_type in BrowserDriverType:
      if driver_type.is_remote_driver:
        self.assertTrue(driver_type.is_remote_browser)

  def test_is_remote_driver(self):
    remote_driver_types = {
        BrowserDriverType.CHROMEOS_SSH,
        BrowserDriverType.LINUX_SSH,
    }
    for driver_type in BrowserDriverType:
      self.assertEqual(driver_type.is_remote_driver, driver_type
                       in remote_driver_types)

  def test_is_android(self):
    android_types = {
        BrowserDriverType.ANDROID,
        BrowserDriverType.ANDROID_CDP,
    }
    for driver_type in BrowserDriverType:
      self.assertEqual(driver_type.is_android, driver_type in android_types)

  def test_is_remote_browser(self):
    remote_browser_types = {
        BrowserDriverType.ANDROID,
        BrowserDriverType.ANDROID_CDP,
        BrowserDriverType.CHROMEOS_SSH,
        BrowserDriverType.LINUX_SSH,
    }
    for driver_type in BrowserDriverType:
      self.assertEqual(driver_type.is_remote_browser, driver_type
                       in remote_browser_types)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
