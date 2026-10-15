# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from typing_extensions import override

import crossbench.path as pth
from crossbench.cli.ui import ui
from crossbench.plt.macos import MacOSPlatform
from crossbench.probes.profiling.context.base import PosixProfilingContext
from crossbench.probes.profiling.enum import TargetMode
from crossbench.probes.xcode_instruments.recorder import XctraceRecorder

if TYPE_CHECKING:
  from crossbench.probes.profiling.system_profiling import ProfilingProbe
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run

_MAC_TRACE_TEMPLATE_PATH: Final[pth.LocalPath] = pth.LocalPath(
    __file__).parents[1] / "time-profile.tracetemplate"

_XPATH_EXPRESSION: Final[str] = (
    "//trace-toc/run/data/table["
    '@category="PointsOfInterest" and @schema="os-signpost"]|'
    '//trace-toc/run/data/table[@schema="cpu-profile"]')
KB = 1024

_STOP_TIMEOUT_S: Final[int] = 60


class MacOSProfilingContext(PosixProfilingContext):

  def __init__(self, probe: ProfilingProbe, run: Run) -> None:
    super().__init__(probe, run)
    assert self.target in (
        TargetMode.SYSTEM_WIDE, TargetMode.RENDERER_PROCESS_ONLY), (
            f"Unsupported profiling mode for Mac: {self.target!s}")
    self._recorder: XctraceRecorder | None = None

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    return super().get_default_result_path().parent / "profile.trace"

  def _start_xctrace(self, pid: int | None = None) -> None:
    browser_platform = self.browser_platform
    assert isinstance(browser_platform, MacOSPlatform)
    self._recorder = XctraceRecorder(
        browser_platform,
        _MAC_TRACE_TEMPLATE_PATH,
        self.result_path,
        attach_pid=pid,
        stop_timeout_s=_STOP_TIMEOUT_S)
    self._recorder.start()

  def start(self) -> None:
    pass

  @override
  def start_story_run(self) -> None:
    super().start_story_run()
    # In theory this could start earlier but we leave it here as the
    # renderer-process mode requires us to run when we are guaranteed
    # to have a renderer available.
    if self.target == TargetMode.SYSTEM_WIDE:
      self._start_xctrace()
    elif self.target == TargetMode.RENDERER_PROCESS_ONLY:
      self._start_xctrace(self.cached_renderer_pid_tid.pid)
    else:
      raise ValueError(f"Invalid target: {self.target}")

  def stop(self) -> None:
    assert self._recorder, "Missing profiling recorder"
    self._recorder.request_stop()

  def teardown(self) -> ProbeResult:
    self.stop_process()
    trace_xml_path = self._export_trace_xml()
    return self.browser_result(
        trace=(self.result_path,), perfetto=(trace_xml_path,))

  def _export_trace_xml(self) -> pth.AnyPath:
    trace_xml_path = self.result_path.with_name("profile.trace.xml")
    with self.run.actions(
        f"Probe {self.probe.name}: Exporting {trace_xml_path.name}",
        verbose=True), ui.spinner():
      self.browser_platform.sh("xctrace", "export", "--input", self.result_path,
                               "--output", trace_xml_path, "--xpath",
                               _XPATH_EXPRESSION)
      if self.browser_platform.file_size(trace_xml_path) < 100 * KB:
        logging.error(
            "Got an empty or very small %s file. "
            "xctrace might not have captured any CPU samples because the "
            "benchmark was too short (it takes a few seconds to attach), "
            "or due to missing system permissions (SIP/Developer Tools).",
            trace_xml_path.name)
      return trace_xml_path

  def stop_process(self) -> None:
    if self._recorder:
      self._recorder.finalize()
