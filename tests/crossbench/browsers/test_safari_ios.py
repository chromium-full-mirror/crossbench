# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import json
from unittest import mock

from pyfakefs.fake_filesystem import OSType
from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.enums import WindowTarget
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.safari.webdriver import SafariWdaIOS
from crossbench.browsers.settings import Settings
from crossbench.plt.ios import IOSPlatform
from crossbench.runner.groups.session import BrowserSessionRunGroup
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase
from tests.crossbench.mock_helper import MacOsMockPlatform
from tests.crossbench.plt.test_ios import DEVICES_SINGLE, SIMULATORS_SAMPLE


class SafariIosBrowserTestCase(CrossbenchFakeFsTestCase):
  __test__ = True

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.os = OSType.MACOS
    self.host_platform = self.setup_host_platform()

  def setup_host_platform(self) -> MacOsMockPlatform:
    platform = MacOsMockPlatform()

    @contextlib.contextmanager
    def mock_named_temporary_file(suffix=None, prefix=None, dir=None):
      del suffix, prefix, dir
      yield pth.LocalPath("/devicectl_output.json")

    platform.NamedTemporaryFile = mock_named_temporary_file
    return platform

  def setup_platform(self) -> IOSPlatform:
    if self.fs.exists("/devicectl_output.json"):
      self.fs.remove_object("/devicectl_output.json")
    self.fs.create_file(
        "/devicectl_output.json",
        contents=json.dumps(DEVICES_SINGLE),
    )
    self.host_platform.expect_sh(
        "xcrun",
        "devicectl",
        "list",
        "devices",
        "--json-output=/devicectl_output.json",
        result="",
    )
    self.host_platform.expect_sh(
        "xcrun",
        "simctl",
        "list",
        "devices",
        "booted",
        "--json",
        result=json.dumps(SIMULATORS_SAMPLE),
    )
    return IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")

  def test_attributes(self) -> None:
    platform = self.setup_platform()
    browser = SafariWdaIOS(
        "test-safari",
        platform.path("/Applications/Safari.app"),
        settings=Settings(platform=platform),
    )
    attrs = browser.attributes()
    self.assertTrue(attrs & BrowserAttributes.SAFARI)
    self.assertTrue(attrs & BrowserAttributes.MOBILE)
    self.assertFalse(attrs & BrowserAttributes.WEBDRIVER)

  def test_version_and_paths(self) -> None:
    platform = self.setup_platform()
    browser = SafariWdaIOS(
        "test-safari",
        platform.path("/Applications/Safari.app"),
        settings=Settings(platform=platform),
    )
    self.assertEqual(browser.version.major, 17)
    self.assertIsNone(browser._setup_cache_dir())

  def test_start_and_show_url(self) -> None:
    platform = self.setup_platform()
    mock_network = mock.MagicMock()
    mock_network.is_running = True
    mock_network.extra_flags.return_value = ()
    browser = SafariWdaIOS(
        "test-safari",
        platform.path("/Applications/Safari.app"),
        settings=Settings(platform=platform, network=mock_network),
    )
    mock_wda = mock.MagicMock()
    platform._wda = mock_wda

    session = mock.create_autospec(
        BrowserSessionRunGroup,
        instance=True,
        extra_flags=(),
    )
    session.network = mock.MagicMock()
    session.network.extra_flags.return_value = ()

    browser.start(session)
    mock_wda.terminate_app.assert_called_once_with("com.apple.mobilesafari")
    mock_wda.launch_app.assert_called_once_with("com.apple.mobilesafari")
    self.assertTrue(browser.is_running)

    browser.show_url("https://example.com", WindowTarget.SELF)
    mock_wda.open_url.assert_called_once_with("https://example.com")

    with self.assertRaises(NotImplementedError):
      browser.show_url("https://example.com", WindowTarget.NEW_TAB)

    # about:blank and data: URLs should be ignored.
    mock_wda.open_url.reset_mock()
    browser.show_url("about:blank")
    browser.show_url("data:text/html;charset=utf-8,<html></html>")
    mock_wda.open_url.assert_not_called()

    mock_wda.terminate_app.reset_mock()
    browser.force_quit()
    mock_wda.terminate_app.assert_called_once_with("com.apple.mobilesafari")
    self.assertFalse(browser.is_running)

  def test_js_not_implemented_and_user_agent(self) -> None:
    platform = self.setup_platform()
    browser = SafariWdaIOS(
        "test-safari",
        platform.path("/Applications/Safari.app"),
        settings=Settings(platform=platform),
    )
    self.assertIn("Safari", browser.user_agent())
    with self.assertRaises(NotImplementedError):
      browser.js("return 1;")

  def test_performance_mark_skips_js(self) -> None:
    platform = self.setup_platform()
    browser = SafariWdaIOS(
        "test-safari",
        platform.path("/Applications/Safari.app"),
        settings=Settings(platform=platform),
    )
    # performance_mark should succeed without calling js().
    browser.performance_mark("test-mark")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
