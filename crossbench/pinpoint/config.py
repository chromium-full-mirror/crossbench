# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import re
from typing import Any, Self

from typing_extensions import override

from crossbench.cli.config.flags import FlagsConfig
from crossbench.cli.ui import ui
from crossbench.config import ConfigObject, ConfigParser
from crossbench.helper.collection_helper import close_matches_message
from crossbench.parse import NumberParser
from crossbench.pinpoint import patch_resolver
from crossbench.pinpoint.benchmarks import all_stories, default_story, \
    is_crossbench_benchmark
from crossbench.pinpoint.helper import annotate
from crossbench.pinpoint.list_benchmarks import fetch_benchmarks
from crossbench.pinpoint.list_bots import fetch_bots
from crossbench.pinpoint.list_builds import fetch_builds
from crossbench.pinpoint.list_stories import fetch_stories


@dataclasses.dataclass(frozen=True)
class VariantConfig(ConfigObject):
  """Represents one arm of an A/B test (e.g., base or experiment)."""

  commit: str = "recent"
  patch: str | None = None
  flags: FlagsConfig = dataclasses.field(default_factory=FlagsConfig)

  @classmethod
  @override
  def create(
      cls,
      commit: str = "recent",
      patch: str | None = None,
      flags: FlagsConfig | None = None,
  ) -> Self:
    if flags is None:
      flags = FlagsConfig()
    return cls(commit=commit, patch=patch, flags=flags)

  @classmethod
  def config_parser(cls) -> ConfigParser[VariantConfig]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "commit",
        default="recent",
        type=cls.parse_commit,
        help="Git commit hash for the build. Accepts a full commit hash, "
        "'HEAD' (latest commit), or 'recent' (the most recent build).")
    parser.add_argument(
        "patch",
        type=cls.parse_patch,
        help="Gerrit patch to apply to the commit. Supported formats: "
        "'12345' (optional patchset: '12345/6'), 'c/12345', "
        "'crrev/c/12345', 'crrev/12345', 'crrev.com/c/12345' "
        "'crrev.com/12345', or a full URL. "
        "Note: All patches must be for chromium-review; "
        "chrome-internal-review is not supported.")
    parser.add_argument(
        "flags",
        type=FlagsConfig,
        default=FlagsConfig(),
        help="Chrome flags forwarded to the browser.")
    return parser

  @classmethod
  def parse_commit(cls, value: str) -> str:
    if value.upper() in ("HEAD", "-HEAD", ""):
      return "HEAD"
    if value.lower() == "recent":
      return "recent"
    if re.match(r"^[0-9a-fA-F]{8,40}$", value):
      return value.lower()
    raise ValueError(f"Invalid commit value: {value}")

  @classmethod
  def parse_patch(cls, value: str) -> str:
    return patch_resolver.resolve_patch(value)

  @classmethod
  def parse_str(cls, value: str) -> VariantConfig:
    raise NotImplementedError

  def override_commit(self, commit: str | None, bot: str) -> Self:
    resolved_commit = self.parse_commit(commit or self.commit)
    if resolved_commit == "recent":
      resolved_commit = fetch_builds(bot)[0].commit
    return dataclasses.replace(self, commit=resolved_commit)

  def override_patch(self, patch: str | None) -> Self:
    if not patch:
      return self
    return dataclasses.replace(self, patch=self.parse_patch(patch))

  def override_flags(self,
                     flags: str | None = None,
                     js_flags: str | None = None,
                     enable_features: str | None = None,
                     disable_features: str | None = None,
                     enable_blink_features: str | None = None,
                     disable_blink_features: str | None = None) -> Self:
    extra_flags: dict[str, str | None] = {}
    if flags and flags.strip():
      extra_flags = dict(FlagsConfig.parse(flags)["default"][0].flags.items())
    input_flags = {
        "--js-flags": js_flags,
        "--enable-features": enable_features,
        "--disable-features": disable_features,
        "--enable-blink-features": enable_blink_features,
        "--disable-blink-features": disable_blink_features,
    }
    filtered_flags = {k: v for k, v in input_flags.items() if v is not None}
    combined_flags = self.flags_as_dict() | extra_flags | filtered_flags
    if combined_flags_str := self.flags_dict_to_str(combined_flags):
      return dataclasses.replace(
          self, flags=FlagsConfig.parse(combined_flags_str))
    return self

  def flags_as_dict(self) -> dict[str, str | None]:
    if not self.flags.get("default"):
      return {}
    return dict(self.flags["default"][0].flags.items())

  def flags_as_str(self) -> str | None:
    flags = self.flags_as_dict()
    return self.flags_dict_to_str(flags)

  @classmethod
  def flags_dict_to_str(cls, flags: dict[str, str | None]) -> str | None:
    if not flags:
      return None
    parts = []
    for flag, value in flags.items():
      parts.append(f"{flag}={value}" if value is not None else flag)
    return " ".join(parts)

  def extra_browser_flags(self, is_crossbench: bool) -> str | None:
    flags = self.flags_as_str()
    if not flags:
      return None
    if is_crossbench:
      return flags
    return f'--extra-browser-args="{flags}"'


