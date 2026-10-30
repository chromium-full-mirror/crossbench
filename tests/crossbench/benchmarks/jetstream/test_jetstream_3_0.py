# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing_extensions import override

from crossbench.benchmarks.jetstream.jetstream_3_0 import \
    JetStream30Benchmark, JetStream30Probe, JetStream30ProbeContext, \
    JetStream30Story
from tests import test_helper
# Only import module to avoid exposing the abstract test classes to the runner.
from tests.crossbench.benchmarks.jetstream import jetstream_helper


class JetStream30TestCase(jetstream_helper.JetStream3BaseTestCase):

  @property
  @override
  def benchmark_cls(self):
    return JetStream30Benchmark

  @property
  @override
  def story_cls(self):
    return JetStream30Story

  @property
  @override
  def probe_cls(self):
    return JetStream30Probe

  @property
  @override
  def probe_context_cls(self):
    return JetStream30ProbeContext

  @property
  def name(self):
    return "jetstream_3.0"


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
