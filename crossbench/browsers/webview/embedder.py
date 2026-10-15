# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import collections
import logging
import os
import shlex
from typing import TYPE_CHECKING, Final, MutableMapping, MutableSet, \
    Sequence, cast

from immutabledict import immutabledict
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chromium.webdriver import ChromiumDriver
from typing_extensions import override

from crossbench.browsers.webview.webview import Webview
from crossbench.cli.ui import ui

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.benchmarks.embedder.embedder_benchmark import \
      EmbedderBenchmark
  from crossbench.browsers.settings import Settings
  from crossbench.runner.groups.session import BrowserSessionRunGroup
  from crossbench.types import Json

EMBEDDER_SHORT_NAME_TO_PACKAGE: Final[immutabledict[str, str]] = immutabledict({
    "googlequicksearchbox":
        "com.google.android.googlequicksearchbox",
    "velvet":
        "com.google.android.googlequicksearchbox",
    "maitier":
        "com.google.android.libraries.ads.mobile.maitier.testapps.webview",
    "webview_test_app":
        "com.google.android.libraries.ads.mobile.maitier.testapps.webview",
    "webview_embedder":
        "org.chromium.webview_shell",
})


class WebviewEmbedder(Webview):

  _INSTALLED_APK_PATHS: Final[MutableMapping[str, MutableSet[pth.AnyPath]]] = (
      collections.defaultdict(set))

  def __init__(self,
               label: str,
               path: pth.AnyPath | None = None,
               settings: Settings | None = None) -> None:
    super().__init__(label, path, settings)
    self._session: BrowserSessionRunGroup | None = None

  @override
  def start(self, session: BrowserSessionRunGroup) -> None:
    # Start is a no-op. Embedder activity will be started by the Benchmark.
    # Webview will be started by the Embedder. Driver will be started
    # by the ProbeContext. We do, however, need to run custom setup commands,
    # set up browser flags, and kill any currently running Embedder app
    # instances to make sure it picks up the new flags when started by the
    # Benchmark.
    session_benchmark = cast("EmbedderBenchmark", session.benchmark)
    # Push files from host to device before device setup.
    for (source, destination) in session_benchmark.embedder_push_files:
      self.platform.push(source, destination)
    if setup_command_config := session_benchmark.embedder_setup_command_config:
      for command in setup_command_config.commands:
        self.platform.sh(*command.command)
    self._session = session
    atexit.register(self._teardown)
    self._backup_chrome_flags()
    args = self._get_browser_flags_for_session(session)
    logging.debug("%s: setting flags file contents in %s", self,
                  self._chrome_command_line_path)
    self.platform.write_text(self._chrome_command_line_path,
                             shlex.join(("webview", *args)))
    self.adb_force_stop()
    self._log_browser_start(args)
    self._is_running = True

  @override
  def quit(self) -> None:
    # External code that started the driver is responsible for shutting it down.
    self._is_running = False
    self._restore_chrome_flags()
    self._teardown_cache_dir()
    self._teardown()

  def _teardown(self) -> None:
    atexit.unregister(self._teardown)
    if self._session:
      session_benchmark = cast("EmbedderBenchmark", self._session.benchmark)
      if teardown_config := session_benchmark.embedder_teardown_command_config:
        for command in teardown_config.commands:
          self.platform.sh(*command.command)
      self._session = None

  @override
  def _start_driver(self, session: BrowserSessionRunGroup,
                    driver_path: pth.AnyPath) -> ChromiumDriver:
    options = self._create_options(session, [])
    service = webdriver.ChromeService(executable_path=os.fspath(driver_path))
    driver = webdriver.Chrome(options=options, service=service)
    return driver

  def _init_driver(self, session: BrowserSessionRunGroup) -> None:
    self._private_driver = self._start_driver(session, self.driver_path)
    self._set_driver_timeouts(session)

  def start_driver(self, session: BrowserSessionRunGroup) -> ChromiumDriver:
    self._init_driver(session)
    # Take a snapshot of all handles as we might need to restart driver
    handles = self._private_driver.window_handles[:]
    for handle in handles:
      self._private_driver.switch_to.window(handle)
      try:
        # Check tab responsiveness
        _ = self._private_driver.current_url
      except Exception:  # noqa: BLE001
        # This is probably the wrong tab. Restart the driver and try another.
        self._private_driver.quit()
        self._init_driver(session)
        continue
      else:
        # This tab works, we can return the driver.
        assert isinstance(self._private_driver, ChromiumDriver)
        return self._private_driver
    # We tried all tabs and none worked.
    raise RuntimeError("Failed to attach driver")

  @override
  def _create_options(self, session: BrowserSessionRunGroup,
                      args: Sequence[str]) -> ChromeOptions:
    options = ChromeOptions()
    options.add_experimental_option("androidPackage", self.android_package)
    session_benchmark = cast("EmbedderBenchmark", session.benchmark)
    if process_name := session_benchmark.embedder_process_name:
      options.add_experimental_option("androidProcess",
                                      f"{self.android_package}:{process_name}")
    options.add_experimental_option("androidUseRunningApp", True)
    return options

  @override
  def _log_browser_start(self,
                         args: tuple[str, ...],
                         driver_path: pth.AnyPath | None = None) -> None:
    super()._log_browser_start(args, driver_path)
    logging.info("📱 STARTING BROWSER Embedder: %s",
                 self.platform.app_version(self.android_package))

  @override
  def _lookup_android_package(self, path: pth.AnyPath) -> str:
    path_str = str(path)
    if path_str in EMBEDDER_SHORT_NAME_TO_PACKAGE:
      return EMBEDDER_SHORT_NAME_TO_PACKAGE[path_str]
    if path.suffix == ".apk":
      path_str_lower = path_str.lower()
      for short_name, package_name in EMBEDDER_SHORT_NAME_TO_PACKAGE.items():
        if short_name in path_str_lower:
          return package_name
    return super()._lookup_android_package(path)

  @override
  def _setup_binary(self) -> None:
    if self.path.suffix == ".apk":
      device_id = self.platform.serial_id
      if self.path not in self._INSTALLED_APK_PATHS[device_id]:
        title = f"Installing {self.path.name} on {self.platform}"
        with ui.spinner(title=title):
          self.platform.adb.uninstall(self.android_package, missing_ok=True)
          self.platform.adb.install(self.path)
        self._INSTALLED_APK_PATHS[device_id].add(self.path)
    super()._setup_binary()

  @override
  def performance_mark(self,
                       name: str,
                       detail: Json = None,
                       prefix: str = "crossbench-") -> None:
    # The driver, and Webview instance might not exist when this is called
    # See also comments above on .start()
    logging.debug("%s: skipping performance_mark: %s%s", self, prefix, name)
