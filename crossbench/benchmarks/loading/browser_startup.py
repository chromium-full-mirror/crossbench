# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Mapping, Sequence

import pandas as pd
from tabulate import tabulate
from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.base import RegexFilter
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.parse import ObjectParser
from crossbench.probes.probe import Probe, ProbePriority
from crossbench.probes.probe_context import EmptyProbeContext
from crossbench.probes.results import EmptyProbeResult, LocalProbeResult
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe

if TYPE_CHECKING:
  import argparse

  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.stories.story import Story


class BrowserStartupProbe(BenchmarkProbeMixin, Probe):
  """Summarizes browser startup trace_processor metrics per story."""

  NAME: ClassVar = "browser_startup"
  PRIORITY: ClassVar = ProbePriority.PRE_TRACE_PROCESSOR
  IS_GENERAL_PURPOSE: ClassVar = False
  PRODUCES_DATA: ClassVar = False
  SUMMARY_CSV_NAME: ClassVar = "startup_summary.csv"
  METADATA_COLUMNS: ClassVar[frozenset[str]] = frozenset({
      "cb_browser",
      "cb_story",
      "cb_temperature",
      "cb_run",
  })
  SUMMARY_COLUMNS: ClassVar[tuple[str, ...]] = (
      "metric",
      "cb_story",
      "cb_browser",
      "count",
      "median",
      "p90",
      "iqr",
      "mean",
      "std",
      "min",
      "max",
  )

  @override
  def get_context_cls(self) -> type[EmptyProbeContext[BrowserStartupProbe]]:
    return EmptyProbeContext

  @classmethod
  def compute_summary(
      cls, csv_files: Sequence[pth.LocalPath]) -> pd.DataFrame:
    rows: list[dict[str, str | int | float]] = []
    for csv_path in csv_files:
      rows.extend(cls._summarize_csv_file(csv_path))
    return pd.DataFrame(rows, columns=cls.SUMMARY_COLUMNS)

  @classmethod
  def _summarize_csv_file(
      cls, csv_path: pth.LocalPath) -> list[dict[str, str | int | float]]:
    if not csv_path.is_file() or csv_path.stat().st_size == 0:
      return []
    try:
      df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
      return []
    if df.empty or not {"cb_browser", "cb_story"}.issubset(df.columns):
      return []
    rows: list[dict[str, str | int | float]] = []
    metric_cols = [
        col for col in df.columns if col not in cls.METADATA_COLUMNS
    ]
    for metric_col in metric_cols:
      rows.extend(cls._summarize_metric_column(df, str(metric_col)))
    return rows

  @classmethod
  def _summarize_metric_column(
      cls, df: pd.DataFrame,
      metric_col: str) -> list[dict[str, str | int | float]]:
    numeric_df = df[["cb_story", "cb_browser"]].copy()
    numeric_df["value"] = pd.to_numeric(df[metric_col], errors="coerce")
    numeric_df = numeric_df.dropna(subset=["value"])
    if numeric_df.empty:
      return []
    rows: list[dict[str, str | int | float]] = []
    grouped = numeric_df.groupby(["cb_story", "cb_browser"], sort=False)
    for (story, browser), group_df in grouped:
      series = group_df["value"]
      count = int(len(series))
      p90 = float(series.quantile(0.90))
      q75 = float(series.quantile(0.75))
      q25 = float(series.quantile(0.25))
      rows.append({
          "metric": metric_col,
          "cb_story": str(story),
          "cb_browser": str(browser),
          "count": count,
          "median": float(series.median()),
          "p90": p90,
          "iqr": q75 - q25,
          "mean": float(series.mean()),
          "std": float(series.std(ddof=1)) if count > 1 else 0.0,
          "min": float(series.min()),
          "max": float(series.max()),
      })
    return rows

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    if not (trace_result := group.results.get_by_name(
        TraceProcessorProbe.NAME)):
      return EmptyProbeResult()
    if not (csv_list := trace_result.csv_list):
      return EmptyProbeResult()
    summary_df = self.compute_summary(csv_list)
    if summary_df.empty:
      return EmptyProbeResult()
    summary_file = group.get_local_probe_result_path(self).with_name(
        self.SUMMARY_CSV_NAME)
    summary_df.to_csv(summary_file, index=False)
    return LocalProbeResult(csv=(summary_file,))

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    if not (result := group.results.get(self)) or not result.csv_list:
      return
    summary_file = result.csv
    summary_table = tabulate(
        pd.read_csv(summary_file),
        headers="keys",
        tablefmt="plain",
        showindex=False,
        floatfmt=".2f")
    logging.critical("Browser Startup Summary:\n%s", summary_table)


class BrowserStartupPageFilter(LoadingPageFilter):
  """Page filter for browser startup benchmark."""

  @classmethod
  @override
  def _add_story_grouping_arguments(
      cls, group: argparse._MutuallyExclusiveGroup) -> None:
    group.add_argument(
        "--combined",
        dest="separate",
        action="store_false",
        help="Run each story in the same session.")
    group.add_argument(
        "--separate",
        action="store_true",
        help="Run each story in a fresh browser. (default)")
    group.set_defaults(separate=True)


class BrowserStartupBenchmark(LoadingBenchmark):
  """Benchmark for measuring browser startup performance."""

  NAME = "browser-startup"
  PROBES: ClassVar = (BrowserStartupProbe,)
  STORY_FILTER_CLS: ClassVar = BrowserStartupPageFilter

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ()

  @classmethod
  def _base_dir(cls) -> pth.LocalPath:
    return config.config_dir() / "benchmark" / "browser_startup"

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe.hjson"

  @classmethod
  def default_pages_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "story.hjson"

  @classmethod
  @override
  def get_pages_config(cls,
                       args: argparse.Namespace | None = None) -> PagesConfig:
    if args and (pages_config := args.pages_config):
      return pages_config
    return PagesConfig.parse(cls.default_pages_config_path())

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> Sequence[Story]:
    page_config = cls.get_pages_config(args)
    if stories := args.stories:
      all_page_labels = [page.any_label for page in page_config.pages]
      regex_filter = RegexFilter(
          all_names=all_page_labels, default_names=all_page_labels)
      filtered_page_labels = regex_filter.process_all(
          ObjectParser.str_list(stories, "stories"))
      filtered_pages = tuple(page for page in page_config.pages
                             if page.any_label in filtered_page_labels)
      page_config = PagesConfig(
          pages=filtered_pages, secrets=page_config.secrets)
    return cls.STORY_FILTER_CLS.from_config(
        cls.DEFAULT_STORY_CLS,  # type: ignore[type-abstract]
        args,
        page_config).stories

  @classmethod
  @override
  def describe_stories(cls) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for page_config in cls.get_pages_config().pages:
      result[page_config.any_label] = page_config.first_url
    return result

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return tuple(page.any_label for page in cls.get_pages_config().pages)
