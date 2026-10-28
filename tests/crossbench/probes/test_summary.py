# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock

from crossbench import path as pth
from crossbench.probes.internal.summary import ResultsSummaryProbe
from crossbench.probes.results import EmptyProbeResult, LocalProbeResult, \
    ProbeResultDict
from tests import test_helper


class ResultsSummaryProbeTestCase(unittest.TestCase):

  def test_merge_missing(self):
    group = mock.Mock()
    group.first_run.results = ProbeResultDict(pth.AnyPath("test/out/results"))
    probe = ResultsSummaryProbe()
    result = probe.merge_cache_temperatures(group)
    self.assertTrue(result.is_empty)

  def test_merge_empty(self):
    group = mock.Mock()
    first_run = mock.Mock()
    group.runs = [first_run]
    first_run.results = ProbeResultDict(pth.AnyPath("test/out/results"))
    probe = ResultsSummaryProbe()
    first_run.results[probe] = EmptyProbeResult()
    with mock.patch.object(probe, "write_group_result") as mock_write:
      probe.merge_repetitions(group)
    mock_write.assert_called()

  def test_merge_repetitions_missing(self):
    probe = ResultsSummaryProbe()
    with tempfile.TemporaryDirectory() as tmp_dir:
      result_file = pth.LocalPath(tmp_dir) / "cb.results.json"
      browser_data = {"log": {}}
      run_data = {
          "browser": browser_data,
          "cwd": "run/0",
          "probes": {},
          "success": True,
          "errors": [],
      }
      with result_file.open("w", encoding="utf-8") as f:
        json.dump(run_data, f)
      good_run = mock.Mock()
      good_run.results = ProbeResultDict(pth.AnyPath("test/out/results/0"))
      good_run.results[probe] = LocalProbeResult(json=(result_file,))
      failed_run = mock.Mock()
      failed_run.results = ProbeResultDict(pth.AnyPath("test/out/results/1"))
      group = mock.Mock()
      group.runs = [good_run, failed_run]
      with mock.patch.object(probe, "write_group_result") as mock_write:
        probe.merge_repetitions(group)
    mock_write.assert_called_once()
    merged_data = mock_write.call_args.args[1]
    self.assertEqual(len(merged_data["repetitions"]), 1)
    self.assertEqual(merged_data["repetitions"][0]["cwd"], "run/0")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
