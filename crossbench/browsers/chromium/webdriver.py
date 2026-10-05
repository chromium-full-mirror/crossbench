# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import logging
import re
import subprocess
import time
from typing import TYPE_CHECKING, Any, Final, Sequence

from immutabledict import immutabledict
from selenium.webdriver.chromium import webdriver as chromium_webdriver
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
from typing_extensions import override

from crossbench import exception
from crossbench import hjson as cb_hjson
from crossbench import path as pth
from crossbench.browsers.chromium.base import ChromiumBaseMixin
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.browsers.chromium_based.webdriver import ChromiumBasedWebDriver
from crossbench.cli.config.apk_helper import CHROME_APK_HELPER_NAMES
from crossbench.cli.config.secrets import GoogleUsernamePassword
from crossbench.cli.ui import ui
from crossbench.helper import wait
from crossbench.parse import NumberParser
from crossbench.plt.android_adb import AndroidAdbPlatform
from crossbench.plt.base import SubprocessError
from crossbench.plt.bin import Binaries
from crossbench.plt.chromeos_ssh import ChromeOsSshPlatform
from crossbench.plt.linux_ssh import LinuxSshPlatform

if TYPE_CHECKING:
  import datetime as dt

  from selenium import webdriver
  from selenium.webdriver.chromium.options import ChromiumOptions
  from selenium.webdriver.chromium.service import ChromiumService

  from crossbench.browsers.apk_config import ApkConfig
  from crossbench.browsers.settings import Settings
  from crossbench.browsers.version import BrowserVersion
  from crossbench.cli.config.secrets import UsernamePassword
  from crossbench.plt.base import Platform
  from crossbench.plt.process_meminfo import ProcessMeminfo
  from crossbench.runner.groups.session import BrowserSessionRunGroup

# Android is high-tech and reads chrome flags from an app-specific file.
# TODO: extend support to more than just chrome.
_FLAG_ROOT: pth.AnyPosixPath = pth.AnyPosixPath("/data/local/tmp/")
FLAGS_WEBLAYER: pth.AnyPosixPath = _FLAG_ROOT / "weblayer-command-line"
FLAGS_WEBVIEW: pth.AnyPosixPath = _FLAG_ROOT / "webview-command-line"
FLAGS_CONTENT_SHELL: pth.AnyPosixPath = (
    _FLAG_ROOT / "content-shell-command-line")
FLAGS_CHROME: pth.AnyPosixPath = _FLAG_ROOT / "chrome-command-line"


class ChromiumWebDriver(ChromiumBaseMixin, ChromiumBasedWebDriver):

  @override
  def _create_driver(
      self, options: ChromiumOptions,
      service: ChromiumService) -> chromium_webdriver.ChromiumDriver:
    return chromium_webdriver.ChromiumDriver(
        browser_name="chromium",
        vendor_prefix="goog",
        options=options,
        service=service)


def install_apk(platform: AndroidAdbPlatform, apk_config: ApkConfig | None,
                browser_package: str) -> bool:
  if not apk_config:
    logging.debug("Android APK install skipped (no apk_config)")
    return False
  if not browser_package:
    raise ValueError("Android APK installation requires a browser package name")
  adb = platform.adb
  with exception.annotate(f"Installing Android APK {browser_package}"):
    logging.debug("Android APK install: apk=%s package=%s", apk_config.path,
                  browser_package)
    if apk_config.reinstall:
      adb.uninstall(browser_package, missing_ok=True)
    elif adb.is_installed(browser_package):
      logging.info("Skipping APK reinstall for %s", browser_package)
      return False
    else:
      logging.info("Package %s missing; installing", browser_package)
    host_apk_path: pth.LocalPath = platform.host_path(apk_config.path)
    logging.info("Installing APK %s on %s", host_apk_path, platform)
    adb.install(
        host_apk_path,
        allow_downgrade=apk_config.allow_downgrade,
        modules=apk_config.modules)
    if not adb.is_installed(browser_package):
      raise ValueError(
          f"Did not install {browser_package} with {host_apk_path}. "
          "Possibly mismatching browser package name.")
  return True


