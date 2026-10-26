# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import logging
import re
from typing import TYPE_CHECKING, ClassVar, Final, Iterator, Mapping, Self, \
    Sequence

from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.enums import ReadyState, WindowTarget
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.meminfo import MeminfoAction
from crossbench.action_runner.action.switch_tab import SwitchTabAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.benchmarks.loading.config.blocks import ActionBlock
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.benchmarks.loading.page.base import Page
from crossbench.benchmarks.loading.page.interactive import InteractivePage
from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import DurationParser, NumberParser
from crossbench.replacements import Replacements

if TYPE_CHECKING:
  import argparse

  from crossbench.action_runner.action.action import Action
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.runner.run import Run
  from crossbench.stories.story import Story
  from crossbench.types import JsonDict

STORY_NAME: Final[str] = "multiwindow-memory-stress"
SCRIPTS_DIR: Final[pth.LocalPath] = pth.LocalPath(__file__).parent / "scripts"
STRESS_ALLOC_JS: Final[pth.LocalPath] = SCRIPTS_DIR / "stress_alloc.js"
REVISIT_TAB_JS: Final[pth.LocalPath] = SCRIPTS_DIR / "revisit_tab.js"

STARTER_URL: Final[str] = ("data:text/html,<title>Starter</title>"
                           "<body>Starting multiwindow-memory-stress</body>")
# The title is part of the URL so that it is kept if a discarded tab is
# reloaded, which is needed to find the tab again with SwitchTabAction.
STRESS_TAB_URL_TEMPLATE: Final[str] = (
    "data:text/html,<!doctype html><html><head><title>Tab {tab_index}</title>"
    "</head><body><h2>Stress Tab</h2></body></html>")

DEFAULT_WINDOWS: Final[int] = 6
DEFAULT_TABS_PER_WINDOW: Final[int] = 5
DEFAULT_TAB_WAIT: Final[dt.timedelta] = dt.timedelta(milliseconds=400)
DEFAULT_REVISIT_WAIT: Final[dt.timedelta] = dt.timedelta(milliseconds=250)

# Default per-tab sizes per GiB of device memory.
ALLOC_MB_PER_GIB: Final[float] = 22.5
IMAGES_PER_GIB: Final[float] = 1.25
MIN_IMAGE_COUNT: Final[int] = 2

MEMINFO_TIMEOUT: Final[dt.timedelta] = dt.timedelta(seconds=60)
REVISIT_JS_TIMEOUT: Final[dt.timedelta] = dt.timedelta(seconds=60)
STARTER_LOAD_TIMEOUT: Final[dt.timedelta] = dt.timedelta(minutes=1)
TAB_LOAD_TIMEOUT: Final[dt.timedelta] = dt.timedelta(minutes=3)
COOLDOWN_DURATION: Final[dt.timedelta] = dt.timedelta(seconds=10)

WINDOWS_HELP: Final[str] = "Number of browser windows to open."
TABS_PER_WINDOW_HELP: Final[str] = "Number of tabs to open in each window."
ALLOC_MB_HELP: Final[str] = (
    "MB of anonymous JS heap to allocate per tab. "
    f"Default is {ALLOC_MB_PER_GIB} MB per GiB of device memory.")
IMAGE_COUNT_HELP: Final[str] = (
    "Number of discardable images (~2 MB each when decoded) to create per "
    f"tab. Default is {IMAGES_PER_GIB} per GiB of device memory, "
    f"at least {MIN_IMAGE_COUNT}.")
TAB_WAIT_HELP: Final[str] = (
    "Wait after the allocation and after the first revisit of each newly "
    "opened tab.")
REVISIT_WAIT_HELP: Final[str] = "Wait after revisiting each tab."


