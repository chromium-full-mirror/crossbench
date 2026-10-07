# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.helper import fs_helper
from crossbench.probes.chromium_probe import ChromiumProbe
from crossbench.probes.probe import ProbeConfigParser, ProbeContext, ProbeKeyT
from crossbench.probes.probe_error import ProbeValidationError
from crossbench.probes.result_location import ResultLocation
from crossbench.str_enum_with_help import StrEnumWithHelp

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.results import ProbeResult, ProbeResultDict
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.run import Run


@enum.unique
class NetLogCaptureMode(StrEnumWithHelp):
  """Capture mode for Chromium NetLog logging."""

  @classmethod
  @override
  def _missing_(cls, value: object) -> NetLogCaptureMode | None:
    value_str = str(value).lower()
    if value_str == "normal":
      return NetLogCaptureMode.DEFAULT
    if value_str == "includesensitive":
      return NetLogCaptureMode.INCLUDE_SENSITIVE
    if value_str == "all":
      return NetLogCaptureMode.EVERYTHING
    return super()._missing_(value)

  DEFAULT = ("default",
             "Logs default set of events, excluding sensitive information.")
  INCLUDE_SENSITIVE = ("include_sensitive",
                       "Includes sensitive data like cookies and credentials.")
  EVERYTHING = ("everything", "Logs all events and transferred socket bytes.")

  @property
  def flag_value(self) -> str:
    if self == NetLogCaptureMode.DEFAULT:
      return "Default"
    if self == NetLogCaptureMode.INCLUDE_SENSITIVE:
      return "IncludeSensitive"
    if self == NetLogCaptureMode.EVERYTHING:
      return "Everything"
    raise ValueError(f"Unknown capture mode: {self}")


class NetLogProbe(ChromiumProbe):
  """
  Chromium-only Probe for capturing internal network activity into a NetLog
  JSON file. The resulting netlog dump can be analyzed with tools like Catapult
  NetLog Viewer.
  """
  NAME: ClassVar[str] = "netlog"
  RESULT_LOCATION: ClassVar[ResultLocation] = ResultLocation.BROWSER

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "capture_mode",
        type=NetLogCaptureMode,
        default=NetLogCaptureMode.DEFAULT,
        help="Capture mode for netlog.")
    return parser

  def __init__(
      self,
      capture_mode: NetLogCaptureMode = NetLogCaptureMode.DEFAULT,
  ) -> None:
    super().__init__()
    self._capture_mode = capture_mode

  @property
  def capture_mode(self) -> NetLogCaptureMode:
    return self._capture_mode

  @property
  @override
  def key(self) -> ProbeKeyT:
    return super().key + (("capture_mode", self._capture_mode),)

  @property
  @override
  def result_path_name(self) -> str:
    return "netlog.json"

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    for flag in ("--log-net-log", "--net-log-capture-mode"):
      if flag in browser.flags:
        raise ProbeValidationError(
            self, f"Browser already has conflicting {flag} flag")

  @override
  def get_context_cls(self) -> type[NetLogProbeContext]:
    return NetLogProbeContext

  @override
  def log_run_result(self, run: Run) -> None:
    self._log_results(run.results)

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    self._log_results(group.results)

  def _log_results(self, result_dict: ProbeResultDict) -> None:
    if self not in result_dict:
      return
    result = result_dict[self]
    if result.is_empty:
      return
    logging.info("-" * 80)
    logging.critical("NetLog results:")
    for file in result.all_files():
      logging.critical("  %s [%s]", file, fs_helper.get_file_size(file))


class NetLogProbeContext(ProbeContext[NetLogProbe]):

  @override
  def setup(self) -> None:
    self.session.extra_flags["--log-net-log"] = str(self.result_path)
    self.session.extra_flags[
        "--net-log-capture-mode"] = self.probe.capture_mode.flag_value

  @override
  def start(self) -> None:
    pass

  @override
  def stop(self) -> None:
    pass

  @override
  def teardown(self) -> ProbeResult:
    if not self.browser_platform.is_file(self.result_path):
      return self.empty_result()
    return self.browser_result(file=(self.result_path,))