@dataclasses.dataclass(frozen=True)
class BisectStartVariantConfig(VariantConfig):
  """Represents the start arm of a bisect job."""

  def validate(self) -> None:
    if self.patch:
      raise ValueError(
          "Patch is not supported for start variant in bisect jobs.")


@dataclasses.dataclass(frozen=True)
class BisectEndVariantConfig(VariantConfig):
  """Represents the end arm of a bisect job."""

  def validate(self) -> None:
    if self.patch:
      raise ValueError("Patch is not supported for end variant in bisect jobs.")
    if self.flags and self.flags != FlagsConfig():
      raise ValueError(
          "Flags are not supported for end variant in bisect jobs.")


@dataclasses.dataclass(frozen=True)
class PinpointJobConfigMixin:
  benchmark: str
  bot: str
  story: str | None = None

  @classmethod
  def resolve_benchmark(cls, benchmark: str) -> str | None:
    if not benchmark:
      raise ValueError(
          "Benchmark is required. "
          "Run 'cb pp benchmarks' to list all available benchmarks.")
    available_benchmarks = fetch_benchmarks()
    if benchmark not in available_benchmarks:
      msg, _ = close_matches_message(benchmark, available_benchmarks,
                                     "benchmark")
      return f"{msg}\nRun 'cb pp benchmarks' to list all available benchmarks."
    return None

  @classmethod
  def resolve_bot(cls, bot: str) -> str | None:
    if not bot:
      raise ValueError(
          "Bot is required. Run 'cb pp bots' to list all available bots.")
    available_bots = fetch_bots()
    if bot not in available_bots:
      msg, _ = close_matches_message(bot, available_bots, "bot")
      return f"{msg}\nRun 'cb pp bots' to list all available bots."
    return None

  @classmethod
  def resolve_story(cls, benchmark: str,
                    story: str | None) -> tuple[str | None, str | None]:
    if is_crossbench_benchmark(benchmark):
      if not story:
        story = default_story(benchmark)
      elif story not in all_stories(benchmark):
        return story, f"Unknown story: {story}"
    else:
      stories = fetch_stories(benchmark)
      if not story and len(stories) == 1:
        story = stories[0]

      if story not in stories:
        return story, f"Unknown story: {story}"
    return story, None

  @classmethod
  def parse_extra_browser_args(cls,
                               extra_browser_args: str | None) -> FlagsConfig:
    if not extra_browser_args:
      return FlagsConfig()
    if match := re.search(r'--extra-browser-args="(.*?)"', extra_browser_args):
      return FlagsConfig.parse(match.group(1))
    return FlagsConfig.parse(extra_browser_args)


