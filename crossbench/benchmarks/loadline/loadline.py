# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import logging
import subprocess
from typing import TYPE_CHECKING, ClassVar, Mapping

import pandas as pd
from tabulate import tabulate
from typing_extensions import override

from crossbench.benchmarks.base import RegexFilter
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.parse import ObjectParser
from crossbench.probes.probe import Probe, ProbePriority
from crossbench.probes.results import LocalProbeResult
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.benchmarks.loading.page.base import Page
  from crossbench.plt.base import Platform
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.runner import Runner


class LoadLineProbe(BenchmarkProbeMixin, Probe):
  IS_GENERAL_PURPOSE: ClassVar = False
  PRODUCES_DATA: ClassVar = False
  BENCHMARK_NAME: ClassVar[str] = "LoadLine"
  BENCHMARK_VERSION: ClassVar[str] = ""
  PRIORITY: ClassVar = ProbePriority.PRE_TRACE_PROCESSOR

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._scores_file: pth.LocalPath | None = None
    self._breakdown_file: pth.LocalPath | None = None
    self._warnings: list[str] = []

  def _is_device_online(self, platform: Platform) -> bool:
    # 8.8.8.8 is highly likely to be online, so using it to determine if the
    # device is connected to the internet.
    ping_result = platform.sh(
        "ping",
        "-c1",
        "-W2",
        "8.8.8.8",
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    return ping_result.returncode == 0

  def _check_connectivity(self, runner: Runner) -> None:
    for platform in runner.platforms:
      if not self._is_device_online(platform):
        self._warnings.append(f"Device {platform.unique_name} is not connected "
                              "to internet.")

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    logging.critical("%s Benchmark (%s)", self.BENCHMARK_NAME,
                     self.BENCHMARK_VERSION)
    if len(self._warnings) > 0:
      logging.warning("Warnings registered during the run that can potentially "
                      "affect scores:")
      for warning in self._warnings:
        logging.warning(warning)
    logging.info("-" * 80)
    if scores_file := self._scores_file:
      logging.critical("%s scores:", self.BENCHMARK_NAME)
      logging.critical(
          tabulate(pd.read_csv(scores_file), headers="keys", tablefmt="plain"))
      logging.info("- " * 40)
    if breakdown_file := self._breakdown_file:
      logging.critical("%s breakdown (loading stage durations, in ms):",
                       self.BENCHMARK_NAME)
      logging.critical(
          tabulate(
              pd.read_csv(breakdown_file), headers="keys", tablefmt="plain"))

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    self._scores_file = group.get_local_probe_result_path(self).with_name(
        "benchmark_score.csv")
    self._compute_score(group).to_csv(self._scores_file)
    self._breakdown_file = group.get_local_probe_result_path(self).with_name(
        "breakdown.csv")
    self._compute_breakdown(group).to_csv(self._breakdown_file)
    return LocalProbeResult(csv=(self._scores_file, self._breakdown_file))

  def _load_query_result(self, group: BrowsersRunGroup,
                         query: str) -> pd.DataFrame:
    trace_result = group.results.get_by_name(TraceProcessorProbe.NAME)
    assert trace_result, f"{group} has no TraceProcessorProbe result"
    all_results = trace_result.csv_list
    query_result: pth.LocalPath | None = None
    for result in all_results:
      if result.stem == query:
        query_result = result
        break
    assert query_result is not None, f"{self.NAME}: {query} result not found"
    return pd.read_csv(query_result)

  @abc.abstractmethod
  def _compute_score(self, group: BrowsersRunGroup) -> pd.DataFrame:
    pass

  @abc.abstractmethod
  def _compute_breakdown(self, group: BrowsersRunGroup) -> pd.DataFrame:
    pass


class LoadLinePageFilter(LoadingPageFilter):
  """LoadLine benchmark for phone/tablet."""

  @classmethod
  def add_page_config_parser(cls, parser: argparse.ArgumentParser) -> None:
    page_config_group = parser.add_mutually_exclusive_group()
    cls.add_page_config_arguments(page_config_group)

  @classmethod
  def _add_story_grouping_arguments(
      cls, group: argparse._MutuallyExclusiveGroup) -> None:
    # Loadline always needs separate substories for metrics calculation.
    group.add_argument(
        "--separate",
        action="store_const",
        const=True,
        default=True,
        help="Run each story in a fresh browser (enabled by default).")

  @classmethod
  @override
  def default_stories(cls) -> tuple[Page, ...]:
    return cls.all_stories()

  @classmethod
  @override
  def all_stories(cls) -> tuple[Page, ...]:
    return ()


class LoadLineBenchmark(LoadingBenchmark, metaclass=abc.ABCMeta):
  STORY_FILTER_CLS: ClassVar = LoadLinePageFilter

  _page_config: PagesConfig | None = None

  @classmethod
  @override
  def cli_epilog(cls) -> str:
    return (
        "IMPORTANT: This benchmark requires access to a special Google Cloud "
        "Storage bucket. Please refer to https://chromium.googlesource.com/"
        "crossbench/+/main/config/benchmark/loadline/README.md#cloud-bucket-"
        "access for how to get access.")

  @classmethod
  @abc.abstractmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    pass

  @classmethod
  @abc.abstractmethod
  @override
  def default_network_config_path(cls) -> pth.LocalPath:
    pass

  @classmethod
  @abc.abstractmethod
  def default_pages_config_path(cls) -> pth.LocalPath:
    pass

  @classmethod
  @override
  def get_pages_config(cls,
                       args: argparse.Namespace | None = None) -> PagesConfig:
    # Use manual caching, since args is not hashable.
    if not args or not args.pages_config:
      if cls._page_config is None:
        cls._page_config = PagesConfig.parse(cls.default_pages_config_path())
      return cls._page_config
    if args.config:
      raise argparse.ArgumentTypeError(
          "--config is not supported with loadline.")
    return args.pages_config

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    config = cls.get_pages_config(args)
    assert config, "Missing page config"

    if args.stories:
      all_page_labels = [str(page.label) for page in config.pages]
      regex_filter = RegexFilter(
          all_names=all_page_labels, default_names=all_page_labels)
      filtered_page_labels = regex_filter.process_all(
          ObjectParser.str_list(args.stories, "stories"))
      filtered_pages = tuple(
          page for page in config.pages if page.label in filtered_page_labels)
      config = PagesConfig(pages=filtered_pages, secrets=config.secrets)

    return cls.STORY_FILTER_CLS.from_config(
        cls.DEFAULT_STORY_CLS,  # type: ignore[type-abstract]
        args,
        config).stories

  @classmethod
  @override
  def describe_stories(cls) -> Mapping[str, str]:
    # TODO: Use full story objects
    result: dict[str, str] = {}
    for page_config in cls.get_pages_config().pages:
      result[page_config.any_label] = page_config.first_url
    return result

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return tuple(page.any_label for page in cls.get_pages_config().pages)
