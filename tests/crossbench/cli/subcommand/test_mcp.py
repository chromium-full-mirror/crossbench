# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from unittest import mock

from immutabledict import immutabledict

from crossbench import path as pth
from crossbench.cli.subcommand.mcp import McpSubcommand
from tests import test_helper


class McpSubcommandTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    class DummyParser:

      def add_argument(self, *args, **kwargs):
        pass

      def set_defaults(self, *args, **kwargs):
        pass

    class DummySubparsers:

      def add_parser(self, *args, **kwargs):
        return DummyParser()

    class MockBenchmarkCls:
      NAME = "manual"

      @classmethod
      def aliases(cls) -> tuple[str, ...]:
        return ()

      @classmethod
      def describe(cls) -> dict[str, str]:
        return {"doc": "Manual benchmark"}

    class MockSubcommand:

      def __init__(self) -> None:
        self.parser = argparse.ArgumentParser()

      def init_cli_parser(self) -> None:
        pass

    class DummyCLI:

      def __init__(self) -> None:
        self.BENCHMARKS = [MockBenchmarkCls]
        self.subparsers = DummySubparsers()
        self.benchmark_subcommands = immutabledict(
            {MockBenchmarkCls: MockSubcommand()})

      def add_debugging_arguments(self,
                                  parser: argparse.ArgumentParser) -> None:
        pass

    self.cli = DummyCLI()
    self.cli.subparsers.add_parser("mcp")
    self.mcp_cmd = McpSubcommand(self.cli)

    # Mock paths to avoid touching real filesystem
    self.mock_state_file = mock.MagicMock(spec=pth.LocalPath)
    self.mock_out_dir = mock.MagicMock(spec=pth.LocalPath)

    self.mcp_cmd._mcp_session_dir = self.mock_out_dir
    self.mcp_cmd._status_file = self.mock_state_file

  def test_status_not_running(self):
    self.mock_state_file.exists.return_value = False
    status = self.mcp_cmd.status()
    self.assertFalse(status.running)

  def test_status_running(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps({
        "pid": 123,
        "endpoint": "ws://localhost:1234",
        "cmd": [],
    })

    with mock.patch(
        "crossbench.plt.PLATFORM.process_info") as mock_process_info:
      mock_process_info.return_value = {"pid": 123}
      status = self.mcp_cmd.status()
      self.assertTrue(status.running)
      self.assertEqual(status.pid, 123)
      self.assertEqual(status.endpoint, "ws://localhost:1234")

  @mock.patch("subprocess.Popen")
  def test_start(self, mock_popen):
    self.mock_state_file.exists.return_value = False
    self.mock_out_dir.exists.return_value = False

    # Mock process
    mock_process = mock.MagicMock()
    mock_process.pid = 123
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    # Mock glob for CDP file
    mock_cdp_file = mock.MagicMock(spec=pth.LocalPath)
    mock_cdp_file.is_file.return_value = True
    mock_cdp_file.read_text.return_value = "ws://localhost:1234"
    self.mock_out_dir.glob.return_value = [mock_cdp_file]

    status = self.mcp_cmd.start_benchmark("manual",
                                          ["--url=https://google.com"])

    self.assertTrue(status.running)
    self.assertEqual(status.pid, 123)
    self.assertEqual(status.endpoint, "ws://localhost:1234")

    self.mock_state_file.write_text.assert_called_once()

  def test_start_benchmark_invalid_name(self):
    status = self.mcp_cmd.start_benchmark("invalid_benchmark", [])
    self.assertFalse(status.running)
    self.assertIn("Unknown benchmark", status.error)

  def test_start_build_command_manual_defaults(self):
    cmd = self.mcp_cmd._start_build_command("manual", [])
    self.assertIn("--expose-cdp", cmd)
    self.assertIn("--start-after=0s", cmd)
    self.assertIn(f"--run-for={self.mcp_cmd.DEFAULT_MANUAL_DURATION}", cmd)
    self.assertIn("--no-splash", cmd)
    self.assertTrue(any(arg.startswith("--out-dir=") for arg in cmd))

  def test_start_build_command_manual_override(self):
    cmd = self.mcp_cmd._start_build_command(
        "manual", ["--start-after=10s", "--run-for=60s"])
    self.assertIn("--expose-cdp", cmd)
    self.assertIn("--start-after=10s", cmd)
    self.assertNotIn("--start-after=0s", cmd)
    self.assertIn("--run-for=60s", cmd)
    self.assertNotIn(f"--run-for={self.mcp_cmd.DEFAULT_MANUAL_DURATION}", cmd)

  def test_start_build_command_splash_flags(self):
    # No splash flags provided, should add --no-splash
    cmd = self.mcp_cmd._start_build_command("manual", [])
    self.assertIn("--no-splash", cmd)

    # --no-splash provided, should NOT add another one
    cmd = self.mcp_cmd._start_build_command("manual", ["--no-splash"])
    self.assertEqual(cmd.count("--no-splash"), 1)

    # --nosplash provided, should NOT add --no-splash
    cmd = self.mcp_cmd._start_build_command("manual", ["--nosplash"])
    self.assertNotIn("--no-splash", cmd)
    self.assertIn("--nosplash", cmd)

    # --splash provided, should NOT add --no-splash
    cmd = self.mcp_cmd._start_build_command("manual", ["--splash"])
    self.assertNotIn("--no-splash", cmd)
    self.assertIn("--splash", cmd)

  def test_start_build_command_with_positional(self):
    cmd = self.mcp_cmd._start_build_command(
        "loading", ["--url=https://google.com", "extra_arg"])
    self.assertIn("--no-splash", cmd)
    self.assertIn("--url=https://google.com", cmd)
    self.assertIn("extra_arg", cmd)

  def test_split_args(self):
    cb_args, browser_args = self.mcp_cmd._split_args(
        ["--url=https://google.com", "--", "--chrome-flag"])
    self.assertSequenceEqual(cb_args, ["--url=https://google.com"])
    self.assertSequenceEqual(browser_args, ["--", "--chrome-flag"])

    cb_args, browser_args = self.mcp_cmd._split_args(
        ["--url=https://google.com"])
    self.assertSequenceEqual(cb_args, ["--url=https://google.com"])
    self.assertSequenceEqual(browser_args, [])

    # Test that _start_build_command preserves them and adds MCP flags
    with mock.patch(
        "crossbench.plt.base.Platform.is_headless",
        new_callable=mock.PropertyMock) as mock_headless:
      mock_headless.return_value = True
      cmd = self.mcp_cmd._start_build_command(
          "manual", ["--url=https://google.com", "--", "--chrome-flag"])

    expected_cmd = [
        sys.executable,
        str(pth.ROOT_DIR / "cb.py"),
        "manual",
        "--url=https://google.com",
        "--expose-cdp",
        "--start-after=0s",
        "--run-for=1800s",
        "--no-splash",
        "--headless",
        mock.ANY,
        "--",
        "--chrome-flag",
    ]
    self.assertEqual(cmd, expected_cmd)
    self.assertTrue(cmd[9].startswith("--out-dir="))

  def test_stop(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps({
        "pid": 123,
        "endpoint": "ws://localhost:1234",
        "cmd": [],
    })

    mock_process = mock.MagicMock()
    mock_process.poll.return_value = 0
    self.mcp_cmd._process = mock_process

    with mock.patch(
        "crossbench.plt.PLATFORM.send_signal") as mock_send_signal, \
         mock.patch(
             "crossbench.plt.PLATFORM.kill") as mock_kill:
      with mock.patch.object(
          self.mcp_cmd,
          "_get_results_data",
          side_effect=RuntimeError("No results")):
        res = self.mcp_cmd.stop()
        mock_send_signal.assert_called_once()
        mock_kill.assert_not_called()
        self.assertEqual(res, "Benchmark session stopped.")
        self.assertIsNone(self.mcp_cmd._process)

  def test_stop_orphaned_session(self):
    self.mock_state_file.exists.return_value = True
    self.mcp_cmd._process = None

    with mock.patch(
        "crossbench.plt.PLATFORM.terminate_gracefully") as mock_terminate:
      with mock.patch.object(
          self.mcp_cmd,
          "_get_results_data",
          side_effect=RuntimeError("No results")):
        res = self.mcp_cmd.stop()
        mock_terminate.assert_not_called()
        self.mock_state_file.unlink.assert_called_once()
        self.assertEqual(res, "Benchmark session stopped.")

  def test_results_running_error(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps({"pid": 123})
    with mock.patch(
        "crossbench.plt.PLATFORM.process_info", return_value=mock.MagicMock()):
      with self.assertRaises(RuntimeError):
        self.mcp_cmd.results()

  def test_results_success(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps(
        {"out_dir": str(self.mock_out_dir)})

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False) as tmp:
      tmp.write('{"score": 100}')
      tmp_path = pth.LocalPath(tmp.name)

    self.mock_out_dir.glob.return_value = [tmp_path]

    mock_active = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level.exists.return_value = False
    self.mock_out_dir.__truediv__.return_value = mock_active
    mock_active.__truediv__.return_value = mock_top_level

    try:
      res = self.mcp_cmd.results()
      self.assertEqual(res, {"score": 100})
    finally:
      tmp_path.unlink()

  def test_results_with_run(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps(
        {"out_dir": str(self.mock_out_dir)})

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False) as tmp:
      tmp.write('{"run": {"index": 1}, "probes": {"probe1": {"data": 1}}}')
      tmp_path = pth.LocalPath(tmp.name)

    self.mock_out_dir.glob.return_value = [tmp_path]

    mock_active = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level.exists.return_value = False
    self.mock_out_dir.__truediv__.return_value = mock_active
    mock_active.__truediv__.return_value = mock_top_level

    try:
      res = self.mcp_cmd.results(run=1)
      self.assertEqual(res, {"probe1": {"data": 1}})
    finally:
      tmp_path.unlink()

  def test_results_with_run_and_probe(self):
    self.mock_state_file.exists.return_value = True
    self.mock_state_file.read_text.return_value = json.dumps(
        {"out_dir": str(self.mock_out_dir)})

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False) as tmp:
      tmp.write('{"run": {"index": 1}, "probes": {"probe1": {"data": 1}}}')
      tmp_path = pth.LocalPath(tmp.name)

    self.mock_out_dir.glob.return_value = [tmp_path]

    mock_active = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level = mock.MagicMock(spec=pth.LocalPath)
    mock_top_level.exists.return_value = False
    self.mock_out_dir.__truediv__.return_value = mock_active
    mock_active.__truediv__.return_value = mock_top_level

    try:
      res = self.mcp_cmd.results(run=1, probe_name="probe1")
      self.assertEqual(res, {"data": 1})
    finally:
      tmp_path.unlink()

  def test_describe_benchmark(self):
    res = self.mcp_cmd.describe_benchmark()
    self.assertIsInstance(res, dict)
    self.assertIn("manual", res)

  def test_describe_benchmark_with_arg(self):
    res = self.mcp_cmd.describe_benchmark("manual")
    self.assertIsInstance(res, dict)
    self.assertIn("doc", res)

  def test_describe_probes_without_arg(self):
    res = self.mcp_cmd.describe_probes()
    self.assertIsInstance(res, dict)
    self.assertIn("perfetto", res)

  def test_describe_probes_with_arg(self):
    res = self.mcp_cmd.describe_probes("perfetto")
    self.assertIsInstance(res, dict)
    self.assertIn("perfetto", res)

  def test_describe_configs_without_arg(self):
    res = self.mcp_cmd.describe_configs()
    self.assertIsInstance(res, dict)
    self.assertTrue(len(res) > 0)

  def test_describe_configs_with_arg(self):
    all_configs = self.mcp_cmd.describe_configs()
    self.assertTrue(len(all_configs) > 0)

    found = False
    for key in all_configs:
      res = self.mcp_cmd.describe_configs(key)
      if len(res) > 0:
        found = True
        break
      res = self.mcp_cmd.describe_configs(key.lower())
      if len(res) > 0:
        found = True
        break

    self.assertTrue(found, "No config object could be described by its key")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