class ChromiumWebDriverAndroid(ChromiumBasedWebDriver):
  MIN_SET_WINDOW_RECT_VERSION: Final[ChromiumVersion] = ChromiumVersion(
      (153, 0, 7994, 0))

  def __init__(self,
               label: str,
               path: pth.AnyPath | None = None,
               settings: Settings | None = None) -> None:
    assert settings, "Android browser needs custom settings and platform"
    self._installed_android_package: str | None = None
    self._chrome_command_line_path: pth.AnyPath = FLAGS_CHROME
    self._previous_command_line_contents: str | None = None
    self._needs_restore_chrome_flags: bool = False
    super().__init__(label, path, settings)
    self._android_package: Final[str] = self._lookup_android_package(self.path)
    if not self._android_package:
      raise RuntimeError("Could not find matching adb package for "
                         f"{self.path} on {self.platform}")

  def _lookup_android_package(self, path: pth.AnyPath) -> str:
    return self.platform.app_path_to_package(path)

  @override
  def _setup_binary(self) -> None:
    super()._setup_binary()
    self._setup_android_apk()
    self._setup_binary_permissions()

  def _setup_android_apk(self) -> None:
    if install_apk(self.platform, self.settings.apk_config,
                   self.android_package):
      self._installed_android_package = self.android_package

  def _uninstall_android_apk(self) -> None:
    # Uninstall only if this run installed the APK.
    if not self._installed_android_package:
      return
    try:
      logging.info("Uninstalling APK package %s",
                   self._installed_android_package)
      self.platform.adb.uninstall(
          self._installed_android_package, missing_ok=True)
    except SubprocessError as e:
      logging.warning("Error uninstalling APK: %s", e)
    finally:
      self._installed_android_package = None

  @property
  def android_package(self) -> str:
    return self._android_package

  @property
  @override
  def platform(self) -> AndroidAdbPlatform:
    assert isinstance(
        self._platform,
        AndroidAdbPlatform), (f"Invalid platform: {self._platform}")
    return self._platform

  @override
  def _resolve_binary(self,
                      path: pth.AnyPath) -> tuple[pth.AnyPath, pth.AnyPath]:
    return path, path

  UNSUPPORTED_FLAGS: tuple[str, ...] = (
      "--disable-sync",
      "--window-size",
      "--window-position",
  )

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> webdriver.Remote:
    self.adb_force_stop()
    if session.browser.wipe_system_user_data or self.clear_cache_dir:
      self.adb_force_clear()
      self._setup_binary_permissions()
    self._backup_chrome_flags()
    driver = self._start_chromedriver(session, driver_path)
    self._dismiss_any_os_permission_prompts()
    return driver

  # Some Android OEMs display permission prompts that we cannot turn off via adb
  # (e.g. because the permissions can't be granted in advance) or device
  # settings. However, these prompts interfere with UI automation, so we attempt
  # to dismiss these here instead.
  def _dismiss_any_os_permission_prompts(self) -> None:
    focused_window = None
    try:
      for _ in wait.wait_with_backoff(10):
        try:
          for _ in wait.wait_with_backoff(1):
            focused_window = self.platform.adb.focused_window()
            if focused_window and self.android_package in focused_window:
              return
        except TimeoutError:
          if focused_window:
            logging.debug("Attempting to dismiss unexpected focused window %s",
                          focused_window or "None")
            self.platform.adb.shell("input", "keyevent", "KEYCODE_ESCAPE")
    except TimeoutError:
      logging.warning("Couldn't validate app focus, focused window: %s",
                      focused_window or "None")

  def _backup_chrome_flags(self) -> None:
    assert self._previous_command_line_contents is None, (
        "Got unexpected previous flags: {self._previous_command_line_contents}")
    self._previous_command_line_contents = self._read_device_flags()
    assert not self._needs_restore_chrome_flags, "Invalid flag restore state."
    self._needs_restore_chrome_flags = True
    atexit.register(self._restore_chrome_flags)

  def _read_device_flags(self) -> str | None:
    if not self.platform.exists(self._chrome_command_line_path):
      return None
    return self.platform.cat(self._chrome_command_line_path)

  def adb_force_stop(self) -> None:
    self.platform.adb.force_stop(self.android_package)
    # Prevent background Chrome from intercepting the devtools abstract socket
    if self.android_package != "com.android.chrome":
      self.platform.adb.force_stop("com.android.chrome")

  def adb_force_clear(self) -> None:
    self.platform.adb.force_clear(self.android_package)

  def force_quit(self) -> None:
    try:
      try:
        super().force_quit()
      finally:
        self.adb_force_stop()
    finally:
      try:
        self._restore_chrome_flags()
      finally:
        self._uninstall_android_apk()

  @override
  def meminfo(self, timeout: dt.timedelta) -> list[ProcessMeminfo]:
    return self.platform.process_meminfo(self.android_package, timeout)

  @override
  def dump_java_heap(self, label: str, trace_buffer_size_kb: int,
                     timeout: dt.timedelta) -> pth.AnyPath:
    return self.platform.dump_java_heap(self.android_package, label,
                                        trace_buffer_size_kb, timeout)

  def _restore_chrome_flags(self) -> None:
    atexit.unregister(self._restore_chrome_flags)
    if not self._needs_restore_chrome_flags:
      return
    current_flags = self._read_device_flags()
    if current_flags != self._previous_command_line_contents:
      logging.warning("%s: flags file changed during run", self)
      logging.debug("before: %s", self._previous_command_line_contents)
      logging.debug("current: %s", current_flags)
    if self._previous_command_line_contents is None:
      logging.debug("%s: deleting chrome flags file: %s", self,
                    self._chrome_command_line_path)
      self.platform.rm(self._chrome_command_line_path, missing_ok=True)
    else:
      logging.debug("%s: restoring previous flags file contents in %s", self,
                    self._chrome_command_line_path)
      self.platform.write_text(self._chrome_command_line_path,
                               self._previous_command_line_contents)
    self._needs_restore_chrome_flags = False
    self._previous_command_line_contents = None

  @override
  def _create_options(self, session: BrowserSessionRunGroup,
                      args: Sequence[str]) -> ChromiumOptions:
    options: ChromiumOptions = super()._create_options(session, args)
    options.binary_location = ""
    options.add_experimental_option("androidPackage", self.android_package)
    options.add_experimental_option("androidDeviceSerial",
                                    self.platform.adb.serial_id)
    # Always pass this to prevent Chromedriver
    # from attempting (and failing) to clear data.
    # However, this option is only supported on M98+ (crrev.com/c/3243690).
    if not self.clear_cache_dir or (session.browser.version and
                                    session.browser.version.major >= 98):
      options.add_experimental_option("androidKeepAppDataDir", True)
    return options

  def _setup_binary_permissions(self) -> None:
    try:
      self.platform.adb.grant_permissions(self.android_package)
    except SubprocessError as e:
      logging.warning("Error setting app permissions: %s", e)

  def _supports_set_window_rect(self) -> bool:
    # Chromedriver still hardcodes the 'setWindowRect' capability to false for
    # Android devices (crbug.com/534416988), so check the browser version is at
    # or above the version that landed crrev.com/c/8084624.
    return self.version >= self.MIN_SET_WINDOW_RECT_VERSION

  @override
  def _setup_window(self) -> None:
    if self.viewport.is_maximized:
      self.maximize_window()
    elif (not self.viewport.is_default and self.viewport.has_size and
          self._supports_set_window_rect()):
      self._private_driver.set_window_position(self.viewport.x, self.viewport.y)
      self._private_driver.set_window_size(self.viewport.width,
                                           self.viewport.height)
    else:
      logging.debug("%s: Skipping viewport settings %s on %s",
                    type(self).__name__, self.viewport, self)

  @override
  def maximize_window(self) -> None:
    if self._supports_set_window_rect():
      super().maximize_window()
      return
    self._maximize_window_uiautomator()

  def _maximize_window_uiautomator(self) -> None:
    try:
      with self.platform.uiautomator_device(root_device=False) as device:
        # TODO(b/417165220): Update to standard Android OS window management
        # once available. UIAutomator widget hierarchy search is a placeholder.
        buttons = device.ui.find(resourceIdMatches="(?i).*maximize_window")
        if not buttons:
          logging.debug("Could not find maximize button via UIAutomator.")
          return

        for button in reversed(buttons):
          desc = button.get("contentDescription", "").lower()
          if "maximize" in desc:
            center = button.get("visibleCenter")
            if center and "x" in center and "y" in center:
              logging.info(
                  "Found maximize button for active window at (%d, %d), "
                  "clicking.",
                  center["x"],
                  center["y"],
              )
              device.ui.click(center["x"], center["y"])
              time.sleep(1)
              return

        logging.info("No maximize button found or already maximized.")
        return
    except subprocess.SubprocessError as e:
      logging.warning("Could not maximize Android window: %s", e)


