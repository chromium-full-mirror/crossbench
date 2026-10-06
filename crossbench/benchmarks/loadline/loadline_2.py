# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

import numpy as np
import pandas as pd
from scipy.stats import t as scipy_t
from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.position import PositionConfig
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loading.page.interactive import InteractivePage
from crossbench.benchmarks.loadline.loadline import LoadLineBenchmark, \
    LoadLineProbe
from crossbench.flags.chrome import ChromeFlags
from crossbench.probes.probe_context import ProbeContext

if TYPE_CHECKING:
  import argparse

  from crossbench.action_runner.base import ActionRunner
  from crossbench.benchmarks.loading.page.base import Page
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.flags.base import Flags
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner
  from crossbench.stories.story import Story

# We should increase the minor version number every time there are any changes
# that might affect the benchmark score.
VERSION_STRING: Final[str] = "2.5.0"


def _metric_stats(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
  metric_stats = {}
  for metric, metric_df in df.groupby("metric"):
    values = metric_df["value"].dropna().values
    n = len(values)
    if n == 0:
      continue
    mean = float(np.mean(values))
    if n > 1:
      s = float(np.std(values, ddof=1))
      se = s / np.sqrt(n)
      t = float(scipy_t.ppf(1 - (1 - 0.95) / 2, n - 1))
      delta = t * se
    else:
      delta = 0.0
      se = 0.0
    metric_stats[str(metric)] = {
        "mean": mean,
        "delta": delta,
        "se": se,
        "n": n,
    }
  return metric_stats


def process_scores(df: pd.DataFrame,
                   expected_metrics: int = 10) -> pd.DataFrame:
  run_metrics = (
      df.groupby(["cb_browser", "metric",
                  "cb_run"])["value"].mean().reset_index())
  results: dict[str, dict[str, str]] = {}
  for browser, browser_df in run_metrics.groupby("cb_browser"):
    if not (metric_stats := _metric_stats(browser_df)):
      continue

    log_means = []
    rel_vars = []
    n_values = []
    metric_results: dict[str, str] = {}
    for metric, stats in metric_stats.items():
      metric_mean = stats["mean"]
      metric_delta = stats["delta"]
      # The globo workload was modified at some point, and to keep scores
      # comparable between versions, we introduced a coefficient.
      # See crbug.com/479819560 for details.
      if metric == "globo_homepage_interactive":
        metric_mean *= 0.58
        metric_delta *= 0.58

      if stats["n"] > 1:
        metric_results[metric] = f"{metric_mean:.3f} ± {metric_delta:.3f}"
      else:
        metric_results[metric] = f"{metric_mean:.3f}"

      assert metric_mean > 0
      log_means.append(float(np.log(metric_mean)))
      rel_vars.append(float((stats["se"] / stats["mean"])**2))
      n_values.append(stats["n"])

    metric_results = {m: metric_results[m] for m in sorted(metric_stats.keys())}

    # Only compute the total if all metrics are present.
    if len(log_means) == expected_metrics:
      # Use the Delta Method (first-order Taylor series expansion) to
      # approximate the variance of the total score from the standard errors
      # of individual metrics.
      # Let T = exp(1/M * sum(ln(X_i))). Assuming independent metrics,
      # the variance of ln(X_i) is approximately
      # Var(X_i) / X_i^2 = (SE_i / Mean_i)^2.
      # Therefore, Var(ln(T)) is approx 1/M^2 * sum((SE_i / Mean_i)^2).
      # Applying the Delta Method again for the final exponential
      # transformation gives:
      # SE(T) approx T * sqrt(Var(ln(T))).
      total_mean = float(np.exp(np.mean(log_means)))
      total_df = int(np.round(np.mean([n - 1 for n in n_values])))
      if total_df > 0:
        total_se = (
            total_mean * float(np.sqrt(np.sum(rel_vars))) / len(log_means))
        total_t = float(scipy_t.ppf(0.975, total_df))
        total_delta = total_t * total_se
        metric_results["TOTAL_SCORE"] = (
            f"{total_mean:.3f} ± {total_delta:.3f}")
      else:
        metric_results["TOTAL_SCORE"] = f"{total_mean:.3f}"

    results[str(browser)] = metric_results

  total = pd.DataFrame(results)
  total.index.name = "Metric"
  return total


class LoadLine2Probe(LoadLineProbe):
  NAME: ClassVar = "loadline2_probe"
  BENCHMARK_NAME: ClassVar = "LoadLine2"
  BENCHMARK_VERSION: ClassVar[str] = VERSION_STRING

  @override
  def get_context_cls(self) -> type[LoadLine2ProbeContext]:
    return LoadLine2ProbeContext

  @override
  def setup(self, runner: Runner) -> None:
    super().setup(runner)
    self._check_connectivity(runner)

  @override
  def _compute_score(self, group: BrowsersRunGroup) -> pd.DataFrame:
    df = self._load_query_result(group, "loadline2_benchmark_score")
    return process_scores(df)

  @override
  def _compute_breakdown(self, group: BrowsersRunGroup) -> pd.DataFrame:
    df = self._load_query_result(group, "loadline2_breakdown")
    df["os"] = df[["network", "process_launch"]].max(axis=1)
    df = df.groupby(["cb_browser", "page"])[[
        "os",
        "renderer_visual",
        "renderer_interactive",
        "gpu_visual",
        "gpu_interactive",
    ]].mean()
    df.index.names = ["browser", "story"]
    return df


class LoadLine2ProbeContext(ProbeContext[LoadLine2Probe]):

  def start(self) -> None:
    pass

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    return self.empty_result()


class LoadLine2CombinedPage(CombinedPage):

  @override
  def run_with(self, run: Run, action_runner: ActionRunner,
               multiple_tabs: bool) -> None:
    del multiple_tabs
    for page in self._pages:
      if not isinstance(page, InteractivePage):
        page.run_with(run, action_runner, False)
        continue
      for block in page.blocks:
        if block.label == "load" and run.browser_platform.is_android:
          # Trigger a scheduling boost on devices that boost performance on
          # user input.
          action = ClickAction.create(
              source=InputSource.TOUCH,
              position=PositionConfig.from_coordinates(0, 0))
          action_runner.click_touch(action)
        action_runner.run_blocks(run, page, (block,))

  @override
  def run_once(self, run: Run) -> None:
    self.run_with(run, run.action_runner, self.tabs.multiple_tabs)


class LoadLine2Benchmark(LoadLineBenchmark):
  PROBES: ClassVar = (LoadLine2Probe,)
  DEFAULT_REPETITIONS: ClassVar = 50
  DETERMINISTIC: bool = False

  def __init__(self, *args, deterministic: bool = False, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    if deterministic:
      LoadLine2Benchmark.DETERMINISTIC = True
      LoadLine2Probe.BENCHMARK_VERSION += "-deterministic"

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    super().add_cli_arguments(parser)
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help=("Make Chrome behave more deterministically during loading. Note "
              "that this can affect scores. For experimental use only."))
    parser.add_argument(
        "--benchmark-version", action="version", version=f"{VERSION_STRING}")
    return parser

  @classmethod
  @override
  def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["deterministic"] = args.deterministic
    return kwargs

  @classmethod
  def _base_dir(cls) -> pth.LocalPath:
    return config.config_dir() / "benchmark" / "loadline2"

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config.hjson"

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    pages = super().stories_from_cli_args(args)
    return (LoadLine2CombinedPage(pages, playback=args.playback),)

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if browser_attributes.is_chromium_based:
      chrome_flags = ChromeFlags(flags)
      # By design, Loadline2 wants some stories to always use a new renderer
      # process and some to use an existing renderer, therefore covering both
      # cases. The flag here forces a navigation to a new website to create a
      # new renderer, except when navigating from about:blank. So we can
      # achieve the goal by passing the flag and navigating to about:blank
      # before stories that must use an existing renderer.
      chrome_flags.set("--site-per-process")
      # Also make sure Chrome doesn't create renderers in advance, so that sites
      # that require a new renderer are blocked on new process creation.
      chrome_flags.features.disable("SpareRendererForSitePerProcess")
      # With BFCache on, the web page is kept in memory for some time after
      # navigating away from it. This can interfere with the next page load,
      # increasing measurement noise. To reduce noise, we disable BFCache.
      chrome_flags.set("--disable-back-forward-cache")
      # Additional flags that make Chrome behavior more deterministic, at the
      # expense of making it less representative of real-world usage.
      if cls.DETERMINISTIC:
        # Prevent parsing javascript in a background thread, because less
        # concurrency implies more determinism. Note that trace analysis shows
        # parsing is more relevant for loadline than higher JS compilation
        # tiers.
        chrome_flags.js_flags.set("--no-script-streaming")
        # Run optimization guide hints fetch consistently on start up, to avoid
        # it interfering with a page load at some random moment later.
        chrome_flags.set("--optimization-guide-fetch-hints-override-timer")
      return chrome_flags
    return flags


class LoadLine2PhoneBenchmark(LoadLine2Benchmark):
  """LoadLine 2 benchmark for phones.
  """
  NAME: ClassVar = "loadline2-phone"

  @classmethod
  @override
  def default_pages_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "page_config_phone.hjson"

  @classmethod
  @override
  def default_network_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "network_config_phone.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-phone", "ll2-phone")


class LoadLine2TabletBenchmark(LoadLine2Benchmark):
  """LoadLine 2 benchmark for tablets.
  """
  NAME: ClassVar = "loadline2-tablet"

  @classmethod
  @override
  def default_pages_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "page_config_tablet.hjson"

  @classmethod
  @override
  def default_network_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "network_config_tablet.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-tablet", "ll2-tablet")

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if browser_attributes.is_chromium_based:
      flags.set("--request-desktop-sites")
    return flags


class LoadLine2PhoneDebugBenchmark(LoadLine2PhoneBenchmark):
  """LoadLine 2 benchmark for phones, with more tracing categories, for easier
  performance analysis.
  """
  NAME: ClassVar = "loadline2-phone-debug"
  DEFAULT_REPETITIONS: ClassVar = 1

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_debug.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-phone-debug",)


class LoadLine2TabletDebugBenchmark(LoadLine2TabletBenchmark):
  """LoadLine 2 benchmark for tablets, with more tracing categories, for easier
  performance analysis.
  """
  NAME: ClassVar = "loadline2-tablet-debug"
  DEFAULT_REPETITIONS: ClassVar = 1

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_debug.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("ld2-tablet-debug",)
