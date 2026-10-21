# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
from typing import TYPE_CHECKING, ClassVar, Final, Sequence, TypedDict

from selenium import webdriver
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.webdriver.safari.service import Service as SafariService
from typing_extensions import override

from crossbench import exception
from crossbench import path as pth
from crossbench.action_runner.action.enums import WindowTarget
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.safari.safari import Safari, find_safaridriver
from crossbench.browsers.safari.version import SafariVersion
from crossbench.browsers.webdriver import DriverException, WebDriverBrowser
from crossbench.cli.ui import ui
from crossbench.helper.wait import WaitRange
from crossbench.plt.ios import IOSPlatform
from crossbench.plt.wda import WDAError

if TYPE_CHECKING:
  from crossbench.browsers.settings import Settings
  from crossbench.runner.groups.session import BrowserSessionRunGroup
  from crossbench.types import Json


class SafariDriverKwargs(TypedDict):
  service: SafariService
  options: SafariOptions


class SafariWebDriver(WebDriverBrowser, Safari):

  MAX_STARTUP_TIMEOUT: ClassVar[dt.timedelta] = dt.timedelta(seconds=10)
  # Delay between launching safaridriver and sending the first session
  # request. safaridriver answers HTTP requests before it has finished
  # enumerating attached devices, so a session requested too early might not
  # see all of them.
  DRIVER_WARMUP_DELAY: ClassVar[dt.timedelta] = dt.timedelta(seconds=0)

  def __init__(self,
               label: str,
               path: pth.AnyPath,
               settings: Settings | None = None) -> None:
    super().__init__(label, path, settings)
    assert self.platform.is_apple, f"Unsupported platform: {self.platform}"
    self._service: SafariService | None = None

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.SAFARI | BrowserAttributes.WEBDRIVER

  @override
  def _find_driver(self) -> pth.AnyPath:
    # TODO: support remote platform
    assert self.host_platform.is_local, "Remote platform is not supported yet"
    return self.host_platform.local_path(
        find_safaridriver(self.path, self.platform))

  @override
  def _setup_driver_log_file(self) -> pth.LocalPath:
    raise NotImplementedError("Cannot use custom driver log path for Safari")

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> webdriver.Remote:
    return self._start_safari_driver(session, driver_path)

  def _start_safari_driver(self, session: BrowserSessionRunGroup,
                           driver_path: pth.AnyPath) -> webdriver.Safari:
    assert not self._is_running
    logging.info("STARTING BROWSER: browser: %s driver: %s", self.path,
                 driver_path)

    options: SafariOptions = self._get_driver_options(session)
    session.setup_selenium_options(options)

    service = self._create_service(self.host_platform.local_path(driver_path))
    driver_kwargs: SafariDriverKwargs = {"service": service, "options": options}

    try:
      with ui.spinner(), exception.annotate(
          "Starting safaridriver with retries"):
        driver = self._start_driver_with_retries(driver_path, driver_kwargs)
        self.host_platform.sleep(0.5)
    except BaseException:
      self._stop_service()
      raise

    assert driver.session_id, "Could not start webdriver"
    logs: pth.AnyPath = (
        self.host_platform.home() / "Library/Logs/com.apple.WebDriver" /
        driver.session_id)
    all_logs = list(self.host_platform.glob(logs, "safaridriver*"))
    if all_logs:
      first_log_file = all_logs[0]
      self._driver_log_file = pth.LocalPath(first_log_file)
      assert self.host_platform.is_file(first_log_file), (
          f"Invalid log file {first_log_file}")
    return driver

  def _create_service(self, driver_path: pth.LocalPath) -> SafariService:
    """Creates the safaridriver service without starting it.

    With reuse_service=True selenium leaves starting and stopping safaridriver
    to us, see _ensure_service_running(). This lets us insert
    DRIVER_WARMUP_DELAY between launching safaridriver and the first session
    request, which selenium would otherwise send immediately.
    """
    assert not self._service, "safaridriver service is already running"
    service = SafariService(
        executable_path=os.fspath(driver_path), reuse_service=True)
    self._service = service
    return service

  def _ensure_service_running(self, service: SafariService) -> None:
    """(Re)starts safaridriver if needed and waits for device discovery.

    Note that selenium stops the service after a failed session request
    regardless of reuse_service, so this is needed before every attempt.
    """
    if service.is_connectable():
      return
    service.start()
    if delay := self.DRIVER_WARMUP_DELAY:
      logging.debug("SafariWebDriver: waiting %s for device discovery", delay)
      self.host_platform.sleep(delay)

  def _stop_service(self) -> None:
    if not self._service:
      return
    try:
      self._service.stop()
    except (OSError, subprocess.SubprocessError) as e:
      logging.debug("Could not stop safaridriver service: %s", e)
    finally:
      self._service = None

  # TODO(cbruni): implement iOS platform
  def _start_driver_with_retries(
      self, driver_path: pth.AnyPath,
      driver_kwargs: SafariDriverKwargs) -> webdriver.Safari:
    # safaridriver for iOS / technology preview seems to be brittle.
    # Let's give it several chances to start up.
    seen_exceptions: set[type[Exception]] = set()
    retries = 0
    for _ in WaitRange(
        min=2, timeout=self.MAX_STARTUP_TIMEOUT).wait_with_backoff():
      try:
        # Selenium stops the service after a failed session request, so we
        # have to (re)start it before every attempt.
        self._ensure_service_running(driver_kwargs["service"])
        return webdriver.Safari(**driver_kwargs)
      except Exception as e:  # noqa: BLE001
        retries += 1
        exception_type = type(e)
        message = str(e).lower()
        if "--enable" in message or "remote automation" in message:
          logging.error(
              "Safari Remote Automation is not enabled. "
              "Please run '%s --enable' or enable it in "
              "Safari's 'Develop' menu.", driver_path)
          raise DriverException("Could not start SafariWebDriver") from e
        logging.warning(
            "SafariWebDriver: startup failed (%s: %s), retrying...",
            exception_type, e)
        # After 2 retries we don't accept the same error twice.
        if retries >= 2 and exception_type in seen_exceptions:
          logging.error("SafariWebDriver: startup error %s", e)
          raise DriverException("Could not start SafariWebDriver") from e
        logging.debug("SafariWebDriver: startup error %s", e)
        seen_exceptions.add(type(e))
    raise DriverException("Could not start SafariWebDriver")

  def _get_driver_options(self,
                          session: BrowserSessionRunGroup) -> SafariOptions:
    options = SafariOptions()
    # Don't wait for document-ready.
    options.set_capability("pageLoadStrategy", "none")

    args = self._get_browser_flags_for_session(session)
    for arg in args:
      options.add_argument(arg)

    if self._settings.driver_logging:
      options.set_capability("safari:diagnose", "true")
    if "Technology Preview" in self.app_name:
      options.set_capability("browserName", "Safari Technology Preview")
      options.use_technology_preview = True
    return options

  @override
  def _validate_driver_version(self) -> None:
    # The bundled driver is always ok
    for parent in self.driver_path.parents:
      if parent == self.path.parent:
        return
    version = self.host_platform.sh_stdout(self.driver_path, "--version")
    assert str(self.version.major) in version, (
        f"safaridriver={self.driver_path} version='{version}' "
        f" doesn't match safari version={self.version.major}")

  @override
  def _setup_window(self) -> None:
    super()._setup_window()
    self.platform.exec_apple_script(f"""
        tell application "{self.app_name}"
          activate
        end tell""")

  @override
  def quit(self) -> None:
    super().quit()
    if self.platform.is_macos:
      # Safari needs some additional push to quit properly
      self.platform.exec_apple_script(f"""
          tell application "{self.app_name}"
            quit
          end tell""")

  @override
  def force_quit(self) -> None:
    try:
      super().force_quit()
    finally:
      # Selenium does not stop a reused service, so we have to do it here.
      self._stop_service()
      # Certain safaridriver versions keep on lingering around when they fail.
      self.host_platform.killall("safaridriver")


