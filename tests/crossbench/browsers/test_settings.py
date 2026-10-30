# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench import path as pth
from crossbench import plt
from crossbench.browsers.settings import Settings
from crossbench.browsers.splash_screen import SplashScreen
from crossbench.browsers.viewport import Viewport
from crossbench.cli.config.env import EnvConfig
from crossbench.flags.base import Flags
from crossbench.flags.chrome import ChromeFlags
from crossbench.flags.js_flags import JSFlags
from tests import test_helper


class SettingsTestCase(unittest.TestCase):

  def test_defaults(self):
    settings = Settings()
    self.assertEqual(settings.flags, Flags())
    self.assertEqual(settings.js_flags, Flags())
    self.assertIsNone(settings.cache_dir)
    self.assertTrue(settings.clear_cache_dir)
    self.assertEqual(settings.viewport, Viewport.DEFAULT)
    self.assertIsNone(settings.driver_path)
    self.assertEqual(settings.splash_screen, SplashScreen.DEFAULT)
    self.assertTrue(settings.network.is_live)
    self.assertFalse(settings.wipe_system_user_data)
    self.assertEqual(settings.platform, plt.PLATFORM)
    self.assertEqual(settings.env_config, EnvConfig.default())
    self.assertIsNone(settings.browser_version)
    self.assertTrue(settings.start_browser)

  def test_start_browser_false_forces_no_splash_screen(self) -> None:
    settings = Settings(start_browser=False)
    self.assertFalse(settings.start_browser)
    self.assertEqual(settings.splash_screen, SplashScreen.NONE)

    settings_none = Settings(
        start_browser=False, splash_screen=SplashScreen.NONE)
    self.assertFalse(settings_none.start_browser)
    self.assertEqual(settings_none.splash_screen, SplashScreen.NONE)

    with self.assertRaisesRegex(ValueError, "SplashScreen"):
      _ = Settings(start_browser=False, splash_screen=SplashScreen.DETAILED)

  def test_custom(self):
    flags = Flags({"--one": "1", "--two": "2"}).freeze()
    js_flags = Flags({"--js-one": "js-1", "--js-two": "js-2"}).freeze()
    settings = Settings(
        flags,
        js_flags,
        cache_dir=pth.LocalPath("cache"),
        clear_cache_dir=False,
        viewport=Viewport.FULLSCREEN,
        driver_path=pth.LocalPath("driver"),
        splash_screen=SplashScreen.DETAILED,
        env_config=EnvConfig(cpu_max_usage_percent=10),
        browser_version="120.0.6099.224")
    self.assertEqual(settings.flags, flags)
    self.assertEqual(settings.js_flags, js_flags)
    self.assertEqual(settings.cache_dir, pth.LocalPath("cache"))
    self.assertFalse(settings.clear_cache_dir)
    self.assertEqual(settings.viewport, Viewport.FULLSCREEN)
    self.assertEqual(settings.driver_path, pth.LocalPath("driver"))
    self.assertEqual(settings.splash_screen, SplashScreen.DETAILED)
    self.assertTrue(settings.network.is_live)
    self.assertEqual(settings.env_config, EnvConfig(cpu_max_usage_percent=10))
    self.assertEqual(settings.browser_version, "120.0.6099.224")

  def test_js_flags_alone(self):
    js_flags = Flags({"--js-one": "js-1", "--js-two": "js-2"}).freeze()
    settings = Settings(js_flags=js_flags)
    self.assertEqual(settings.flags, Flags())
    self.assertEqual(settings.js_flags, js_flags)

  def test_chrome_flags(self):
    flags = ChromeFlags({"--one": "1", "--two": "2"}).freeze()
    settings = Settings(flags)
    self.assertEqual(settings.flags, flags)
    self.assertIsInstance(settings.flags, ChromeFlags)
    self.assertEqual(settings.js_flags, JSFlags())
    self.assertIsInstance(settings.js_flags, JSFlags)

  def test_chrome_flags_js_flags(self):
    flags = ChromeFlags({
        "--one": "1",
        "--two": "2",
        "--js-flags": "--js-one=js-1",
    }).freeze()
    settings = Settings(flags)
    self.assertEqual(settings.flags, flags)
    self.assertIsInstance(settings.flags, ChromeFlags)
    self.assertEqual(settings.js_flags, JSFlags({"--js-one": "js-1"}))
    self.assertIsInstance(settings.js_flags, JSFlags)

  def test_chrome_flags_separate_js_flags(self):
    flags = ChromeFlags({"--one": "1", "--two": "2"}).freeze()
    js_flags = Flags({"--js-one": "js-1", "--js-two": "js-2"}).freeze()
    settings = Settings(flags, js_flags)
    self.assertEqual(settings.flags, flags)
    self.assertIsInstance(settings.flags, ChromeFlags)
    self.assertEqual(settings.js_flags, js_flags)
    self.assertIsInstance(settings.js_flags, Flags)

  def test_ambiguous_js_flags(self):
    flags = ChromeFlags({"--one": "1", "--js-flags": "--js-one=js-1"}).freeze()
    with self.assertRaises(ValueError) as cm:
      _ = Settings(flags, js_flags=Flags({"--js-two": "js-2"}))
    self.assertIn("js-flags", str(cm.exception))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
