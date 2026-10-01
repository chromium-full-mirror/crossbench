# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import datetime as dt
import pathlib
import re
import unittest
from unittest import mock

import urllib3

from crossbench import path as pth
from crossbench.browsers.browser import Browser
from crossbench.browsers.chromium.base import ChromiumBaseMixin
from crossbench.browsers.chromium.driver_finder import ChromeDriverFinder
from crossbench.browsers.chromium.webdriver import ChromiumWebDriver, \
    LocalChromiumWebDriverAndroid
from crossbench.browsers.chromium_based import helper
from crossbench.browsers.chromium_based.webdriver import ChromiumBasedWebDriver
from crossbench.browsers.settings import Settings
from crossbench.browsers.viewport import Viewport
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.mock_helper import AndroidAdbMockPlatform, \
    LinuxMockPlatform, MacOsMockPlatform, MockPlatform


class LocalChromeWebDriverAndroidTestCase(BaseCrossbenchTestCase):

  def test_is_apk_helper(self):
    self.assertTrue(
        LocalChromiumWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/chrome_public_apk")))
    self.assertTrue(
        LocalChromiumWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/trichrome_chrome_64_32_bundle")))
    self.assertFalse(LocalChromiumWebDriverAndroid.is_apk_helper(None))
    self.assertFalse(
        LocalChromiumWebDriverAndroid.is_apk_helper(
            pth.AnyPath("org.chromium.chrome")))
    self.assertFalse(
        LocalChromiumWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/out/arm64/chrome")))

  def test_is_local_build_mock_browser(self):
    self.assertTrue(self.browsers)
    for browser in self.browsers:
      self.assertFalse(browser.is_local_build)

  def test_is_local_build(self):
    build_dir = pathlib.Path("/home/testuser/chrome/src/out/release")
    path = build_dir / mock_browser.MockChromium.mock_app_binary()
    self.fs.create_file(path, st_size=1000)
    self.assertFalse(helper.is_in_build_dir(path, self.platform))

    version_str = mock_browser.MockChromium.VERSION
    with mock.patch.object(
        self.platform, "app_version", return_value=version_str):
      # Missing args.gn => cannot detect local build:
      browser = ChromiumWebDriver(
          "local", path=path, settings=Settings(platform=self.platform))
      self.assertFalse(browser.is_local_build)
      self.assertEqual(browser.version.version_str, version_str)

      self.fs.create_file(build_dir / "args.gn")
      self.assertTrue(helper.is_in_build_dir(path, self.platform))
      browser = ChromiumWebDriver(
          "local", path=path, settings=Settings(platform=self.platform))
      self.assertTrue(browser.is_local_build)
      self.assertFalse(browser.version.has_channel)
      self.assertEqual(browser.version.version_str, version_str)

  def test_find_build_dir(self):
    gn_dir = pth.LocalPath("/home/testuser/chrome/src/out/gn_build")
    self.fs.create_file(gn_dir / "args.gn")
    self.assertEqual(helper.find_build_dir(gn_dir, self.platform), gn_dir)
    self.assertEqual(
        helper.find_build_dir(gn_dir / "chrome", self.platform), gn_dir)

    ninja_dir = pth.LocalPath("/home/testuser/chrome/src/out/ninja_build")
    self.fs.create_file(ninja_dir / "build.ninja")
    self.assertEqual(helper.find_build_dir(ninja_dir, self.platform), ninja_dir)

    unstripped_dir = pth.LocalPath("/home/testuser/chrome/src/out/isolated")
    self.fs.create_dir(unstripped_dir / "lib.unstripped")
    self.assertEqual(
        helper.find_build_dir(
            unstripped_dir / "clang_x64/chromedriver", self.platform),
        unstripped_dir)

  def test_profile_data_dir(self):
    build_dir = pathlib.Path("/home/testuser/chrome/src/out/release")
    path = build_dir / mock_browser.MockChromium.mock_app_binary()
    self.fs.create_file(path, st_size=1000)
    self.fs.create_file(build_dir / "args.gn")

    version_str = mock_browser.MockChromium.VERSION
    with mock.patch.object(
        self.platform, "app_version", return_value=version_str):
      cache_dir = pth.AnyPath("/tmp/my-cache-dir")
      browser = ChromiumWebDriver(
          "local",
          path=path,
          settings=Settings(platform=self.platform, cache_dir=cache_dir))
      browser.setup()

      self.assertEqual(browser.profile_data_dir, cache_dir)

  def test_user_data_dir_flags(self):
    build_dir = pathlib.Path("/home/testuser/chrome/src/out/release")
    path = build_dir / mock_browser.MockChromium.mock_app_binary()
    self.fs.create_file(path, st_size=1000)
    self.fs.create_file(build_dir / "args.gn")

    version_str = mock_browser.MockChromium.VERSION
    with mock.patch.object(
        self.platform, "app_version", return_value=version_str):
      browser = ChromiumWebDriver(
          "local", path=path, settings=Settings(platform=self.platform))

      custom_dir = pth.AnyPath("/tmp/custom-user-data-dir")
      browser.flags["--user-data-dir"] = str(custom_dir)
      browser.setup()

      self.assertEqual(browser.profile_data_dir, custom_dir)


class MockChromiumBasedWebDriver(ChromiumBaseMixin, ChromiumBasedWebDriver):

  def __init__(self, label, driver) -> None:
    mock_platform = mock.MagicMock(name="Mock Platform")
    mock_platform.app_version.side_effect = [mock_browser.MockChromium.VERSION]
    self._private_driver = driver
    super().__init__(
        label=label, path=None, settings=Settings(platform=mock_platform))

  def _create_driver(self, options, service):
    raise RuntimeError("start() should not be called")


class ChromiumBasedWebDriverTestCase(unittest.TestCase):

  def _make_tab_switch_mocks(self, handles, current):
    mock_driver = mock.MagicMock(name="Mock Driver")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)

    def switch_to_window(handle):
      mock_driver.current_window_handle = handle
      mock_driver.title = handle
      mock_driver.current_url = f"https://{handle}.com"

    switch_to_window(current)

    mock_driver.switch_to.window.side_effect = switch_to_window
    mock_driver.window_handles = handles
    return (browser, mock_driver)

  def test_switch_tab_title(self):
    browser, mock_driver = self._make_tab_switch_mocks(["a", "b", "c"], "b")

    browser.switch_tab(title=re.compile("^c$"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "c")
    self.assertEqual(mock_driver.current_url, "https://c.com")

    browser.switch_tab(title=re.compile("^a$"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "a")
    self.assertEqual(mock_driver.current_url, "https://a.com")

    browser.switch_tab(title=re.compile("^b$"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "b")
    self.assertEqual(mock_driver.current_url, "https://b.com")

  def test_switch_tab_url(self):
    browser, mock_driver = self._make_tab_switch_mocks(["1", "2", "3"], "2")

    browser.switch_tab(url=re.compile(".*3.*"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "3")
    self.assertEqual(mock_driver.current_url, "https://3.com")

    browser.switch_tab(url=re.compile(".*1.*"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "1")
    self.assertEqual(mock_driver.current_url, "https://1.com")

    browser.switch_tab(url=re.compile(".*2.*"), timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "2")
    self.assertEqual(mock_driver.current_url, "https://2.com")

  def test_switch_tab_index(self):
    browser, mock_driver = self._make_tab_switch_mocks(["1", "2", "3"], "2")

    # Switch to current tab.
    browser.switch_tab(tab_index=1, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "2")
    self.assertEqual(mock_driver.current_url, "https://2.com")

    # Switch to first tab.
    browser.switch_tab(tab_index=0, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "1")
    self.assertEqual(mock_driver.current_url, "https://1.com")

    # Overflow tab_index.
    with self.assertRaises(IndexError):
      browser.switch_tab(tab_index=3, timeout=dt.timedelta(seconds=5))

    # Switch to last tab using negative tab_index.
    browser.switch_tab(tab_index=-1, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "3")
    self.assertEqual(mock_driver.current_url, "https://3.com")

    # Underflow tab_index.
    with self.assertRaises(IndexError):
      browser.switch_tab(tab_index=-4, timeout=dt.timedelta(seconds=5))

  def test_switch_relative_tab_index(self):
    browser, mock_driver = self._make_tab_switch_mocks(["1", "2", "3"], "2")

    # Switch to current tab
    browser.switch_tab(relative_tab_index=0, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "2")
    self.assertEqual(mock_driver.current_url, "https://2.com")

    # Next tab.
    browser.switch_tab(relative_tab_index=1, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "3")
    self.assertEqual(mock_driver.current_url, "https://3.com")

    # Wrap positive.
    browser.switch_tab(relative_tab_index=1, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "1")
    self.assertEqual(mock_driver.current_url, "https://1.com")

    # Wrap negative
    browser.switch_tab(relative_tab_index=-1, timeout=dt.timedelta(seconds=5))
    self.assertEqual(mock_driver.title, "3")
    self.assertEqual(mock_driver.current_url, "https://3.com")

  def test_get_renderer_pid(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    with mock.patch.object(browser, "js", return_value=12345):
      self.assertEqual(browser.get_renderer_pid(), 12345)
    with mock.patch.object(browser, "js", return_value=None):
      self.assertIsNone(browser.get_renderer_pid())
    base_mock = mock.Mock(spec=Browser)
    self.assertIsNone(Browser.get_renderer_pid(base_mock))

  def test_get_renderer_main_tid(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    with mock.patch.object(browser, "js", return_value=6789):
      self.assertEqual(browser.get_renderer_main_tid(), 6789)
    with mock.patch.object(browser, "js", return_value=None):
      self.assertIsNone(browser.get_renderer_main_tid())
    base_mock = mock.Mock(spec=Browser)
    self.assertIsNone(Browser.get_renderer_main_tid(base_mock))

  def test_find_driver_pid_capabilities_fallback(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    mock_driver.service.process.pid = 1111
    mock_driver.capabilities = {"goog:processID": 2222}
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    browser.platform.is_local = True
    browser.platform.process_children.return_value = []
    browser._find_driver_pid()
    self.assertEqual(browser._driver_pid, 1111)
    self.assertEqual(browser.pid, 2222)

  def test_quit_waits_for_browser_quit(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    browser._is_running = True
    browser._pid = 2222
    browser._driver_pid = 1111
    browser.platform.is_local = True
    browser.platform.is_android = False
    browser.platform.is_macos = False
    browser.platform.host_platform.is_local = True
    browser.platform.process_info.side_effect = [{"pid": 2222}, None]
    browser.platform.host_platform.process_info.return_value = None

    with mock.patch.object(browser, "close_all_tabs") as mock_close_all_tabs:
      browser.quit()
      mock_close_all_tabs.assert_called_once_with()

    mock_driver.execute.assert_called_once_with(
        "executeCdpCommand", {
            "cmd": "Browser.close",
            "params": {},
        })
    mock_driver.close.assert_not_called()
    self.assertEqual(browser.platform.process_info.call_count, 2)
    browser.platform.terminate.assert_not_called()
    self.assertIsNone(browser._pid)
    mock_driver.quit.assert_called_once_with()

  def test_quit_handles_http_error(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    mock_driver.execute.side_effect = urllib3.exceptions.MaxRetryError(
        mock.Mock(), "/session/test/chromium/send_command_and_get_result")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    browser._is_running = True
    browser._pid = 2222
    browser._driver_pid = 1111
    browser.platform.is_local = True
    browser.platform.is_android = False
    browser.platform.is_macos = False
    browser.platform.host_platform.is_local = True
    browser.platform.process_info.side_effect = [{"pid": 2222}, None]
    browser.platform.host_platform.process_info.return_value = None

    with mock.patch.object(browser, "close_all_tabs") as mock_close_all_tabs:
      browser.quit()
      mock_close_all_tabs.assert_called_once_with()

    self.assertEqual(browser.platform.process_info.call_count, 2)
    browser.platform.terminate.assert_not_called()
    self.assertIsNone(browser._pid)
    mock_driver.quit.assert_called_once_with()

  def test_clear_cache_resets_cache_dir_on_rm_error(self):
    mock_driver = mock.MagicMock(name="Mock Driver")
    browser = MockChromiumBasedWebDriver("test-driver", mock_driver)
    # Settings default to clear_cache_dir=True, so the rm path is exercised.
    self.assertTrue(browser.clear_cache_dir)
    cache_dir = pth.AnyPath("/tmp/chrome_cache_dir")
    browser._cache_dir = cache_dir
    browser.platform.rm.side_effect = PermissionError("Locked file")

    with self.assertRaises(PermissionError):
      browser._teardown_cache_dir()

    browser.platform.rm.assert_called_once_with(
        cache_dir, missing_ok=True, dir=True)
    self.assertIsNone(browser._cache_dir)


class ChromeDriverFinderTestCase(BaseCrossbenchTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.mock_browser = mock.MagicMock()
    self.mock_browser.platform.is_linux = False
    self.mock_browser.platform.is_macos = False
    self.mock_browser.platform.is_android = False
    self.mock_browser.platform.is_win = False
    self.mock_browser.platform.host_platform = self.platform
    self.mock_browser.version.major = 120

  def test_find_local_build_macos(self):
    self.mock_browser.platform.is_macos = True
    out_dir = pth.AnyPath("/Users/user/chromium/src/out/Official")
    app_path = out_dir / "Chromium.app"
    bin_path = app_path / "Contents" / "MacOS" / "Chromium"
    driver_path = out_dir / "chromedriver"

    self.fs.create_file(bin_path, st_size=1000)
    self.fs.create_file(driver_path, st_size=1000)

    self.mock_browser.app_path = app_path
    self.mock_browser.path = bin_path

    finder = ChromeDriverFinder(self.mock_browser)

    found_driver = finder.find_local_build()
    self.assertEqual(str(found_driver), str(driver_path))

  def test_find_local_build_linux(self):
    self.mock_browser.platform.is_linux = True
    out_dir = pth.AnyPath("/home/user/chromium/src/out/Default")
    app_path = out_dir / "chrome"
    driver_path = out_dir / "chromedriver"

    self.fs.create_file(app_path, st_size=1000)
    self.fs.create_file(driver_path, st_size=1000)

    self.mock_browser.app_path = app_path
    self.mock_browser.path = app_path

    finder = ChromeDriverFinder(self.mock_browser)

    found_driver = finder.find_local_build()
    self.assertEqual(str(found_driver), str(driver_path))

  def test_find_local_build_android(self):
    self.mock_browser.platform.is_android = True

    out_dir = pth.AnyPath("/home/user/chromium/src/out/Android")
    app_path = out_dir / "bin/chrome_apk"
    driver_path = out_dir / "clang_x64/chromedriver"

    self.fs.create_file(app_path, st_size=1000)
    self.fs.create_file(driver_path, st_size=1000)

    self.mock_browser.app_path = app_path
    self.mock_browser.path = app_path

    finder = ChromeDriverFinder(self.mock_browser)

    found_driver = finder.find_local_build()
    self.assertEqual(str(found_driver), str(driver_path))


class ChromiumPathMacOSTest(BaseCrossbenchTestCase):

  def setup_platform(self) -> MockPlatform:
    return MacOsMockPlatform()

  def test_macos_app_path_resolution(self):
    app_path = pth.AnyPath("/Applications/Chromium.app")
    bin_path = app_path / "Contents" / "MacOS" / "Chromium"

    self.fs.create_file(bin_path, st_size=1000)
    self.platform.app_version = mock.MagicMock(return_value="120.0.0.0")

    # Test passing the bundle path
    browser = ChromiumWebDriver(
        "test-label", path=app_path, settings=Settings(platform=self.platform))
    self.assertEqual(str(browser.app_path), str(app_path))
    self.assertEqual(str(browser.path), str(bin_path))

    # Test passing the binary path
    browser2 = ChromiumWebDriver(
        "test-label-2",
        path=bin_path,
        settings=Settings(platform=self.platform))
    self.assertEqual(str(browser2.app_path), str(app_path))
    self.assertEqual(str(browser2.path), str(bin_path))


class ChromiumPathLinuxTest(BaseCrossbenchTestCase):

  def setup_platform(self) -> MockPlatform:
    return LinuxMockPlatform()

  def test_linux_path_resolution(self):
    bin_path = pth.AnyPath("/usr/bin/chromium")
    self.fs.create_file(bin_path, st_size=1000)
    self.platform.app_version = mock.MagicMock(return_value="120.0.0.0")

    browser = ChromiumWebDriver(
        "test-label", path=bin_path, settings=Settings(platform=self.platform))
    self.assertEqual(str(browser.app_path), str(bin_path))
    self.assertEqual(str(browser.path), str(bin_path))

  def test_explicit_browser_version(self):
    bin_path = pth.AnyPath("/usr/bin/chromium")
    self.fs.create_file(bin_path, st_size=1000)
    self.platform.app_version = mock.MagicMock(
        side_effect=AssertionError("app_version should not be called"))

    browser = ChromiumWebDriver(
        "test-label",
        path=bin_path,
        settings=Settings(
            platform=self.platform, browser_version="120.0.6099.224"))
    self.assertEqual(browser.version.parts_str, "120.0.6099.224")
    self.platform.app_version.assert_not_called()

  def test_linux_driver_lookup(self):
    out_dir = pth.AnyPath("/home/user/chromium/src/out/Default")
    bin_path = out_dir / "chrome"
    driver_path = out_dir / "chromedriver"

    self.fs.create_file(bin_path, st_size=1000)
    self.fs.create_file(driver_path, st_size=1000)
    self.fs.create_file(out_dir / "args.gn")

    self.platform.app_version = mock.MagicMock(return_value="120.0.0.0")

    browser = ChromiumWebDriver(
        "test-label", path=bin_path, settings=Settings(platform=self.platform))
    browser.validate_binary()

    self.assertEqual(str(browser.driver_path), str(driver_path))


class MockLocalChromiumWebDriverAndroid(ChromiumBaseMixin,
                                        LocalChromiumWebDriverAndroid):

  def _create_driver(self, options, service):
    raise RuntimeError("start() should not be called")


class ChromiumPathAndroidTest(BaseCrossbenchTestCase):

  def setup_platform(self) -> MockPlatform:
    mock_adb = mock.MagicMock()
    mock_adb.serial_id = "mock-serial-id"
    mock_adb.build_version = 30
    mock_adb.build_description = "mock-build-description"
    mock_adb.packages.return_value = ["org.chromium.chrome"]

    host_platform = LinuxMockPlatform()
    platform = AndroidAdbMockPlatform(host_platform=host_platform, adb=mock_adb)
    platform.exists = mock.MagicMock(return_value=True)
    platform.is_file = mock.MagicMock(return_value=True)
    return platform

  def _create_android_browser(
      self,
      version: str,
      viewport: Viewport = Viewport.DEFAULT,
  ) -> MockLocalChromiumWebDriverAndroid:
    out_dir = pth.AnyPath("/home/user/chromium/src/out/Android")
    chrome_public_apk_path = out_dir / "bin/chrome_public_apk"
    driver_path = out_dir / "clang_x64/chromedriver"

    self.fs.create_file(chrome_public_apk_path, st_size=1000)
    self.fs.create_file(driver_path, st_size=1000)
    self.fs.create_file(out_dir / "args.gn")

    output = f"Package name: org.chromium.chrome\nversionName: {version}"
    self.platform.host_platform.sh_stdout = mock.MagicMock(return_value=output)

    browser = MockLocalChromiumWebDriverAndroid(
        "test-label",
        path=chrome_public_apk_path,
        settings=Settings(
            platform=self.platform, browser_version=version, viewport=viewport))
    browser._private_driver = mock.MagicMock()
    return browser

  def test_android_driver_lookup(self):
    browser = self._create_android_browser("120.0.0.0")
    browser.validate_binary()
    driver_path = pth.AnyPath(
        "/home/user/chromium/src/out/Android/clang_x64/chromedriver")
    self.assertEqual(str(browser.driver_path), str(driver_path))

  def test_setup_window_maximized_legacy_uiautomator(self):
    browser = self._create_android_browser(
        "153.0.7993.0", viewport=Viewport.MAXIMIZED)
    with mock.patch.object(self.platform,
                           "uiautomator_device") as mock_uiautomator:
      browser._setup_window()
      mock_uiautomator.assert_called_once_with(root_device=False)
    browser._private_driver.maximize_window.assert_not_called()

  def test_setup_window_maximized_webdriver(self):
    browser = self._create_android_browser(
        "153.0.7994.0", viewport=Viewport.MAXIMIZED)
    with mock.patch.object(self.platform,
                           "uiautomator_device") as mock_uiautomator:
      browser._setup_window()
      mock_uiautomator.assert_not_called()
    browser._private_driver.maximize_window.assert_called_once_with()

  def test_setup_window_explicit_bounds_unsupported_version(self):
    browser = self._create_android_browser(
        "153.0.7993.0", viewport=Viewport(800, 600, 20, 30))
    browser._setup_window()
    browser._private_driver.set_window_position.assert_not_called()
    browser._private_driver.set_window_size.assert_not_called()

  def test_setup_window_explicit_bounds_supported_version(self):
    browser = self._create_android_browser(
        "153.0.7994.0", viewport=Viewport(800, 600, 20, 30))
    browser._setup_window()
    browser._private_driver.set_window_position.assert_called_once_with(20, 30)
    browser._private_driver.set_window_size.assert_called_once_with(800, 600)

  def test_setup_window_default_viewport_skipped(self):
    browser = self._create_android_browser(
        "153.0.7994.0", viewport=Viewport.DEFAULT)
    browser._setup_window()
    browser._private_driver.maximize_window.assert_not_called()
    browser._private_driver.set_window_position.assert_not_called()
    browser._private_driver.set_window_size.assert_not_called()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
