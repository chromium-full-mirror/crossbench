# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from crossbench.benchmarks.speedometer.speedometer_3 import \
    Speedometer3Benchmark, Speedometer3Probe, Speedometer3ProbeContext, \
    Speedometer3Story

if TYPE_CHECKING:
  from crossbench.benchmarks.base import VersionParts
  from crossbench.benchmarks.speedometer.speedometer import ProbeClsTupleT


class Speedometer31Probe(Speedometer3Probe):
  """
  Speedometer3-specific probe (compatible with v3.1).
  Extracts all speedometer times and scores.
  """
  NAME: ClassVar[str] = "speedometer_3.1"

  @override
  def get_context_cls(self) -> type[Speedometer31ProbeContext]:
    return Speedometer31ProbeContext


class Speedometer31ProbeContext(Speedometer3ProbeContext):
  pass


class Speedometer31Story(Speedometer3Story):
  __doc__ = Speedometer3Story.__doc__
  NAME: ClassVar[str] = "speedometer_3.1"
  URL: ClassVar[str] = "https://chromium-workloads.web.app/speedometer/v3.1/"
  URL_OFFICIAL: ClassVar[str] = "https://browserbench.org/Speedometer3.1/"
  URL_CHROME_FORK: ClassVar[
      str] = "https://chromium-workloads.web.app/speedometer/v3.1-custom/"


class Speedometer31Benchmark(Speedometer3Benchmark):
  """
  Benchmark runner for Speedometer 3.1
  """
  NAME: ClassVar[str] = "speedometer_3.1"
  DEFAULT_STORY_CLS: ClassVar = Speedometer31Story  # type: ignore
  PROBES: ClassVar[ProbeClsTupleT] = (Speedometer31Probe,)

  @classmethod
  @override
  def version(cls) -> VersionParts:
    return (3, 1)

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("sp", "sp-latest", "speedometer", "speedometer-latest", "sp3",
            "sp3-latest", "speedometer3", "speedometer3-latest",
            "speedometer_3", "speedometer_3-latest", *super().aliases())
