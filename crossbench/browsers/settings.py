# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Final

from crossbench import path as pth
from crossbench import plt
from crossbench.browsers.splash_screen import SplashScreen
from crossbench.browsers.viewport import Viewport
from crossbench.cli.config.env import EnvConfig
from crossbench.cli.config.secrets import Secrets
from crossbench.flags.base import Flags, FlagsData
from crossbench.flags.chrome import ChromeFlags
from crossbench.network.live import LiveNetwork

if TYPE_CHECKING:
  from crossbench.browsers.apk_config import ApkConfig
  from crossbench.cli.config.extension import ExtensionConfig
  from crossbench.network.base import Network


class Settings:
  """Container object for browser agnostic settings."""

  def __init__(
      self,
      flags: FlagsData | None = None,
      js_flags: FlagsData | None = None,
      cache_dir: pth.AnyPath | None = None,
      clear_cache_dir: bool = True,
      network: Network | None = None,
      driver_path: pth.AnyPath | None = None,
      viewport: Viewport | None = None,
      splash_screen: SplashScreen | None = None,
      platform: plt.Platform | None = None,
      secrets: Secrets = Secrets(),
      driver_logging: bool = False,
      wipe_system_user_data: bool = False,
      http_request_timeout: dt.timedelta = dt.timedelta(),
      env_config: EnvConfig | None = None,
      extensions: tuple[ExtensionConfig, ...] | None = None,
      apk_config: ApkConfig | None = None,
      browser_version: str | None = None,
      start_browser: bool = True,
  ) -> None:
    self._flags: Final[Flags] = self._convert_flags(flags, "flags")
    self._js_flags: Final[Flags] = self._extract_js_flags(self._flags, js_flags)
    self._cache_dir: Final[pth.AnyPath | None] = cache_dir
    self._clear_cache_dir: Final[bool] = clear_cache_dir
    self._platform: Final[plt.Platform] = platform or plt.PLATFORM
    self._driver_path: Final[pth.AnyPath | None] = driver_path
    self._network: Final[Network] = network or LiveNetwork()
    self._viewport: Viewport = viewport or Viewport.DEFAULT
    if not start_browser:
      if splash_screen and splash_screen is not SplashScreen.NONE:
        raise ValueError(
            "SplashScreen cannot be used when start_browser is False.")
      splash_screen = SplashScreen.NONE
    self._splash_screen: Final[
        SplashScreen] = splash_screen or SplashScreen.DEFAULT
    self._secrets: Final[Secrets] = secrets
    self._driver_logging: Final[bool] = driver_logging
    self._wipe_system_user_data: Final[bool] = wipe_system_user_data
    self._http_request_timeout: Final[dt.timedelta] = http_request_timeout
    self._env_config: Final[EnvConfig] = env_config or EnvConfig.default()
    self._extensions: Final[tuple[ExtensionConfig, ...]] = extensions or ()
    self._apk_config: Final[ApkConfig | None] = apk_config
    self._browser_version: Final[str | None] = browser_version
    self._start_browser: Final[bool] = start_browser

  def _extract_js_flags(self, flags: Flags,
                        js_flags: FlagsData | None) -> Flags:
    if isinstance(flags, ChromeFlags):
      chrome_js_flags = flags.js_flags
      if not js_flags:
        return chrome_js_flags
      if chrome_js_flags:
        raise ValueError(
            f"Ambiguous js-flags: flags.js_flags={chrome_js_flags!r}, "
            f"js_flags={js_flags!r}")
    return self._convert_flags(js_flags, "--js-flags")

  def _convert_flags(self, flags: FlagsData | None, label: str) -> Flags:
    if isinstance(flags, str):
      raise ValueError(f"{label} should be a list, but got: {flags!r}")
    if not flags:
      return Flags()
    if isinstance(flags, Flags):
      return flags
    return Flags(flags)

  @property
  def driver_logging(self) -> bool:
    return self._driver_logging

  @property
  def flags(self) -> Flags:
    return self._flags

  @property
  def js_flags(self) -> Flags:
    return self._js_flags

  @property
  def cache_dir(self) -> pth.AnyPath | None:
    return self._cache_dir

  @property
  def clear_cache_dir(self) -> bool:
    return self._clear_cache_dir

  @property
  def driver_path(self) -> pth.AnyPath | None:
    return self._driver_path

  @property
  def platform(self) -> plt.Platform:
    return self._platform

  @property
  def network(self) -> Network:
    return self._network

  @property
  def secrets(self) -> Secrets:
    return self._secrets

  @property
  def splash_screen(self) -> SplashScreen:
    return self._splash_screen

  @property
  def wipe_system_user_data(self) -> bool:
    return self._wipe_system_user_data

  @property
  def http_request_timeout(self) -> dt.timedelta:
    return self._http_request_timeout

  @property
  def env_config(self) -> EnvConfig:
    return self._env_config

  @property
  def extensions(self) -> tuple[ExtensionConfig, ...]:
    return self._extensions

  @property
  def apk_config(self) -> ApkConfig | None:
    return self._apk_config

  @property
  def browser_version(self) -> str | None:
    return self._browser_version

  @property
  def start_browser(self) -> bool:
    return self._start_browser

  @property
  def viewport(self) -> Viewport:
    return self._viewport

  @viewport.setter
  def viewport(self, value: Viewport) -> None:
    assert self._viewport.is_default
    self._viewport = value
