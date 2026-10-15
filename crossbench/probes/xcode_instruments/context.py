# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from typing_extensions import override

from crossbench.plt.ios import IOSPlatform
from crossbench.plt.macos import MacOSPlatform
from crossbench.probes.probe_context import ProbeContext
from crossbench.probes.profiling.enum import TargetMode
from crossbench.probes.xcode_instruments.recorder import XctraceRecorder

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.probes.results import ProbeResult
  from crossbench.probes.xcode_instruments.xcode_instruments import \
      XcodeInstrumentsProbe
  from crossbench.runner.run import Run


class XcodeInstrumentsContext(ProbeContext["XcodeInstrumentsProbe"]):
  """Records an Instruments `.trace` with `xctrace record` on the host Mac."""

  def __init__(self, probe: XcodeInstrumentsProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._recorder: XctraceRecorder | None = None
    self._target: Final[TargetMode] = self.probe.target

  @property
  def target(self) -> TargetMode:
    return self._target

  @property
  def _host(self) -> MacOSPlatform:
    # xctrace always runs on the host Mac, even for iOS device recordings.
    host_platform = self.host_platform
    assert isinstance(host_platform, MacOSPlatform)
    return host_platform

  def get_attach_pid(self) -> int | None:
    match self._target:
      case TargetMode.SYSTEM_WIDE:
        return None
      case TargetMode.BROWSER_APP_ONLY:
        if pid := self.browser.pid:
          return pid
        raise ValueError(
            "Couldn't perform browser-app tracing. Maybe this browser "
            "doesn't support this? Choose a different target mode.")
      case TargetMode.RENDERER_PROCESS_ONLY:
        if pid := self.browser.get_renderer_pid():
          return pid
        raise ValueError(
            "Couldn't perform renderer-only tracing. Maybe this browser "
            "doesn't support this? Choose a different target mode.")
      case _:
        raise ValueError(f"Invalid target: {self._target}")

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    result_dir = super().get_default_result_path()
    self._host.mkdir(result_dir)
    return result_dir / "trace.trace"

  @override
  def start(self) -> None:
    pass

  @override
  def start_story_run(self) -> None:
    super().start_story_run()
    device_udid: str | None = None
    if self.browser_platform.is_ios:
      browser_platform = self.browser_platform
      assert isinstance(browser_platform, IOSPlatform)
      device_udid = browser_platform.udid
    attach_pid = self.get_attach_pid()
    self._recorder = XctraceRecorder(
        self._host,
        self.probe.template,
        self.local_result_path,
        attach_pid=attach_pid,
        device_udid=device_udid)
    self._recorder.start()

  @override
  def stop(self) -> None:
    if self._recorder:
      self._recorder.request_stop()

  @override
  def teardown(self) -> ProbeResult:
    if self._recorder:
      self._recorder.finalize()
    return self.local_result(file=(self.local_result_path,))
