# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import json
import unittest
from typing import TYPE_CHECKING

from crossbench.cli.cli import CrossBenchCLI
from tests import test_helper

if TYPE_CHECKING:
  from tests.test_helper import TestEnv


def _browser_config(device_id, adb_path) -> str:
  return json.dumps({
      "browser": "chrome-stable",
      "driver": {
          "type": "adb",
          "device_id": device_id,
          "adb_bin": adb_path,
      },
  })


class BenchmarkType(enum.StrEnum):
  PHONE = "loadline2-phone"
  TABLET = "loadline2-tablet"
  WEBAPI_PHONE = "loadline2-webapi-phone"
  WEBAPI_TABLET = "loadline2-webapi-tablet"
  DEBUG = "loadline2-phone-debug"


def _verify_default_metrics(out_dir, require_all_metrics=True):
  result_csv = out_dir / "benchmark_score.csv"
  with result_csv.open() as csv:
    lines = csv.readlines()
    assert len(lines) > 1
    if require_all_metrics:
      assert len(lines) == 12

    titles = lines[0].split(",")
    assert len(titles) == 2
    assert titles[0] == "Metric"

    metrics = dict(line.split(",") for line in lines[1:])

    def check_ci_value(val: str) -> None:
      val = val.strip()
      parts = val.split(" ± ")
      assert len(parts) in (
          1,
          2,
      ), f"Value '{val}' does not match expected metric format"
      assert float(parts[0]) > 0, f"Expected positive mean, got {parts[0]}"
      if len(parts) == 2:
        assert (float(parts[1])
                >= 0), f"Expected non-negative delta, got {parts[1]}"

    for metric, value in metrics.items():
      assert metric, f"Encountered empty metric name. CSV contents: {lines}"
      assert value, f"Encountered empty value. CSV contents: {lines}"
      check_ci_value(value)

    if require_all_metrics:
      assert len(metrics) == 11  # 10 metrics + TOTAL
      assert "TOTAL_SCORE" in metrics, f"Total score missing: {lines}"
      value = metrics["TOTAL_SCORE"]
      assert value, f"Encountered empty value. CSV contents: {lines}"
      check_ci_value(value)


def test_loadline2_phone(device_id, adb_path, test_env: TestEnv) -> None:
  _test_loadline2_default(device_id, adb_path, BenchmarkType.PHONE, test_env)


def test_loadline2_tablet(device_id, adb_path, test_env: TestEnv) -> None:
  _test_loadline2_default(device_id, adb_path, BenchmarkType.TABLET, test_env)


# TODO(crbug.com/489679186): Find a way to test LoadLine 2 WebAPI without root.
@unittest.skip("LoadLine2 WebAPI requires root to run")
def test_loadline2_webapi_phone(device_id, adb_path, test_env: TestEnv) -> None:
  _test_loadline2_default(device_id, adb_path, BenchmarkType.WEBAPI_PHONE,
                          test_env)


# TODO(crbug.com/489679186): Find a way to test LoadLine 2 WebAPI without root.
@unittest.skip("LoadLine2 WebAPI requires root to run")
def test_loadline2_webapi_tablet(device_id, adb_path,
                                 test_env: TestEnv) -> None:
  _test_loadline2_default(device_id, adb_path, BenchmarkType.WEBAPI_TABLET,
                          test_env)


def test_loadline2_debug(device_id, adb_path, test_env: TestEnv) -> None:
  _test_loadline2_default(device_id, adb_path, BenchmarkType.DEBUG, test_env)


def _test_loadline2_default(device_id, adb_path, benchmark_type,
                            test_env: TestEnv) -> None:
  cli = CrossBenchCLI()
  browser_config = _browser_config(device_id, adb_path)
  out_dir = test_env.results_dir / f"default_{benchmark_type}"
  cli.run([
      benchmark_type,
      f"--browser={browser_config}",
      "--repeat=1",
      "--debug",
      f"--out-dir={out_dir}",
      "--time-unit=2s",
      *list(test_env.cq_flags),
  ])

  # With only 1 repetition, there's a chance that one story won't produce a
  # metric. To avoid flaky failures, we only check that some metrics are
  # present.
  _verify_default_metrics(out_dir, require_all_metrics=False)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
