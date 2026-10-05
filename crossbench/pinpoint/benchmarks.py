# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from immutabledict import immutabledict

import crossbench.benchmarks.all as benchmarks
from crossbench.benchmarks.base import StoryFilter

if TYPE_CHECKING:
  from crossbench.benchmarks.base import Benchmark

_BENCHMARK_BY_PINPOINT_NAME: Final[immutabledict[
    str, type[Benchmark]]] = immutabledict({
        "blink-ai.crossbench": benchmarks.BlinkAIBenchmark,
        "devtools_frontend.crossbench": benchmarks.DevToolsFrontendBenchmark,
        "embedder.crossbench": benchmarks.EmbedderBenchmark,
        "jetstream2.crossbench": benchmarks.JetStream22Benchmark,
        "jetstream2.0.crossbench": benchmarks.JetStream20Benchmark,
        "jetstream2.1.crossbench": benchmarks.JetStream21Benchmark,
        "jetstream2.2.crossbench": benchmarks.JetStream22Benchmark,
        "jetstream3.crossbench": benchmarks.JetStream30Benchmark,
        "jetstream3.0.crossbench": benchmarks.JetStream30Benchmark,
        "jetstream-main.crossbench": benchmarks.JetStreamMainBenchmark,
        "loading.crossbench": benchmarks.LoadingBenchmark,
        "loadline_phone.crossbench": benchmarks.LoadLine1PhoneBenchmark,
        "loadline_tablet.crossbench": benchmarks.LoadLine1TabletBenchmark,
        "loadline2_phone.crossbench": benchmarks.LoadLine2PhoneBenchmark,
        "loadline2_tablet.crossbench": benchmarks.LoadLine2TabletBenchmark,
        "memory.desktop": benchmarks.MemoryBenchmark,
        "motionmark1.0.crossbench": benchmarks.MotionMark10Benchmark,
        "motionmark1.1.crossbench": benchmarks.MotionMark11Benchmark,
        "motionmark1.2.crossbench": benchmarks.MotionMark12Benchmark,
        "motionmark1.3.crossbench": benchmarks.MotionMark13Benchmark,
        "motionmark1.3.1.crossbench": benchmarks.MotionMark131Benchmark,
        "motionmark1.3.2.crossbench": benchmarks.MotionMark132Benchmark,
        "motionmark2.0.crossbench": benchmarks.MotionMark20Benchmark,
        "speedometer": benchmarks.Speedometer10Benchmark,
        "speedometer2.crossbench": benchmarks.Speedometer21Benchmark,
        "speedometer2.0.crossbench": benchmarks.Speedometer20Benchmark,
        "speedometer2.1.crossbench": benchmarks.Speedometer21Benchmark,
        "speedometer3.crossbench": benchmarks.Speedometer31Benchmark,
        "speedometer3.0.crossbench": benchmarks.Speedometer30Benchmark,
        "speedometer3.1.crossbench": benchmarks.Speedometer31Benchmark,
        "speedometer-main.crossbench": benchmarks.SpeedometerMainBenchmark,
    })

_BENCHMARK_NAME_BY_PINPOINT_NAME: Final[immutabledict[
    str, str]] = immutabledict({
        v.NAME: k for k, v in _BENCHMARK_BY_PINPOINT_NAME.items()
    })


def pinpoint_benchmark_name(crossbench_name: str) -> str | None:
  return _BENCHMARK_NAME_BY_PINPOINT_NAME.get(crossbench_name)


def is_crossbench_benchmark(pinpoint_name: str) -> bool:
  return pinpoint_name in _BENCHMARK_BY_PINPOINT_NAME


def all_stories(pinpoint_name: str) -> list[str]:
  benchmark = _BENCHMARK_BY_PINPOINT_NAME.get(pinpoint_name)
  if not benchmark:
    return []
  stories = list(benchmark.DEFAULT_STORY_CLS.all_story_names())
  if default_story_name := default_story(pinpoint_name):
    return [default_story_name, *stories]
  return stories


def default_story(pinpoint_name: str) -> str | None:
  benchmark = _BENCHMARK_BY_PINPOINT_NAME.get(pinpoint_name)
  if not benchmark:
    return None
  filter_cls = getattr(benchmark, "STORY_FILTER_CLS", StoryFilter)
  return filter_cls.DEFAULT_STORY_NAME