class SafariWebdriverIOS(SafariWebDriver):
  MAX_STARTUP_TIMEOUT: ClassVar[dt.timedelta] = dt.timedelta(seconds=15)
  # USB-attached devices are discovered noticeably later than Wi-Fi
  # (CoreDevice) ones. Without this delay safaridriver only considers the
  # Wi-Fi devices for the first session request and fails for USB devices.
  DRIVER_WARMUP_DELAY: ClassVar[dt.timedelta] = dt.timedelta(seconds=1)

  @override
  def _get_driver_options(self,
                          session: BrowserSessionRunGroup) -> SafariOptions:
    options = super()._get_driver_options(session)
    assert isinstance(self.platform, IOSPlatform)
    desired_cap = {
        # "browserName": "Safari",
        # "browserVersion": "17.0.3", # iOS version
        # "safari:deviceType": "iPhone",
        # "safari:deviceName": "XXX's iPhone",
        "safari:deviceUDID": self.platform.udid,
        "platformName": "iOS",
        "safari:initialUrl": "about:blank",
        "safari:openLinksInBackground": True,
        "safari:allowPopups": True,
    }
    if self.platform.is_simulator:
      desired_cap["safari:useSimulator"] = True
    for key, value in desired_cap.items():
      options.set_capability(key, value)
    return options

  @override
  def _setup_window(self) -> None:
    pass

  @override
  def _resolve_binary(self,
                      path: pth.AnyPath) -> tuple[pth.AnyPath, pth.AnyPath]:
    return path, path

  @override
  def _setup_cache_dir(self) -> pth.AnyPath | None:
    # TODO: Can we manage cache dir on iOS?
    return None


