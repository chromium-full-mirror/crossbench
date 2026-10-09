# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import subprocess
from typing import IO, TYPE_CHECKING, ClassVar, Iterator, Self

from typing_extensions import override

from crossbench.parse import DurationParser, NumberParser, PathParser
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeContext, \
    ProbeIncompatibleBrowser
from crossbench.probes.probe_error import ProbeValidationError

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner


class BitsProbe(Probe):
  """
  Probe for the external BITS/Kibble power measurement tool.
  Starts BITS in the background on the host during the run
  and stops it afterwards.
  """
  NAME: ClassVar[str] = "bits"
  BITS_CHANNEL_AVERAGES_CSV_NAME: ClassVar[str] = "bits_channel_averages.csv"
  DEFAULT_DURATION: ClassVar[dt.timedelta] = dt.timedelta(seconds=99999)
  DEFAULT_PORT: ClassVar[int] = 15909

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "bits_path",
        aliases=("path",),
        type=PathParser.existing_file_path,
        required=True,
        help="Path to the BITS external tool binary on the host.")
    parser.add_argument(
        "bits_out",
        aliases=(
            "out",
            "collection",
        ),
        type=str,
        required=False,
        default="",
        help="Output identifier for the BITS tool.")
    parser.add_argument(
        "bits_device",
        aliases=("device",),
        type=str,
        default="",
        help="Device identifier for the BITS tool.")
    parser.add_argument(
        "duration",
        type=DurationParser.positive_duration,
        default=cls.DEFAULT_DURATION,
        help="Duration for the BITS tool to run.")
    parser.add_argument(
        "port",
        type=NumberParser.positive_int,
        default=cls.DEFAULT_PORT,
        help="Port number for the BITS tool.")
    return parser

  def __init__(
      self,
      bits_path: pth.LocalPath,
      bits_out: str = "",
      bits_device: str = "",
      duration: dt.timedelta = DEFAULT_DURATION,
      port: int = DEFAULT_PORT,
  ) -> None:
    super().__init__()
    if duration < dt.timedelta(seconds=1):
      raise ValueError(f"Duration must be at least 1s, but got: {duration}")
    self._bits_path: pth.LocalPath = bits_path
    assert self._bits_path.is_file()
    self._bits_service_path: pth.LocalPath = (
        bits_path.parent / "bits_service.sh")
    self._bits_out: str = bits_out
    self._bits_device: str = bits_device
    self._duration: dt.timedelta = duration
    self._port: int = port
    self._service_proc: subprocess.Popen | None = None

  @property
  def bits_path(self) -> pth.LocalPath:
    return self._bits_path

  @property
  def bits_out(self) -> str:
    return self._bits_out

  @property
  def bits_device(self) -> str:
    return self._bits_device

  @property
  def duration(self) -> dt.timedelta:
    return self._duration

  @property
  def port(self) -> int:
    return self._port

  def _get_connected_devices(self) -> list[str] | None:
    res = self.host_platform.sh(
        self.bits_path,
        "--list_devices",
        "--service_port",
        str(self._port),
        check=False,
        capture_output=True,
    )
    if res.returncode != 0:
      return None
    stdout = res.stdout
    if isinstance(stdout, bytes):
      stdout = stdout.decode("utf-8", "replace")
    return [d.strip() for d in stdout.strip().splitlines() if d.strip()]

  def _start_service(
      self, timeout: dt.timedelta = dt.timedelta(seconds=15)) -> None:
    assert self._service_proc is None
    if not self.host_platform.is_file(self._bits_service_path):
      raise ProbeValidationError(self, f"No script: {self._bits_service_path}")
    logging.info("Starting BITS service in background...")
    self._service_proc = self.host_platform.popen(
        str(self._bits_service_path),
        "--port",
        str(self._port),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert self._service_proc.stdout

    # Expected startup stdout sequence from bits_service.sh:
    # 1. "Bits server started, logging to ..." (server process started)
    # 2. "######## INITIALIZING COLLECTORS ########" (hardware calibration)
    # 3. "Successfully retrieved calibration data..." (hardware ready)
    # 4. "[TS] (...) Received SW timestamp #1: ..." (sync acquired, streaming)
    ready_marker = "Received SW timestamp"

    deadline = dt.datetime.now() + timeout
    while dt.datetime.now() < deadline:
      if not (raw := self._service_proc.stdout.readline()):
        self._stop_service()
        raise ProbeValidationError(self, "BITS service stopped unexpectedly.")
      line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
      if ready_marker in line:
        return

    self._stop_service()
    raise ProbeValidationError(self, "Timed out waiting for BITS service.")

  def _stop_service(self) -> None:
    if not self._service_proc:
      return
    logging.info("Stopping BITS service (PID: %s)", self._service_proc.pid)
    self.host_platform.terminate_gracefully(self._service_proc)
    self._service_proc = None

  def _resolve_target_device(self, devices: list[str] | None = None) -> str:
    if devices is None:
      devices = self._get_connected_devices() or []
    if not devices:
      self._stop_service()
      raise ProbeValidationError(self, f"No devices on port {self.port}.")
    if self.bits_device:
      if self.bits_device not in devices:
        self._stop_service()
        raise ProbeValidationError(self, f"Unknown device: {self.bits_device}")
      return self.bits_device
    if len(devices) > 1:
      self._stop_service()
      raise ProbeValidationError(self, "Multiple Bits devices found.")
    return devices[0]

  @override
  def setup(self, runner: Runner) -> None:
    super().setup(runner)

    # Note: If BITS is already running on a different port than self.port,
    # starting a new instance here will fail due to USB conflicts over the
    # Kibble devices. We consciously skip guarding against this.

    if (devices := self._get_connected_devices()) is None:
      self._start_service()
      status = "BITS service started"
    else:
      status = "BITS service is already running"
    device = self._resolve_target_device(devices)
    logging.info("%s (port: %s, device: %s).", status, self.port, device)

  # TODO: Consider adding Probe.teardown() following wider discussion.
  def teardown(self) -> None:
    self._stop_service()

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    if not browser.platform.is_android:
      raise ProbeIncompatibleBrowser(
          self, browser, "BITS probe is only supported on Android devices.")

  @override
  def get_context_cls(self) -> type[BitsProbeContext]:
    return BitsProbeContext


class BitsProbeContext(ProbeContext[BitsProbe]):

  def __init__(self, probe: BitsProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._process: subprocess.Popen | None = None
    self._bits_out_id = self.probe.bits_out or dt.datetime.now().strftime(
        "%Y%m%d_%H%M%S")

  @property
  def bits_out_id(self) -> str:
    return self._bits_out_id

  @contextlib.contextmanager
  def _log_files(self, mode: str) -> Iterator[tuple[IO[str], IO[str]]]:
    stdout_path = self.local_result_path / "stdout.txt"
    stderr_path = self.local_result_path / "stderr.txt"
    with stdout_path.open(mode, encoding="utf-8") as stdout, \
         stderr_path.open(mode, encoding="utf-8") as stderr:
      yield stdout, stderr

  def _start_collection(self) -> None:
    logging.info("Starting BITS collection (ID: %s)", self.bits_out_id)
    self.host_platform.mkdir(self.local_result_path)

    json_path = self.local_result_path / "bits.json"
    self.host_platform.write_text(
        json_path,
        json.dumps({"bits_out_id": self.bits_out_id}, indent=2),
    )

    device_args: tuple[str, ...] = ("--service_port", str(self.probe.port))
    if self.probe.bits_device:
      device_args += ("--device", self.probe.bits_device)

    with self._log_files("w") as (stdout, stderr):
      self._process = self.host_platform.popen(
          self.probe.bits_path,
          "--create",
          self.bits_out_id,
          "--duration",
          f"{self.probe.duration.total_seconds():.0f}s",
          *device_args,
          stdout=stdout,
          stderr=stderr,
      )

  def _stop_collection(self) -> None:
    logging.info("Stopping BITS collection (ID: %s)", self.bits_out_id)
    self._run_service_cmd("--stop", self.bits_out_id)
    avg_path = (
        self.local_result_path / self.probe.BITS_CHANNEL_AVERAGES_CSV_NAME)
    with avg_path.open("w", encoding="utf-8") as avg_file:
      self._run_service_cmd(
          "--print_channel_averages", self.bits_out_id, stdout_file=avg_file)

  def _run_service_cmd(
      self,
      *args: pth.AnyPathLike,
      stdout_file: IO[str] | None = None,
  ) -> None:
    cmd = (
        self.probe.bits_path,
        *args,
        "--service_port",
        str(self.probe.port),
    )
    with self._log_files("a") as (stdout, stderr):
      self.host_platform.sh(*cmd, stdout=stdout_file or stdout, stderr=stderr)

  @override
  def start(self) -> None:
    pass

  @override
  def start_story_run(self) -> None:
    self._start_collection()

  @override
  def stop_story_run(self) -> None:
    self._stop_collection()

  @override
  def stop(self) -> None:
    pass

  @override
  def teardown(self) -> ProbeResult:
    if self.host_platform.exists(self.local_result_path):
      files = [
          f for f in self.local_result_path.iterdir()
          if self.host_platform.is_file(f)
      ]
      return self.local_result(file=files)
    return self.empty_result()
