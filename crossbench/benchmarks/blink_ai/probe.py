# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

from typing_extensions import override

from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.parse import DurationParser
from crossbench.probes.json import JsonResultProbe, JsonResultProbeContext
from crossbench.probes.metric import MetricsMerger
from crossbench.probes.vram import VramPoller

if TYPE_CHECKING:
  from crossbench.benchmarks.base import Benchmark
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import ProbeConfigParser
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.actions import Actions
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run
  from crossbench.types import Json

BYTES_PER_MB: Final[int] = 1024 * 1024
DEFAULT_VRAM_INTERVAL: Final[dt.timedelta] = dt.timedelta(seconds=1)
MIN_VRAM_INTERVAL: Final[dt.timedelta] = dt.timedelta(milliseconds=50)


class BlinkAIProbe(BenchmarkProbeMixin, JsonResultProbe):
  """
  Custom probe for Blink AI benchmark.
  Extracts window.metrics from the browser tab and monitors GPU VRAM usage.
  """
  NAME: ClassVar[str] = "blink_ai"

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "vram_interval",
        type=DurationParser.duration_range(min=MIN_VRAM_INTERVAL),
        default=DEFAULT_VRAM_INTERVAL,
        help="Polling interval for VRAM / GPU memory usage.",
    )
    return parser

  def __init__(
      self,
      benchmark: Benchmark | None = None,
      vram_interval: dt.timedelta = DEFAULT_VRAM_INTERVAL,
  ) -> None:
    super().__init__(benchmark=benchmark)
    if vram_interval < MIN_VRAM_INTERVAL:
      raise ValueError(
          f"Polling interval must be >= {MIN_VRAM_INTERVAL.total_seconds()}s, "
          f"but got: {vram_interval}")
    self._vram_interval: Final[dt.timedelta] = vram_interval

  @property
  def vram_interval(self) -> dt.timedelta:
    return self._vram_interval

  @override
  def attach(self, browser: Browser) -> None:
    super().attach(browser)
    for flag in (
        "--disable-component-update",
        "--disable-optimization-guide-model-downloads-for-benchmarking",
    ):
      browser.flags.pop(flag, None)

  @override
  def create_context(self, run: Run) -> BlinkAIProbeContext:
    context = super().create_context(run)
    assert isinstance(context, BlinkAIProbeContext)
    return context

  @override
  def get_context_cls(self) -> type[BlinkAIProbeContext]:
    return BlinkAIProbeContext

  @override
  def merge_stories(self, group: StoriesRunGroup) -> ProbeResult:
    merged = MetricsMerger.merge_json_list(
        repetitions_group.results[self].json
        for repetitions_group in group.repetitions_groups)
    return self.write_group_result(group, merged)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    return self.merge_browsers_json_list(group).merge(
        self.merge_browsers_csv_list(group))


class BlinkAIProbeContext(JsonResultProbeContext[BlinkAIProbe]):
  JS: ClassVar[str] = "return JSON.stringify(window.metrics || {});"

  def __init__(self, probe: BlinkAIProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._vram_poller: Final[VramPoller] = VramPoller(self.browser_platform,
                                                      self.probe.vram_interval)

  @override
  def start(self) -> None:
    super().start()
    self._vram_poller.start()

  @override
  def stop(self) -> None:
    self._vram_poller.stop()
    super().stop()

  @override
  def to_json(self, actions: Actions) -> Json:
    metrics: dict[str, Any] = {}
    if json_payload := actions.js(self.JS):
      metrics.update(json.loads(json_payload))
    self._extract_vram_metrics(metrics)
    return metrics

  def _record_vram_stats(
      self,
      metrics: dict[str, Any],
      prefix: str,
      peak_mb: float,
      baseline_mb: float,
  ) -> dict[str, float]:
    stats = {
        "peak": peak_mb,
        "baseline": baseline_mb,
        "delta": max(0.0, peak_mb - baseline_mb),
    }
    for key, val_mb in stats.items():
      metrics[f"{prefix}_{key}_mb"] = val_mb
      metrics[f"{prefix}_{key}_bytes"] = round(val_mb * BYTES_PER_MB)
    return {f"{key}_mb": val_mb for key, val_mb in stats.items()}

  def _extract_vram_metrics(self, metrics: dict[str, Any]) -> None:
    peak = self._vram_poller.peak
    if not peak:
      return
    baseline = self._vram_poller.baseline
    total_peak = sum(peak.values())
    total_baseline = sum(baseline.get(gpu_id, 0.0) for gpu_id in peak)
    vram_dict: dict[str,
                    Any] = self._record_vram_stats(metrics, "vram", total_peak,
                                                   total_baseline)
    for gpu_id, gpu_peak in peak.items():
      gpu_base = baseline.get(gpu_id, 0.0)
      if len(peak) > 1:
        vram_dict[gpu_id] = self._record_vram_stats(metrics, f"vram_{gpu_id}",
                                                    gpu_peak, gpu_base)
      else:
        vram_dict[gpu_id] = dict(vram_dict)
    metrics["vram"] = vram_dict
