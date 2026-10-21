# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Iterable, Self

from typing_extensions import override

from crossbench.plt.android_adb import AndroidAdbPlatform
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeContext, \
    ProbeIncompatibleBrowser
from crossbench.probes.probe_context import BaseProbeContext, \
    ProbeSessionContext

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.session import BrowserSessionRunGroup


class LogcatAndroidProbe(Probe):
  """
  Android-only probe to collect logcat traces.
  """
  NAME: ClassVar = "logcat"

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "filterspec",
        type=str,
        is_list=True,
        default=(),
        help="Filter specifications are a series of <tag>[:priority]")
    return parser

  def __init__(self, filterspec: Iterable[str]) -> None:
    super().__init__()
    self._filterspec: Final[tuple[str, ...]] = tuple(filterspec)

  @property
  def filterspec(self) -> tuple[str, ...]:
    return self._filterspec

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    if not browser.platform.is_android:
      raise ProbeIncompatibleBrowser(self, browser, "Only supported on android")

  @override
  def get_context_cls(self) -> type[AndroidLogcatProbeContext]:
    return AndroidLogcatProbeContext

  @override
  def create_session_context(
      self: Self,
      session: BrowserSessionRunGroup) -> AndroidLogcatProbeSessionContext:
    return AndroidLogcatProbeSessionContext(self, session)


class AndroidLogcatProbeContextMixin(BaseProbeContext[LogcatAndroidProbe]):

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._logcat_start_time: str | None = None

  def _get_browser_platform_time(self) -> str:
    return self.browser_platform.sh_stdout("date",
                                           "+%Y-%m-%d %H:%M:%S").rstrip()

  def _log_to_logcat(self, msg: str) -> None:
    self.browser_platform.sh("log", "-t", "crossbench", msg)

  @property
  def browser_platform(self) -> AndroidAdbPlatform:
    browser_platform = super().browser_platform  # type: ignore
    assert isinstance(browser_platform, AndroidAdbPlatform), (
        f"Expected android platform, but got {browser_platform}")
    return browser_platform

  def _capture_logcat_file(self, dest_file: pth.LocalPath) -> None:
    assert self._logcat_start_time, "Missing logcat start time"
    with dest_file.open("w", encoding="utf-8") as f:
      self.browser_platform.sh(
          "logcat",
          "-t",
          self._logcat_start_time + ".000",
          *self.probe.filterspec,
          stdout=f)

  def teardown(self) -> ProbeResult:
    file = self.local_result_path.with_suffix(".txt")
    self._capture_logcat_file(file)
    return self.local_result(txt=(file,))


class AndroidLogcatProbeContext(AndroidLogcatProbeContextMixin,
                                ProbeContext[LogcatAndroidProbe]):

  @override
  def start(self) -> None:
    self._logcat_start_time = self._get_browser_platform_time()
    self._log_to_logcat("logcat probe start")

  @override
  def stop(self) -> None:
    self._log_to_logcat("logcat probe end")


class AndroidLogcatProbeSessionContext(AndroidLogcatProbeContextMixin,
                                       ProbeSessionContext[LogcatAndroidProbe]):

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    path = super().get_default_result_path()
    return path.with_name(f"{path.name}.session")

  @override
  def start(self) -> None:
    self._logcat_start_time = self._get_browser_platform_time()
    self._log_to_logcat("logcat session probe start")

  @override
  def stop(self) -> None:
    self._log_to_logcat("logcat session probe end")
