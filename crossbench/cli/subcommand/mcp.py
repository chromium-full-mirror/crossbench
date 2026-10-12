# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import shlex
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.cli.parser import CBArgumentParser
from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.cli.subcommand.describe import DescribeSubcommand
from crossbench.flags.base import Flags
from crossbench.helper.wait import WaitRange
from crossbench.parse import ObjectParser
from crossbench.probes.cdp_endpoint import CDPEndpointProbe
from crossbench.probes.internal.summary import ResultsSummaryProbe

if TYPE_CHECKING:
  from crossbench.cli.cli import CrossBenchCLI
  from crossbench.cli.types import Subparsers


class DescribeSubcommandNoParser(DescribeSubcommand):

  def __init__(self, cli: CrossBenchCLI) -> None:
    super().__init__(cli)
    self._parser = CBArgumentParser()

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    return parser


@dataclasses.dataclass
class StatusResult:
  running: bool
  pid: int | None = None
  endpoint: str | None = None
  message: str | None = None
  error: str | None = None
  stdout: str | None = None
  stderr: str | None = None


class McpSubcommand(CrossbenchSubcommand):
  """Subcommand to manage MCP integration for manual benchmarks."""

  DEFAULT_MANUAL_DURATION = "1800s"

  def __init__(self, cli: CrossBenchCLI) -> None:
    super().__init__(cli)
    self._mcp_session_dir: pth.LocalPath | None = None
    self._status_file: pth.LocalPath | None = None
    self._process: subprocess.Popen | None = None

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "mcp",
        help="Start the Crossbench MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Start a MCP server to let agents control Crossbench.")
    self._parser = parser
    parser.set_defaults(crossbench_subcommand=self)
    return parser

  @property
  def mcp_session_dir(self) -> pth.LocalPath:
    if not self._mcp_session_dir:
      raise RuntimeError(
          "MCP session not initialized. Run the subcommand first.")
    return self._mcp_session_dir

  @property
  def state_file(self) -> pth.LocalPath:
    if not self._status_file:
      raise RuntimeError(
          "MCP session not initialized. Run the subcommand first.")
    return self._status_file

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    del args
    self._mcp_session_dir = pth.get_out_dir(pth.ROOT_DIR, suffix="mcp")
    self._mcp_session_dir.mkdir(parents=True, exist_ok=True)
    self._status_file = self._mcp_session_dir / "mcp_status.json"

    mcp = FastMCP(
        "Crossbench",
        instructions="""You are investigating the performance of websites
      and browsers.

      1. Use "describe_benchmark()" to understand more about a benchmark
         and its flags and options.
      2. Use "describe_probes()" to understand more about the available probes
         Probes collect data, lik perfetto traces, profiles or v8 logs.
      3. Use "start_benchmark()" to start a benchmark
      4. Once the benchmark is running use the "status" tool to figure
         out whether it's still running
      5. Once completed (and/or after using the "stop()" tool) use "results()"
         to access all results or individual probe results.

      Special benchmarks:
        - **loading**: for predefined page interactions and loading
        - **manual**: for manual benchmarks (use with --url), for chrome
          browsers this will also expose the CDP endpoint that you
          can use to control the browser for your agent. Use "stop()" to
          explicitly stop the benchmark.
      """)

    mcp.tool()(self.describe_benchmark)
    mcp.tool()(self.describe_probes)
    mcp.tool()(self.describe_configs)
    mcp.tool()(self.start_benchmark)
    mcp.tool()(self.status)
    mcp.tool()(self.stop)
    mcp.tool()(self.results)

    mcp.run(transport="stdio")

  def start_benchmark(self,
                      name: str,
                      args: list[str],
                      force_stop: bool = True) -> StatusResult:
    """Starts any benchmark and exposes the CDP endpoint.

    Configurations:
    - Use the benchmark flags to modify browser/ runtime behavior
      (see describe_benchmark() tool)
    - Use the --probe flag to add more projects to extract more data
      (see describe_probes() tool)

    Args:
        name: Name of the benchmark to run (e.g., "loading", "manual").
        args: List of arguments for the benchmark (e.g.,
          ["--url=https://google.com"]). Use the describe_benchmark() tool to
          discover more flags and options.
        force_stop: Whether to force stop an existing active session.
    """
    stdout_path = self.mcp_session_dir / "stdout.txt"
    stderr_path = self.mcp_session_dir / "stderr.txt"
    try:
      self._start_check_preconditions(name, force_stop)
      cmd = self._start_build_command(name, args)

      process = self._start_launch_process(cmd)
      self._process = process
      endpoint: str | None = self._start_wait_for_endpoint(process, name, args)
      state = {
          "pid": process.pid,
          "endpoint": endpoint,
          "cmd": cmd,
      }
      self.state_file.parent.mkdir(parents=True, exist_ok=True)
      self.state_file.write_text(json.dumps(state, indent=2))

      return StatusResult(
          running=True,
          pid=process.pid,
          endpoint=endpoint,
          message="Benchmark started successfully.",
          stdout=str(stdout_path),
          stderr=str(stderr_path))
    except Exception as e:  # noqa: BLE001
      return StatusResult(
          running=False,
          error=str(e),
          stdout=str(stdout_path),
          stderr=str(stderr_path))

  def _start_check_preconditions(self, name: str, force_stop: bool) -> None:
    valid_benchmarks = [b.NAME for b in self.cli.BENCHMARKS]
    if name not in valid_benchmarks:
      raise ValueError(f"Unknown benchmark {name!r}. "
                       f"Valid choices: {valid_benchmarks}")

    if not self._is_session_active():
      self.state_file.unlink(missing_ok=True)
    elif force_stop:
      logging.debug("Existing MCP session found. Stopping it...")
      self.stop()
    else:
      raise RuntimeError("Benchmark session is already running. "
                         "Set force_stop=True to stop it and start a new one.")

    if self.mcp_session_dir.exists():
      logging.debug("Clearing old session data in: %s", self.mcp_session_dir)
      if self.mcp_session_dir.is_dir():
        shutil.rmtree(self.mcp_session_dir, ignore_errors=True)
      else:
        self.mcp_session_dir.unlink()

  @staticmethod
  def _split_args(args: list[str]) -> tuple[list[str], list[str]]:
    cb_args: list[str] = []
    browser_args: list[str] = []
    target: list[str] = cb_args
    for arg in args:
      if arg == "--":
        target = browser_args
      target.append(arg)
    return cb_args, browser_args

  def _start_build_command(self, benchmark_name: str,
                           benchmark_args: list[str]) -> list[str]:
    cb_py = pth.ROOT_DIR / "cb.py"
    cb_args, browser_args = self._split_args(benchmark_args)

    # Use Flags only to check for existing flags
    flags = Flags()
    for arg in cb_args:
      if arg.startswith("-"):
        flags.update(Flags.parse_str(arg))

    if benchmark_name == "manual":
      if "--expose-cdp" not in flags:
        cb_args.append("--expose-cdp")
      if "--start-after" not in flags:
        cb_args.append("--start-after=0s")
      if "--run-for" not in flags:
        cb_args.append(f"--run-for={self.DEFAULT_MANUAL_DURATION}")

    if {"--no-splash", "--nosplash", "--splash"}.isdisjoint(flags):
      cb_args.append("--no-splash")

    if plt.PLATFORM.is_headless and "--headless" not in flags:
      cb_args.append("--headless")
      logging.debug("Platform is headless, automatically adding --headless")

    if "--out-dir" in flags:
      raise ValueError("Cannot provide custom --out-dir for MCP sessions")
    cb_args.append(f"--out-dir={self.mcp_session_dir / 'result'}")

    cmd = [sys.executable, str(cb_py), benchmark_name]
    cmd.extend(cb_args)
    cmd.extend(browser_args)

    self.mcp_session_dir.mkdir(parents=True, exist_ok=True)
    return cmd

  def _start_launch_process(self, cmd: list[str]) -> subprocess.Popen:
    logging.debug("Starting benchmark with command: %s", shlex.join(cmd))

    stdout_file = (self.mcp_session_dir / "stdout.txt").open("w")
    stderr_file = (self.mcp_session_dir / "stderr.txt").open("w")
    try:
      process = subprocess.Popen(
          cmd, stdout=stdout_file, stderr=stderr_file, start_new_session=True)
    finally:
      stdout_file.close()
      stderr_file.close()

    return process

  def _start_wait_for_endpoint(self, process: subprocess.Popen, name: str,
                               args: list[str]) -> str | None:
    if name != "manual" and "--probe=cdp_endpoint" not in args:
      return None

    logging.debug("Waiting for CDP endpoint file...")
    try:
      if endpoint := self._retry_read_endpoint(process):
        return endpoint
    except TimeoutError:
      raise RuntimeError("Timed out waiting for CDP endpoint file.") from None

    stderr_path = self.mcp_session_dir / "stderr.txt"
    if stderr_path.exists():
      logging.debug("=== Last 100 lines of stderr ===")
      lines = stderr_path.read_text().splitlines()
      for line in lines[-100:]:
        logging.debug(line)
      logging.debug("=================================")

    if process.poll() is None:
      logging.debug("Terminating benchmark process...")
      process.terminate()
      process.wait()
    raise RuntimeError("Failed to obtain CDP endpoint.")

  def _retry_read_endpoint(self, process: subprocess.Popen) -> str | None:
    wait_range = WaitRange(min=0.5, timeout=60, factor=1.2)
    for _ in wait_range.wait_with_backoff():
      if process.poll() is not None:
        raise RuntimeError(
            f"Benchmark process exited early with code {process.returncode}.")

      matches = list(
          self.mcp_session_dir.glob(f"**/{CDPEndpointProbe.FILE_NAME}"))
      if not matches:
        continue
      endpoint_file = matches[0]
      if not endpoint_file.is_file():
        continue
      if endpoint := endpoint_file.read_text().strip():
        return endpoint
    return None

  def _is_session_active(self) -> bool:
    if self._process:
      return self._process.poll() is None
    if not self.state_file.exists():
      return False
    try:
      state = json.loads(self.state_file.read_text())
      pid = state.get("pid")
      return bool(pid and plt.PLATFORM.process_info(pid))
    except Exception:  # noqa: BLE001
      return False

  def status(self) -> StatusResult:
    """Checks if a benchmark session is currently still running.

    Returns:
        A StatusResult object with the current status of the benchmark session.
    """
    if not self.state_file.exists():
      return StatusResult(running=False)

    state = json.loads(self.state_file.read_text())
    pid = state.get("pid")
    endpoint = state.get("endpoint")
    running = self._is_session_active()

    stdout_path = self.mcp_session_dir / "stdout.txt"
    stderr_path = self.mcp_session_dir / "stderr.txt"
    stdout = str(stdout_path)
    stderr = str(stderr_path)

    return StatusResult(
        running=running,
        pid=pid,
        endpoint=endpoint,
        stdout=stdout,
        stderr=stderr)

  def stop(self) -> dict | str:
    """Stops the active benchmark session and cleans up.

    Returns:
        A dict with the results data if the benchmark has completed or
        a message indicating that the session was stopped or no active session
        was found.
    """
    results_data = {}
    try:
      results_data = self._get_results_data()
    except Exception as e:  # noqa: BLE001
      logging.debug("Could not load results data on stop: %s", e)
    finally:
      cleaned_up_session = self._stop_session()
    if results_data:
      return results_data
    if cleaned_up_session:
      return "Benchmark session stopped."
    return "No active session was found to stop."

  def _stop_session(self) -> bool:
    if not self._process:
      if self.state_file.exists():
        self.state_file.unlink()
        return True
      return False

    logging.debug("Stopping MCP session via Popen...")
    try:
      self._stop_session_process_gracefully()
    finally:
      self._process = None
      self.state_file.unlink(missing_ok=True)
    return True

  def _get_stdout_size(self) -> int:
    stdout_path = self.mcp_session_dir / "stdout.txt"
    try:
      return stdout_path.stat().st_size
    except FileNotFoundError:
      return 0

  def _is_session_process_running(self) -> bool:
    return self._process is not None and self._process.poll() is None

  def _stop_session_process_gracefully(self) -> None:
    assert self._process, "No active session process to stop."
    plt.PLATFORM.send_signal(self._process, plt.PLATFORM.signals.SIGTERM)

    last_size = self._get_stdout_size()
    start_uptime = plt.PLATFORM.uptime()
    last_progress_time = start_uptime

    wait_range = WaitRange(min=2.0, timeout=60.0)
    for _ in wait_range.wait_with_backoff():
      if not self._is_session_process_running():
        logging.debug("Process terminated successfully.")
        break

      current_size = self._get_stdout_size()
      if current_size > last_size:
        logging.debug("Process is making progress (stdout size increased).")
        last_size = current_size
        last_progress_time = plt.PLATFORM.uptime()
      elif (plt.PLATFORM.uptime() - last_progress_time).total_seconds() > 10:
        logging.warning("Process seems stuck (no stdout progress for 10s).")
        break

    if self._is_session_process_running():
      logging.warning("Process did not terminate, killing...")
      plt.PLATFORM.kill(self._process)
      self._process.wait()

  def results(self,
              run: int | None = None,
              probe_name: str | None = None) -> dict:
    """Returns the results data after the benchmark has stopped that you
    can use for additional analysis. For the exact format see the probe's
    description via the "describe_probes()" tool.

    Args:
        run: Optional run index to get files for.
        probe_name: Optional probe name to get files for.
    """
    status = self.status()
    if status.running:
      raise RuntimeError(
          "Cannot get results while the session is still running. "
          "Stop it first.")

    data = self._get_results_data(run)

    if probe_name:
      probes_data = data.get("probes", {})
      if probe_name not in probes_data:
        raise RuntimeError(f"Probe {probe_name} not found in results.")
      return probes_data[probe_name]

    if run is not None:
      return data.get("probes", {})

    return data

  def _get_results_data(self, run: int | None = None) -> dict:
    if not self.state_file.exists():
      raise RuntimeError("No benchmark session found.")
    results_files = list(
        self.mcp_session_dir.glob(f"**/{ResultsSummaryProbe.FILE_NAME}"))
    if not results_files:
      raise RuntimeError(f"Results file not found in {self.mcp_session_dir}.")

    if run is not None:
      for file_path in results_files:
        data = ObjectParser.dict(ObjectParser.json_file(file_path))
        if data.get("run", {}).get("index") == run:
          return data
      raise RuntimeError(f"Results for run {run} not found.")

    top_level_path = (
        self.mcp_session_dir / "active" / ResultsSummaryProbe.FILE_NAME)
    if top_level_path.exists():
      return ObjectParser.dict(ObjectParser.json_file(top_level_path))
    return ObjectParser.dict(ObjectParser.json_file(results_files[0]))

  def describe_benchmark(self, benchmark_name: str = "") -> dict:
    """Returns the help data for benchmarks.

    Lists all benchmarks if no name is provided.
    """
    describe_cmd = DescribeSubcommandNoParser(self.cli)
    data = describe_cmd.help_data("benchmarks", benchmark_name or None)
    if benchmark_name:
      return dict(data["benchmarks"].get(benchmark_name, {}))
    return data["benchmarks"]

  def describe_probes(self, name: str = "") -> dict:
    """Describes available probes or a specific probe.

    Lists all available probes if no name is provided or empty.

    Args:
        name: Optional name of the probe to describe.
    """
    describe_cmd = DescribeSubcommandNoParser(self.cli)
    data = describe_cmd.help_data("probes", name or None)
    return data["probes"]

  def describe_configs(self, name: str = "") -> dict:
    """Describes available configs or a specific config.

    Lists all available configs if no name is provided or empty.

    Args:
        name: Optional name of the config to describe.
    """
    describe_cmd = DescribeSubcommandNoParser(self.cli)
    data = describe_cmd.help_data("config-objects", name or None)
    return data["config_objects"]