@dataclasses.dataclass(frozen=True)
class PinpointTryJobConfig(PinpointJobConfigMixin, ConfigObject):
  """Representation of a Pinpoint "try job" configuration."""

  story_tags: str | None = None
  base: VariantConfig = dataclasses.field(default_factory=VariantConfig)
  experiment: VariantConfig = dataclasses.field(default_factory=VariantConfig)
  repeat: int = 30
  bug: int | None = None

  @classmethod
  @override
  def create(
      cls,
      benchmark: str,
      bot: str,
      story: str | None = None,
      story_tags: str | None = None,
      base: VariantConfig | None = None,
      experiment: VariantConfig | None = None,
      repeat: int = 30,
      bug: int | None = None,
  ) -> Self:
    if base is None:
      base = VariantConfig()
    if experiment is None:
      experiment = VariantConfig()
    return cls(
        benchmark=benchmark,
        bot=bot,
        story=story,
        story_tags=story_tags,
        base=base,
        experiment=experiment,
        repeat=repeat,
        bug=bug,
    )

  @classmethod
  def config_parser(cls) -> ConfigParser[PinpointTryJobConfig]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "benchmark",
        type=str,
        help="Benchmark name (e.g., 'speedometer3').",
    )
    parser.add_argument(
        "bot",
        type=str,
        help="The bot configuration to run on (e.g., 'linux-perf')")
    parser.add_argument(
        "story",
        type=str,
        help="Optional story to run within the benchmark. "
        "Obtained automatically for the given benchmark if not specified.",
    )
    parser.add_argument(
        "story_tags",
        type=str,
        help="Optional story tags to filter stories. "
        "Required if no story can be obtained automatically.",
    )
    parser.add_argument(
        "base",
        type=VariantConfig,
        default=VariantConfig(),
        help="Configuration for the base variant of the A/B test.")
    parser.add_argument(
        "experiment",
        type=VariantConfig,
        default=VariantConfig(),
        help="Configuration for the experiment variant of the A/B test.")
    parser.add_argument(
        "repeat",
        type=NumberParser.positive_int,
        default=30,
        help="The number of times to repeat the experiment.")
    parser.add_argument(
        "bug",
        type=NumberParser.positive_int,
        help="Optional bug ID associated with the job.")
    return parser

  @classmethod
  def parse_str(cls, value: str) -> PinpointTryJobConfig:
    raise NotImplementedError

  @classmethod
  def parse_and_override(
      cls,
      config: str | None = None,
      benchmark: str | None = None,
      bot: str | None = None,
      story: str | None = None,
      story_tags: str | None = None,
      repeat: int | None = None,
      bug: int | None = None,
      base_commit: str | None = None,
      exp_commit: str | None = None,
      base_patch: str | None = None,
      exp_patch: str | None = None,
      base_flags: str | None = None,
      exp_flags: str | None = None,
      base_js_flags: str | None = None,
      exp_js_flags: str | None = None,
      base_enable_features: str | None = None,
      exp_enable_features: str | None = None,
      base_disable_features: str | None = None,
      exp_disable_features: str | None = None,
      base_enable_blink_features: str | None = None,
      exp_enable_blink_features: str | None = None,
      base_disable_blink_features: str | None = None,
      exp_disable_blink_features: str | None = None,
  ) -> PinpointTryJobConfig:
    """Create a new valid PinpointTryJobConfig instance for new jobs."""
    with annotate("Parsing job configuration"):
      if config:
        parsed = super().parse(config)
      else:
        parsed = PinpointTryJobConfig(benchmark="", bot="")

      resolved_benchmark = benchmark or parsed.benchmark
      resolved_bot = bot or parsed.bot
      resolved_story = story or parsed.story

      benchmark_warning = cls.resolve_benchmark(resolved_benchmark)
      bot_warning = cls.resolve_bot(resolved_bot)
      resolved_story, story_warning = cls.resolve_story(resolved_benchmark,
                                                        resolved_story)

      warnings = [benchmark_warning, bot_warning, story_warning]

      resolved_story_tags = story_tags or parsed.story_tags
      if not resolved_story and not resolved_story_tags:
        raise ValueError("Story or story_tags must be specified.")

      resolved_repeat = repeat if repeat is not None else parsed.repeat
      resolved_bug = bug if bug is not None else parsed.bug

      base = parsed.base.override_commit(base_commit, bot=resolved_bot)
      base = base.override_patch(base_patch)
      base = base.override_flags(
          flags=base_flags,
          js_flags=base_js_flags,
          enable_features=base_enable_features,
          disable_features=base_disable_features,
          enable_blink_features=base_enable_blink_features,
          disable_blink_features=base_disable_blink_features,
      )

      experiment = parsed.experiment.override_commit(
          exp_commit, bot=resolved_bot)
      experiment = experiment.override_patch(exp_patch)
      experiment = experiment.override_flags(
          flags=exp_flags,
          js_flags=exp_js_flags,
          enable_features=exp_enable_features,
          disable_features=exp_disable_features,
          enable_blink_features=exp_enable_blink_features,
          disable_blink_features=exp_disable_blink_features,
      )

    show_warnings([w for w in warnings if w])

    return cls(
        benchmark=resolved_benchmark,
        bot=resolved_bot,
        story=resolved_story,
        story_tags=resolved_story_tags,
        base=base,
        experiment=experiment,
        repeat=resolved_repeat,
        bug=resolved_bug,
    )

  def to_request_dict(self) -> dict[str, Any]:
    return {
        "comparison_mode":
            "try",
        "benchmark":
            self.benchmark,
        "configuration":
            self.bot,
        "story":
            self.story,
        "story_tags":
            self.story_tags,
        "initial_attempt_count":
            self.repeat,
        "bug_id":
            self.bug,
        "base_git_hash":
            self.base.commit,
        "end_git_hash":
            self.experiment.commit,
        "base_patch":
            self.base.patch,
        "experiment_patch":
            self.experiment.patch,
        "base_extra_args":
            self.base.extra_browser_flags(
                is_crossbench_benchmark(self.benchmark)),
        "experiment_extra_args":
            self.experiment.extra_browser_flags(
                is_crossbench_benchmark(self.benchmark)),
        "tags":
            '{"origin": "pinpoint_cli"}',
    }

  @classmethod
  def from_response_dict(cls, raw_dict: dict[str, Any]) -> PinpointTryJobConfig:
    """Returns a valid PinpointTryJobConfig if the server response is valid."""
    comparison_mode = raw_dict.get("comparison_mode")
    if comparison_mode != "try":
      raise ValueError(
          'Invalid comparison mode {comparison_mode} expected "try".')
    arguments = raw_dict["arguments"]

    def value_or_none(value: Any) -> Any:
      return value if value else None

    # An empty field created from the Web UI is an empty string. Such empty
    # fields are replaced with None to make it possible to convert the result
    # config to JSON and back to PinpointTryJobConfig for creating new jobs.
    return PinpointTryJobConfig(
        benchmark=arguments["benchmark"],
        bot=arguments["configuration"],
        story=value_or_none(arguments.get("story")),
        story_tags=value_or_none(arguments.get("story_tags")),
        repeat=NumberParser.positive_int(arguments["initial_attempt_count"],
                                         "repeat"),
        bug=value_or_none(arguments.get("bug_id")),
        base=VariantConfig(
            commit=arguments.get("base_git_hash"),
            patch=value_or_none(arguments.get("base_patch")),
            flags=cls.parse_extra_browser_args(
                arguments.get("base_extra_args")),
        ),
        experiment=VariantConfig(
            commit=arguments.get("end_git_hash"),
            patch=value_or_none(arguments.get("experiment_patch")),
            flags=cls.parse_extra_browser_args(
                arguments.get("experiment_extra_args")),
        ),
    )

  def to_dict(self) -> dict[str, Any]:
    result = dataclasses.asdict(self)
    result["base"]["flags"] = self.base.flags_as_str()
    result["experiment"]["flags"] = self.experiment.flags_as_str()
    return result


