# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import logging
import multiprocessing
import shlex
import subprocess
import time
from typing import TYPE_CHECKING, Final

from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.cli.ui import ui
from crossbench.helper import fs_helper
from crossbench.plt.bin import Binaries
from crossbench.probes.profiling.context.base import PosixProfilingContext
from crossbench.probes.profiling.enum import CleanupMode

if TYPE_CHECKING:
  from crossbench.plt.base import Platform
  from crossbench.plt.types import ListCmdArgs
  from crossbench.probes.profiling.system_profiling import ProfilingProbe
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run

V8_PERF_PROF_PATH_FLAG_MIN_VERSION: Final = ChromiumVersion((118, 0, 5993, 48))
PERF_DATA_PATTERN: Final[str] = "*.perf.data"
JIT_DUMP_PATTERN: Final[str] = "jit-*.dump"
PPROF_SUFFIX: Final[str] = ".pprof"
JITTED_SUFFIX: Final[str] = ".jitted"


class LinuxProfilingContext(PosixProfilingContext):
  TEMP_FILE_PATTERNS = (
      "*.perf.data.jitted",
      "jitted-*.so",
      JIT_DUMP_PATTERN,
  )
  TEMP_DIR_PATTERNS = (
      "jitdump",
      "debug",
  )

  def __init__(self, probe: ProfilingProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._run_pprof: Final[bool] = self.probe.run_pprof(run.browser)

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    result_dir = super().get_default_result_path()
    self.browser_platform.mkdir(result_dir)
    return result_dir

  @property
  def has_perf_prof_path(self) -> bool:
    return self.browser.version > V8_PERF_PROF_PATH_FLAG_MIN_VERSION

  @property
  def run_pprof(self) -> bool:
    return self._run_pprof

  @property
  @override
  def traceconv_platform(self) -> Platform:
    return self.browser_platform

  @override
  def setup(self) -> None:
    self.setup_v8_log_path()
    if self.has_perf_prof_path:
      self.session.extra_js_flags["--perf-prof-path"] = str(self.result_path)
    prepare_linux_perf_env(self.browser_platform, self.result_path, {})
    self.setup_traceconv()

  def start(self) -> None:
    if not self.probe.sample_browser_process:
      return
    if self.run.browser.pid is None:
      logging.warning("Cannot sample browser process")
      return
    perf_data_file: pth.AnyPath = self.result_path / "browser.perf.data"
    # TODO: not fully working yet
    self._profiling_process = self.browser_platform.popen(
        "perf",
        "record",
        f"--call-graph={self.probe.call_graph_mode or 'fp'}",
        f"--freq={self.probe.frequency or 'max'}",
        f"--clockid={self.probe.clockid or 'mono'}",
        f"--output={perf_data_file}",
        f"--pid={self.run.browser.pid}",
        stdin=subprocess.PIPE)
    if self._profiling_process.poll():
      raise ValueError("Could not start linux profiler")

  @override
  def start_story_run(self) -> None:
    super().start_story_run()
    if self.start_profiling_after_setup():
      (self._renderer_pid, self._renderer_tid) = self.cached_renderer_pid_tid

  def stop(self) -> None:
    self.stop_process()

  def stop_process(self) -> None:
    if self._profiling_process:
      self.browser_platform.terminate_gracefully(self._profiling_process)
      self._profiling_process = None

  def teardown(self) -> ProbeResult:
    # Waiting for linux-perf to flush all perf data
    if self.probe.sample_browser_process:
      logging.debug("Waiting for browser process to stop")
      time.sleep(3)
    if self.probe.sample_browser_process:
      logging.info("Browser process did not stop after 3s. "
                   "You might get partial profiles")
    time.sleep(2)

    perf_files: list[pth.AnyPath] = fs_helper.sort_by_file_size(
        list(self.browser_platform.glob(self.result_path, PERF_DATA_PATTERN)),
        self.browser_platform)
    perf_files = self._filter_perf_files(perf_files)
    raw_perf_files = perf_files
    urls: list[str] = []
    pprof_files: list[pth.AnyPath] = []
    try:
      if self.probe.sample_js:
        perf_files = self._inject_v8_symbols(self.run, perf_files)
      if self.run_traceconv:
        pprof_files = self._export_to_traceconv(self.run, perf_files)
      if self.run_pprof:
        urls = self._export_to_pprof(self.run, pprof_files or perf_files)
    finally:
      self._clean_up_temp_files(
          self.run, has_exported_profile=bool(pprof_files or urls))
    if urls:
      logging.debug("Profiling results: %s", urls)
      return self.browser_result(
          url=urls, file=raw_perf_files, pprof=pprof_files)
    if pprof_files:
      return self.browser_result(file=raw_perf_files, pprof=pprof_files)
    # Fall back to raw_perf_files if .jitted files were removed by cleanup.
    perf_files = [f for f in perf_files if self.browser_platform.exists(f)
                 ] or raw_perf_files
    if Binaries.PPROF.exists(self.browser_platform):
      logging.info("Run pprof over all (or single) perf data files "
                   "for interactive analysis:")
      logging.info("   pprof --http=localhost:1984 %s",
                   " ".join(map(str, perf_files)))
    return self.browser_result(perfetto=perf_files)

  def _filter_perf_files(self,
                         perf_files: list[pth.AnyPath]) -> list[pth.AnyPath]:
    if not self.start_profiling_after_setup():
      return perf_files
    renderer_pid = self._renderer_pid
    if not renderer_pid:
      return perf_files
    # There will be exactly one matching file, usually the largest one
    for perf_file in reversed(perf_files):
      if self._extract_perf_pid(perf_file) == str(renderer_pid):
        return [perf_file]
    logging.error(
        "Found no matching profiling for renderer PID %s. "
        "Using largest profile.", renderer_pid)
    return [perf_files[-1]]

  def _extract_perf_pid(self, perf_file: pth.AnyPath) -> str:
    # Run 'perf script' to extract *all* pids in the result file. This might
    # return a lot of data, thus let's filter it directly on the
    # browser platform.
    maybe_pid = self.browser_platform.sh_stdout(  # noqa: S604
        shlex.join(
            ("perf", "--buildid-dir", str(perf_file.parent / "debug"), "script",
             "-i", str(perf_file), "-F", "pid")) + " | head -n1",
        shell=True)
    return maybe_pid.strip()

  def _inject_v8_symbols(self, run: Run,
                         perf_files: list[pth.AnyPath]) -> list[pth.AnyPath]:
    with run.actions(
        f"Probe {self.probe.name}: "
        f"Injecting V8 symbols into {len(perf_files)} profiles",
        verbose=True), ui.spinner():
      # Filter out empty files
      perf_files = [
          file for file in perf_files
          if self.browser_platform.file_size(file) > 0
      ]
      if self.browser_platform.is_remote:
        # Use loop, as we cannot easily serialize the remote platform.
        perf_jitted_files = [
            linux_perf_probe_inject_v8_symbols(file, self.browser_platform)
            for file in perf_files
        ]
      else:
        assert self.browser_platform == plt.PLATFORM
        with multiprocessing.Pool() as pool:
          perf_jitted_files = list(
              pool.imap(linux_perf_probe_inject_v8_symbols, perf_files))
      return [file for file in perf_jitted_files if file is not None]

  def _export_to_pprof(self, run: Run,
                       perf_files: list[pth.AnyPath]) -> list[str]:
    assert self.run_pprof
    run_details_json = json.dumps(run.get_browser_details_json())
    with run.actions(
        f"Probe {self.probe.name}: "
        f"exporting {len(perf_files)} profiles to pprof (slow)",
        verbose=True), ui.spinner():
      if self.browser_platform.sh(
          "gcertstatus", check=False, quiet=True).returncode != 0:
        logging.info("Authenticating with gcert:")
        self.browser_platform.sh("gcert")
      size = len(perf_files)
      items = zip(perf_files, [run_details_json] * size, strict=True)
      urls: list[str] = []
      if self.browser_platform.is_remote:
        # Use loop, as we cannot easily serialize the remote platform.
        for perf_data_file, run_details in items:
          url = linux_perf_probe_pprof(perf_data_file, run_details,
                                       self.browser_platform)
          if url:
            urls.append(url)
      else:
        assert self.browser_platform == plt.PLATFORM
        with multiprocessing.Pool() as pool:
          urls = [
              url for url in pool.starmap(linux_perf_probe_pprof, items) if url
          ]
      try:
        if perf_files:
          # TODO: Add "combined" profile again
          pass
      except Exception as e:  # noqa: BLE001
        logging.debug("Failed to run pprof: %s", e)
      return urls

  @override
  def _get_traceconv_symbol_dirs(self) -> tuple[pth.AnyPath, ...]:
    return (
        self.browser.path.parent,
        self.result_path,
        self.result_path / "debug",
        self.result_path / "jitdump",
    )

  def _clean_up_temp_files(self,
                           run: Run,
                           has_exported_profile: bool = False) -> None:
    """Cleans up temporary profiling files and symbol directories."""
    if self.probe.cleanup_mode == CleanupMode.NEVER:
      logging.debug("%s: skipping cleanup", self.probe)
      return
    if self.probe.cleanup_mode == CleanupMode.AUTO:
      if not has_exported_profile:
        logging.debug("%s: skipping auto cleanup without exported profile",
                      self.probe)
        return
    cleanup_dirs = {self.result_path, run.out_dir}
    for cleanup_dir in cleanup_dirs:
      for pattern in self.TEMP_FILE_PATTERNS:
        for file in self.browser_platform.glob(cleanup_dir, pattern):
          self.browser_platform.rm(file, missing_ok=True)
    if has_exported_profile:
      for pattern in self.TEMP_DIR_PATTERNS:
        for directory in self.browser_platform.glob(self.result_path, pattern):
          self.browser_platform.rm(directory, dir=True, missing_ok=True)


def prepare_linux_perf_env(platform: plt.Platform,
                           cwd: pth.AnyPath,
                           env: dict[str, str] | None = None) -> dict[str, str]:
  abs_cwd = platform.absolute(cwd)
  if env is None:
    env = dict(platform.environ)
  jit_dump_dir = abs_cwd / "jitdump"
  platform.mkdir(jit_dump_dir, parents=True, exist_ok=True)
  env["JITDUMPDIR"] = str(jit_dump_dir)
  debug_dir = abs_cwd / "debug"
  platform.mkdir(debug_dir, parents=True, exist_ok=True)
  env["PERF_BUILDID_DIR"] = str(debug_dir)
  return env


KB = 1024


def linux_perf_probe_inject_v8_symbols(
    perf_data_file: pth.AnyPath,
    platform: plt.Platform | None = None) -> pth.AnyPath | None:
  platform = platform or plt.PLATFORM
  assert platform.is_file(perf_data_file)
  output_file = perf_data_file.with_suffix(".data.jitted")
  assert not platform.exists(output_file)
  env = prepare_linux_perf_env(platform, perf_data_file.parent)
  try:
    # TODO: use remote chdir
    platform.sh(
        "perf",
        "--buildid-dir",
        str(perf_data_file.parent / "debug"),
        "inject",
        "--jit",
        f"--input={perf_data_file}",
        f"--output={output_file}",
        env=env)
  except plt.SubprocessError as e:
    if platform.file_size(perf_data_file) > 200 * KB:
      logging.warning("Failed processing: %s\n%s", perf_data_file, e)
    else:
      # TODO: investigate why almost all small perf.data files fail
      logging.debug("Failed processing small profile (likely empty): %s\n%s",
                    perf_data_file, e)
  if not platform.exists(output_file):
    return None
  return output_file


def linux_perf_probe_pprof(perf_data_file: pth.AnyPath,
                           run_details: str,
                           platform: plt.Platform | None = None) -> str | None:
  platform = platform or plt.PLATFORM
  size = fs_helper.get_file_size(perf_data_file, platform=platform)
  env = prepare_linux_perf_env(platform, perf_data_file.parent)
  url: str = ""
  try:
    cmd: ListCmdArgs = [Binaries.PPROF.resolve_cached(platform)]
    if perf_data_file.suffix != PPROF_SUFFIX:
      cmd.append("-symbolize=force")
    cmd.extend(("-flame", f"-add_comment={run_details}", perf_data_file))
    url = platform.sh_stdout(*cmd, env=env).strip()
  except plt.SubprocessError as e:
    if perf_data_file.suffix == PPROF_SUFFIX:
      logging.warning("Failed processing pprof file: %s\n%s", perf_data_file, e)
      return None
    # Occasionally small .jitted files fail, likely due perf inject silently
    # failing?
    perf_data_file, maybe_url = _linux_perf_probe_pprof_fallback(
        perf_data_file, run_details, platform, e)
    if not maybe_url:
      logging.warning("Failed processing: %s\n%s", perf_data_file, e)
      return None
    url = maybe_url
  if perf_data_file.suffix == PPROF_SUFFIX:
    logging.info("PPROF (symbolized via traceconv):")
  elif perf_data_file.suffix == JITTED_SUFFIX:
    logging.info("PPROF (with js-symbols):")
  else:
    logging.info("PPROF (no js-symbols):")
  logging.info("  file:         %s [%s]", perf_data_file.name, size)
  logging.info("  pprof result: %s", url)
  return url


def _linux_perf_probe_pprof_fallback(
    perf_data_file: pth.AnyPath, run_details: str, platform: plt.Platform,
    e: Exception) -> tuple[pth.AnyPath, str | None]:
  raw_perf_data_file = perf_data_file.with_suffix("")
  if perf_data_file.suffix != JITTED_SUFFIX or (
      not platform.exists(raw_perf_data_file)):
    return perf_data_file, None
  logging.debug(
      "pprof best-effort: falling back to standard perf data "
      "without js symbols: %s \n"
      "Got failures for %s: %s", raw_perf_data_file, perf_data_file.name, e)
  url = None
  try:
    url = platform.sh_stdout(
        Binaries.PPROF.resolve_cached(platform),
        "-symbolize=force",
        "-flame",
        f"-add_comment={run_details}",
        raw_perf_data_file,
    ).strip()
  except plt.SubprocessError as e2:
    logging.debug("pprof -flame failed: %s", e2)
  return raw_perf_data_file, url
