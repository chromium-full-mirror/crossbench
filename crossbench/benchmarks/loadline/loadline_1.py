# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np
from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.loadline.loadline import LoadLineBenchmark, \
    LoadLineProbe
from crossbench.probes.probe_context import ProbeContext

if TYPE_CHECKING:
  import pandas as pd

  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.flags.base import Flags
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.runner import Runner
  from crossbench.stories.story import Story

# We should increase the minor version number every time there are any changes
# that might affect the benchmark score.
VERSION_STRING: Final[str] = "1.6.0"

_DEPRECATION_MESSAGE = (
    "⚠️  Please run LoadLine2 which supersedes this benchmark.")


def process_scores(df: pd.DataFrame) -> pd.DataFrame:
  df = df.groupby(["cb_browser",
                   "cb_story"])["score"].mean().reset_index().pivot(
                       columns=["cb_story"],
                       index=["cb_browser"],
                       values=["score"])
  df = df.droplevel(0, axis=1)
  # The globo workload was modified at some point, and to keep scores
  # comparable between versions, we introduced a coefficient.
  # See crbug.com/479819560 for details.
  if "globo_homepage" in df:
    df["globo_homepage"] *= 0.64
  df["TOTAL_SCORE"] = np.exp(np.log(df).mean(axis=1))
  df.index.rename("browser", inplace=True)
  df = df.reindex(
      columns=(
          ["TOTAL_SCORE", *sorted(
              c for c in df.columns if c != "TOTAL_SCORE")]))
  return df


def process_breakdown(df: pd.DataFrame) -> pd.DataFrame:
  df["os"] = df[["network", "process_launch"]].max(axis=1)
  df = df.groupby([
      "cb_browser",
      "cb_story",
  ])[["os", "renderer", "compositor", "gpu", "surfaceflinger"]].mean()
  df.index.names = ["browser", "story"]
  return df


class LoadLine1Probe(LoadLineProbe):
  NAME: ClassVar = "loadline_probe"
  BENCHMARK_NAME: ClassVar = "LoadLine"
  BENCHMARK_VERSION: ClassVar[str] = VERSION_STRING

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._warnings.append(_DEPRECATION_MESSAGE)

  @override
  def get_context_cls(self) -> type[LoadLine1ProbeContext]:
    return LoadLine1ProbeContext

  @override
  def setup(self, runner: Runner) -> None:
    super().setup(runner)
    self._check_connectivity(runner)

  @override
  def _compute_score(self, group: BrowsersRunGroup) -> pd.DataFrame:
    df = self._load_query_result(group, "loadline_benchmark_score")
    return process_scores(df)

  @override
  def _compute_breakdown(self, group: BrowsersRunGroup) -> pd.DataFrame:
    df = self._load_query_result(group, "loadline_breakdown")
    if any(df["network"] > df["process_launch"]):
      self._warnings.append("Some runs were affected by network latency.")
    return process_breakdown(df)


class LoadLine1ProbeContext(ProbeContext[LoadLine1Probe]):

  def start(self) -> None:
    pass

  @override
  def start_story_run(self) -> None:
    benchmark_type = ("loadline-phone" if "phone" in self.probe.benchmark.NAME
                      else "loadline-tablet")
    self.run.performance_mark(
        f"LoadLine/{benchmark_type}/{self.run.story.name}", prefix="")

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    return self.empty_result()


class LoadLine1Benchmark(LoadLineBenchmark):
  PROBES: ClassVar = (LoadLine1Probe,)
  DEFAULT_REPETITIONS: ClassVar = 100

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    super().add_cli_arguments(parser)
    parser.add_argument(
        "--benchmark-version", action="version", version=f"{VERSION_STRING}")
    return parser

  @classmethod
  def _base_dir(cls) -> pth.LocalPath:
    return config.config_dir() / "benchmark" / "loadline"

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config.hjson"


class LoadLine1PhoneBenchmark(LoadLine1Benchmark):
  """LoadLine benchmark for phones.
  """
  NAME: ClassVar = "loadline-phone"

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
    return ("loadline1-phone", "ld-phone", "ld1-phone", "ll-phone")


class LoadLine1TabletBenchmark(LoadLine1Benchmark):
  """LoadLine benchmark for tablets.
  """
  NAME: ClassVar = "loadline-tablet"

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
    return ("loadline1-tablet", "ld-tablet", "ld1-tablet", "ll-tablet")

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if browser_attributes.is_chromium_based:
      flags.set("--request-desktop-sites")
    return flags


class LoadLine1PhoneDebugBenchmark(LoadLine1PhoneBenchmark):
  """LoadLine benchmark for phones, with more tracing categories, for easier
  performance analysis.
  """
  NAME: ClassVar = "loadline-phone-debug"
  DEFAULT_REPETITIONS: ClassVar = 1

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_debug.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("loadline1-phone-debug", "ld-phone-debug", "ld1-phone-debug")


class LoadLine1TabletDebugBenchmark(LoadLine1TabletBenchmark):
  """LoadLine benchmark for tablets, with more tracing categories, for easier
  performance analysis.
  """
  NAME: ClassVar = "loadline-tablet-debug"
  DEFAULT_REPETITIONS: ClassVar = 1

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config_debug.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("loadline1-tablet-debug", "ld-tablet-debug", "ld1-tablet-debug")


class LoadLine1PhoneFastBenchmark(LoadLine1PhoneBenchmark):
  """LoadLine benchmark for phones, with less repetitions, for faster local
  experiments.
  """
  NAME: ClassVar = "loadline-phone-fast"
  DEFAULT_REPETITIONS: ClassVar = 10

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("loadline1-phone-fast", "ld-phone-fast", "ld1-phone-fast")


class LoadLine1TabletFastBenchmark(LoadLine1TabletBenchmark):
  """LoadLine benchmark for tablets, with less repetitions, for faster local
  experiments.
  """
  NAME: ClassVar = "loadline-tablet-fast"
  DEFAULT_REPETITIONS: ClassVar = 10

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("loadline1-tablet-fast", "ld-tablet-fast", "ld1-tablet-fast")
