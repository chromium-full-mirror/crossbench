# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import unittest
from typing import Any
from unittest import mock

from typing_extensions import override

from crossbench import path as pth
from crossbench.probes.bits import BitsProbe, BitsProbeContext, _ClockSync
from crossbench.probes.probe import ProbeIncompatibleBrowser
from crossbench.probes.probe_error import ProbeValidationError
from crossbench.probes.results import EmptyProbeResult, LocalProbeResult
from tests import test_helper
from tests.crossbench.probes.helper import BaseProbeTestCase


class BitsProbeTestCase(BaseProbeTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(self.bits_path)

  def test_bits_probe_parsing_valid(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "run_id",
        "duration": "1s",
    })
    self.assertEqual(probe.bits_path, self.bits_path)
    self.assertEqual(probe.bits_out, "run_id")
    self.assertEqual(probe.duration, dt.timedelta(seconds=1))

  def test_bits_probe_parsing_default_out(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
    })
    self.assertEqual(probe.bits_out, "")
    run = self.mock_run()
    now = dt.datetime(2026, 7, 2, 17, 0, 55)
    with mock.patch("crossbench.probes.bits.dt.datetime") as mock_datetime:
      mock_datetime.now.return_value = now
      context = probe.create_context(run)
      self.assertEqual(context.bits_out_id, "20260702_170055")

  def test_distinct_runs_have_distinct_ids(self) -> None:
    probe = BitsProbe(self.bits_path)
    run1 = self.mock_run()
    run2 = self.mock_run()

    now = dt.datetime(2026, 7, 2, 17, 0, 55)
    later = dt.datetime(2026, 7, 2, 17, 1, 10)
    with mock.patch("crossbench.probes.bits.dt.datetime") as mock_datetime:
      mock_datetime.now.side_effect = [now, later]
      context1 = probe.create_context(run1)
      context2 = probe.create_context(run2)

    self.assertEqual(context1.bits_out_id, "20260702_170055")
    self.assertEqual(context2.bits_out_id, "20260702_170110")

  def test_bits_probe_non_file_path(self) -> None:
    non_existent = pth.LocalPath(self.platform.default_tmp_dir) / "missing_file"
    with self.assertRaises(AssertionError):
      BitsProbe(non_existent)

  def test_bits_probe_parsing_missing_path(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      BitsProbe.parse_dict({"bits_out": "run_id"})

  def test_bits_probe_parsing_zero_duration(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      BitsProbe.parse_dict({
          "bits_path": str(self.bits_path),
          "bits_out": "run_id",
          "duration": "0s",
      })

  def test_bits_probe_parsing_subsecond_duration(self) -> None:
    with self.assertRaises(ValueError):
      BitsProbe.parse_dict({
          "bits_path": str(self.bits_path),
          "bits_out": "run_id",
          "duration": "500ms",
      })

  def test_bits_probe_parsing_negative_duration(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      BitsProbe.parse_dict({
          "bits_path": str(self.bits_path),
          "bits_out": "run_id",
          "duration": "-5s",
      })

  def test_bits_probe_parsing_default_duration(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
    })
    self.assertEqual(probe.bits_path, self.bits_path)
    self.assertEqual(probe.bits_out, "test_run_id")
    self.assertEqual(probe.duration, BitsProbe.DEFAULT_DURATION)

  def test_bits_probe_parsing_custom_duration(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
        "duration": "2m",
    })
    self.assertEqual(probe.bits_path, self.bits_path)
    self.assertEqual(probe.bits_out, "test_run_id")
    self.assertEqual(probe.duration, dt.timedelta(minutes=2))
    self.assertEqual(probe.bits_device, "")

  def test_bits_probe_parsing_device(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
        "device": "custom_id",
    })
    self.assertEqual(probe.bits_device, "custom_id")

  def test_bits_probe_parsing_device_empty(self) -> None:
    probe_empty = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
        "device": "",
    })
    self.assertEqual(probe_empty.bits_device, "")

  def test_bits_probe_parsing_no_port_specified(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
    })
    self.assertEqual(probe.port, BitsProbe.DEFAULT_PORT)

  def test_bits_probe_parsing_custom_port(self) -> None:
    probe = BitsProbe.parse_dict({
        "bits_path": str(self.bits_path),
        "bits_out": "test_run_id",
        "port": 1234,
    })
    self.assertEqual(probe.port, 1234)

  def test_bits_probe_parsing_zero_port(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      BitsProbe.parse_dict({
          "bits_path": str(self.bits_path),
          "bits_out": "run_id",
          "port": 0,
      })

  def test_bits_probe_parsing_negative_port(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      BitsProbe.parse_dict({
          "bits_path": str(self.bits_path),
          "bits_out": "run_id",
          "port": -8080,
      })

  def test_validate_browser_incompatible(self) -> None:
    probe = BitsProbe(self.bits_path, "test_run_id")
    browser = self.magic_mock_browser
    browser.platform.is_android = False
    env = mock.MagicMock()
    with self.assertRaises(ProbeIncompatibleBrowser):
      probe.validate_browser(env, browser)

  def test_validate_browser_compatible(self) -> None:
    probe = BitsProbe(self.bits_path, "test_run_id")
    browser = self.magic_mock_browser
    browser.platform.is_android = True
    env = mock.MagicMock()
    probe.validate_browser(env, browser)

  def _check_probe_lifecycle(self,
                             bits_device: str,
                             port: int | None = None) -> None:
    kwargs: dict[str, Any] = {}
    if port is not None:
      kwargs["port"] = port
    probe = BitsProbe(
        self.bits_path,
        "test_run_id",
        bits_device=bits_device,
        duration=dt.timedelta(seconds=120),
        **kwargs,
    )
    run = self.mock_run()
    run.browser_session.browser.platform.serial_id = "serial"
    run.browser_session.browser.platform.clock_boottime_ns.return_value = 1

    host_platform = run.browser_session.browser.host_platform
    host_platform.popen = mock.MagicMock()
    host_platform.sh = mock.MagicMock()

    context = probe.create_context(run)

    # 1. start() and start_story_setup() should not touch BITS
    context.start()
    context.start_story_setup()
    host_platform.popen.assert_not_called()

    # 2. start_story_run() should spawn BITS
    context.start_story_run()
    host_platform.popen.assert_called_once()
    call_args = host_platform.popen.call_args.args

    expected_port = port if port is not None else BitsProbe.DEFAULT_PORT
    expected_device_args: list[str] = ["--service_port", str(expected_port)]
    if bits_device:
      expected_device_args += ["--device", bits_device]

    self.assertSequenceEqual(
        call_args,
        (
            self.bits_path,
            "--create",
            "test_run_id",
            "--duration",
            "120s",
            *expected_device_args,
        ),
    )
    self.assertIn("stdout", host_platform.popen.call_args.kwargs)
    self.assertIn("stderr", host_platform.popen.call_args.kwargs)

    # 3. stop_story_run() should stop BITS
    context.stop_story_run()
    expected_stop_args = ["--service_port", str(expected_port)]

    self.assertEqual(len(host_platform.sh.call_args_list), 3)
    stop_call, _, export_call = host_platform.sh.call_args_list
    self.assertSequenceEqual(
        stop_call.args,
        (
            self.bits_path,
            "--stop",
            "test_run_id",
            *expected_stop_args,
        ),
    )
    self.assertIn("stdout", stop_call.kwargs)
    self.assertIn("stderr", stop_call.kwargs)

    expected_perfetto_path = context.local_result_path / "test_run_id.pftrace"
    self.assertSequenceEqual(
        export_call.args,
        (
            self.bits_path,
            "--collection",
            "test_run_id",
            "--channels",
            BitsProbe.PERFETTO_CHANNELS,
            "--write_perfetto",
            expected_perfetto_path,
            *expected_stop_args,
        ),
    )
    self.assertIn("stdout", export_call.kwargs)
    self.assertIn("stderr", export_call.kwargs)

    # Reset mocks to verify that the final stop phase is a clean no-op
    host_platform.popen.reset_mock()
    host_platform.sh.reset_mock()

    # 4. stop() should be a no-op
    context.stop()
    host_platform.popen.assert_not_called()
    host_platform.sh.assert_not_called()

    self.assertIsInstance(context.teardown(), LocalProbeResult)

  def test_probe_lifecycle(self) -> None:
    self._check_probe_lifecycle(bits_device="")

  def test_probe_lifecycle_with_device(self) -> None:
    self._check_probe_lifecycle(bits_device="device_id_123")

  def test_probe_lifecycle_with_port(self) -> None:
    self._check_probe_lifecycle(bits_device="", port=1234)

  def test_probe_lifecycle_with_device_and_port(self) -> None:
    self._check_probe_lifecycle(bits_device="device_id_123", port=1234)

  def test_collect_channel_averages(self) -> None:
    probe = BitsProbe(
        self.bits_path,
        "test_run_id",
        port=1234,
    )
    run = self.mock_run()
    host_platform = run.browser_session.browser.host_platform
    host_platform.popen = mock.MagicMock()
    host_platform.sh = mock.MagicMock()

    context = probe.create_context(run)
    context.start_story_run()
    context.stop_story_run()

    self.assertEqual(len(host_platform.sh.call_args_list), 3)
    _stop_call, avg_call, _export_call = host_platform.sh.call_args_list
    self.assertEqual(
        avg_call.args,
        (
            self.bits_path,
            "--print_channel_averages",
            "test_run_id",
            "--service_port",
            "1234",
        ),
    )
    self.assertIn("stdout", avg_call.kwargs)
    avg_path = (
        context.local_result_path / BitsProbe.BITS_CHANNEL_AVERAGES_CSV_NAME)
    self.assertTrue(avg_path.exists())


class ClockSyncTestCase(unittest.TestCase):

  def setUp(self) -> None:
    super().setUp()
    patcher = mock.patch("crossbench.probes.bits.time")
    self.addCleanup(patcher.stop)
    self.time_ns = patcher.start().time_ns
    self.device = mock.Mock()

  def test_offset_ns(self) -> None:
    self.time_ns.return_value = 1_000
    self.device.clock_boottime_ns.return_value = 5_000
    self.assertEqual(_ClockSync(self.device).offset_ns, 4_000)
    self.device.clock_boottime_ns.return_value = 500
    self.assertEqual(_ClockSync(self.device).offset_ns, -500)

  def test_to_json(self) -> None:
    self.time_ns.side_effect = [900, 1_100] * _ClockSync.SAMPLE_COUNT
    self.device.clock_boottime_ns.return_value = 5_000
    self.assertDictEqual(
        _ClockSync(self.device).to_json(), {
            "host_realtime_ns": 1_000,
            "device_boottime_ns": 5_000,
            "offset_ns": 4_000,
            "round_trip_ns": 200,
        })

  def test_best_of_three(self) -> None:
    # Round trips of 200, 100 and 400 host ticks: the second sample wins,
    # with the host time taken as the midpoint of its bracket.
    self.time_ns.side_effect = [100, 300, 1000, 1100, 2000, 2400]
    self.device.clock_boottime_ns.side_effect = [10, 20, 30]
    sync = _ClockSync(self.device)
    self.assertEqual(
        (sync.round_trip_ns, sync.host_realtime_ns, sync.device_boottime_ns),
        (100, 1050, 20))
    self.assertEqual(self.device.clock_boottime_ns.call_count,
                     _ClockSync.SAMPLE_COUNT)


class BitsProbePerfettoTestCase(BaseProbeTestCase):
  HOST_REALTIME_NS = 1_791_367_605_185_683_067
  DEVICE_BOOTTIME_NS = 505_175_536_601_118

  @override
  def setUp(self) -> None:
    super().setUp()
    self.bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(self.bits_path)
    self.run = self.mock_run()
    self.device = self.run.browser_session.browser.platform
    self.device.clock_boottime_ns.return_value = self.DEVICE_BOOTTIME_NS
    self.host_platform = self.run.browser_session.browser.host_platform
    self.host_platform.popen = mock.MagicMock()
    self.host_platform.sh = mock.MagicMock()
    time_patcher = mock.patch("crossbench.probes.bits.time")
    self.addCleanup(time_patcher.stop)
    time_patcher.start().time_ns.return_value = self.HOST_REALTIME_NS

  def _create_context(
      self,
      trace_bytes: bytes | None = None,
  ) -> tuple[BitsProbeContext, pth.LocalPath]:
    probe = BitsProbe(self.bits_path, "test_run_id", port=1234)
    context = probe.create_context(self.run)
    perfetto_path = context.local_result_path / "test_run_id.pftrace"

    def sh_side_effect(*args: Any, **_: Any) -> None:
      if "--write_perfetto" in args and trace_bytes is not None:
        self.fs.create_file(perfetto_path, contents=trace_bytes)

    self.host_platform.sh.side_effect = sh_side_effect
    return context, perfetto_path

  def _read_bits_json(self, context: BitsProbeContext) -> Any:
    json_path = context.local_result_path / BitsProbe.BITS_JSON_NAME
    with json_path.open(encoding="utf-8") as f:
      return json.load(f)

  def test_save_perfetto(self) -> None:
    context, perfetto_path = self._create_context(b"perfetto-bytes")
    context.start_story_setup()
    context.start_story_run()
    context.stop_story_run()
    self.assertEqual(perfetto_path.read_bytes(), b"perfetto-bytes")
    self.assertEqual(
        self._read_bits_json(context), {
            "bits_out_id": "test_run_id",
            "clock_sync": {
                "host_realtime_ns": self.HOST_REALTIME_NS,
                "device_boottime_ns": self.DEVICE_BOOTTIME_NS,
                "offset_ns": self.DEVICE_BOOTTIME_NS - self.HOST_REALTIME_NS,
                "round_trip_ns": 0,
            },
        })

    result = context.teardown()
    self.assertEqual(result.get_all("pftrace"), [perfetto_path])

  def test_save_perfetto_missing_file(self) -> None:
    context, perfetto_path = self._create_context()
    context.start_story_run()
    with mock.patch("logging.critical") as mock_critical:
      context.stop_story_run()
      mock_critical.assert_called_once_with("Missing BITS Perfetto trace: %s",
                                            perfetto_path)

  def test_clock_sync_failure_keeps_bits_out_id(self) -> None:
    context, _ = self._create_context(b"perfetto-bytes")
    self.device.clock_boottime_ns.side_effect = subprocess.SubprocessError()
    with self.assertRaises(subprocess.SubprocessError):
      context.start_story_setup()
    context.start_story_run()
    context.stop_story_run()
    self.assertEqual(
        self._read_bits_json(context), {"bits_out_id": "test_run_id"})

  def test_clock_sync_is_read_during_story_setup(self) -> None:
    context, _ = self._create_context(b"perfetto-bytes")
    with mock.patch("logging.info") as mock_info:
      context.start_story_setup()
      mock_info.assert_any_call(
          "BITS clock sync: device - host = %d ns (+/- %d ns)",
          self.DEVICE_BOOTTIME_NS - self.HOST_REALTIME_NS, 0)
    self.assertEqual(self.device.clock_boottime_ns.call_count,
                     _ClockSync.SAMPLE_COUNT)
    context.start_story_run()
    context.stop_story_run()
    self.assertEqual(self.device.clock_boottime_ns.call_count,
                     _ClockSync.SAMPLE_COUNT)

  def test_log_results(self) -> None:
    probe = BitsProbe(self.bits_path, "test_run_id")
    trace_path = pth.LocalPath(
        self.platform.default_tmp_dir) / "test_run_id.pftrace"
    self.fs.create_file(trace_path, contents=b"perfetto-bytes")
    run = mock.MagicMock()
    run.results = {probe: LocalProbeResult(file=(trace_path,))}

    group = mock.MagicMock()
    group.runs = [run]
    with mock.patch("logging.critical") as mock_critical:
      probe.log_browsers_result(group)
      mock_critical.assert_any_call("BITS Perfetto trace results:")
      mock_critical.assert_any_call("  - %s : %s", trace_path, "14.00 B")

  def test_log_results_empty(self) -> None:
    probe = BitsProbe(self.bits_path, "test_run_id")
    run = mock.MagicMock()
    run.results = {probe: EmptyProbeResult()}

    group = mock.MagicMock()
    group.runs = [run]
    with mock.patch("logging.critical") as mock_critical:
      probe.log_browsers_result(group)
      mock_critical.assert_not_called()


class BitsProbeServiceTestCase(BaseProbeTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    tmp_dir = pth.LocalPath(self.platform.default_tmp_dir)
    self.bits_path = tmp_dir / "bits"
    self.service_script = tmp_dir / "bits_service.sh"
    self.fs.create_file(self.bits_path)
    self.runner = mock.MagicMock()
    self.mock_proc = mock.MagicMock()
    self.mock_proc.pid = 12345
    sh_patcher = mock.patch.object(self.platform, "sh")
    self.addCleanup(sh_patcher.stop)
    self.mock_sh = sh_patcher.start()

    popen_patcher = mock.patch.object(
        self.platform, "popen", return_value=self.mock_proc)
    self.addCleanup(popen_patcher.stop)
    self.mock_popen = popen_patcher.start()

    # Mock terminate_gracefully to prevent sending real OS signals (SIGTERM)
    # to mock_proc.pid, and to assert whether teardown stopped the process.
    terminate_patcher = mock.patch.object(self.platform, "terminate_gracefully")
    self.addCleanup(terminate_patcher.stop)
    self.mock_terminate = terminate_patcher.start()

  def _sh_result(self, stdout: str | bytes = "") -> subprocess.CompletedProcess:
    if isinstance(stdout, str):
      stdout = stdout.encode("utf-8")
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)

  def _sh_error(self) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"")

  def test_setup_service_already_running(self) -> None:
    self.mock_sh.return_value = self._sh_result("device_1\n")
    probe = BitsProbe(self.bits_path, port=15909)
    with mock.patch("logging.info") as mock_info:
      probe.setup(self.runner)
      mock_info.assert_called_with(
          "%s (port: %s, device: %s).",
          "BITS service is already running",
          15909,
          "device_1",
      )
    self.mock_sh.assert_called_once_with(
        self.bits_path,
        "--list_devices",
        "--service_port",
        "15909",
        check=False,
        capture_output=True,
    )
    self.mock_popen.assert_not_called()
    probe.teardown()
    self.mock_terminate.assert_not_called()

  def test_setup_service_already_running_bytes_stdout(self) -> None:
    self.mock_sh.return_value = self._sh_result(b"device_1\n")
    probe = BitsProbe(self.bits_path, port=15909, bits_device="device_1")
    with mock.patch("logging.info") as mock_info:
      probe.setup(self.runner)
      mock_info.assert_called_with(
          "%s (port: %s, device: %s).",
          "BITS service is already running",
          15909,
          "device_1",
      )
    self.mock_sh.assert_called_once_with(
        self.bits_path,
        "--list_devices",
        "--service_port",
        "15909",
        check=False,
        capture_output=True,
    )
    self.mock_popen.assert_not_called()
    probe.teardown()
    self.mock_terminate.assert_not_called()

  def test_setup_service_missing_script(self) -> None:
    self.mock_sh.return_value = self._sh_error()
    probe = BitsProbe(self.bits_path)
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.mock_sh.assert_called_once()
    self.assertIn("No script: ", str(cm.exception))

  def test_setup_service_auto_start_and_stop(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.side_effect = [self._sh_error(), self._sh_result("device_1\n")]
    self.mock_proc.stdout.readline.side_effect = [
        b"Preparing custom Bits temporary folder...\n",
        b"Launching Bits service...\n",
        b"######## INITIALIZING COLLECTORS ########\n",
        b"[TS] (GB094B002A7) Received SW timestamp #1: host_ns=123\n",
    ]
    probe = BitsProbe(self.bits_path, port=15909)
    with mock.patch("logging.info") as mock_info:
      probe.setup(self.runner)
      mock_info.assert_called_with(
          "%s (port: %s, device: %s).",
          "BITS service started",
          15909,
          "device_1",
      )
    self.mock_popen.assert_called_once_with(
        str(self.service_script),
        "--port",
        "15909",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    probe.teardown()
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_auto_start_custom_port(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.side_effect = [self._sh_error(), self._sh_result("device_1\n")]
    self.mock_proc.stdout.readline.side_effect = [
        "Received SW timestamp\n",
    ]
    probe = BitsProbe(self.bits_path, port=12345)
    probe.setup(self.runner)
    self.mock_popen.assert_called_once_with(
        str(self.service_script),
        "--port",
        "12345",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    probe.teardown()
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_no_devices_detected(self) -> None:
    self.mock_sh.return_value = self._sh_result()
    probe = BitsProbe(self.bits_path, port=15909)
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertIn("No devices on port 15909.", str(cm.exception))

  def test_setup_service_auto_start_no_devices_cleans_up(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.side_effect = [self._sh_error(), self._sh_result("")]
    self.mock_proc.stdout.readline.side_effect = ["Received SW timestamp\n"]
    probe = BitsProbe(self.bits_path, port=15909)
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertIn("No devices on port 15909.", str(cm.exception))
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_multiple_devices_without_device_flag(self) -> None:
    self.mock_sh.return_value = self._sh_result("device_A\ndevice_B\n")
    probe = BitsProbe(self.bits_path, port=15909)
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertIn("Multiple Bits devices found.", str(cm.exception))

  def test_setup_service_target_device_missing(self) -> None:
    self.mock_sh.return_value = self._sh_result("device_B\ndevice_C\n")
    probe = BitsProbe(self.bits_path, bits_device="device_A")
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertIn("Unknown device: device_A", str(cm.exception))

  def test_setup_service_auto_start_device_missing_cleans_up(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.side_effect = [
        self._sh_error(),
        self._sh_result("device_B\ndevice_C\n"),
    ]
    self.mock_proc.stdout.readline.side_effect = ["Received SW timestamp\n"]
    probe = BitsProbe(self.bits_path, bits_device="device_A")
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertIn("Unknown device: device_A", str(cm.exception))
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_target_device_matched(self) -> None:
    self.mock_sh.return_value = self._sh_result("device_A\ndevice_B\n")
    probe = BitsProbe(self.bits_path, bits_device="device_A")
    probe.setup(self.runner)

  def test_setup_service_auto_start_target_device_matched(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.side_effect = [
        self._sh_error(),
        self._sh_result("device_A\ndevice_B\n"),
    ]
    self.mock_proc.stdout.readline.side_effect = ["Received SW timestamp\n"]
    probe = BitsProbe(self.bits_path, bits_device="device_A")
    probe.setup(self.runner)
    probe.teardown()
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_premature_exit(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.return_value = self._sh_error()
    self.mock_proc.stdout.readline.side_effect = [
        "Launching Bits service...\n",
        "ERROR: Port in use\n",
        "",  # EOF
    ]
    probe = BitsProbe(self.bits_path)
    with self.assertRaises(ProbeValidationError) as cm:
      probe.setup(self.runner)
    self.assertEqual(
        str(cm.exception), "Probe(bits): BITS service stopped unexpectedly.")
    self.mock_terminate.assert_called_once_with(self.mock_proc)

  def test_setup_service_timeout(self) -> None:
    self.fs.create_file(self.service_script)
    self.mock_sh.return_value = self._sh_error()
    self.mock_proc.stdout.readline.side_effect = ["Launching...\n"]
    start_time = dt.datetime(2026, 7, 2, 12, 0, 0)
    later_time = dt.datetime(2026, 7, 2, 12, 0, 20)
    probe = BitsProbe(self.bits_path)
    with mock.patch("crossbench.probes.bits.dt.datetime") as mock_dt:
      mock_dt.now.side_effect = [start_time, later_time, later_time]
      with self.assertRaises(ProbeValidationError) as cm:
        probe._start_service(timeout=dt.timedelta(seconds=10))
      self.assertIn("Timed out waiting for BITS service", str(cm.exception))
    self.mock_terminate.assert_called_once_with(self.mock_proc)


class BitsProbeResultsFileTestCase(BaseProbeTestCase):
  MOCK_NOW = dt.datetime(2026, 7, 2, 17, 0, 55)
  MOCK_NOW_STR = "20260702_170055"
  HOST_REALTIME_NS = 1_000
  DEVICE_BOOTTIME_NS = 5_000

  @override
  def setUp(self) -> None:
    super().setUp()
    tmp_dir = pth.LocalPath(self.platform.default_tmp_dir)
    self.bits_path = tmp_dir / "bits"
    self.fs.create_file(self.bits_path)
    self.run = self.mock_run(result_path=tmp_dir / "bits.json")
    device = self.run.browser_session.browser.platform
    device.clock_boottime_ns.return_value = self.DEVICE_BOOTTIME_NS
    self.host_platform = self.run.browser_session.browser.host_platform
    self.host_platform.popen = mock.MagicMock()
    self.host_platform.sh = mock.MagicMock()
    time_patcher = mock.patch("crossbench.probes.bits.time")
    self.addCleanup(time_patcher.stop)
    time_patcher.start().time_ns.return_value = self.HOST_REALTIME_NS

  def _create_context(self, bits_out: str) -> BitsProbeContext:
    probe = BitsProbe(self.bits_path, bits_out=bits_out)
    with mock.patch("crossbench.probes.bits.dt.datetime") as mock_datetime:
      mock_datetime.now.return_value = self.MOCK_NOW
      context = probe.create_context(self.run)
    return context

  def _teardown(self, context: BitsProbeContext) -> LocalProbeResult:
    result = context.teardown()
    self.assertIsInstance(result, LocalProbeResult)
    self.assertTrue(context.local_result_path.exists())
    return result

  def _test_output(self, bits_out: str) -> Any:
    context = self._create_context(bits_out)
    self.assertFalse(context.local_result_path.exists())
    context.start_story_setup()
    context.start_story_run()
    self.assertTrue(context.local_result_path.exists())
    result = self._teardown(context)
    with result.json.open("r", encoding="utf-8") as f:
      return json.load(f)

  def test_explicit_out_id(self) -> None:
    self.assertEqual(
        self._test_output("explicit_id"), {
            "bits_out_id": "explicit_id",
            "clock_sync": {
                "host_realtime_ns": 1_000,
                "device_boottime_ns": 5_000,
                "offset_ns": 4_000,
                "round_trip_ns": 0,
            },
        })

  def test_auto_generated_out_id(self) -> None:
    self.assertEqual(
        self._test_output(""), {
            "bits_out_id": self.MOCK_NOW_STR,
            "clock_sync": {
                "host_realtime_ns": 1_000,
                "device_boottime_ns": 5_000,
                "offset_ns": 4_000,
                "round_trip_ns": 0,
            },
        })

  def test_without_start(self) -> None:
    context = self._create_context("test_run_id")
    self.assertFalse(context.local_result_path.exists())
    result = context.teardown()
    self.assertIsInstance(result, EmptyProbeResult)
    self.assertFalse(context.local_result_path.exists())

  def test_story_setup_without_start(self) -> None:
    context = self._create_context("test_run_id")
    context.start_story_setup()
    self.assertFalse(context.local_result_path.exists())
    self.assertIsInstance(context.teardown(), EmptyProbeResult)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
