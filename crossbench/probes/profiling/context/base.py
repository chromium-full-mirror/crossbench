# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import logging
from functools import cached_property
from typing import TYPE_CHECKING, Final, Sequence, cast

from typing_extensions import override

from crossbench.cli.ui import ui
from crossbench.plt.bin import Binaries
from crossbench.plt.posix import PosixPlatform
from crossbench.probes.cb_perfetto import traceconv
from crossbench.probes.probe_context import ProbeContext
from crossbench.probes.profiling.enum import TargetMode
from crossbench.probes.trace_processor.context.symbolizing import \
    ChromiumSymbolPathFinder
from crossbench.probes.v8.log import V8LogProbe

if TYPE_CHECKING:
  import subprocess

  from crossbench import path as pth
  from crossbench.plt.base import Platform
  from crossbench.probes.profiling.system_profiling import ProfilingProbe
  from crossbench.runner.run import Run


class ProfilingContext(ProbeContext, metaclass=abc.ABCMeta):

  def __init__(self, probe: ProfilingProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._profiling_process: subprocess.Popen | None = None
    self._story_ready: bool = False
    self._target: Final[TargetMode] = self.probe.resolve_target_mode(
        run.browser)
    assert self._target is not TargetMode.AUTO, "unexpected target mode"

  @property
  def target(self) -> TargetMode:
    return self._target

  def start_profiling_after_setup(self) -> bool:
    return self.probe.start_profiling_after_setup(self._target)

  def setup_v8_log_path(self) -> None:
    if any(isinstance(probe, V8LogProbe) for probe in self.run.probes):
      return
    # Try to get a bit a cleaner output folder by redirecting v8 logging output
    # to v8.log.
    v8_log_dir = self.result_path.parent / V8LogProbe.NAME / "v8.log"
    self.browser_platform.mkdir(v8_log_dir)
    self.session.extra_js_flags["--logfile"] = str(v8_log_dir)

  @override
  def start_story_run(self) -> None:
    self._story_ready = True

  @override
  def stop_story_run(self) -> None:
    if self.start_profiling_after_setup():
      self._verify_current_renderer_pid()

  def _verify_current_renderer_pid(self) -> None:
    original_render_pid, _ = self.cached_renderer_pid_tid
    current_renderer_pid, _ = self._get_renderer_pid_tid()
    if current_renderer_pid != original_render_pid:
      logging.error(
          "Renderer PID changed from %d to %d during the run. "
          "This can happen when navigating URLs during profiling.",
          original_render_pid, current_renderer_pid)

  @cached_property
  def cached_renderer_pid_tid(self) -> tuple[int, int]:
    """Cached renderer PID / TID"""
    return self._get_renderer_pid_tid()

  def _get_renderer_pid_tid(self) -> tuple[int, int]:
    assert self._story_ready, (
        "Fetching renderer PID/TID before the story is loaded could lead to "
        "the wrong PID/TID being used. This should never happen TM!")
    renderer_pid = self.browser.get_renderer_pid()
    renderer_main_tid = self.browser.get_renderer_main_tid()
    if renderer_pid is None or renderer_main_tid is None:
      error_message = (
          "Unable to get Renderer PID/TID from browser. "
          "Is the browser binary a sufficiently new version? "
          "For RENDERER_MAIN_ONLY/RENDERER_PROCESS_ONLY profiling, at least "
          "https://chromium-review.googlesource.com/c/chromium/src/+/5374765 "
          "is required.")
      logging.error(error_message)
      raise ValueError(error_message)
    return renderer_pid, renderer_main_tid


class PosixProfilingContext(ProfilingContext):

  def __init__(self, probe: ProfilingProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._run_traceconv: Final[bool] = self.probe.run_traceconv(run.browser)
    self._traceconv_bin: pth.AnyPath | None = None

  @property
  @override
  def browser_platform(self) -> PosixPlatform:
    return cast(PosixPlatform, super().browser_platform)

  @property
  def traceconv_platform(self) -> Platform:
    return self.host_platform

  @property
  def run_traceconv(self) -> bool:
    """Returns whether traceconv export is enabled and active for this run."""
    return self._run_traceconv

  @property
  def traceconv_bin(self) -> pth.AnyPath | None:
    return self._traceconv_bin

  def setup_traceconv(self) -> None:
    if not self._run_traceconv:
      return
    self._traceconv_bin = Binaries.TRACE_PROCESSOR_SHELL.search(
        self.traceconv_platform)
    assert self._traceconv_bin is not None, (
        f"Probe {self.probe.name}: traceconv binary missing")

  def _get_traceconv_symbol_dirs(self) -> tuple[pth.AnyPath, ...]:
    if symbols_path := ChromiumSymbolPathFinder(self.browser).path:
      return (symbols_path,)
    return ()

  def _get_traceconv_env(self) -> dict[str, str]:
    """Builds execution environment with symbolizer mode and paths."""
    return traceconv.symbolizer_env(self.traceconv_platform,
                                    self._get_traceconv_symbol_dirs())

  def _export_to_traceconv(
      self, run: Run, perf_files: Sequence[pth.AnyPath]) -> list[pth.AnyPath]:
    """Exports perf data files to symbolized .pprof files via traceconv."""
    assert self._traceconv_bin is not None, "traceconv binary not initialized"
    with run.actions(
        f"Probe {self.probe.name}: "
        f"exporting {len(perf_files)} profiles with traceconv",
        verbose=True), ui.spinner():
      pprof_files: list[pth.AnyPath] = []
      env = self._get_traceconv_env()
      for perf_file in perf_files:
        if pprof_file := traceconv.convert_profile(
            self.traceconv_platform, self._traceconv_bin, perf_file, env=env):
          pprof_files.append(pprof_file)
      return pprof_files
