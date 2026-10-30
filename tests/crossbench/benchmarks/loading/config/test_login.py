# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import pathlib

from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.loading_benchmark import LoadingPageFilter
from crossbench.benchmarks.loading.page.base import Page
from crossbench.browsers.settings import Settings
from crossbench.cli.config.secrets import GoogleUsernamePassword, \
    UsernamePassword
from crossbench.flags.base import Flags
from crossbench.runner.groups.session import BrowserSessionRunGroup
from tests import test_helper
from tests.crossbench.action_runner.action_runner_test_case import \
    ActionRunnerTestCase
from tests.crossbench.mock_browser import MockChromeStable
from tests.crossbench.mock_helper import ChromeOsSshMockPlatform, \
    LinuxMockPlatform
from tests.crossbench.runner.helper import MockRun, MockRunner


class ChromeOSLoginTestCase(ActionRunnerTestCase):
  _CONFIG_DATA = {
      "secrets": {
          "google": {
              "username": "test",
              "password": "s3cr3t",
          },
      },
      "pages": {
          "Google Story": {
              "login": "google",
              "actions": [{
                  "action": "get",
                  "url": "https://www.google.com",
              }],
          },
      },
  }

  def setUp(self) -> None:
    super().setUp()
    self.host_platform = LinuxMockPlatform()
    self.platform = ChromeOsSshMockPlatform(
        host_platform=self.host_platform,
        host="1.1.1.1",
        port="1234",
        ssh_port="22",
        ssh_user="root")

    self.platform.expect_sh("[", "-e", "/usr/bin/google-chrome", "]", result="")
    self.platform.expect_sh("[", "-f", "/usr/bin/google-chrome", "]", result="")

    self.browser = MockChromeStable(
        "mock browser", settings=Settings(platform=self.platform))
    self.runner = MockRunner()
    self.root_dir = pathlib.Path()
    self.session = BrowserSessionRunGroup(self.runner.env,
                                          self.runner.probes, self.browser,
                                          Flags(), 1, self.root_dir, True, True)
    self.mock_run = MockRun(self.runner, self.session, "run 1")
    self.action_runner = self.mock_run.action_runner

  def expect_successful_google_login(self):
    # Wait for readystate interactive
    self.browser.expect_js(result=True)

    # Wait for email field
    self.browser.expect_js(result=True)
    # Click submit email
    self.browser.expect_js(result=None)

    # Wait for password field
    self.browser.expect_js(result=True)
    # Click submit password
    self.browser.expect_js(result=None)

    # Wait for redirect after password
    self.browser.expect_js(result=True)
    # Wait for readystate complete
    self.browser.expect_js(result=True)
    # Return successful login URL
    self.browser.expect_js(result="https://myaccount.google.com")
    # Check for suspicious activity
    self.browser.expect_js(result=False)

  def test_google_account(self):
    config = PagesConfig.parse(self._CONFIG_DATA)
    page = LoadingPageFilter.from_config(Page, self.mock_args(), config).stories

    self.expect_successful_google_login()

    self.mock_run.story_secrets = page[0].secrets
    self.assertIsNotNone(config.pages[0].login)
    config.pages[0].login.run_with(self.action_runner)

  def test_logged_in_google_account(self):
    config = PagesConfig.parse(self._CONFIG_DATA)
    page = LoadingPageFilter.from_config(Page, self.mock_args(), config).stories

    self.browser.expect_is_logged_in(GoogleUsernamePassword("test", "s3cr3t"))

    self.mock_run.story_secrets = page[0].secrets
    self.assertIsNotNone(config.pages[0].login)
    config.pages[0].login.run_with(self.action_runner)

  def test_logged_in_non_google_account(self):
    config = PagesConfig.parse(self._CONFIG_DATA)
    page = LoadingPageFilter.from_config(Page, self.mock_args(), config).stories

    self.browser.expect_is_logged_in(UsernamePassword("test", "s3cr3t"))

    self.expect_successful_google_login()

    self.mock_run.story_secrets = page[0].secrets
    self.assertIsNotNone(config.pages[0].login)
    config.pages[0].login.run_with(self.action_runner)

  def test_full_account_maintenance_flow(self):
    config = PagesConfig.parse(self._CONFIG_DATA)
    page = LoadingPageFilter.from_config(Page, self.mock_args(), config).stories

    # Wait for readystate interactive
    self.browser.expect_js(result=True)

    # Wait for email field
    self.browser.expect_js(result=True)
    # Click submit email
    self.browser.expect_js(result=None)

    # Wait for password field
    self.browser.expect_js(result=True)
    # Click submit password
    self.browser.expect_js(result=None)

    # Wait for redirect after password
    self.browser.expect_js(result=True)
    # Wait for readystate complete
    self.browser.expect_js(result=True)

    # Return passkey URL
    passkey_url = (
        "https://accounts.google.com/v3/signin/speedbump/passkeyenrollment")
    self.browser.expect_js(result=passkey_url)
    # Wait for skip element
    self.browser.expect_js(result={"count": 1})
    # Click skip element
    self.browser.expect_js(result={"count": 1})
    # Wait for URL change
    self.browser.expect_js(result=True)
    # Wait for ready state complete
    self.browser.expect_js(result=True)

    # Return passkey URL
    self.browser.expect_js(result="https://gds.google.com/web/recoveryoptions")
    # Wait for skip element
    self.browser.expect_js(result={"count": 1})
    # Click skip element
    self.browser.expect_js(result={"count": 1})
    # Wait for URL change
    self.browser.expect_js(result=True)
    # Wait for ready state complete
    self.browser.expect_js(result=True)

    # Return passkey URL
    self.browser.expect_js(result="https://gds.google.com/web/homeaddress")
    # Wait for skip element
    self.browser.expect_js(result={"count": 1})
    # Click skip element
    self.browser.expect_js(result={"count": 1})
    # Wait for URL change
    self.browser.expect_js(result=True)
    # Wait for ready state complete
    self.browser.expect_js(result=True)

    # Return successful login URL
    self.browser.expect_js(result="https://myaccount.google.com")

    # Return suspicious activity is present
    self.browser.expect_js(result=True)
    # Click suspicious activity button
    self.browser.expect_js(result={"count": 1})
    # Wait for 'yes' button
    self.browser.expect_js(result={"count": 1})
    # Click 'yes' button
    self.browser.expect_js(result={"count": 1})
    # Wait 'yes' button not present.
    self.browser.expect_js(result={"count": 1})

    self.mock_run.story_secrets = page[0].secrets
    self.assertIsNotNone(config.pages[0].login)
    config.pages[0].login.run_with(self.action_runner)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
