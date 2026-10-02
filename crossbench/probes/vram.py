# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import threading
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

from typing_extensions import override

from crossbench.parse import DurationParser
from crossbench.probes.json import JsonResultProbe, JsonResultProbeContext
from crossbench.probes.metric import MetricsMerger

if TYPE_CHECKING:
  from crossbench.plt.base import Platform
  from crossbench.probes.probe import ProbeConfigParser
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.actions import Actions
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run
  from crossbench.types import Json

_MIN_POLL_INTERVAL: Final[dt.timedelta] = dt.timedelta(seconds=0.05)
_DEFAULT_POLL_INTERVAL: Final[dt.timedelta] = dt.timedelta(seconds=1)

class VramProbe(JsonResultProbe):
  """
  Probe to monitor GPU VRAM / Unified RAM usage during a run.
  Supports Nvidia, AMD, Intel, Apple Silicon macOS, Windows, Linux, and Android.
  """
  NAME: ClassVar[str] = "vram"

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_default_argument(
        "interval",
        type=DurationParser.duration_range(
            min=_MIN_POLL_INTERVAL, name="interval"),
        default=_DEFAULT_POLL_INTERVAL,
        help="Polling interval for VRAM / GPU memory usage.")
    return parser

  def __init__(self, interval: dt.timedelta = _DEFAULT_POLL_INTERVAL) -> None:
    super().__init__()
    if interval < _MIN_POLL_INTERVAL:
      raise ValueError(f"Interval {interval} is too small, must be >= 0.05s")
    self._interval = interval

  @property
  def interval(self) -> dt.timedelta:
    return self._interval

  @override
  def get_context_cls(self) -> type[VramProbeContext]:
    return VramProbeContext

  @override
  def merge_stories(self, group: StoriesRunGroup) -> ProbeResult:
    merged = MetricsMerger.merge_json_list(
        repetitions_group.results[self].json
        for repetitions_group in group.repetitions_groups)
    return self.write_group_result(group, merged)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    return self.merge_browsers_json_list(group)


class VramPoller:
  """Background thread to poll GPU VRAM / Unified memory at regular
  intervals."""

  def __init__(self, platform: Platform, interval: dt.timedelta) -> None:
    self._platform: Platform = platform
    self._interval: dt.timedelta = interval
    self._thread: threading.Thread | None = None
    self._stop_event = threading.Event()
    self._baseline: dict[str, float] = {}
    self._peak: dict[str, float] = {}
    self._lock = threading.Lock()

  @property
  def peak(self) -> dict[str, float]:
    with self._lock:
      return dict(self._peak)

  @property
  def baseline(self) -> dict[str, float]:
    with self._lock:
      return dict(self._baseline)

  def start(self) -> None:
    initial = self._platform.gpu_vram_used()
    with self._lock:
      self._baseline = dict(initial)
      self._peak = dict(initial)

    self._stop_event.clear()
    self._thread = threading.Thread(target=self._run, daemon=True)
    self._thread.start()

  def stop(self) -> None:
    if self._thread:
      self._stop_event.set()
      self._thread.join(timeout=5)
      self._thread = None

  def _run(self) -> None:
    interval_s = self._interval.total_seconds()
    while not self._stop_event.wait(interval_s):
      current = self._platform.gpu_vram_used()
      with self._lock:
        for gpu_id, mem in current.items():
          if gpu_id not in self._peak or mem > self._peak[gpu_id]:
            self._peak[gpu_id] = mem


class VramProbeContext(JsonResultProbeContext[VramProbe]):
  _poller: VramPoller

  def __init__(self, probe: VramProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._poller = VramPoller(self.browser_platform, self.probe.interval)

  @override
  def start(self) -> None:
    self._poller.start()

  @override
  def stop(self) -> None:
    self._poller.stop()
    # Call base method so _json_data is extracted and saved for teardown
    super().stop()

  @override
  def to_json(self, actions: Actions) -> Json:
    del actions
    peak = self._poller.peak
    baseline = self._poller.baseline
    if not peak:
      return {}

    metrics: dict[str, Any] = {}
    for gpu_id, peak_mem in peak.items():
      metrics[f"{gpu_id}/peak_mb"] = peak_mem
      base_mem = baseline.get(gpu_id, 0.0)
      metrics[f"{gpu_id}/baseline_mb"] = base_mem
      metrics[f"{gpu_id}/delta_mb"] = max(0.0, peak_mem - base_mem)

    # If single GPU, also expose root peak_mb, baseline_mb, and delta_mb
    if len(peak) == 1:
      gpu_id = next(iter(peak))
      metrics["peak_mb"] = peak[gpu_id]
      metrics["baseline_mb"] = baseline.get(gpu_id, 0.0)
      metrics["delta_mb"] = max(0.0, peak[gpu_id] - baseline.get(gpu_id, 0.0))
    elif len(peak) > 1:
      total_peak = sum(peak.values())
      total_base = sum(baseline.values())
      metrics["peak_mb"] = total_peak
      metrics["baseline_mb"] = total_base
      metrics["delta_mb"] = max(0.0, total_peak - total_base)

    return metrics
