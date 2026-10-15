# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import datetime as dt
import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar, Final, Iterator, Mapping, \
    Sequence

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import path as pth
from crossbench.benchmarks.base import SubStoryBenchmark
from crossbench.benchmarks.embedder.config.cujs import CUJsConfig
from crossbench.benchmarks.embedder.config.setup_commands import \
    SetupCommandsConfig
from crossbench.browsers.webview.embedder import WebviewEmbedder
from crossbench.cli.ui.ui import timer
from crossbench.parse import ObjectParser
from crossbench.stories.story import Story

if TYPE_CHECKING:
  from crossbench.action_runner.config import ActionRunnerConfig
  from crossbench.benchmarks.loading.config.blocks import ActionBlock
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.plt.types import TupleCmdArgs
  from crossbench.runner.run import Run


class EmbedderStory(Story, metaclass=abc.ABCMeta):

  def __init__(self, name: str, actions: Sequence[ActionBlock]):
    duration = dt.timedelta(seconds=30)
    self._actions = actions
    super().__init__(name, duration)

  def setup(self, run: Run) -> None:
    # TODO(zbikowski): Add a way to ensure embedder is installed.
    # Launching the Google Quick Search app
    run_benchmark = run.benchmark
    assert isinstance(run_benchmark, EmbedderBenchmark)
    run_browser = run.browser
    assert isinstance(run_browser, WebviewEmbedder)
    if run_benchmark.embedder_drop_caches:
      run_browser.adb_force_stop()
      run.browser_platform.sh("am", "kill-all")
      run.browser_platform.clear_memory_page_cache()
    activity = run_benchmark.android_activity
    if "." not in activity:
      activity = f".{activity}"
    cmd: TupleCmdArgs = ("am", "start", "-S", "-W", "-n",
                         f"{run_browser.android_package}/{activity}")
    if action := run_benchmark.android_action:
      if "." not in action:
        action = f"{run_browser.android_package}.{action}"
      cmd = (*cmd, "-a", action)
    for key, value in run_benchmark.android_extras.items():
      cmd = (*cmd, "-e", key, value)
    run.browser_platform.sh(*cmd)
    logging.info("Starting Embedder Benchmark...")

  def run(self, run: Run) -> None:
    with timer():
      logging.info("-" * 80)
      action_runner = run.action_runner
      for block in self._actions:
        for action in block:
          action_runner.run_action(run, action)
    # Empty line to preserve timer output.
    print()
    logging.info("Stopping Embedder Benchmark...")

  def teardown(self, run: Run) -> None:
    # Return to home screen after the story has run
    run.browser_platform.sh("am", "start", "-a", "android.intent.action.MAIN",
                            "-c", "android.intent.category.HOME")

  @classmethod
  def all_story_names(cls) -> tuple[str, ...]:
    return ()


