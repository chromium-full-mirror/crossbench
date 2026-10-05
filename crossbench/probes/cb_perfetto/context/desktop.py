# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from crossbench.probes.cb_perfetto.constants import PERFETTO_CONFIG_NAME, \
    PERFETTO_TRACE_NAME
from crossbench.probes.cb_perfetto.context.base import PerfettoProbeContext
from crossbench.probes.cb_perfetto.downloader import PerfettoToolDownloader

if TYPE_CHECKING:
  import subprocess

  from crossbench import path as pth
  from crossbench.plt.types import TupleCmdArgs
  from crossbench.probes.cb_perfetto.perfetto import PerfettoProbe
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run


class DesktopPerfettoProbeContext(PerfettoProbeContext):

  def __init__(self, probe: PerfettoProbe, run: Run) -> None:
    self._tracebox_proc: subprocess.Popen | None = None
    super().__init__(probe, run)
    self._tracebox_bin: pth.AnyPath = self.probe.tracebox_bin

  @override
  def get_browser_config_path(self) -> pth.AnyPath:
    return self.result_path.with_name(PERFETTO_CONFIG_NAME)

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    return self._run.get_default_probe_result_path(
        self._probe).with_name(PERFETTO_TRACE_NAME)

  @override
  def setup(self) -> None:
    self._setup_validate_bin()
    self._tracebox_proc = self._setup_tracebox()
    super().setup()

  @override
  def _setup_validate_bin(self) -> None:
    if not self.browser_platform.which(self._tracebox_bin):
      self._tracebox_bin = PerfettoToolDownloader(
          "tracebox", platform=self.browser_platform).download()
    super()._setup_validate_bin()

  @override
  def teardown(self) -> ProbeResult:
    self._teardown_tracebox()
    return super().teardown()

  def _setup_tracebox(self) -> subprocess.Popen:
    return self.browser_platform.popen(self._tracebox_bin, "traced",
                                       "traced_probes")

  def _teardown_tracebox(self) -> None:
    if self._tracebox_proc:
      self._tracebox_proc.terminate()
      self._tracebox_proc = None

  @property
  @override
  def perfetto_cmd(self) -> TupleCmdArgs:
    return (self._tracebox_bin, "perfetto")
