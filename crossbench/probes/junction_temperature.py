# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import subprocess
from typing import TYPE_CHECKING, ClassVar, Final, Self

from typing_extensions import override

import crossbench.path as pth
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeContext, \
    ProbeIncompatibleBrowser, ProbeKeyT
from crossbench.str_enum_with_help import StrEnumWithHelp

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run

_TMU_PATH: Final[pth.AnyPath] = pth.AnyPath(
    "/sys/kernel/metrics/thermal/tr_by_group/tmu")
_STATS_RESET_PATH: Final[pth.AnyPath] = _TMU_PATH / "stats_reset"
_STATS_PATH: Final[pth.AnyPath] = _TMU_PATH / "stats"


@enum.unique
class JunctionTemperatureMode(StrEnumWithHelp):
  """Measurement mode for JunctionTemperatureProbe."""
  RUN = ("run", "Measure the whole run")
  STORY = ("story", "Measure only the core story run")


_JtMode = JunctionTemperatureMode


class JunctionTemperatureProbe(Probe):
  """
  Android-only probe to collect Thermal Residency Stats, i.e. metrics
  detailing how much time (residency) the device's junction temperature (the
  internal silicon temperature of the chip itself) spends within specific
  temperature brackets.
  """
  NAME: ClassVar[str] = "junction_temperature"

  @classmethod
  def stats_reset_path(cls) -> pth.AnyPath:
    return _STATS_RESET_PATH

  @classmethod
  def stats_path(cls) -> pth.AnyPath:
    return _STATS_PATH

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "mode",
        type=_JtMode,
        default=_JtMode.STORY,
        help="Timeframe during which TMU statistics are collected.")
    return parser

  def __init__(self, mode: _JtMode = _JtMode.STORY) -> None:
    super().__init__()
    self._mode: Final[_JtMode] = mode

  @property
  def mode(self) -> _JtMode:
    return self._mode

  @property
  @override
  def key(self) -> ProbeKeyT:
    return super().key + (("mode", self.mode),)

  @property
  @override
  def result_path_name(self) -> str:
    return f"{self.name}.txt"

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    if not browser.platform.is_android:
      raise ProbeIncompatibleBrowser(self, browser, "Only supported on android")

    # Verify the device supports su to run commands as root, which is required
    # to read the TMU stats file.
    try:
      output = browser.platform.sh_stdout("su", "0", "id")
    except (subprocess.SubprocessError, RuntimeError) as e:
      raise ProbeIncompatibleBrowser(self, browser,
                                     "Can't use root on this device.") from e
    if "uid=0(root)" not in output:
      raise ProbeIncompatibleBrowser(self, browser,
                                     "Can't use root on this device.")

    # Verify the thermal metrics directory exists on the device.
    # For simplicity's sake, we assume all relevant files exist under this
    # directory and don't check explicitly.
    try:
      browser.platform.sh_stdout("su", "0", "test", "-d", _TMU_PATH)
    except (subprocess.SubprocessError, RuntimeError) as e:
      raise ProbeIncompatibleBrowser(self, browser, "TMU path missing.") from e

  @override
  def get_context_cls(self) -> type[JunctionTemperatureProbeContext]:
    return JunctionTemperatureProbeContext


class JunctionTemperatureProbeContext(ProbeContext[JunctionTemperatureProbe]):

  def __init__(self, probe: JunctionTemperatureProbe, run: Run) -> None:
    super().__init__(probe, run)

  def _run_rooted_cmd(self, cmd: str) -> str:
    return self.browser_platform.sh_stdout("su", "0", "sh", "-c", cmd)

  def _reset_tmu_stats(self) -> None:
    self._run_rooted_cmd(f"echo 1 > {_STATS_RESET_PATH}")

  def _collect_and_write_stats(self) -> None:
    tmu_stats = ""
    try:
      tmu_stats = self._run_rooted_cmd(f"cat {_STATS_PATH}")
    except (subprocess.SubprocessError, OSError, RuntimeError) as e:
      tmu_stats = f"Could not read TMU stats: {e}"

    file = self.local_result_path
    with file.open("w", encoding="utf-8") as f:
      f.write(tmu_stats)

  @override
  def setup(self) -> None:
    super().setup()
    if self.probe.mode == _JtMode.RUN:
      self._reset_tmu_stats()

  @override
  def start(self) -> None:
    pass

  @override
  def start_story_run(self) -> None:
    super().start_story_run()
    if self.probe.mode == _JtMode.STORY:
      self._reset_tmu_stats()

  @override
  def stop_story_run(self) -> None:
    super().stop_story_run()
    if self.probe.mode == _JtMode.STORY:
      self._collect_and_write_stats()

  @override
  def stop(self) -> None:
    pass

  @override
  def teardown(self) -> ProbeResult:
    if self.probe.mode == _JtMode.RUN:
      self._collect_and_write_stats()
    if not self.local_result_path.exists():
      return self.empty_result()
    return self.local_result(txt=(self.local_result_path,))
