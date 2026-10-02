# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import contextlib
import copy
import dataclasses
import datetime as dt
from typing import TYPE_CHECKING, Any, Iterator, cast

from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.action_runner.action.enums import ReadyState, WindowTarget
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.browser import Browser
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.browsers.settings import Settings
from crossbench.flags.chrome import ChromeFeatures, ChromeFlags
from crossbench.network.base import Network
from crossbench.plt.android_adb import AndroidAdbPlatform

if TYPE_CHECKING:
  import re

  from crossbench.browsers.version import BrowserVersion
  from crossbench.cli.config.secrets import UsernamePassword
  from crossbench.flags.base import FlagsData
  from crossbench.flags.js_flags import JSFlags
  from crossbench.runner.groups.session import BrowserSessionRunGroup


@dataclasses.dataclass(frozen=True)
class JsInvocation:
  result: Any
  script: str | re.Pattern | None = None
  arguments: list[Any] | None = None
  timeout: dt.timedelta | None = None


class MockNetwork(Network):

  @contextlib.contextmanager
  @override
  def open(self: MockNetwork,
           session: BrowserSessionRunGroup) -> Iterator[MockNetwork]:
    with super().open(session):
      assert session.browser.network is self
      yield self
      assert self.is_running


class MockBrowser(Browser, metaclass=abc.ABCMeta):
  MACOS_BIN_NAME: str = ""
  VERSION: str = "100.22.33.44"

  @classmethod
  @abc.abstractmethod
  def mock_app_path(cls, platform: plt.Platform) -> pth.AnyPath:
    pass

  @classmethod
  def setup_fs(cls, fs, platform: plt.Platform = plt.PLATFORM) -> None:
    app_path = cls.mock_app_path(platform)
    macos_bin_name = app_path.stem
    if cls.MACOS_BIN_NAME:
      macos_bin_name = cls.MACOS_BIN_NAME
    cls.setup_bin(fs, app_path, macos_bin_name, platform)

  @classmethod
  def setup_bin(cls,
                fs,
                bin_path: pth.AnyPath,
                macos_bin_name: str,
                platform: plt.Platform = plt.PLATFORM) -> None:
    if platform.is_macos:
      assert bin_path.suffix == ".app"
      bin_path = bin_path / "Contents" / "MacOS" / macos_bin_name
    elif platform.is_win:
      assert bin_path.suffix == ".exe"
    if not platform.exists(bin_path):
      fs.create_file(bin_path)

  @classmethod
  @override
  def default_flags(cls,
                    initial_data: FlagsData = None,
                    milestone: int = 0) -> ChromeFlags:
    return ChromeFlags.for_milestone(initial_data, milestone)

  def __init__(self,
               label: str,
               path: pth.AnyPath | None = None,
               settings: Settings | None = None):
    settings = settings or Settings()
    platform = settings.platform
    path = path or self.mock_app_path(platform)
    self._app_path = path
    if maybe_driver := settings.driver_path:
      assert isinstance(maybe_driver,
                        pth.AnyPath) and platform.exists(maybe_driver)
    super().__init__(label, path, settings=settings)
    self.url_list: list[str] = []
    self.expected_js: list[JsInvocation] = []
    self.expected_is_logged_in: list[UsernamePassword] = []
    self.invoked_js: list[JsInvocation] = []
    self.did_run: bool = False
    self.tab_handler_generator = self._tab_handler_generator()
    self.tab_list: list[int] = [next(self.tab_handler_generator)]
    self._current_url: str = ""
    self._default_js_return = None
    self._performance_marks: list[str] = []
    self._performance_marks_details: list[Any] = []

  def expect_js(
      self,
      expected_js: JsInvocation | None = None,
      result: Any = None,
  ) -> None:
    if not expected_js:
      self.expected_js.append(JsInvocation(result=result))
      return
    self.expected_js.append(expected_js)
    return

  def was_js_invoked(self, script: str) -> bool:
    return any(script is invoked_js.script for invoked_js in self.invoked_js)

  def expect_is_logged_in(self, secret: UsernamePassword) -> None:
    self.expected_is_logged_in.append(secret)

  @override
  def _setup_cache_dir(self) -> pth.AnyPath | None:
    return None

  @override
  def _clear_cache(self, cache_dir: pth.AnyPath | None) -> None:
    del cache_dir
    self._cache_dir = None

  @override
  def start(self, session: BrowserSessionRunGroup) -> None:
    assert not self._is_running
    self._is_running = True
    self.did_run = True

  @override
  def force_quit(self) -> None:
    if not self._is_running:
      return
    self._is_running = False

  @override
  def _extract_version(self) -> BrowserVersion:
    return ChromiumVersion.parse(self.VERSION)

  @override
  def user_agent(self) -> str:
    return f"Mock Browser {self.type_name()}, {self.VERSION}"

  @override
  def show_url(
      self,
      url,
      target: WindowTarget = WindowTarget.SELF,
      ready_state: ReadyState = ReadyState.ANY,
      timeout: dt.timedelta = dt.timedelta(),
  ) -> None:
    self.url_list.append(url)

  def trusted_click(self, selector: str) -> None:
    self.js(
        "const el = document.querySelector(arguments[0]); "
        "if (el) el.click();",
        arguments=[selector])

  @override
  def current_window_id(self) -> str:
    return str(self.tab_list[-1])

  def _tab_handler_generator(self):
    tab_handler = 0
    while True:
      yield tab_handler
      tab_handler += 1

  @override
  def switch_to_new_tab(self) -> None:
    self.tab_list.append(next(self.tab_handler_generator))

  @override
  def js(self, script, timeout: dt.timedelta | None = None, arguments=()):

    self.invoked_js.append(
        JsInvocation(
            result=None, script=script, arguments=arguments, timeout=timeout))

    if self._default_js_return:
      return self._default_js_return

    if self.expected_js is None:
      return None

    assert self.expected_js, ("Not enough expected_js available. "
                              "Please add another expected_js entry for "
                              f"arguments={arguments} \n"
                              f"Script: {script}")
    expectation = self.expected_js.pop(0)

    if expectation.timeout:
      assert expectation.timeout == timeout, (
          f"JS timeout does not match. "
          f"Expected: {expectation.timeout} Got: {timeout}")

    if expected_script := expectation.script:
      if isinstance(expected_script, str):
        result = expected_script == script
      else:
        result = expected_script.fullmatch(script)
      assert result, (f"JS script does not match expectation. "
                      f"Expected: {expected_script} Got: {script}")

    if expectation.arguments:
      assert len(expectation.arguments) == len(arguments), (
          f"Number of JS arguments does not match. "
          f"Expected: {len(expectation.arguments)} Got: {len(arguments)}")

      for expected_argument, argument in zip(
          expectation.arguments, arguments, strict=True):
        assert expected_argument == argument, (
            f"Arguments do not match. "
            f"Expected: {expected_argument} Got: {argument}")

    # Return copies to avoid leaking data between repetitions.
    return copy.deepcopy(expectation.result)

  @override
  def performance_mark(self,
                       name: str,
                       detail: Any = None,
                       prefix: str = "crossbench-") -> None:
    self.performance_marks.append(prefix + name)
    self.performance_marks_details.append(detail)

  @property
  def performance_marks(self) -> list[str]:
    return self._performance_marks

  @property
  def performance_marks_details(self) -> list[Any]:
    return self._performance_marks_details

  @override
  def is_logged_in(self,
                   secret: UsernamePassword,
                   strict: bool = False) -> bool:
    for login in self.expected_is_logged_in:
      if type(login) is type(secret):
        if login.username == secret.username:
          return True
        if strict:
          raise RuntimeError("Secret mismatch")
    return False

  def set_current_url(self, url: str) -> None:
    self._current_url = url

  def set_default_js_return(self, return_val: Any) -> None:
    self._default_js_return = return_val

  @property
  def current_url(self) -> str:
    return self._current_url

  @override
  def _resolve_binary(self,
                      path: pth.AnyPath) -> tuple[pth.AnyPath, pth.AnyPath]:
    if self.platform.is_ios:
      return path, path
    return super()._resolve_binary(path)


