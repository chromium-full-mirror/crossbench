# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Self

from typing_extensions import override

from crossbench.browsers.chromium_based.chromium_based import ChromiumBased
from crossbench.parse import PathParser
from crossbench.probes.probe import Probe, ProbeConfigParser, \
    ProbeIncompatibleBrowser, ProbeKeyT
from crossbench.probes.probe_error import ProbeValidationError
from crossbench.probes.profiling.enum import TargetMode
from crossbench.probes.result_location import ResultLocation
from crossbench.probes.xcode_instruments.context import XcodeInstrumentsContext

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.runner.run import Run


class XcodeInstrumentsProbe(Probe):
  """Records an Xcode Instruments trace with `xctrace`."""
  NAME: ClassVar = "xcode_instruments"
  # xctrace always runs on the host Mac, even when recording an iOS device, so
  # the resulting .trace bundle lives on the host.
  RESULT_LOCATION: ClassVar = ResultLocation.LOCAL

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "template",
        type=PathParser.existing_file_path,
        required=True,
        help=("Path to the Instruments .tracetemplate to record with. The "
              "template determines which instruments are recorded. Required: "
              "there is no default template."))
    parser.add_argument(
        "target",
        type=TargetMode,
        choices=(
            TargetMode.SYSTEM_WIDE,
            TargetMode.BROWSER_APP_ONLY,
            TargetMode.RENDERER_PROCESS_ONLY,
        ),
        default=TargetMode.SYSTEM_WIDE,
        help="What process(es) should be traced.")
    return parser

  def __init__(self,
               template: pth.LocalPath,
               target: TargetMode = TargetMode.SYSTEM_WIDE) -> None:
    super().__init__()
    self._template: Final[pth.LocalPath] = template
    self._target: Final[TargetMode] = target

  @property
  def template(self) -> pth.LocalPath:
    return self._template

  @property
  def target(self) -> TargetMode:
    return self._target

  def start_profiling_after_setup(self, target: TargetMode) -> bool:
    return target == TargetMode.RENDERER_PROCESS_ONLY

  @property
  @override
  def key(self) -> ProbeKeyT:
    return (*super().key, ("template", str(self._template)),
            ("target", str(self._target)))

  @override
  def attach(self, browser: Browser) -> None:
    super().attach(browser)
    if browser.attributes().is_chromium_based:
      if self.start_profiling_after_setup(self._target):
        assert isinstance(browser, ChromiumBased)
        browser.flags.enable_benchmarking_api()

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    browser_platform = browser.platform
    if not (browser_platform.is_macos or browser_platform.is_ios):
      raise ProbeIncompatibleBrowser(self, browser,
                                     "only supported on macOS and iOS")
    host_platform = browser.host_platform
    if not host_platform.is_macos:
      raise ProbeIncompatibleBrowser(self, browser,
                                     "xctrace recording requires a macOS host")
    if not host_platform.which("xctrace"):
      raise ProbeValidationError(self, "Please install Xcode to use xctrace")
    supported_targets = (TargetMode.SYSTEM_WIDE, TargetMode.BROWSER_APP_ONLY,
                         TargetMode.RENDERER_PROCESS_ONLY)
    if self._target not in supported_targets:
      raise ProbeIncompatibleBrowser(
          self, browser, f"Unsupported target mode: {self._target}. "
          f"Should be one of {supported_targets}.")

  @override
  def create_context(self, run: Run) -> XcodeInstrumentsContext:
    return XcodeInstrumentsContext(self, run)