class LocalChromiumWebDriverAndroid(ChromiumWebDriverAndroid):
  """
  Custom version that uses a locally built bundle wrapper.
  https://chromium.googlesource.com/chromium/src/+/HEAD/docs/android_build_instructions.md
  """

  @classmethod
  def is_apk_helper(cls, path: pth.AnyPath | None) -> bool:
    if not path or len(path.parts) == 1:
      return False
    return path.name in CHROME_APK_HELPER_NAMES

  def __init__(self,
               label: str,
               path: pth.AnyPath | None = None,
               settings: Settings | None = None) -> None:
    assert settings, "Android browser needs custom settings and platform"
    assert path, "Got invalid empty path"
    if not self.is_apk_helper(path):
      raise ValueError(
          "Locally built chrome version does not work with packaged apks.")
    if settings.apk_config:
      raise ValueError(f"{self.type_name()} cannot be used with "
                       "an additional apk_config settings.")
    self._package_info: Final[immutabledict[str,
                                            Any]] = self._parse_package_info(
                                                settings.platform, path)
    super().__init__(label, path, settings)

  @override
  def _lookup_android_package(self, path: pth.AnyPath) -> str:
    return self._package_info["Package name"]

  # TODO: enable override again.
  # @override
  def _extract_version(self) -> BrowserVersion:
    return self.version_cls().parse(self._package_info["versionName"])

  def _parse_package_info(self, platform: Platform,
                          path: pth.AnyPath) -> immutabledict[str, Any]:
    output = platform.host_platform.sh_stdout(
        path, "package-info").rstrip().splitlines()
    package_info = {}
    for line in output:
      key, value = line.split(": ")
      package_info[key] = cb_hjson.loads_unique_keys(value)
    return immutabledict(package_info)

  @override
  def _setup_android_apk(self) -> None:
    with ui.spinner(title=f"Installing {self.path.name} on {self.platform}"):
      self.host_platform.sh_stdout(self.path, "install",
                                   f"--device={self.platform.serial_id}")