class MultiwindowMemoryStressStoryFilter(LoadingPageFilter):
  """
  Create multiwindow-memory-stress story.
  """

  @classmethod
  @override
  def add_cli_arguments(
      cls, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = super().add_cli_arguments(parser)
    group = parser.add_argument_group("Multiwindow Memory Stress Options")
    group.add_argument(
        "--windows",
        type=NumberParser.positive_int,
        default=DEFAULT_WINDOWS,
        help=f"{WINDOWS_HELP} Default is {DEFAULT_WINDOWS}.")
    group.add_argument(
        "--tabs-per-window",
        type=NumberParser.positive_int,
        default=DEFAULT_TABS_PER_WINDOW,
        help=f"{TABS_PER_WINDOW_HELP} Default is {DEFAULT_TABS_PER_WINDOW}.")
    group.add_argument(
        "--alloc-mb",
        type=NumberParser.positive_zero_int,
        default=None,
        help=ALLOC_MB_HELP)
    group.add_argument(
        "--image-count",
        type=NumberParser.positive_zero_int,
        default=None,
        help=IMAGE_COUNT_HELP)
    group.add_argument(
        "--tab-wait",
        type=DurationParser.positive_or_zero_duration,
        default=DEFAULT_TAB_WAIT,
        help=f"{TAB_WAIT_HELP} Default is 400ms.")
    group.add_argument(
        "--revisit-wait",
        type=DurationParser.positive_or_zero_duration,
        default=DEFAULT_REVISIT_WAIT,
        help=f"{REVISIT_WAIT_HELP} Default is 250ms.")
    return parser

  @classmethod
  @override
  def add_page_config_parser(cls, parser: argparse.ArgumentParser) -> None:
    # The story is generated from the benchmark specific CLI args, custom
    # pages are not supported.
    pass

  @classmethod
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    page = MultiwindowMemoryStressPage(
        StressConfig.from_cli_args(args),
        playback=args.playback,
        tabs=args.tabs,
        about_blank_duration=args.about_blank_duration)
    return (page,)


@dataclasses.dataclass(frozen=True)
class StressConfig(ConfigObject):
  """
  Parameters for multiwindow-memory-stress.
  alloc_mb and image_count are derived from the device memory at run time if
  they are None.
  """
  windows: int = DEFAULT_WINDOWS
  tabs_per_window: int = DEFAULT_TABS_PER_WINDOW
  alloc_mb: int | None = None
  image_count: int | None = None
  tab_wait: dt.timedelta = DEFAULT_TAB_WAIT
  revisit_wait: dt.timedelta = DEFAULT_REVISIT_WAIT

  @override
  def validate(self) -> None:
    super().validate()
    NumberParser.positive_int(self.windows, "windows")
    NumberParser.positive_int(self.tabs_per_window, "tabs_per_window")
    if self.alloc_mb is not None:
      NumberParser.positive_zero_int(self.alloc_mb, "alloc_mb")
    if self.image_count is not None:
      NumberParser.positive_zero_int(self.image_count, "image_count")
    DurationParser.positive_or_zero_duration(self.tab_wait, "tab_wait")
    DurationParser.positive_or_zero_duration(self.revisit_wait, "revisit_wait")

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    # The short form only sets the number of windows, e.g. "6".
    return cls.config_parser().parse_str(value)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_default_argument(
        "windows",
        type=NumberParser.positive_int,
        default=DEFAULT_WINDOWS,
        help=WINDOWS_HELP)
    parser.add_argument(
        "tabs_per_window",
        type=NumberParser.positive_int,
        default=DEFAULT_TABS_PER_WINDOW,
        help=TABS_PER_WINDOW_HELP)
    parser.add_argument(
        "alloc_mb",
        type=NumberParser.positive_zero_int,
        default=None,
        help=ALLOC_MB_HELP)
    parser.add_argument(
        "image_count",
        type=NumberParser.positive_zero_int,
        default=None,
        help=IMAGE_COUNT_HELP)
    parser.add_argument(
        "tab_wait",
        type=DurationParser.positive_or_zero_duration,
        default=DEFAULT_TAB_WAIT,
        help=TAB_WAIT_HELP)
    parser.add_argument(
        "revisit_wait",
        type=DurationParser.positive_or_zero_duration,
        default=DEFAULT_REVISIT_WAIT,
        help=REVISIT_WAIT_HELP)
    return parser

  @classmethod
  def from_cli_args(cls, args: argparse.Namespace) -> Self:
    return cls(
        windows=args.windows,
        tabs_per_window=args.tabs_per_window,
        alloc_mb=args.alloc_mb,
        image_count=args.image_count,
        tab_wait=args.tab_wait,
        revisit_wait=args.revisit_wait)

  @property
  def is_resolved(self) -> bool:
    return self.alloc_mb is not None and self.image_count is not None

  def default_alloc_mb(self, total_memory_mb: int) -> int:
    return round(total_memory_mb / 1024 * ALLOC_MB_PER_GIB)

  def default_image_count(self, total_memory_mb: int) -> int:
    return max(MIN_IMAGE_COUNT, round(total_memory_mb / 1024 * IMAGES_PER_GIB))

  def resolve(self, total_memory_mb: int) -> StressConfig:
    """Returns a copy with the unset per-tab sizes derived from the device
    memory."""
    alloc_mb = self.alloc_mb
    if alloc_mb is None:
      alloc_mb = self.default_alloc_mb(total_memory_mb)
    image_count = self.image_count
    if image_count is None:
      image_count = self.default_image_count(total_memory_mb)
    return dataclasses.replace(self, alloc_mb=alloc_mb, image_count=image_count)

  def to_json(self) -> JsonDict:
    return {
        "windows": self.windows,
        "tabs_per_window": self.tabs_per_window,
        "alloc_mb": self.alloc_mb,
        "image_count": self.image_count,
        "tab_wait": self.tab_wait.total_seconds(),
        "revisit_wait": self.revisit_wait.total_seconds(),
    }


class MultiwindowMemoryStressPage(InteractivePage):
  """
  Opens --windows x --tabs-per-window memory-allocating tabs, then revisits
  every tab.
  The action blocks are created at run time since the per-tab sizes depend on
  the device memory.
  """

  def __init__(
      self,
      config: StressConfig,
      playback: PlaybackController = PlaybackController.default(),
      tabs: TabController = TabController.default(),
      about_blank_duration: dt.timedelta = dt.timedelta(),
  ) -> None:
    self._config: StressConfig = config
    self._resolved_config: StressConfig | None = None
    self._stress_blocks: tuple[ActionBlock, ...] = (self._init_block(),)
    super().__init__(
        name=STORY_NAME,
        blocks=self._stress_blocks,
        playback=playback,
        tabs=tabs,
        about_blank_duration=about_blank_duration)

  @property
  def config(self) -> StressConfig:
    return self._config

  @property
  def resolved_config(self) -> StressConfig | None:
    return self._resolved_config

  @property
  @override
  def blocks(self) -> tuple[ActionBlock, ...]:
    return self._stress_blocks

  @override
  def run_once(self, run: Run) -> None:
    self._update_blocks(run)
    super().run_once(run)
    # Close the tabs so the next iteration starts from a single tab again.
    run.browser.close_all_tabs()

  @override
  def run_with(self, action_runner: ActionRunner, multiple_tabs: bool) -> None:
    self._update_blocks(action_runner.run)
    super().run_with(action_runner, multiple_tabs)

  def _update_blocks(self, run: Run) -> None:
    config = self._config.resolve(run.browser.platform.total_memory_mb())
    logging.info("%s: alloc_mb=%s image_count=%s per tab", STORY_NAME,
                 config.alloc_mb, config.image_count)
    self._resolved_config = config
    init_block = self._init_block()
    self._stress_blocks = (init_block, *_StressBlocks(
        config, start_index=init_block.index + 1))

  def _init_block(self) -> ActionBlock:
    return ActionBlock(
        label="stage-0-init",
        index=0,
        actions=(
            GetAction.create(
                url=STARTER_URL,
                ready_state=ReadyState.COMPLETE,
                timeout=STARTER_LOAD_TIMEOUT,
                target=WindowTarget.SELF),
            MeminfoAction.create(title="before_open", timeout=MEMINFO_TIMEOUT),
        ))

  @override
  def details_json(self) -> JsonDict:
    result = super().details_json()
    result["actions"] = [block.to_json() for block in self.blocks]
    config = self._resolved_config or self._config
    result["config"] = config.to_json()
    return result


class _StressBlocks:
  """
  Yields the blocks after the init block: open each window with its tabs,
  revisit the tabs window by window, cooldown.
  """

  def __init__(self, config: StressConfig, start_index: int) -> None:
    assert config.is_resolved, "Per-tab sizes must be resolved"
    self._config: StressConfig = config
    self._index: int = start_index

  def __iter__(self) -> Iterator[ActionBlock]:
    windows = range(1, self._config.windows + 1)
    for window in windows:
      yield self._block(f"stage-{window}-window-{window}",
                        self._open_window_actions(window))
    for window in windows:
      yield self._block(f"cycle-window-{window}",
                        self._cycle_window_actions(window))
    yield self._block("stage-final-cooldown", self._cooldown_actions())

  def _block(self, label: str, actions: Sequence[Action]) -> ActionBlock:
    block = ActionBlock(label=label, index=self._index, actions=tuple(actions))
    self._index += 1
    return block

  def _meminfo(self, title: str) -> MeminfoAction:
    return MeminfoAction.create(title=title, timeout=MEMINFO_TIMEOUT)

  def _wait(self, duration: dt.timedelta) -> WaitAction:
    return WaitAction.create(duration=duration)

  def _mark(self, name: str) -> JsAction:
    """Creates a performance mark in the current tab."""
    return JsAction.create(script=f'performance.mark("{name}", {{}});')

  def _tab_index(self, window: int, tab: int) -> str:
    return str((window - 1) * self._config.tabs_per_window + tab)

  def _open_window_actions(self, window: int) -> list[Action]:
    actions: list[Action] = []
    for tab in range(self._config.tabs_per_window):
      target = WindowTarget.NEW_WINDOW if tab == 0 else WindowTarget.NEW_TAB
      actions.extend(
          self._open_tab_actions(window, self._tab_index(window, tab), target))
    actions.append(self._meminfo(self._window_meminfo_title(window)))
    return actions

  def _window_meminfo_title(self, window: int) -> str:
    if window == self._config.windows:
      return "after_open"
    return f"after_w{window}_t{window * self._config.tabs_per_window}"

  def _open_tab_actions(self, window: int, tab_index: str,
                        target: WindowTarget) -> list[Action]:
    return [
        # Emitted in the previous tab, so the page load includes opening the
        # new tab.
        self._mark(f"page-load~{tab_index}"),
        GetAction.create(
            url=STRESS_TAB_URL_TEMPLATE.format(tab_index=tab_index),
            ready_state=ReadyState.COMPLETE,
            timeout=TAB_LOAD_TIMEOUT,
            target=target),
        JsAction.create(
            script_path=STRESS_ALLOC_JS,
            replacements=Replacements.create({
                "ALLOC_MB": self._config.alloc_mb,
                "IMAGE_COUNT": self._config.image_count,
                "TAB_INDEX": tab_index,
                "WINDOW_INDEX": str(window),
            })),
        # Wait to throttle memory allocation across tabs.
        self._wait(self._config.tab_wait),
        self._mark(f"tab-revisit-start~open~{tab_index}"),
        self._revisit_js("open", tab_index),
        self._wait(self._config.tab_wait),
    ]

  def _cycle_window_actions(self, window: int) -> list[Action]:
    actions: list[Action] = []
    for tab in range(self._config.tabs_per_window):
      tab_index = self._tab_index(window, tab)
      actions.extend([
          # Emitted in the previous tab, so the revisit includes switching to
          # the tab and waking up its renderer.
          self._mark(f"tab-revisit-start~cycle~{tab_index}"),
          SwitchTabAction.create(title=re.compile(f"^Tab {tab_index}$")),
          self._revisit_js("cycle", tab_index),
          self._wait(self._config.revisit_wait),
      ])
    return actions

  def _revisit_js(self, phase: str, tab_index: str) -> JsAction:
    return JsAction.create(
        script_path=REVISIT_TAB_JS,
        timeout=REVISIT_JS_TIMEOUT,
        replacements=Replacements.create({
            "PHASE": phase,
            "TAB_INDEX": tab_index,
        }))

  def _cooldown_actions(self) -> list[Action]:
    return [
        self._meminfo("after_switch"),
        self._wait(COOLDOWN_DURATION),
        self._meminfo("after_cooldown"),
    ]


class MultiwindowMemoryStressBenchmark(LoadingBenchmark):
  """
  Benchmark runner for multiwindow memory stress test.
  """

  NAME: ClassVar = STORY_NAME
  DEFAULT_STORY_CLS: ClassVar = Page
  STORY_FILTER_CLS: ClassVar = MultiwindowMemoryStressStoryFilter

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return pth.LocalPath(__file__).parent / "probe_config.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    # Do not inherit the "load" / "ld" aliases from LoadingBenchmark.
    return ()

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> Sequence[Story]:
    return MultiwindowMemoryStressStoryFilter.stories_from_cli_args(args)

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return ()

  @classmethod
  @override
  def describe_stories(cls) -> Mapping[str, str]:
    # The story is generated from CLI args, avoid building it here.
    return {
        STORY_NAME: ("Open --windows x --tabs-per-window memory-allocating "
                     "tabs, then revisit every tab."),
    }
