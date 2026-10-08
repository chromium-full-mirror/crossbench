# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end tests for the Web Power benchmarks.

CQ runs Android tests on a Linux x86_64 emulator, which lacks hardware ODPM
power rails. As a result, odpm_total_mw in power_scores.csv is left empty (NaN)
on CQ and can only be tested locally against a supported Pixel device.

To verify that the benchmark actually did work on CQ, we also check for
non-zero Chrome CPU time.
"""

from __future__ import annotations

import collections
import csv
from typing import TYPE_CHECKING, Final, Sequence

import pytest

from crossbench import path as pth
from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase
from crossbench.cli.cli import CrossBenchCLI
from crossbench.parse import NumberParser
from tests import test_helper

if TYPE_CHECKING:
  from crossbench.types import TableData
  from tests.test_helper import TestEnv

_POWER_SCORES_FILENAME: Final[str] = "power_scores.csv"
_CPU_TIME_RELPATH: Final[pth.LocalPath] = (
    pth.LocalPath("trace_processor") / "web_power_cpu_time.csv")
_EXPECTED_COLUMNS: Final[tuple[str, ...]] = (
    "cb_browser",
    "cb_story",
    "odpm_total_mw",
    "bits_cpu_mw",
    "bits_soc_total_mw",
)
# TODO(cambr): Import from web_power.base to avoid stale refs.
_CANONICAL_SITES: Final[tuple[str, ...]] = ("ajnews", "cnn", "msn")
_SITE_SCENARIOS: Final[tuple[str, ...]] = ("idle", "scroll", "page-load")
# Repetitions come from --fast to keep CQ runtime short.
_DEFAULT_ITERATIONS: Final[int] = (
    WebPowerBenchmarkBase.fast_mode_default_overrides()["repetitions"])


def _run_web_power(
    subcommand: str,
    browser_config: str,
    test_env: TestEnv,
    extra_args: Sequence[str],
) -> None:
  CrossBenchCLI().run([
      subcommand,
      f"--browser={browser_config}",
      f"--out-dir={test_env.results_dir}",
      "--fast",
      "--required-device-config-mode=warn",
      *extra_args,
      *test_env.cq_flags,
  ])


def _load_csv(csv_path: pth.LocalPath) -> TableData:
  """Reads a CSV file as a table of rows and columns.

  Args:
    csv_path: Path to the CSV file to read.

  Returns:
    A list of rows, where each outer item is a row and each inner item is a
    column string.
  """
  with csv_path.open(encoding="utf-8") as csv_file:
    return list(csv.reader(csv_file))


def _load_power_scores(results_dir: pth.LocalPath) -> dict[str, dict[str, str]]:
  rows = _load_csv(results_dir / _POWER_SCORES_FILENAME)
  assert rows, f"Empty {_POWER_SCORES_FILENAME} in {results_dir}"
  headers = tuple(rows[0])
  assert (headers == _EXPECTED_COLUMNS
         ), f"Unexpected headers {headers}, expected {_EXPECTED_COLUMNS}"

  scores: dict[str, dict[str, str]] = {}
  for row in rows[1:]:
    assert len(row) == len(_EXPECTED_COLUMNS), (
        f"Expected {len(_EXPECTED_COLUMNS)} columns in row {row}, "
        f"got {len(row)}")
    row_dict = dict(zip(headers, row, strict=True))
    assert row_dict["cb_browser"], f"Missing cb_browser in row: {row_dict}"
    story = row_dict["cb_story"]
    assert (story not in scores
           ), f"Duplicate story {story!r} in {_POWER_SCORES_FILENAME}: {rows}"
    scores[story] = row_dict
  return scores


def _verify_cpu_time(
    results_dir: pth.LocalPath,
    expected_stories: Sequence[str],
    expected_iterations: int = _DEFAULT_ITERATIONS,
) -> None:
  rows = _load_csv(results_dir / _CPU_TIME_RELPATH)
  assert (
      len(rows)
      > 1), f"Expected header and data rows in {_CPU_TIME_RELPATH}, got: {rows}"
  headers = rows[0]
  story_idx = headers.index("cb_story")
  run_idx = headers.index("cb_run")
  cpu_time_idx = headers.index("cpu_time_ms")

  cpu_time_by_story_run: dict[str, dict[int, float]] = collections.defaultdict(
      lambda: collections.defaultdict(float))
  for row in rows[1:]:
    story = row[story_idx]
    run_number = NumberParser.positive_zero_int(row[run_idx])
    cpu_time = NumberParser.positive_zero_float(row[cpu_time_idx])
    cpu_time_by_story_run[story][run_number] += cpu_time

  assert sorted(cpu_time_by_story_run) == sorted(expected_stories), (
      f"Expected stories {sorted(expected_stories)} in {_CPU_TIME_RELPATH}, "
      f"got {sorted(cpu_time_by_story_run)}")
  expected_runs = set(range(expected_iterations))
  for story, runs in cpu_time_by_story_run.items():
    assert set(runs) == expected_runs, (
        f"Expected {expected_iterations} iterations ({expected_runs}) "
        f"for {story}, got {sorted(runs)}")
    for run_number, total_cpu_ms in runs.items():
      assert total_cpu_ms > 0, (
          f"Expected positive cpu_time_ms for {story} (run {run_number}), "
          f"got {total_cpu_ms}")


def _verify_power_scores(
    results_dir: pth.LocalPath,
    expected_stories: Sequence[str],
) -> None:
  scores = _load_power_scores(results_dir)
  assert sorted(scores) == sorted(expected_stories), (
      f"Expected stories {expected_stories}, got {sorted(scores)}")
  for story, row in scores.items():
    odpm_val = row["odpm_total_mw"].strip()
    if not odpm_val:
      # Handle devices without ODPM power rails (e.g. emulators).
      continue
    assert (NumberParser.positive_zero_float(odpm_val)
            > 0), f"Invalid odpm_total_mw for {story}: {row}"


@pytest.mark.parametrize(
    "subcommand,extra_args,expected_stories",
    [
        (
            "web-power",
            [],
            [
                *(f"web-power-{scenario}-{site}" for scenario in _SITE_SCENARIOS
                  for site in _CANONICAL_SITES),
                "web-power-media-playback-youtube",
            ],
        ),
        (
            "web-power-media-playback",
            ["--volume=unchanged", "--no-fullscreen"],
            ["web-power-media-playback-youtube"],
        ),
        *((
            f"web-power-{scenario}",
            [f"--site={site}"],
            [f"web-power-{scenario}-{site}"],
        ) for scenario in _SITE_SCENARIOS for site in _CANONICAL_SITES),
        *((
            "web-power",
            [f"--stories=#{scenario}"],
            [f"web-power-{scenario}-{site}" for site in _CANONICAL_SITES],
        ) for scenario in _SITE_SCENARIOS),
        *((
            "web-power",
            [f"--stories=#{site}"],
            [f"web-power-{scenario}-{site}" for scenario in _SITE_SCENARIOS],
        ) for site in _CANONICAL_SITES),
    ],
)
def test_web_power(
    browser_config: str,
    test_env: TestEnv,
    subcommand: str,
    extra_args: Sequence[str],
    expected_stories: Sequence[str],
) -> None:
  _run_web_power(subcommand, browser_config, test_env, extra_args)

  _verify_power_scores(test_env.results_dir, expected_stories)
  _verify_cpu_time(test_env.results_dir, expected_stories)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