class AutoForwardingRemoteWebDriver(RemoteWebDriver):
  """
  Wraps RemoteWebDriver, but starts, stops, and forwards ports for chromedriver.
  """

  # Example ss output line (with whitespace shortened):
  # LISTEN 0 5 127.0.0.1:34595 0.0.0.0:* users:(("chromedriver",pid=80388,fd=8))
  SS_CHROMEDRIVER_LINE_RE: Final[re.Pattern] = re.compile(
      r"^LISTEN\s+"
      # Recv-Q
      r"\d+\s+"
      # Send-Q
      r"\d+\s+"
      # Local Address:Port
      r"127.0.0.1:(?P<port>\d+)\s+"
      # Peer Address:Port
      r"\S+\s+"
      # Process
      r"users:\(\("
      r"\"chromedriver\",pid=\d+,fd=\d+"
      r"\)\)\s*$",
      re.MULTILINE)

  _forward_port: int
  _chromedriver: subprocess.Popen | None

  def __init__(
      self,
      platform: LinuxSshPlatform,
      chromedriver_path: pth.AnyPath | None,
      options: ChromiumOptions,
  ) -> None:
    self._platform: Final[LinuxSshPlatform] = platform
    with exception.annotate("Starting chromedriver"):
      self._killall_chromedriver()
      self._chromedriver = platform.popen(
          chromedriver_path or Binaries.CHROMEDRIVER.resolve(platform),
          stdin=subprocess.PIPE)
      driver_port = self._wait_for_driver_port()
      self._forward_port = platform.ports.forward(0, driver_port)
      logging.info(
          "Chromedriver listening on %d forwarded through local port %d",
          driver_port, self._forward_port)
    super().__init__(f"http://127.0.0.1:{self._forward_port}", options=options)

  def quit(self) -> None:
    try:
      super().quit()
    finally:
      self._stop_remote_driver()

  def _stop_remote_driver(self) -> None:
    if not self._chromedriver:
      return
    try:
      self._chromedriver.terminate()
      self._chromedriver = None
    finally:
      try:
        # Closing the ssh connection doesn't terminate chromedriver, so kill it.
        self._killall_chromedriver()
      finally:
        if forward_port := self._forward_port:
          self._platform.ports.stop_forward(forward_port)
          self._forward_port = 0

  def _killall_chromedriver(self) -> None:
    self._platform.killall("chromedriver")

  def _wait_for_driver_port(self) -> int:
    for _ in wait.wait_with_backoff(10):
      listening = self._platform.sh_stdout("ss", "-HOlntp")
      if m := self.SS_CHROMEDRIVER_LINE_RE.search(listening):
        return NumberParser.port_number(m[1], "driver port")
    raise RuntimeError("not reached")