class EmbedderBenchmark(SubStoryBenchmark):
  """
  Benchmark runner for a WV embedder app mode.
  """
  NAME: ClassVar = "embedder"
  DEFAULT_STORY_CLS: ClassVar = EmbedderStory
  _ANDROID_EXTRA_RE: Final[re.Pattern[str]] = re.compile(
      r"(?P<key>[^=:]+)[=:](?P<value>.*)", re.DOTALL)

  def __init__(
      self,
      stories: Sequence[Story],
      action_runner_config: ActionRunnerConfig | None = None,
      embedder_process_name: str = "search",
      embedder_push_files: Sequence[str] = (),
      embedder_setup_command_config: SetupCommandsConfig | None = None,
      embedder_teardown_command_config: SetupCommandsConfig | None = None,
      embedder_drop_caches: bool = False,
      android_action: str = "GOOGLE_SEARCH",
      android_activity: str = "SearchActivity",
      android_extras: Sequence[str | tuple[str, str]] | Mapping[str, str] = (),
  ) -> None:
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS)
    super().__init__(stories, action_runner_config)
    self._embedder_process_name = embedder_process_name
    self._embedder_push_files = embedder_push_files
    self._embedder_setup_command_config = embedder_setup_command_config
    self._embedder_teardown_command_config = embedder_teardown_command_config
    self._embedder_drop_caches = embedder_drop_caches
    self._android_action = android_action
    self._android_activity = android_activity
    self._android_extras: immutabledict[str, str] = (
        self._parse_android_extras(android_extras))

  @property
  def embedder_process_name(self) -> str:
    return self._embedder_process_name

  @property
  def embedder_push_files(self) -> Iterator[tuple[pth.LocalPath, pth.AnyPath]]:
    for push_file in self._embedder_push_files:
      source, destination = push_file.split(":", 1)
      yield pth.LocalPath(source), pth.AnyPosixPath(destination)

  @property
  def embedder_setup_command_config(self) -> SetupCommandsConfig | None:
    return self._embedder_setup_command_config

  @property
  def embedder_teardown_command_config(self) -> SetupCommandsConfig | None:
    return self._embedder_teardown_command_config

  @property
  def embedder_drop_caches(self) -> bool:
    return self._embedder_drop_caches

  @property
  def android_action(self) -> str:
    return self._android_action

  @property
  def android_activity(self) -> str:
    return self._android_activity

  @property
  def android_extras(self) -> immutabledict[str, str]:
    return self._android_extras

  @classmethod
  def parse_android_extra(cls, value: str) -> tuple[str, str]:
    extra = ObjectParser.non_empty_str(value, "android_extra")
    if match := cls._ANDROID_EXTRA_RE.fullmatch(extra):
      return match.group("key"), match.group("value")
    raise argparse.ArgumentTypeError(
        f"Invalid --android-extras format {extra!r}: "
        "expected 'key=value' or 'key:value'.")

  @classmethod
  def _parse_android_extras(
      cls,
      raw_extras: Sequence[str | tuple[str, str]] | Mapping[str, str],
  ) -> immutabledict[str, str]:
    if isinstance(raw_extras, Mapping):
      for key, value in raw_extras.items():
        ObjectParser.non_empty_str(key, "android_extras key")
        ObjectParser.any_str(value, f"android_extras[{key!r}]")
      return immutabledict(raw_extras)
    extras: dict[str, str] = {}
    for extra in raw_extras:
      if isinstance(extra, str):
        key, value = cls.parse_android_extra(extra)
      else:
        key, value = extra
        ObjectParser.non_empty_str(key, "android_extras key")
        ObjectParser.any_str(value, f"android_extras[{key!r}]")
      if key in extras:
        raise argparse.ArgumentTypeError(
            f"Duplicate --android-extras key: {key!r}")
      extras[key] = value
    return immutabledict(extras)

  @classmethod
  @override
  def cli_description(cls) -> str:
    assert cls.__doc__, f"Missing class doc on {cls}"
    return cls.__doc__.strip()

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    super().add_cli_arguments(parser)
    # Workaround to allow passing multiple --embedder-push-files or
    # --android-extras using a flag config that needs to have unique keys.
    parser.allow_abbrev = True
    parser.add_argument(
        "--cujs-config",
        "--cuj-config",
        type=CUJsConfig.parse,
        help="Stories we want to perform in the benchmark run following a"
        "specified scenario.")
    parser.add_argument(
        "--embedder-process-name",
        default="search",
        help="Name of the embedder process.")
    parser.add_argument(
        "--embedder-push-files",
        type=ObjectParser.non_empty_str,
        action="append",
        default=[],
        help="Files to push from host to device, provide one pair of paths "
        "per flag in the format: source:destination")
    parser.add_argument(
        "--embedder-setup-command-config",
        type=SetupCommandsConfig.parse,
        help="Setup commands to run on device before the benchmark.")
    parser.add_argument(
        "--embedder-teardown-command-config",
        type=SetupCommandsConfig.parse,
        help="Teardown commands to run on device after the benchmark.")
    parser.add_argument(
        "--embedder-drop-caches",
        default=False,
        action="store_true",
        help="Drop page cache before running each story.")
    parser.add_argument(
        "--android-action",
        default="GOOGLE_SEARCH",
        type=ObjectParser.any_str,
        help=("The Android action in setup that is passed to the adb intent\n"
              "`am start -a` option. Pass empty string if not applicable."))
    parser.add_argument(
        "--android-activity",
        default="SearchActivity",
        type=ObjectParser.non_empty_str,
        help=("The Android activity name in setup that is passed to the adb\n"
              "intent `am start -n` option."))
    parser.add_argument(
        "--android-extras",
        type=cls.parse_android_extra,
        action="append",
        default=[],
        help=("Intent string extras (-e <key> <value>) to pass to the Android\n"
              "start command, formatted as 'key=value' or 'key:value'."))
    return parser

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> Sequence[Story]:
    config = cls.get_cujs_config(args)
    cujs = tuple(
        EmbedderStory(
            name=cuj_config.label,
            actions=cuj_config.blocks,
        ) for cuj_config in config.cujs)
    return cujs

  @classmethod
  @override
  def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["embedder_process_name"] = args.embedder_process_name
    kwargs["embedder_push_files"] = args.embedder_push_files
    kwargs["embedder_setup_command_config"] = args.embedder_setup_command_config
    kwargs["embedder_teardown_command_config"] = (
        args.embedder_teardown_command_config)
    kwargs["embedder_drop_caches"] = args.embedder_drop_caches
    kwargs["android_action"] = args.android_action
    kwargs["android_activity"] = args.android_activity
    kwargs["android_extras"] = args.android_extras
    return kwargs

  @classmethod
  def get_cujs_config(cls, args: argparse.Namespace) -> CUJsConfig:
    if global_config := args.config:
      # TODO: migrate --config to an already parsed hjson/json dict
      config_file = global_config
      config_data = ObjectParser.hjson_file(config_file)
      if cujs_config_dict := config_data.get("cujs"):
        if args.cujs_config:
          raise argparse.ArgumentTypeError(
              "Conflicting arguments: "
              "either specify a --config file without a 'cujs' property "
              "or remove the --cuj-config argument.")
        # TODO: CUJsConfig.parse_dict should be able to parse the inner dict.
        return CUJsConfig.parse_dict({"cujs": cujs_config_dict})
    return args.cujs_config
