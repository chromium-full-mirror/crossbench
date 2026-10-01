# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import base64
import datetime as dt
import logging
import os
from typing import TYPE_CHECKING, Any, Final, Iterable, Sequence, TextIO

import requests
import selenium.common.exceptions
import urllib3
from selenium.webdriver.chromium.options import ChromiumOptions
from selenium.webdriver.chromium.service import ChromiumService
from selenium.webdriver.chromium.webdriver import ChromiumDriver
from typing_extensions import override

from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.chromium.driver_finder import ChromeDriverFinder, \
    DriverNotFoundError
from crossbench.browsers.chromium.version import ChromeDriverVersion, \
    ChromiumVersion
from crossbench.browsers.chromium_based import helper
from crossbench.browsers.chromium_based.chromium_based import ChromiumBased
from crossbench.browsers.chromium_based.devtools_tracer import DevToolsTracer
from crossbench.browsers.webdriver import WebDriverBrowser
from crossbench.flags.chrome import ChromeFlags
from crossbench.helper import wait
from crossbench.helper.url_helper import get
from third_party.protoc.gen.protos.perfetto.common.track_event_descriptor_pb2 import \
    TrackEventDescriptor

if TYPE_CHECKING:
  import re

  from selenium import webdriver

  from crossbench import path as pth
  from crossbench.browsers.version import BrowserVersion
  from crossbench.flags.base import FlagsT
  from crossbench.runner.groups.session import BrowserSessionRunGroup