class ChromiumWebDriverSsh(ChromiumBasedWebDriver):

  @property
  @override
  def platform(self) -> LinuxSshPlatform:
    assert isinstance(self._platform,
                      LinuxSshPlatform), (f"Invalid platform: {self._platform}")
    return self._platform

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> RemoteWebDriver:
    del driver_path
    args = self._get_browser_flags_for_session(session)
    options = self._create_options(session, args)
    platform = self.platform
    host = platform.host
    port = platform.port
    if port == 0:
      return AutoForwardingRemoteWebDriver(
          platform, self._settings.driver_path, options=options)
    driver = RemoteWebDriver(f"http://{host}:{port}", options=options)
    return driver


class ChromiumWebDriverChromeOsSsh(ChromiumBasedWebDriver):

  @property
  @override
  def platform(self) -> ChromeOsSshPlatform:
    assert isinstance(
        self._platform,
        ChromeOsSshPlatform), (f"Invalid platform: {self._platform}")
    return self._platform

  UNSUPPORTED_FLAGS: tuple[str, ...] = (
      "--user-data-dir",
      "--window-size",
      "--window-position",
  )

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> RemoteWebDriver:
    del driver_path
    platform = self.platform
    host = platform.host
    port = platform.port
    args: tuple[str, ...] = self._get_browser_flags_for_session(session)
    # TODO(spadhi): correctly handle flags:
    #   1. decide which flags to pass to chrome vs chromedriver
    #   2. investigate irrelevant / unsupported flags on ChromeOS
    #   3. filter out and pass the chrome flags to the debugging session below
    #   4. pass the remaining flags to RemoteWebDriver options
    google_login = session.browser.secrets.google
    if google_login:
      dbg_port = platform.create_debugging_session(
          username=google_login.username,
          password=google_login.password,
          browser_flags=args)
    else:
      dbg_port = platform.create_debugging_session(browser_flags=args)
    options = self._create_options(session, args)
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{dbg_port}")

    if port == 0:
      return AutoForwardingRemoteWebDriver(
          platform, self._settings.driver_path, options=options)
    return RemoteWebDriver(f"http://{host}:{port}", options=options)

  # On ChromeOS, the system profile is the same as the browser profile.
  def is_logged_in(self,
                   secret: UsernamePassword,
                   strict: bool = False) -> bool:
    if secret.username == self.platform.username and isinstance(
        secret, GoogleUsernamePassword):
      return True
    if not strict:
      return False
    raise RuntimeError("Login of non-primary Google accounts not supported")
