# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import csv
import functools
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, cast

import pandas as pd
from perfetto.batch_trace_processor.api import BatchTraceProcessor
from tabulate import tabulate
from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.parse import ObjectParser, PathParser
from crossbench.probes.bits import BitsProbe
from crossbench.probes.cb_perfetto.perfetto import PerfettoProbe
from crossbench.probes.probe import Probe, ProbePriority
from crossbench.probes.probe_context import EmptyProbeContext
from crossbench.probes.probe_error import ProbeMissingDataError
from crossbench.probes.results import LocalProbeResult
from crossbench.probes.trace_processor.helper import \
    CBBatchTraceProcessorConfig
from crossbench.probes.trace_processor.query_config import QUERIES_DIR, \
    DeviceSpecificTraceProcessorQuery, TraceProcessorQueryConfig
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe

if TYPE_CHECKING:
  from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.runner import Runner


def _mean_without_outliers(group: pd.Series) -> float:
  """Computes the mean, discarding top and bottom outliers for >=5 runs."""
  if len(group) >= 5:
    return group.sort_values().iloc[1:-1].mean()
  return group.mean()


class WebPowerProbe(BenchmarkProbeMixin, Probe):
  NAME: ClassVar = "web_power_probe"
  PRIORITY: ClassVar = ProbePriority.PRE_TRACE_PROCESSOR
  BENCHMARK_NAME: ClassVar = "WebPower"
  IS_GENERAL_PURPOSE: ClassVar = False
  PRODUCES_DATA: ClassVar = False
  INTERNAL_QUERIES_DIR: ClassVar = (
      pth.ROOT_DIR / "internal" / "probes" / "trace_processor" / "queries" /
      "web_power")
  QUERY_NAME: ClassVar = "power_rails"

  @override
  def get_context_cls(self) -> type[EmptyProbeContext[WebPowerProbe]]:
    return EmptyProbeContext

  @property
  @override
  def benchmark(self) -> WebPowerBenchmarkBase:
    return cast("WebPowerBenchmarkBase", super().benchmark)

  @classmethod
  def _validate_and_resolve_mapping_entry(cls, key: str, value: str,
                                          mapping_dir: pth.LocalPath) -> str:
    ObjectParser.regexp(key, f"mapping key '{key}'")
    sql_file = mapping_dir.parent / f"{value}.sql"
    PathParser.existing_file_path(sql_file, "Mapped SQL file")
    return str(sql_file.resolve())

  @classmethod
  def _load_mapping(cls, mapping_dir: pth.LocalPath) -> dict[str, str]:
    mapping_file = mapping_dir / "mapping.hjson"
    if not mapping_file.is_file():
      raise ValueError(f"Mapping file does not exist: {mapping_file}")
    mapping = ObjectParser.dict(ObjectParser.hjson_file(mapping_file))
    return {
        key: cls._validate_and_resolve_mapping_entry(key, value, mapping_dir)
        for key, value in mapping.items()
    }

  @override
  def get_extra_probes(self, runner: Runner) -> Iterable[Probe]:
    extra_probes: list[Probe] = []

    # BITS: If the user configured BITS via benchmark flags (--bits-path),
    # attach the configured probe. (If the user configured BITS via the generic
    # --probe=bits flag instead, it is already attached to the runner.)
    if self.benchmark.bits_probe and not runner.has_probe("bits"):
      extra_probes.append(self.benchmark.bits_probe)
    is_bits_active = runner.has_probe("bits") or bool(self.benchmark.bits_probe)

    # Perfetto: By default (when BITS is not explicitly added), Web Power
    # measures power rails via Perfetto, unless the user provided a custom
    # Perfetto probe or explicitly disabled Perfetto via --no-probe=perfetto.
    if adding_perfetto := (not is_bits_active and
                           not runner.has_probe("perfetto") and
                           not runner.is_probe_disabled("perfetto")):
      extra_probes.append(self._default_perfetto_probe())
    has_perfetto = adding_perfetto or runner.has_probe("perfetto")

    # TraceProcessor: When Perfetto is active (either user-provided or
    # default-attached), attach the default TraceProcessor to query power rails.
    if has_perfetto and not runner.has_probe("trace_processor"):
      extra_probes.append(self._default_trace_processor_probe())

    return extra_probes

  @classmethod
  def _default_perfetto_probe(cls) -> PerfettoProbe:
    return PerfettoProbe.parse_dict({
        "textproto":
            (config.config_dir() / "benchmark/web_power/perfetto_basic.txtpb"),
        "start_tracing_sequence": "story_run",
    })

  def _default_trace_processor_probe(self) -> TraceProcessorProbe:
    return TraceProcessorProbe(
        queries=[
            self._get_query_config(),
            TraceProcessorQueryConfig.parse_str("web_power/cpu_time"),
        ],
    )

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    result = group.results.get(self)
    if not result or not result.csv:
      return
    scores_file = result.csv
    version_str = ".".join(map(str, self.benchmark.version()))
    scores_table = tabulate(
        pd.read_csv(scores_file),
        headers="keys",
        tablefmt="plain",
        showindex=False)

    logging.critical("%s Benchmark (%s)\n"
                     "%s scores:\n"
                     "%s", self.BENCHMARK_NAME, version_str,
                     self.BENCHMARK_NAME, scores_table)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    result_path = group.get_local_probe_result_path(self)
    scores_file = result_path.with_name("power_scores.csv")
    self._compute_score(group).to_csv(scores_file, index=False)
    return LocalProbeResult(csv=(scores_file,))

  def _compute_score(self, group: BrowsersRunGroup) -> pd.DataFrame:
    trace_result = group.results.get_by_name("trace_processor")
    if trace_result:
      results = trace_result.csv_list
      query_results = [r for r in results if r.stem.endswith(self.QUERY_NAME)]
      if len(query_results) > 1:
        raise ProbeMissingDataError(
            self, f"Multiple {self.QUERY_NAME} results found: {query_results}")

    return self.process_result_dir(
        group.get_local_probe_result_path(self).parent,
        self._get_base_df(group))

  @classmethod
  def _get_odpm_power_rails_data(cls, result_dir: pth.LocalPath,
                                 base_df: pd.DataFrame,
                                 reprocess: bool) -> pd.DataFrame:
    if reprocess:
      if not cls._get_traces(result_dir):
        return pd.DataFrame()
      return cls._reprocess_traces(result_dir, base_df)

    csv_path = result_dir / "trace_processor" / f"{cls.QUERY_NAME}.csv"
    if not csv_path.is_file():
      return pd.DataFrame()
    return pd.read_csv(csv_path)

  @classmethod
  def _get_bits_data(cls, result_dir: pth.LocalPath) -> pd.DataFrame:
    """Discovers and parses all BITS channel average CSVs in the result dir."""
    pattern = f"*/stories/**/bits/{BitsProbe.BITS_CHANNEL_AVERAGES_CSV_NAME}"
    bits_files = [f for f in result_dir.glob(pattern) if f.is_file()]
    records = [
        record for csv_file in bits_files
        if (record := cls._parse_bits_run_record(csv_file, result_dir))
    ]
    return pd.DataFrame(records)

  @classmethod
  def _parse_bits_run_record(cls, csv_file: pth.LocalPath,
                             result_dir: pth.LocalPath) -> dict[str, Any]:
    """Extracts run metadata and channel metrics for a single BITS CSV file."""
    try:
      cb_browser, _, cb_story, cb_run, *_ = csv_file.relative_to(
          result_dir).parts
      return {
          "cb_browser": cb_browser,
          "cb_story": cb_story,
          "cb_run": int(cb_run),
          **cls._parse_bits_channel_averages(csv_file),
      }
    except (ValueError, OSError, csv.Error) as e:
      logging.warning("Failed to parse BITS averages from %s: %s", csv_file, e)
      return {}

  @classmethod
  def _parse_bits_channel_averages(cls,
                                   csv_file: pth.LocalPath) -> dict[str, float]:
    """Parses target BITS channel power averages from a CSV file."""
    channel_map = {
        "CPU:mW": "bits_cpu_mw",
        "SOC_TOTAL:mW": "bits_soc_total_mw",
    }
    results = {metric: float("nan") for metric in channel_map.values()}
    with csv_file.open("r", encoding="utf-8") as f:
      for row in csv.reader(f):
        if len(row) < 2:
          continue
        if metric := channel_map.get(row[0].strip()):
          results[metric] = float(row[1].strip())
    return results

  @classmethod
  def _aggregate_metric_runs(cls, df: pd.DataFrame,
                             columns: list[str]) -> pd.DataFrame:
    """Averages metrics across story runs, discarding outliers for >=5 runs."""
    return (df.groupby([
        "cb_browser",
        "cb_story",
    ])[columns].agg(_mean_without_outliers).reset_index())

  @classmethod
  def _aggregate_odpm_power_rails(cls, df: pd.DataFrame) -> pd.DataFrame:
    df_sum = (
        df.groupby([
            "cb_browser",
            "cb_story",
            "cb_run",
        ])["avg_power_mw"].sum().reset_index(name="odpm_total_mw"))
    return cls._aggregate_metric_runs(df_sum, ["odpm_total_mw"])

  @classmethod
  def _aggregate_bits_data(cls, df: pd.DataFrame) -> pd.DataFrame:
    return cls._aggregate_metric_runs(df, ["bits_cpu_mw", "bits_soc_total_mw"])

  @classmethod
  def _merge_with_base_df(cls, base_df: pd.DataFrame,
                          run_metrics: pd.DataFrame) -> pd.DataFrame:
    """Combines computed metrics with base_df, padding missing runs with NaN.

    Preserves the original column ordering of base_df and appends any newly
    computed metric columns to the end.
    """
    orig_cols = list(base_df.columns)
    for col in orig_cols:
      if col not in run_metrics.columns:
        run_metrics[col] = float("nan")

    if not base_df.empty:
      base_df = base_df.set_index(["cb_browser", "cb_story"])
      run_metrics = run_metrics.set_index(["cb_browser", "cb_story"])
      run_metrics = run_metrics.combine_first(base_df).reset_index()

    new_cols = [c for c in run_metrics.columns if c not in orig_cols]
    return run_metrics[orig_cols + new_cols]

  @classmethod
  def process_result_dir(cls,
                         result_dir: pth.LocalPath,
                         base_df: pd.DataFrame,
                         reprocess: bool = False) -> pd.DataFrame:
    """Processes probe result files and computes aggregated power metrics."""
    metrics_list: list[pd.DataFrame] = []
    if not (df := cls._get_odpm_power_rails_data(result_dir, base_df,
                                                 reprocess)).empty:
      metrics_list.append(cls._aggregate_odpm_power_rails(df))
    if not (bits_df := cls._get_bits_data(result_dir)).empty:
      metrics_list.append(cls._aggregate_bits_data(bits_df))

    if not metrics_list:
      if "odpm_total_mw" not in base_df.columns:
        base_df = base_df.copy()
        base_df["odpm_total_mw"] = "No Data"
      return base_df

    run_metrics = functools.reduce(
        lambda left, right: left.merge(
            right, on=["cb_browser", "cb_story"], how="outer"),
        metrics_list,
    )
    return cls._merge_with_base_df(base_df, run_metrics)

  @classmethod
  def _get_query_config(cls) -> DeviceSpecificTraceProcessorQuery:
    mapping = cls._load_mapping(QUERIES_DIR / "web_power")
    if cls.INTERNAL_QUERIES_DIR.is_dir():
      mapping.update(cls._load_mapping(cls.INTERNAL_QUERIES_DIR))

    return DeviceSpecificTraceProcessorQuery.create(
        name=cls.QUERY_NAME, device_override=mapping)

  @classmethod
  def _get_traces(cls, result_dir: pth.LocalPath) -> list[pth.LocalPath]:
    allowed_exts = (".perfetto-trace", ".perfetto-trace.gz", ".pb", ".pb.gz")
    return [
        t for t in result_dir.glob("*/stories/*/*/*/*")
        if t.is_file() and t.name.endswith(allowed_exts)
    ]

  @classmethod
  def _reprocess_traces(cls, result_dir: pth.LocalPath,
                        base_df: pd.DataFrame) -> pd.DataFrame:
    traces = cls._get_traces(result_dir)
    if not traces:
      raise ValueError(f"No traces found in {result_dir} to reprocess.")

    btp_config = CBBatchTraceProcessorConfig()
    query_config = cls._get_query_config()

    browser_to_model = base_df.set_index("cb_browser")["device_model"].to_dict()

    sql_to_traces: dict[str, list[str]] = {}
    trace_to_meta: dict[str, tuple[str, str, int]] = {}

    for trace in traces:
      cb_browser, _, cb_story, cb_run, *_ = trace.parent.relative_to(
          result_dir).parts

      device_model = browser_to_model[cb_browser]

      resolved = query_config.resolve_for_device_model(device_model)
      if not resolved:
        logging.error("Unsupported device model: %s", device_model)
        continue

      str_trace = str(trace)
      sql_to_traces.setdefault(resolved.sql, []).append(str_trace)
      trace_to_meta[str_trace] = (cb_browser, cb_story, int(cb_run))

    meta_df = pd.DataFrame.from_dict(
        trace_to_meta,
        orient="index",
        columns=["cb_browser", "cb_story", "cb_run"])

    df_list = []
    for sql, batch_traces in sql_to_traces.items():
      with BatchTraceProcessor(traces=batch_traces, config=btp_config) as btp:
        res_df = btp.query_and_flatten(sql)
        if res_df.empty or "_path" not in res_df.columns:
          continue

        if "trace" in res_df.columns:
          res_df = res_df.drop(columns=["trace"])

        res_df = res_df.merge(meta_df, left_on="_path", right_index=True)
        res_df = res_df.drop(columns=["_path"])
        df_list.append(res_df)

    return pd.concat(df_list, ignore_index=True)

  def _get_base_df(self, group: BrowsersRunGroup) -> pd.DataFrame:
    """Create a baseline dataframe with all browser/story combinations
       padded with NaN scores. This gracefully handles unmapped devices."""
    combinations = []
    for run in group.runs:
      combinations.append({
          "cb_browser": run.browser.unique_name,
          "cb_story": run.story.name,
          "odpm_total_mw": float("nan"),
          "bits_cpu_mw": float("nan"),
          "bits_soc_total_mw": float("nan"),
      })
    return pd.DataFrame(
        combinations,
        columns=[
            "cb_browser",
            "cb_story",
            "odpm_total_mw",
            "bits_cpu_mw",
            "bits_soc_total_mw",
        ]).drop_duplicates()
