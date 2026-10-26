# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Mapping, Sequence

from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.base import RegexFilter
from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  import argparse

  from crossbench.stories.story import Story


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