@dataclasses.dataclass(frozen=True)
class PinpointBisectJobConfig(PinpointJobConfigMixin, ConfigObject):
  """Representation of a Pinpoint "bisect job" configuration."""

  chart: str | None = None
  story_tags: str | None = None
  start: BisectStartVariantConfig = dataclasses.field(
      default_factory=BisectStartVariantConfig)
  end: BisectEndVariantConfig = dataclasses.field(
      default_factory=BisectEndVariantConfig)
  repeat: int = 30
  bug: int | None = None

  @classmethod
  @override
  def create(
      cls,
      benchmark: str,
      bot: str,
      chart: str | None = None,
      story: str | None = None,
      story_tags: str | None = None,
      start: BisectStartVariantConfig | None = None,
      end: BisectEndVariantConfig | None = None,
      repeat: int = 30,
      bug: int | None = None,
  ) -> Self:
    if start is None:
      start = BisectStartVariantConfig()
    if end is None:
      end = BisectEndVariantConfig()
    return cls(
        benchmark=benchmark,
        bot=bot,
        chart=chart,
        story=story,
        story_tags=story_tags,
        start=start,
        end=end,
        repeat=repeat,
        bug=bug,
    )

  @classmethod
  def config_parser(cls) -> ConfigParser[PinpointBisectJobConfig]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "benchmark",
        type=str,
        help="Benchmark name (e.g., 'speedometer3').",
    )
    parser.add_argument(
        "bot",
        type=str,
        help="The bot configuration to run on (e.g., 'linux-perf')")
    parser.add_argument(
        "chart", type=str, help="The chart (measurement) to bisect.")
    parser.add_argument(
        "story",
        type=str,
        help="Optional story to run within the benchmark. "
        "Obtained automatically for the given benchmark if not specified.",
    )
    parser.add_argument(
        "story_tags",
        type=str,
        help="Optional story tags to filter stories. "
        "Required if no story can be obtained automatically.",
    )
    parser.add_argument(
        "start",
        type=BisectStartVariantConfig,
        default=BisectStartVariantConfig(),
        help="Configuration for the start variant of the bisect.")
    parser.add_argument(
        "end",
        type=BisectEndVariantConfig,
        default=BisectEndVariantConfig(),
        help="Configuration for the end variant of the bisect.")
    parser.add_argument(
        "repeat",
        type=NumberParser.positive_int,
        default=30,
        help="The number of times to repeat the experiment.")
    parser.add_argument(
        "bug",
        type=NumberParser.positive_int,
        help="Optional bug ID associated with the job.")
    return parser

  @classmethod
  def parse_str(cls, value: str) -> PinpointBisectJobConfig:
    raise NotImplementedError

  @classmethod
  def parse_and_override(
      cls,
      config: str | None = None,
      benchmark: str | None = None,
      bot: str | None = None,
      chart: str | None = None,
      story: str | None = None,
      story_tags: str | None = None,
      repeat: int | None = None,
      bug: int | None = None,
      start_commit: str | None = None,
      end_commit: str | None = None,
      flags: str | None = None,
      js_flags: str | None = None,
      enable_features: str | None = None,
      disable_features: str | None = None,
      enable_blink_features: str | None = None,
      disable_blink_features: str | None = None,
  ) -> PinpointBisectJobConfig:
    """Create a new valid PinpointBisectJobConfig instance for new jobs."""
    with annotate("Parsing job configuration"):
      if config:
        parsed = super().parse(config)
      else:
        parsed = PinpointBisectJobConfig(benchmark="", bot="")

      resolved_benchmark = benchmark or parsed.benchmark
      resolved_bot = bot or parsed.bot
      resolved_story = story or parsed.story

      benchmark_warning = cls.resolve_benchmark(resolved_benchmark)
      bot_warning = cls.resolve_bot(resolved_bot)
      resolved_story, story_warning = cls.resolve_story(resolved_benchmark,
                                                        resolved_story)

      warnings = [benchmark_warning, bot_warning, story_warning]

      resolved_chart = chart or parsed.chart
      if not resolved_chart:
        raise ValueError("Chart is required for bisect jobs.")

      resolved_story_tags = story_tags or parsed.story_tags
      if not resolved_story and not resolved_story_tags:
        raise ValueError("Story or story_tags must be specified.")

      resolved_repeat = repeat or parsed.repeat
      resolved_bug = bug or parsed.bug

      start = parsed.start.override_commit(start_commit, bot=resolved_bot)
      end = parsed.end.override_commit(end_commit, bot=resolved_bot)

      start = start.override_flags(
          flags=flags,
          js_flags=js_flags,
          enable_features=enable_features,
          disable_features=disable_features,
          enable_blink_features=enable_blink_features,
          disable_blink_features=disable_blink_features,
      )

      start.validate()
      end.validate()

    show_warnings([w for w in warnings if w])

    return cls(
        benchmark=resolved_benchmark,
        bot=resolved_bot,
        chart=resolved_chart,
        story=resolved_story,
        story_tags=resolved_story_tags,
        start=start,
        end=end,
        repeat=resolved_repeat,
        bug=resolved_bug,
    )

  def to_request_dict(self) -> dict[str, Any]:
    return {
        "comparison_mode":
            "performance",
        "benchmark":
            self.benchmark,
        "configuration":
            self.bot,
        "chart":
            self.chart,
        "story":
            self.story,
        "story_tags":
            self.story_tags,
        "initial_attempt_count":
            self.repeat,
        "bug_id":
            self.bug,
        "start_git_hash":
            self.start.commit,
        "end_git_hash":
            self.end.commit,
        "extra_test_args":
            self.start.extra_browser_flags(
                is_crossbench_benchmark(self.benchmark)),
        "tags":
            '{"origin": "pinpoint_cli"}',
    }

  @classmethod
  def from_response_dict(cls, raw_dict: dict[str,
                                             Any]) -> PinpointBisectJobConfig:
    """Returns a valid PinpointBisectJobConfig if the server response is
    valid."""
    comparison_mode = raw_dict.get("comparison_mode")
    if comparison_mode != "performance":
      raise ValueError(
          f'Invalid comparison mode {comparison_mode} expected "performance".')
    arguments = raw_dict["arguments"]

    def value_or_none(value: Any) -> Any:
      return value if value else None

    # An empty field created from the Web UI is an empty string. Such empty
    # fields are replaced with None to make it possible to convert the result
    # config to JSON and back to PinpointBisectJobConfig for creating new jobs.
    return PinpointBisectJobConfig(
        benchmark=arguments["benchmark"],
        bot=arguments["configuration"],
        chart=arguments["chart"],
        story=value_or_none(arguments.get("story")),
        story_tags=value_or_none(arguments.get("story_tags")),
        repeat=NumberParser.positive_int(arguments["initial_attempt_count"],
                                         "repeat"),
        bug=value_or_none(arguments.get("bug_id")),
        start=BisectStartVariantConfig(
            commit=arguments.get("start_git_hash"),
            flags=cls.parse_extra_browser_args(
                arguments.get("extra_test_args")),
        ),
        end=BisectEndVariantConfig(commit=arguments.get("end_git_hash")),
    )

  def to_dict(self) -> dict[str, Any]:
    result = dataclasses.asdict(self)
    result["start"]["flags"] = self.start.flags_as_str()
    result["end"]["flags"] = self.end.flags_as_str()
    return result


def show_warnings(warnings: list[str]) -> None:
  if not warnings:
    return

  answer = ui.prompt("\n".join(["Warnings:", *warnings, "Continue?"]), "[Y/n] ")
  if answer.lower().strip() not in ["", "y", "yes"]:
    raise ValueError("Invalid job configuration.")
