# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import json
import logging
import shlex
import subprocess
from typing import TYPE_CHECKING, Any, Sequence

import websocket
from typing_extensions import override

from crossbench.action_runner.action.enums import WindowTarget
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.browsers.chromium_based.chromium_based import ChromiumBased
from crossbench.flags.chrome import ChromeFlags
from crossbench.plt.android_adb import AndroidAdbPlatform
from crossbench.plt.base import SubprocessError

if TYPE_CHECKING:
  import datetime as dt

  from crossbench import path as pth
  from crossbench.browsers.settings import Settings
  from crossbench.flags.base import FlagsT
  from crossbench.runner.groups.session import BrowserSessionRunGroup
  from crossbench.types import JsonDict


class CdpAndroidBrowser(ChromiumBased):
  """Android Chrome browser controlled via Chrome DevTools Protocol over ADB."""

  UNSUPPORTED_FLAGS: tuple[str, ...] = (
      "--disable-sync",
      "--window-size",
      "--window-position",
  )

  # On other platforms, chromedriver sets these flags. We are bypassing
  # chromedriver here, so we set these ourselves.
  CHROMEDRIVER_FLAGS: dict[str, str | None] = {
      "--disable-popup-blocking": None,
      "--enable-automation": None,
      "--allow-pre-commit-input": None,
      "--disable-features": "IgnoreDuplicateNavs,Prewarm",
      "--disable-background-networking": None,
      "--disable-background-timer-throttling": None,
      "--disable-backgrounding-occluded-windows": None,
      "--disable-fre": None,
      "--enable-remote-debugging": None,
      "--remote-allow-origins": "*",
  }

  def __init__(
      self,
      label: str,
      path: pth.AnyPath,
      settings: Settings | None = None,
  ) -> None:
    super().__init__(label=label, path=path, settings=settings)
    self.flags.update(self.CHROMEDRIVER_FLAGS)
    self._previous_command_line_contents: str | None = None
    self._needs_restore_chrome_flags: bool = False
    self._has_started_in_session: bool = False

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return (super().attributes()
            | BrowserAttributes.CHROME
            | BrowserAttributes.MOBILE
            | BrowserAttributes.REMOTE)

  @classmethod
  @override
  def type_name(cls) -> str:
    return "cdp-android"

  @classmethod
  @override
  def version_cls(cls) -> type[ChromiumVersion]:
    return ChromiumVersion

  @override
  def _resolve_binary(self,
                      path: pth.AnyPath) -> tuple[pth.AnyPath, pth.AnyPath]:
    return path, path

  @property
  @override
  def platform(self) -> AndroidAdbPlatform:
    assert isinstance(self._platform, AndroidAdbPlatform)
    return self._platform

  @property
  def android_package(self) -> str:
    return self.platform.app_path_to_package(self.path)

  @property
  def _chrome_command_line_path(self) -> pth.AnyPath:
    return self.platform.path("/data/local/tmp/chrome-command-line")

  def adb_force_stop(self) -> None:
    self.platform.adb.force_stop(self.android_package)
    # Prevent background Chrome from intercepting the devtools abstract socket
    if self.android_package != "com.android.chrome":
      self.platform.adb.force_stop("com.android.chrome")

  def adb_force_clear(self) -> None:
    self.platform.adb.force_clear(self.android_package)

  def _backup_chrome_flags(self) -> None:
    assert self._previous_command_line_contents is None, (
        f"Got unexpected previous flags: {self._previous_command_line_contents}"
    )
    self._previous_command_line_contents = self._read_device_flags()
    assert not self._needs_restore_chrome_flags, "Invalid flag restore state."
    self._needs_restore_chrome_flags = True
    atexit.register(self._restore_chrome_flags)

  def _read_device_flags(self) -> str | None:
    if not self.platform.exists(self._chrome_command_line_path):
      return None
    return self.platform.cat(self._chrome_command_line_path)

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
      logging.debug(
          "%s: deleting chrome flags file: %s",
          self,
          self._chrome_command_line_path,
      )
      self.platform.rm(self._chrome_command_line_path, missing_ok=True)
    else:
      logging.debug(
          "%s: restoring previous flags file contents in %s",
          self,
          self._chrome_command_line_path,
      )
      self.platform.write_text(
          self._chrome_command_line_path,
          self._previous_command_line_contents,
      )
    self._needs_restore_chrome_flags = False
    self._previous_command_line_contents = None

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

  def _setup_binary_permissions(self) -> None:
    try:
      self.platform.adb.grant_permissions(self.android_package)
    except SubprocessError as e:
      logging.warning("Error setting app permissions: %s", e)

  def _set_debug_app(self) -> None:
    self.platform.sh("am", "set-debug-app", "--persistent",
                     self.android_package)

  @override
  def start(self, session: BrowserSessionRunGroup) -> None:
    super().start(session)
    self.adb_force_stop()
    if not self._has_started_in_session:
      if (session and
          session.browser.wipe_system_user_data) or self.clear_cache_dir:
        self.adb_force_clear()
        self._setup_binary_permissions()
      self._has_started_in_session = True
    self._backup_chrome_flags()
    self._set_debug_app()
    flags = tuple(
        sorted(
            self._get_browser_flags_for_session(session) if session else tuple(
                self._filter_flags_for_run(self.flags.copy()))))
    self._log_browser_start(flags)
    flags_str = f"_ {shlex.join(flags)}"
    self.platform.write_text(self._chrome_command_line_path, flags_str)
    self.platform.chmod(self._chrome_command_line_path, 0o666)
    package_name = self.android_package
    self.platform.sh(
        "am",
        "start",
        "-W",
        "-n",
        f"{package_name}/com.google.android.apps.chrome.Main",
        stdout=subprocess.DEVNULL,
    )
    self.platform.start_devtools()
    self._is_running = True

  @override
  def force_quit(self) -> None:
    try:
      super().force_quit()
      try:
        self.platform.stop_devtools()
      except (websocket.WebSocketException, OSError, SubprocessError) as e:
        logging.debug("Error disconnecting DevTools client: %s", e)
      self.adb_force_stop()
    finally:
      self._restore_chrome_flags()
      self._is_running = False

  @override
  def teardown(self) -> None:
    self._has_started_in_session = False
    try:
      self._restore_chrome_flags()
    finally:
      super().teardown()

  def _send_cdp(self, method: str, params: JsonDict | None = None) -> JsonDict:
    return self.platform.send_cdp_command(method, params)

  @override
  def show_url(self,
               url: str,
               target: WindowTarget = WindowTarget.SELF) -> None:
    if target == WindowTarget.SELF:
      self._send_cdp("Page.navigate", {"url": url})
    elif target in (
        WindowTarget.NEW_TAB,
        WindowTarget.NEW_WINDOW,
        WindowTarget.BLANK,
    ):
      self.platform.switch_to_new_tab(url)
    else:
      raise RuntimeError(f"Unexpected target: {target}")

  @override
  def switch_to_new_tab(self) -> None:
    self.platform.switch_to_new_tab()

  @override
  def js(
      self,
      script: str,
      timeout: dt.timedelta | None = None,
      arguments: Sequence[object] = (),
  ) -> Any:
    del timeout
    args_json = json.dumps(arguments)
    expression = f"(function(){{{script}}}).apply(window, {args_json})"
    res = self._send_cdp("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
    })
    result = res.get("result")
    assert isinstance(result, dict), f"Invalid Runtime.evaluate result: {res}"
    if "exceptionDetails" in result:
      details = result["exceptionDetails"]
      assert isinstance(details, dict), f"Invalid exceptionDetails: {details}"
      error_msg = str(details)
      if isinstance(exception_dict := details.get("exception"), dict):
        error_msg = str(exception_dict.get("description", details))
      raise ValueError(f"Could not execute JS: {error_msg}")
    inner_result = result.get("result")
    assert isinstance(inner_result, dict), f"Invalid RemoteObject: {result}"
    return inner_result.get("value")

  @property
  @override
  def current_url(self) -> str:
    return str(self.js("return window.location.href;"))