def app_root(platform: plt.Platform) -> pth.AnyPath:
  if platform.is_macos:
    return platform.path("/Applications")
  if platform.is_win:
    return platform.path("C:/Program Files")
  return platform.path("/usr/bin")


class MockChromiumBasedBrowser(MockBrowser, metaclass=abc.ABCMeta):

  @override
  def _init_flags(self, settings: Settings) -> ChromeFlags:
    flags = ChromeFlags(settings.flags)
    flags.js_flags.update(settings.js_flags)
    return flags

  @property
  def chrome_flags(self) -> ChromeFlags:
    chrome_flags = cast(ChromeFlags, self.flags)
    assert isinstance(chrome_flags, ChromeFlags)
    return chrome_flags

  @property
  @override
  def js_flags(self) -> JSFlags:
    return self.chrome_flags.js_flags

  @property
  @override
  def features(self) -> ChromeFeatures:
    return self.chrome_flags.features

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED


class MockChromium(MockChromiumBasedBrowser):
  VERSION = "101.22.33.44"

  @classmethod
  def mock_app_binary(cls,
                      platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return platform.path("Chromium.app/Contents/MacOS/Chromium")
    if platform.is_win:
      return platform.path("Google/Chromium/Application/chromium.exe")
    return platform.path("chromium")

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    return app_root(platform) / cls.mock_app_binary(platform)

  @classmethod
  # TODO: enable @override again
  def type_name(cls) -> str:
    return "chromium"

  @classmethod
  # TODO: enable @override again
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.CHROMIUM | BrowserAttributes.CHROMIUM_BASED


class MockChromeBrowser(MockChromiumBasedBrowser, metaclass=abc.ABCMeta):

  @classmethod
  # TODO: enable @override again
  def type_name(cls) -> str:
    return "chrome"

  @classmethod
  # TODO: enable @override again
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED


class MockChromeStable(MockChromeBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Google Chrome.app"
    if platform.is_win:
      return app_root(platform) / "Google/Chrome/Application/chrome.exe"
    return app_root(platform) / "google-chrome"


class MockChromeAndroidStable(MockChromeStable):

  @property
  @override
  def platform(self) -> AndroidAdbPlatform:
    assert isinstance(
        self._platform,
        AndroidAdbPlatform), (f"Invalid platform: {self._platform}")
    return cast(AndroidAdbPlatform, self._platform)

  @override
  def _resolve_binary(self,
                      path: pth.AnyPath) -> tuple[pth.AnyPath, pth.AnyPath]:
    return path, path

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return (BrowserAttributes.CHROME | BrowserAttributes.CHROMIUM_BASED
            | BrowserAttributes.MOBILE)


class MockChromeBeta(MockChromeBrowser):
  VERSION = "101.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Google Chrome Beta.app"
    if platform.is_win:
      return app_root(platform) / "Google/Chrome Beta/Application/chrome.exe"
    return app_root(platform) / "google-chrome-beta"


class MockChromeDev(MockChromeBrowser):
  VERSION = "102.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Google Chrome Dev.app"
    if platform.is_win:
      return app_root(platform) / "Google/Chrome Dev/Application/chrome.exe"
    return app_root(platform) / "google-chrome-unstable"


class MockChromeCanary(MockChromeBrowser):
  VERSION = "103.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Google Chrome Canary.app"
    if platform.is_win:
      return app_root(platform) / "Google/Chrome SxS/Application/chrome.exe"
    return app_root(platform) / "google-chrome-canary"


class MockEdgeBrowser(MockChromiumBasedBrowser, metaclass=abc.ABCMeta):

  @classmethod
  @override
  def type_name(cls) -> str:
    return "edge"

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.EDGE | BrowserAttributes.CHROMIUM_BASED


class MockEdgeStable(MockEdgeBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Microsoft Edge.app"
    if platform.is_win:
      return app_root(platform) / "Microsoft/Edge/Application/msedge.exe"
    return app_root(platform) / "microsoft-edge"


class MockEdgeBeta(MockEdgeBrowser):
  VERSION = "101.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Microsoft Edge Beta.app"
    if platform.is_win:
      return app_root(platform) / "Microsoft/Edge Beta/Application/msedge.exe"
    return app_root(platform) / "microsoft-edge-beta"


class MockEdgeDev(MockEdgeBrowser):
  VERSION = "102.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Microsoft Edge Dev.app"
    if platform.is_win:
      return app_root(platform) / "Microsoft/Edge Dev/Application/msedge.exe"
    return app_root(platform) / "microsoft-edge-dev"


class MockEdgeCanary(MockEdgeBrowser):
  VERSION = "103.22.33.44"

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Microsoft Edge Canary.app"
    if platform.is_win:
      return app_root(platform) / "Microsoft/Edge SxS/Application/msedge.exe"
    return app_root(platform) / "unsupported/msedge-canary"


class MockSafariBrowser(MockBrowser, metaclass=abc.ABCMeta):

  @classmethod
  @override
  def type_name(cls) -> str:
    return "safari"

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.SAFARI

  @property
  @override
  def cache_dir(self) -> pth.AnyPath:
    return self.platform.home() / f"Library/Caches/{self.app_name}"


class MockSafari(MockSafariBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Safari.app"
    if platform.is_win:
      return app_root(platform) / "Unsupported/Safari.exe"
    return platform.path("/unsupported-platform/Safari")


class MockSafariTechnologyPreview(MockSafariBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Safari Technology Preview.app"
    if platform.is_win:
      return app_root(platform) / "Unsupported/Safari Technology Preview.exe"
    return platform.path("/unsupported-platform/Safari Technology Preview")


class MockFirefoxBrowser(MockBrowser, metaclass=abc.ABCMeta):

  @classmethod
  @override
  def type_name(cls) -> str:
    return "firefox"

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return BrowserAttributes.FIREFOX


class MockFirefox(MockFirefoxBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Firefox.app"
    if platform.is_win:
      return app_root(platform) / "Mozilla Firefox/firefox.exe"
    return app_root(platform) / "firefox"


class MockFirefoxDeveloperEdition(MockFirefoxBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Firefox Developer Edition.app"
    if platform.is_win:
      return app_root(platform) / "Firefox Developer Edition/firefox.exe"
    return app_root(platform) / "firefox-developer-edition"


class MockFirefoxNightly(MockFirefoxBrowser):

  @classmethod
  @override
  def mock_app_path(cls, platform: plt.Platform = plt.PLATFORM) -> pth.AnyPath:
    if platform.is_macos:
      return app_root(platform) / "Firefox Nightly.app"
    if platform.is_win:
      return app_root(platform) / "Firefox Nightly/firefox.exe"
    return app_root(platform) / "firefox-trunk"


ALL: tuple[type[MockBrowser], ...] = (
    MockChromeCanary,
    MockChromeDev,
    MockChromeBeta,
    MockChromeStable,
    MockEdgeCanary,
    MockEdgeDev,
    MockEdgeBeta,
    MockEdgeStable,
    MockSafari,
    MockSafariTechnologyPreview,
    MockFirefox,
    MockFirefoxDeveloperEdition,
    MockFirefoxNightly,
)
