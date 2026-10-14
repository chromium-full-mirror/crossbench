# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Original Source: telemetry/internal/backends/chrome/minidump_symbolizer.py
from __future__ import annotations

import abc
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Final

from crossbench import path as pth
from crossbench.browsers.chromium_based.crash import helper
from crossbench.helper import path_finder

if TYPE_CHECKING:
  from crossbench.browsers.chromium_based.crash.minidump_finder import \
      MinidumpFinder
  from crossbench.plt.base import Platform
  from crossbench.plt.types import ListCmdArgs

# 5 is arbitrary, but a reasonable number of paths to print out.
_MAX_PRINTED_BINARIES: Final[int] = 5


class MinidumpSymbolizer(abc.ABC):

  def __init__(self,
               platform: Platform,
               dump_finder: MinidumpFinder,
               build_dir: pth.LocalPath,
               symbols_dir: pth.LocalPath | None = None,
               result_dir: pth.LocalPath | None = None) -> None:
    """Abstract class for handling all minidump symbolizing code.

    Args:
      platform: The platform of the host or test machine.
      dump_finder: The minidump_finder.MinidumpFinder instance that is being
          used to find minidumps for the test.
      build_dir: The directory containing Chromium build artifacts to generate
          symbols from.
      symbols_dir: An optional path to a directory to store symbols for reuse.
          Reusing symbols will result in faster symbolization times, but the
          provided directory *must* be unique per browser binary, e.g. by
          including the hash of the binary in the directory name.
      result_dir: A path to a directory to store symbolization
          results and artifacts.
    """
    # TODO: move arguments to be non-optional.
    if not result_dir:
      raise ValueError("result_dir must be provided for MinidumpSymbolizer")
    self._platform: Final[Platform] = platform
    self._dump_finder: Final[MinidumpFinder] = dump_finder
    self._build_dir: Final[pth.LocalPath] = build_dir
    self._symbols_dir: Final[pth.LocalPath | None] = symbols_dir
    self._result_dir: Final[pth.LocalPath] = result_dir

  def symbolize_minidump(self, minidump: pth.LocalPath) -> str | None:
    """Gets the stack trace from the given minidump.

    Args:
      minidump: the path to the minidump on disk

    Returns:
      None if the stack could not be retrieved for some reason, otherwise a
      string containing the stack trace.
    """
    stackwalk = helper.find_crash_binary(self._platform, "minidump_stackwalk",
                                         self._build_dir,
                                         path_finder.MinidumpStackwalkFinder)
    if not stackwalk:
      logging.warning("minidump_stackwalk binary not found.")
      return None

    # We only want this logic on linux platforms that are still using breakpad.
    # See crbug.com/667475
    if not self._dump_finder.minidump_obtained_from_crashpad(minidump):
      with minidump.open("rb") as infile:
        minidump_stripped = minidump.with_suffix(f"{minidump.suffix}.stripped")
        with minidump_stripped.open("wb") as outfile:
          data = infile.read()
          partition = data.partition(b"MDMP")
          if not partition[1]:
            logging.warning("No MDMP header found in minidump.")
            outfile.write(data)
          else:
            outfile.write(partition[1] + partition[2])
        minidump = minidump_stripped

    symbols_dir = self._symbols_dir
    if not symbols_dir:
      symbols_dir = pth.LocalPath(tempfile.mkdtemp())
    try:
      self._generate_breakpad_symbols(symbols_dir, minidump)
      return self._platform.sh_stdout(stackwalk, minidump, symbols_dir)
    finally:
      if not self._symbols_dir:
        shutil.rmtree(symbols_dir)

  @abc.abstractmethod
  def get_symbol_binaries(self, minidump: pth.LocalPath) -> list[pth.LocalPath]:
    """Returns a list of paths to binaries where symbols may be located.

    Args:
      minidump: The path to the minidump being symbolized.
    """

  def get_breakpad_platform_override(self) -> str | None:
    """Returns the platform to be passed to generate_breakpad_symbols."""
    return None

  def _generate_breakpad_symbols(self, symbols_dir: pth.LocalPath,
                                 minidump: pth.LocalPath) -> None:
    """Generates Breakpad symbols for use with stackwalking tools.

    Args:
      symbols_dir: The directory where symbols will be written to.
      minidump: The path to the minidump being symbolized.
    """
    logging.info("Dumping Breakpad symbols.")
    tools = self._find_breakpad_tools()
    if not tools:
      return
    generate_breakpad_symbols_command, dump_syms_path = tools
    symbol_binaries = self.get_symbol_binaries(minidump)
    cmds = self._collect_breakpad_cmds(symbols_dir, symbol_binaries,
                                       generate_breakpad_symbols_command,
                                       dump_syms_path)
    self._run_breakpad_dump_cmds(cmds)

  def _find_breakpad_tools(self) -> tuple[pth.LocalPath, pth.LocalPath] | None:
    generate_breakpad_symbols_command = helper.find_crash_binary(
        self._platform, "generate_breakpad_symbols.py", self._build_dir,
        path_finder.GenerateBreakpadSymbolsFinder)
    if not generate_breakpad_symbols_command:
      # Also try without .py extension
      generate_breakpad_symbols_command = helper.find_crash_binary(
          self._platform, "generate_breakpad_symbols", self._build_dir)

    if not generate_breakpad_symbols_command:
      logging.warning(
          "generate_breakpad_symbols binary not found, cannot symbolize "
          "minidumps")
      return None

    dump_syms_path = helper.find_crash_binary(self._platform, "dump_syms",
                                              self._build_dir,
                                              path_finder.DumpSymsFinder)
    if not dump_syms_path:
      logging.warning("dump_syms binary not found, cannot symbolize minidumps")
      return None
    return generate_breakpad_symbols_command, dump_syms_path

  def _collect_breakpad_cmds(
      self, symbols_dir: pth.LocalPath, symbol_binaries: list[pth.LocalPath],
      generate_breakpad_symbols_command: pth.LocalPath,
      dump_syms_path: pth.LocalPath) -> list[ListCmdArgs]:
    cmds: list[ListCmdArgs] = []
    cached_binaries: list[pth.LocalPath] = []
    missing_binaries: list[pth.LocalPath] = []
    for binary_path in symbol_binaries:
      if not binary_path.exists():
        missing_binaries.append(binary_path)
        continue
      # Skip dumping symbols for binaries if they already exist in the symbol
      # directory, i.e. whatever is using this symbolizer has opted to cache
      # symbols. The directory will contain a directory with the binary name if
      # it has already been dumped.
      cache_path = symbols_dir / binary_path.name
      if cache_path.is_dir():
        cached_binaries.append(binary_path)
        continue
      cmds.append(
          self._format_breakpad_cmd(binary_path, symbols_dir,
                                    generate_breakpad_symbols_command,
                                    dump_syms_path))
    total_count: int = len(symbol_binaries)
    if missing_binaries:
      self._log_missing_binaries(missing_binaries, total_count)
    if cached_binaries:
      self._log_cached_binaries(cached_binaries, total_count)
    return cmds

  def _format_breakpad_cmd(self, binary_path: pth.LocalPath,
                           symbols_dir: pth.LocalPath,
                           generate_breakpad_symbols_command: pth.LocalPath,
                           dump_syms_path: pth.LocalPath) -> ListCmdArgs:
    cmd: ListCmdArgs = []
    if generate_breakpad_symbols_command.suffix == ".py":
      cmd.append(sys.executable)
    cmd.extend([
        generate_breakpad_symbols_command,
        f"--binary={binary_path}",
        f"--symbols-dir={symbols_dir}",
        f"--build-dir={self._build_dir}",
        f"--dump-syms-path={dump_syms_path}",
    ])
    if platform_override := self.get_breakpad_platform_override():
      cmd.append(f"--platform={platform_override}")
    return cmd

  def _log_missing_binaries(self, missing_binaries: list[pth.LocalPath],
                            total_count: int) -> None:
    logging.warning(
        "Unable to find %d of %d binaries for minidump symbolization. This "
        "is likely not an actual issue, but is worth investigating if the "
        "minidump fails to symbolize properly.", len(missing_binaries),
        total_count)
    if len(missing_binaries) < _MAX_PRINTED_BINARIES:
      logging.warning("Missing binaries: %s", missing_binaries)
    else:
      logging.warning(
          "Run test with high verbosity to get the list of missing binaries.")
      logging.debug("Missing binaries: %s", missing_binaries)

  def _log_cached_binaries(self, cached_binaries: list[pth.LocalPath],
                           total_count: int) -> None:
    logging.info(
        "Skipping symbol dumping for %d of %d binaries due to cached symbols "
        "being present.", len(cached_binaries), total_count)
    if len(cached_binaries) < _MAX_PRINTED_BINARIES:
      logging.info("Skipped binaries: %s", cached_binaries)
    else:
      logging.info(
          "Run test with high verbosity to get the list of binaries with "
          "cached symbols.")
      logging.debug("Skipped binaries: %s", cached_binaries)

  def _run_breakpad_dump_cmds(self, cmds: list[ListCmdArgs]) -> None:
    # We need to prevent the number of file handles that we open from reaching
    # the soft limit set for the current process. This can either be done by
    # ensuring that the limit is suitably large using the resource module or by
    # only starting a relatively small number of subprocesses at once. In order
    # to prevent any potential issues with messing with system limits, the
    # latter is chosen.
    # Typically, this would be handled by using the multiprocessing module's
    # pool functionality, but importing generate_breakpad_symbols and invoking
    # it directly takes significantly longer than alternatives for whatever
    # reason, even if they appear to perform more work. Thus, we could either
    # have each task in the pool create its own subprocess that runs the
    # command or manually limit the number of subprocesses we have at any
    # given time. We go with the latter option since it should be less
    # wasteful.
    processes: dict[subprocess.Popen, ListCmdArgs] = {}
    # Symbol dumping is somewhat I/O constrained, so use double the number of
    # logical cores on the system.
    # TODO: make this configurable or use a proper pool via Platform.
    process_limit = self._platform.cpu_cores(logical=True) * 2
    while cmds or processes:
      self._clear_finished_processes(processes)
      # Add as many more processes as we can.
      while len(processes) < process_limit and cmds:
        cmd = cmds.pop(-1)
        p = self._platform.popen(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        processes[p] = cmd
      # 1 second is fairly arbitrary.
      time.sleep(1)

  def _clear_finished_processes(
      self, processes: dict[subprocess.Popen, ListCmdArgs]) -> None:
    processes_to_delete = []
    for p, cmd in processes.items():
      if p.poll() is not None:
        stdout, stderr = p.communicate()
        if p.returncode:
          if stdout:
            logging.error(stdout.decode())
          if stderr:
            logging.error(stderr.decode())
          logging.warning("Failed to execute %s", cmd)
        processes_to_delete.append(p)
    for p in processes_to_delete:
      del processes[p]