class ChromiumBasedWebDriver(
    WebDriverBrowser, ChromiumBased, metaclass=abc.ABCMeta):

  WEB_DRIVER_OPTIONS: type[ChromiumOptions] = ChromiumOptions
  WEB_DRIVER_SERVICE: type[ChromiumService] = ChromiumService
  UNSUPPORTED_FLAGS: tuple[str, ...] = ()

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._script_id_kwargs_by_window_id: Final[dict[str, Any]] = {}
    self._tracer: DevToolsTracer | None = None
    self._stdout_log_file: TextIO | None = None

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return (BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED
            | BrowserAttributes.WEBDRIVER)

  def use_local_chromedriver(self) -> bool:
    return self.version.major == 0 or self.is_locally_compiled()

  def is_locally_compiled(self) -> bool:
    return bool(self.local_build_dir())

  def local_build_dir(self) -> pth.LocalPath | None:
    if path := helper.find_build_dir(self.app_path, self.host_platform):
      return self.host_platform.local_path(path)
    return None

  def _execute_cdp_cmd(self, driver: webdriver.Remote, cmd: str,
                       cmd_args: dict) -> Any:
    return driver.execute("executeCdpCommand", {
        "cmd": cmd,
        "params": cmd_args,
    })["value"]

  def perfetto_categories(self) -> TrackEventDescriptor:
    descriptor = TrackEventDescriptor()
    response = self._execute_cdp_cmd(self._private_driver,
                                     "Tracing.getTrackEventDescriptor", {})
    if descriptor_b64 := response.get("descriptor", ""):
      data = base64.b64decode(descriptor_b64)
      descriptor.ParseFromString(data)
      return descriptor

    # Fallback to get plain category names without descriptions or tags.
    res = self._execute_cdp_cmd(self._private_driver, "Tracing.getCategories",
                                {})
    for c in res.get("categories", []):
      cat = descriptor.available_categories.add()
      cat.name = c
    return descriptor

  @override
  def _filter_flags_for_run(self, flags: FlagsT) -> FlagsT:
    assert isinstance(flags, ChromeFlags)
    chrome_flags: ChromeFlags = flags
    for flag in self.UNSUPPORTED_FLAGS:
      if flag not in chrome_flags:
        continue
      flag_value = chrome_flags.pop(flag, None)
      logging.debug("Chromium: Removed unsupported flag: %s=%s", flag,
                    flag_value)
    return chrome_flags  # type: ignore

  @override
  def _find_driver_pid(self) -> None:
    service = getattr(self._private_driver, "service", None)
    if not service:
      return
    self._driver_pid = service.process.pid
    candidates: list[int] = []
    for child in self.platform.process_children(self._driver_pid):
      if str(child["exe"]) == str(self.path):
        candidates.append(child["pid"])
    if len(candidates) == 1:
      self._pid = candidates[0]
      return
    if self.platform.is_local:
      capabilities = self._private_driver.capabilities
      if isinstance(capabilities, dict) and isinstance(
          pid := capabilities.get("goog:processID"), int):
        self._pid = pid
        return
    logging.debug(
        "Could not find unique browser process for webdriver: %s, got %s",
        self, candidates)

  @override
  def _find_driver(self) -> pth.AnyPath:
    if self._driver_path:
      return self.driver_path
    finder = ChromeDriverFinder(self)
    assert self.app_path, "Missing browser app_path"
    if self.use_local_chromedriver():
      return finder.find_local_build()
    try:
      return finder.download()
    except DriverNotFoundError as original_download_error:
      logging.debug(
          "Could not download chromedriver, "
          "falling back to finding local build: %s", original_download_error)
      try:
        return finder.find_local_build()
      except DriverNotFoundError as e:
        logging.debug("Could not find fallback chromedriver: %s", e)
        raise original_download_error from e

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> webdriver.Remote:
    return self._start_chromedriver(session, driver_path)

  def _start_chromedriver(self, session: BrowserSessionRunGroup,
                          driver_path: pth.AnyPath) -> ChromiumDriver:
    assert not self._is_running
    assert self.log_file, "Missing log file"
    args = self._get_browser_flags_for_session(session)
    options = self._create_options(session, args)

    self._log_browser_start(args, driver_path)
    service_args: list[str] = []
    if self._settings.driver_logging:
      service_args += [
          "--verbose",
          f"--log-path={os.fspath(self._setup_driver_log_file())}",
      ]

    adb_port = os.environ.get("ANDROID_ADB_SERVER_PORT")
    if adb_port and adb_port.isdigit():
      service_args += ["--adb-port=" + adb_port]

    assert self._stdout_log_file is None, (
        " stdout_log_file should have been unset, but got "
        f"{self._stdout_log_file}")
    # On desktop platforms service logs contain browser stdout, hence the name.
    self._stdout_log_file = self.log_file.with_stem("browser.stdout").open("w+")
    service = self.WEB_DRIVER_SERVICE(
        executable_path=os.fspath(driver_path),
        service_args=service_args,
        log_output=self._stdout_log_file,
    )
    if hasattr(service, "log_file"):
      # TODO: remove once we upgrade the min selenium version
      # Workaround for older selenium versions which ignore the log_file kwarg.
      service.log_file = self._stdout_log_file

    # TODO: support remote platforms
    driver = self._create_driver(options, service)
    # Prevent debugging overhead.
    self._execute_cdp_cmd(driver, "Runtime.setMaxCallStackSizeToCapture",
                          {"size": 0})
    return driver

  def _create_options(self, session: BrowserSessionRunGroup,
                      args: Sequence[str]) -> ChromiumOptions:
    assert not self._is_running
    options: ChromiumOptions = self.WEB_DRIVER_OPTIONS()
    options.set_capability("browserVersion", str(self.version.major))
    # Don't wait for document-ready.
    options.set_capability("pageLoadStrategy", "none")
    if ("--allow-background-interventions" in args and
        not self.platform.is_chromeos):
      # chromedriver will silently add additional args that interfere
      # with background optimizations. Disable those args when the test is
      # run with background interventions allowed.
      options.add_experimental_option("excludeSwitches", [
          "disable-background-timer-throttling",
          "disable-backgrounding-occluded-windows",
      ])
    for arg in args:
      options.add_argument(arg)
    options.binary_location = os.fspath(self.path)
    session.setup_selenium_options(options)
    return options

  @abc.abstractmethod
  def _create_driver(self, options: ChromiumOptions,
                     service: ChromiumService) -> ChromiumDriver:
    pass

  @override
  def _startup_error_hints(self) -> list[str]:
    hints = super()._startup_error_hints()
    if self.is_locally_compiled():
      local_build_dir = self.local_build_dir()
      assert local_build_dir is not None, "expected local_build_dir to be set"
      hints.append(
          helper.get_chromedriver_build_instructions(
              local_build_dir, self.platform.is_android))
    return hints

  @override
  def _validate_driver_version(self) -> None:
    error_message = None
    if self.is_local and helper.is_build_dir(
        self.platform.local_path(self.app_path.parent), self.platform):
      error_message = self._validate_locally_built_driver(
          self.platform.local_path(self.driver_path))
    else:
      error_message = self._validate_any_driver_version(self.driver_path)
    if error_message:
      raise RuntimeError("\n".join(error_message))

  def _validate_locally_built_driver(
      self, driver_path: pth.LocalPath) -> Iterable[str] | None:
    # TODO: migrate to version object on the browser
    browser_version: BrowserVersion = self.version
    assert isinstance(browser_version, ChromiumVersion)
    driver_version = ChromeDriverVersion.parse(
        self.platform.app_version(driver_path))
    if browser_version.parts == driver_version.parts:
      return None
    local_build_dir = self.local_build_dir()
    assert local_build_dir is not None, "expected local_build_dir to be set"
    return (f"Chromedriver version mismatch: driver={driver_version.parts_str} "
            f"browser={browser_version.parts_str} ({self}).",
            helper.get_chromedriver_build_instructions(
                local_build_dir, self.platform.is_android))

  def _validate_any_driver_version(
      self, driver_path: pth.AnyPath) -> Iterable[str] | None:
    raw_version_str = self.host_platform.sh_stdout(driver_path, "--version")
    driver_version = ChromeDriverVersion.parse(raw_version_str)
    if driver_version.major == self.version.major:
      return None
    return (f"Chromedriver version mismatch: driver={driver_version} "
            f"browser={self.version} ({self})",)

  @override
  def clear_cache(self) -> None:
    self._execute_cdp_cmd(self._private_driver, "Network.clearBrowserCache", {})
    self._execute_cdp_cmd(self._private_driver, "Network.clearBrowserCookies",
                          {})

  @override
  def run_script_on_new_document(self, script: str) -> None:
    window_id = self.current_window_id()
    if window_id in self._script_id_kwargs_by_window_id:
      self._execute_cdp_cmd(self._private_driver,
                            "Page.removeScriptToEvaluateOnNewDocument",
                            self._script_id_kwargs_by_window_id[window_id])
    self._script_id_kwargs_by_window_id[window_id] = self._execute_cdp_cmd(
        self._private_driver, "Page.addScriptToEvaluateOnNewDocument",
        {"source": script})

  @override
  def quit(self) -> None:
    self._script_id_kwargs_by_window_id.clear()
    super().quit()

  @override
  def current_window_id(self) -> str:
    return str(self._private_driver.current_window_handle)

  @override
  def switch_window(self, window_id: str) -> None:
    self._private_driver.switch_to.window(window_id)

  @override
  def switch_tab(
      self,
      title: re.Pattern | None = None,
      url: re.Pattern | None = None,
      tab_index: int | None = None,
      relative_tab_index: int | None = None,
      timeout: dt.timedelta = dt.timedelta(seconds=0),
  ) -> str:
    assert not (tab_index is not None and relative_tab_index is not None)
    driver = self._private_driver
    original_handle = driver.current_window_handle
    for _ in wait.wait_with_backoff(timeout):
      # Search through other handles starting from current_window_handle + 1
      try:
        i = driver.window_handles.index(original_handle)
      except ValueError as e:
        raise RuntimeError("Original starting tab no longer exists") from e

      if relative_tab_index is not None:
        tab_index = (i + relative_tab_index) % len(driver.window_handles)
      if tab_index is not None:
        handles = [driver.window_handles[tab_index]]
      else:
        # Start searching with the tab after the current tab.
        handles = driver.window_handles[i + 1:] + driver.window_handles[:i + 1]

      for handle in handles:
        driver.switch_to.window(handle)
        if title is not None and title.search(driver.title) is None:
          continue
        if url is not None and url.search(driver.current_url) is None:
          continue
        return handle
    error = "No new tab found"
    if title is not None:
      error += f" with title matching {title.pattern!r}"
    if url is not None:
      error += f" with url matching {url.pattern!r}"
    if tab_index is not None:
      error += f" with tab_index matching {tab_index}"
    if relative_tab_index is not None:
      error += f" with relative_tab_index matching {tab_index}"
    raise RuntimeError(error)

  @override
  def close_tab(
      self,
      title: re.Pattern | None = None,
      url: re.Pattern | None = None,
      tab_index: int | None = None,
      relative_tab_index: int | None = None,
      timeout: dt.timedelta = dt.timedelta(seconds=0),
  ) -> None:
    driver = self._private_driver
    original_handle = driver.current_window_handle
    tab_to_close = original_handle

    if title or url or (tab_index is not None):
      tab_to_close = self.switch_tab(title, url, tab_index, relative_tab_index,
                                     timeout)

    driver.close()

    if tab_to_close != original_handle:
      driver.switch_to.window(original_handle)
    else:
      # When a tab closes itself, arbitrarily default
      # to switching to the first tab.
      driver.switch_to.window(driver.window_handles[0])

  @override
  def close_all_tabs(self) -> None:
    driver = self._private_driver
    try:
      current_handle = driver.current_window_handle
    except selenium.common.exceptions.WebDriverException as e:
      logging.warning("%s: Could not get current window handle: %s", self, e)
      current_handle = None

    try:
      handles = driver.window_handles
    except selenium.common.exceptions.WebDriverException as e:
      logging.warning("%s: Could not get window handles: %s", self, e)
      handles = []

    for handle in handles:
      if handle == current_handle:
        continue
      try:
        driver.switch_to.window(handle)
        driver.close()
      except (selenium.common.exceptions.WebDriverException,
              urllib3.exceptions.MaxRetryError) as e:
        logging.warning("%s: Got errors while closing tab %s: %s", self, handle,
                        e)

    try:
      # Closing every tab will cause the browser to exit.
      # As a workaround navigate the final tab to about:blank.
      if current_handle:
        driver.switch_to.window(current_handle)
      elif driver.window_handles:
        driver.switch_to.window(driver.window_handles[-1])
      self.show_url("about:blank")
    except (selenium.common.exceptions.WebDriverException,
            urllib3.exceptions.MaxRetryError) as e:
      logging.warning(
          "%s: Got errors while navigating final tab to about:blank: %s", self,
          e)

  @property
  def current_url(self) -> str:
    return self._private_driver.current_url

  # TODO(crbug.com/428953697): Consider unifying BrowserProfilingProbe with
  # other similar ones.
  def start_profiling(self) -> None:
    assert isinstance(self._private_driver, ChromiumDriver)
    self._tracer = DevToolsTracer(self._private_driver)
    self._tracer.start()

  def stop_profiling(self) -> Any:
    assert isinstance(self._private_driver, ChromiumDriver)
    assert self._tracer is not None
    output = self._tracer.end()
    self._tracer = None
    return output

  @override
  def _close_browser_window(self, driver: webdriver.Remote) -> None:
    if self.platform.is_android:
      super()._close_browser_window(driver)
      return
    # Calling driver.close() on the last tab invokes ChromeDriver's
    # ExecuteClose -> session->chrome->Quit(), which immediately terminates
    # the browser process on Windows (TerminateProcess) before background
    # startup tracing (Perfetto) can finish flushing large trace buffers.
    # Sending CDP Browser.close initiates a graceful browser shutdown on the
    # UI thread without triggering ChromeDriver's immediate process kill.
    self._execute_cdp_cmd(driver, "Browser.close", {})

  @override
  def force_quit(self) -> None:
    try:
      super().force_quit()
    finally:
      if self._stdout_log_file:
        self._stdout_log_file.close()
        self._stdout_log_file = None

  @property
  def debugger_address(self) -> str:
    capabilities = self._private_driver.capabilities
    if "goog:chromeOptions" not in capabilities:
      raise RuntimeError("Browser does not support remote debugging. "
                         f"Capabilities: {capabilities}")
    if "debuggerAddress" not in capabilities["goog:chromeOptions"]:
      raise RuntimeError(
          "Browser was not started with remote debugging enabled. "
          f"Capabilities: {capabilities['goog:chromeOptions']}")

    return self._private_driver.capabilities["goog:chromeOptions"][
        "debuggerAddress"]

  @property
  def ws_endpoint(self) -> str:
    try:
      json_response = get(
          f"http://{self.debugger_address}/json/version", retry=3).json()
      if "webSocketDebuggerUrl" not in json_response:
        raise RuntimeError("Could not find webSocketDebuggerUrl in response. "
                           f"Response: {json_response}")

      return json_response["webSocketDebuggerUrl"]
    except requests.exceptions.RequestException as e:
      raise RuntimeError("Could not get target list from "
                         f"http://{self.debugger_address}/json/version") from e