class SafariWdaIOS(Safari):
  """Safari browser implementation on iOS backed by WebDriverAgent."""

  BUNDLE_ID: Final[str] = "com.apple.mobilesafari"

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.SAFARI | BrowserAttributes.MOBILE

  @property
  def ios_platform(self) -> IOSPlatform:
    assert isinstance(self.platform, IOSPlatform)
    return self.platform

  @override
  def _resolve_binary(
      self,
      path: pth.AnyPath,
  ) -> tuple[pth.AnyPath, pth.AnyPath]:
    return path, path

  @override
  def _extract_version(self) -> SafariVersion:
    return SafariVersion.parse(f"Safari {self.platform.version_str}")

  @override
  def _setup_cache_dir(self) -> pth.AnyPath | None:
    return None

  @override
  def start(self, session: BrowserSessionRunGroup) -> None:
    super().start(session)
    self._log_browser_start(self._get_browser_flags_for_session(session))
    # /wda/apps/launch only activates an already running Safari, so terminate
    # it first to start every session from a fresh process.
    try:
      self.ios_platform.wda.terminate_app(self.BUNDLE_ID)
    except (WDAError, OSError) as e:
      logging.debug("Safari not running before launch: %s", e)
    self.ios_platform.wda.launch_app(self.BUNDLE_ID)
    self._is_running = True

  @override
  def show_url(
      self,
      url: str,
      target: WindowTarget = WindowTarget.SELF,
  ) -> None:
    if target != WindowTarget.SELF:
      raise NotImplementedError(
          f"{type(self).__name__}.show_url does not support target {target}")
    logging.debug("SafariWdaIOS.show_url(%s)", url)
    # WDA's /url endpoint uses iOS system URL scheme deep-linking (openURL:
    # via SpringBoard), which only routes http/https URLs to Safari and fails
    # on about:blank.
    if not url or url == "about:blank":
      return
    self.ios_platform.wda.open_url(url)

  @override
  def js(
      self,
      script: str,
      timeout: dt.timedelta | None = None,
      arguments: Sequence[object] = (),
  ) -> None:
    del script, timeout, arguments
    raise NotImplementedError(
        "JavaScript execution is not supported on iOS Safari via WDA.")

  @override
  def performance_mark(
      self,
      name: str,
      detail: Json = None,
      prefix: str = "crossbench-",
  ) -> None:
    del detail
    logging.debug("%s: skipping performance_mark: %s%s", self, prefix, name)

  @override
  def force_quit(self) -> None:
    if not self._is_running:
      return
    logging.info("SafariWdaIOS.force_quit()")
    try:
      self.ios_platform.wda.terminate_app(self.BUNDLE_ID)
    except (WDAError, OSError) as e:
      logging.warning("Failed to terminate Safari on iOS: %s", e)
    self._is_running = False
