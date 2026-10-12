# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing_extensions import override

from crossbench.benchmarks.speedometer.speedometer_3_1 import \
    Speedometer31Benchmark, Speedometer31Probe, Speedometer31ProbeContext, \
    Speedometer31Story
from tests import test_helper
from tests.crossbench.benchmarks.speedometer.helper import \
    Speedometer3BaseTestCase


class Speedometer31TestCase(Speedometer3BaseTestCase):

  @property
  @override
  def benchmark_cls(self):
    return Speedometer31Benchmark

  @property
  @override
  def story_cls(self):
    return Speedometer31Story

  @property
  @override
  def probe_cls(self):
    return Speedometer31Probe

  @property
  @override
  def probe_context_cls(self):
    return Speedometer31ProbeContext

  @property
  @override
  def name(self):
    return "speedometer_3.1"


#  Don't expose abstract BaseTestCase to test runner
del Speedometer3BaseTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
