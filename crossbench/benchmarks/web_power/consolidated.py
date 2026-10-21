# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Sequence

from typing_extensions import override

from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase, \
    WebPowerStory, WebPowerStoryFilter

if TYPE_CHECKING:
  from crossbench.cli.parser import CBArgumentParser


class WebPowerConsolidatedStoryFilter(WebPowerStoryFilter[WebPowerStory]):
  """Story filter for the consolidated Web Power benchmark."""

  @override
  def stories_from_names(self,
                         names: Sequence[str]) -> tuple[WebPowerStory, ...]:
    stories: list[WebPowerStory] = []
    for name in names:
      story = self._create_story_from_name(name)
      stories.append(story)
    return tuple(stories)

  def _create_story_from_name(self, name: str) -> WebPowerStory:
    for story_cls in WebPowerStory.scenario_classes():
      prefix = f"{story_cls.story_name_cls()}-"
      if name.startswith(prefix):
        site_name = name[len(prefix):]
        return self._instantiate_story(story_cls, site_name)
    raise ValueError(f"Unknown story name: {name}")


class WebPowerBenchmark(WebPowerBenchmarkBase):
  """Consolidated Web Power benchmark."""

  NAME: ClassVar = "web-power"
  DEFAULT_STORY_CLS: ClassVar = WebPowerStory
  STORY_FILTER_CLS: ClassVar = WebPowerConsolidatedStoryFilter
  SITE_REQUIRED: ClassVar[bool] = False

  @classmethod
  @override
  def fast_mode_default_overrides(cls) -> dict[str, object]:
    overrides = super().fast_mode_default_overrides()
    for benchmark_cls in WebPowerBenchmarkBase.scenario_benchmarks():
      overrides.update(benchmark_cls.fast_mode_default_overrides())
    return overrides

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    parser = super().add_cli_arguments(parser)
    for benchmark_cls in WebPowerBenchmarkBase.scenario_benchmarks():
      benchmark_cls.add_scenario_cli_arguments(parser)
    return parser
