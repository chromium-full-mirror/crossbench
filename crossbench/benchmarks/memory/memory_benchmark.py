# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import TYPE_CHECKING, ClassVar, Final, NotRequired, Sequence, \
    TypedDict, cast

import selenium.common.exceptions
import urllib3.exceptions
from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action_runner_listener import \
    ActionRunnerListener
from crossbench.benchmarks.benchmark_probe import BenchmarkProbeMixin
from crossbench.benchmarks.loading.config.blocks import ActionBlock
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.benchmarks.loading.page.base import Page
from crossbench.benchmarks.loading.page.live import LivePage
from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import RepeatTabController, \
    TabController
from crossbench.parse import NumberParser
from crossbench.probes.json import JsonResultProbe, JsonResultProbeContext
from crossbench.probes.metric import MetricsMerger
from crossbench.replacements import Replacements

if TYPE_CHECKING:
  import argparse

  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.flags.base import Flags
  from crossbench.probes.results import ProbeResult, ProbeResultDict
  from crossbench.runner.actions import Actions
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run
  from crossbench.stories.story import Story
  from crossbench.types import JsonDict


class PlaybackMetrics(TypedDict):
  final_surviving_tabs_count: int
  alive_tabs_by_tab_index: dict[str, int]
  page_load_duration_ms_by_tab_index: dict[str, float]
  allocation_duration_ms_by_tab_index: dict[str, float]
  tab_index_at_first_kill: int | None
  average_page_load_duration_ms: NotRequired[float]
  average_allocation_duration_ms: NotRequired[float]
  average_alive_tabs_after_first_kill: NotRequired[float]


class MemoryProbe(BenchmarkProbeMixin, JsonResultProbe):
  """
  Memory-specific Probe.
  Extracts the number of alive tabs.
  """
  NAME: ClassVar[str] = "memory_probe"

  @override
  def get_context_cls(self) -> type[MemoryProbeContext]:
    return MemoryProbeContext

  def to_json(self, actions: Actions) -> JsonDict:
    raise NotImplementedError(
        "should not be called, data comes from memory probe context")

  @override
  def log_run_result(self, run: Run) -> None:
    self._log_result(run.results, single_result=True)

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    self._log_result(group.results, single_result=False)

  def _log_result(self, result_dict: ProbeResultDict,
                  single_result: bool) -> None:

    if self not in result_dict:
      return
    results_json: pth.LocalPath = result_dict[self].json
    logging.info("-" * 80)
    logging.critical("Memory results (num of alive tabs):")
    if not single_result:
      logging.critical("  %s", result_dict[self].csv)
    logging.info("- " * 40)

    with results_json.open(encoding="utf-8") as f:
      data = json.load(f)
      if single_result:
        if "final_surviving_tabs_count" in data:
          logging.critical("Score %s", data["final_surviving_tabs_count"])
        else:
          scores = [
              v for k, v in data.items()
              if k.endswith("/final_surviving_tabs_count")
          ]
          logging.critical("Scores %s", scores)
      else:
        self._log_result_metrics(data)

  @override
  def merge_stories(self, group: StoriesRunGroup) -> ProbeResult:
    merged = MetricsMerger.merge_json_list(
        repetitions_group.results[self].json
        for repetitions_group in group.repetitions_groups)
    return self.write_group_result(group, merged)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    return self.merge_browsers_json_list(group).merge(
        self.merge_browsers_csv_list(group))


class MemoryProbeContext(ActionRunnerListener,
                         JsonResultProbeContext[MemoryProbe]):

  def __init__(self, probe: MemoryProbe, run: Run) -> None:
    super().__init__(probe, run)
    benchmark = probe.benchmark
    if not isinstance(benchmark, MemoryBenchmark):
      raise TypeError("The probe only works for MemoryBenchmark")
    run.action_runner.set_listener(self)
    # Records the navigation_start_time time for each window handle.
    self._playbacks_metrics: Final[list[PlaybackMetrics]] = []
    self._navigation_time_ms: Final[dict[str, float]] = {}
    self._tab_count: int = 1
    self._alive_tabs_by_tab_index: Final[dict[str, int]] = {}
    self._page_load_duration_ms_by_tab_index: Final[dict[str, float]] = {}
    self._allocation_duration_ms_by_tab_index: Final[dict[str, float]] = {}
    self._tab_index_at_first_kill: int | None = None

  def start(self) -> None:
    pass

  def reset_playback_state(self) -> None:
    self._save_current_playback_metrics()
    self._navigation_time_ms.clear()
    self._tab_count = 1
    self._tab_index_at_first_kill = None
    self._alive_tabs_by_tab_index.clear()
    self._page_load_duration_ms_by_tab_index.clear()
    self._allocation_duration_ms_by_tab_index.clear()

  def _save_current_playback_metrics(self) -> None:
    if not self._alive_tabs_by_tab_index:
      return

    playback_metrics: PlaybackMetrics = {
        "final_surviving_tabs_count":
            len(self._navigation_time_ms),
        "alive_tabs_by_tab_index":
            dict(self._alive_tabs_by_tab_index),
        "page_load_duration_ms_by_tab_index":
            dict(self._page_load_duration_ms_by_tab_index),
        "allocation_duration_ms_by_tab_index":
            dict(self._allocation_duration_ms_by_tab_index),
        "tab_index_at_first_kill":
            self._tab_index_at_first_kill,
    }

    if self._page_load_duration_ms_by_tab_index:
      playback_metrics["average_page_load_duration_ms"] = (
          sum(self._page_load_duration_ms_by_tab_index.values()) /
          len(self._page_load_duration_ms_by_tab_index))

    if self._allocation_duration_ms_by_tab_index:
      playback_metrics["average_allocation_duration_ms"] = (
          sum(self._allocation_duration_ms_by_tab_index.values()) /
          len(self._allocation_duration_ms_by_tab_index))

    if self._tab_index_at_first_kill is not None:
      after_kill = [
          count for idx, count in self._alive_tabs_by_tab_index.items()
          if int(idx) >= self._tab_index_at_first_kill
      ]
      if after_kill:
        avg = sum(after_kill) / len(after_kill)
        playback_metrics["average_alive_tabs_after_first_kill"] = avg
        try:
          self.run.browser.js(
              "performance.mark('crossbench_avg_tabs_alive', {"
              " detail: { tab_index_at_first_kill: "
              f"{self._tab_index_at_first_kill},"
              f" average_alive_tabs_after_first_kill: {avg} }} }})")
        except (ValueError, selenium.common.exceptions.WebDriverException) as e:
          logging.debug("Could not inject avg tabs mark: %s", e)

    self._playbacks_metrics.append(playback_metrics)

  @override
  def to_json(self, actions: Actions) -> JsonDict:
    # Save the current state in case the test finishes without calling
    # reset_playback_state
    if self._alive_tabs_by_tab_index:
      self._save_current_playback_metrics()
      self._alive_tabs_by_tab_index.clear()  # Prevent double saving

    metrics: dict[str, PlaybackMetrics] = {}
    for i, playback_metrics in enumerate(self._playbacks_metrics):
      metrics[f"playback_{i}"] = playback_metrics
    # TODO: remove once mypy is replaced by pyrefly
    # https://peps.python.org/pep-0728
    return cast("JsonDict", metrics)

  def _increment_tab_count(self) -> None:
    self._tab_count += 1

  def _record_navigation_time(self, run: Run) -> str:
    """
    Record NavigationStart time for the current handle.
    """
    with run.actions("_record_navigation_time", measure=False) as action:
      cur_handle: str = action.current_window_id()
      navigation_start_time = action.js(
          "return window.performance.timing.navigationStart")
      logging.debug("Browser: %s. Navigation starttime for handle %s is %s.",
                    run.browser.unique_name, cur_handle, navigation_start_time)
      self._navigation_time_ms[cur_handle] = navigation_start_time

      tab_index = self._tab_count - 1
      page_loaded = float(
          action.js(
              f"return performance.getEntriesByName('page-loaded~{tab_index}')"
              "[0].startTime"))
      alloc_start = float(
          action.js("return performance.getEntriesByName"
                    f"('allocation-start~{tab_index}')[0].startTime"))
      alloc_done = float(
          action.js("return performance.getEntriesByName"
                    f"('allocation-done~{tab_index}')[0].startTime"))
      alloc_dur = alloc_done - alloc_start
      self._page_load_duration_ms_by_tab_index[str(tab_index)] = page_loaded
      self._allocation_duration_ms_by_tab_index[str(tab_index)] = alloc_dur
      action.js(
          "performance.mark('crossbench_tab_timing', { detail: {"
          f" tab_index: {tab_index}, page_load_duration_ms: {page_loaded},"
          f" allocation_duration_ms: {alloc_dur} }} }})")
      return cur_handle

  def _check_liveness(self, run: Run) -> int:
    """
    Navigate each opened tab, and check if the navigation start time
    has changed. If so, then it means that page has been discarded
    and reloaded. Returns the number of alive tabs.
    """
    alive_count = 0
    dead_handles = []
    with run.actions("_check_liveness", measure=False) as action:
      for handle, handle_navigation_time_ms in self._navigation_time_ms.items():
        logging.debug("Browser: %s. Liveness checking for handle: %s",
                      run.browser, handle)
        try:
          action.switch_window(handle)
          navigation_start_time = action.js(
              "return window.performance.timing.navigationStart", timeout=2)
          if navigation_start_time == handle_navigation_time_ms:
            alive_count += 1
          else:
            # The page was reloaded, meaning it was discarded.
            logging.info("Tab discard detected during liveness check.")
            dead_handles.append(handle)
        except Exception as e:
          if self._error_msg_is_tab_kill(e):
            logging.info("Tab crash detected during liveness check: %s", e)
            dead_handles.append(handle)
          else:
            raise
    for handle in dead_handles:
      del self._navigation_time_ms[handle]
    return alive_count

  def _error_msg_is_tab_kill(self, e: Exception) -> bool:
    if isinstance(e, selenium.common.exceptions.WebDriverException) and (
        "page crash" in str(e) or "tab crashed" in str(e)):
      return True
    if isinstance(e, selenium.common.exceptions.TimeoutException):
      return True
    if isinstance(e, urllib3.exceptions.ReadTimeoutError):
      return True
    # Error msg from `Could not execute JS` due to page crash.
    if isinstance(e, ValueError) and ("page crash" in str(e) or "tab crashed"
                                      in str(e) or "script timeout" in str(e)):
      return True
    return False

  @override
  def handle_page_run(self, run: Run) -> None:
    self._record_navigation_time(run)

    story = run.story
    assert isinstance(story, MemoryPage)
    skip_until: int = story.skip_liveness_checks_until

    if self._tab_count <= skip_until:
      # Delay checking until we reach the threshold, assume all tabs are alive
      alive_count = self._tab_count
    else:
      alive_count = self._check_liveness(run)
      if self._tab_count == skip_until + 1 and alive_count < self._tab_count:
        logging.warning(
            "A dead tab was found during the first liveness check! "
            "This means a tab died while checks were skipped. "
            "The memory metrics may be inaccurate. You should decrease "
            "--skip-liveness-checks-until (currently %s).", skip_until)

    tab_index = self._tab_count - 1
    self._alive_tabs_by_tab_index[str(tab_index)] = alive_count

    if self._tab_index_at_first_kill is None and alive_count < self._tab_count:
      self._tab_index_at_first_kill = tab_index

    if alive_count > 0:
      with run.actions("Record tabs alive", measure=False) as action:
        tab_index = self._tab_count - 1
        try:
          action.js(
              "performance.mark('tabs_alive', { detail: {"
              f" tab_index: {tab_index}, alive_count: {alive_count} }} }})")
        except (ValueError, selenium.common.exceptions.WebDriverException) as e:
          logging.warning("Failed to record alive tabs mark: %s", e)

  @override
  def handle_new_tab(self, run: Run) -> None:
    self._increment_tab_count()


class MemoryBenchmarkStoryFilter(LoadingPageFilter):
  """
  Create memory story.
  """

  @classmethod
  @override
  def add_cli_arguments(
      cls, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = super().add_cli_arguments(parser)
    parser.set_defaults(tabs=RepeatTabController(100))
    parser.add_argument(
        "--memory-percent",
        type=NumberParser.positive_float,
        default=2.0,
        help="Percentage of system memory to allocate per tab. Default is 2.0.")
    parser.add_argument(
        "--skip-liveness-checks-until",
        type=NumberParser.positive_zero_int,
        default=40,
        help="Number of tabs to open before checking for liveness. "
        "Default is 40.")
    return parser

  @override
  def filter_by_name(self, patterns: Sequence[str]) -> tuple[Page, ...]:
    return self.stories_from_cli_args(self.args)

  @classmethod
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    args_dict = vars(args)
    page = MemoryPage(
        "memory",
        args_dict.get("memory_percent", 2.0),
        args_dict.get("skip_liveness_checks_until", 40),
        dt.timedelta(seconds=2),
        tabs=args_dict.get("tabs", RepeatTabController(100)),
        playback=args_dict.get("playback", PlaybackController.default()))
    return (page,)


class MemoryPage(LivePage):

  def __init__(self, name: str, memory_percent: float,
               skip_liveness_checks_until: int, duration: dt.timedelta,
               tabs: TabController, playback: PlaybackController) -> None:
    self.memory_percent: Final[float] = memory_percent
    self.skip_liveness_checks_until: Final[int] = skip_liveness_checks_until
    self._current_tab_index = 0
    self._cached_blocksize: int | None = None
    super().__init__(
        name, "about:blank", duration=duration, tabs=tabs, playback=playback)

  @override
  def run_once(self, run: Run) -> None:
    super().run_once(run)
    run.browser.close_all_tabs()
    self._current_tab_index = 0
    if run.has_probe_context(MemoryProbe):
      listener = run.get_probe_context(MemoryProbe)
      assert isinstance(listener, MemoryProbeContext)
      listener.reset_playback_state()

  @override
  def run_with(self, action_runner: ActionRunner, multiple_tabs: bool) -> None:
    if multiple_tabs:
      self._current_tab_index = 0
      super().run_with(action_runner, multiple_tabs)
    else:
      if self._cached_blocksize is None:
        total_memory_mb = action_runner.browser_platform.total_memory_mb()
        self._cached_blocksize = max(
            1, int(total_memory_mb * (self.memory_percent / 100.0)))
      blocksize = self._cached_blocksize

      tab_index = self._current_tab_index
      self._current_tab_index += 1

      # Allocations are done via an injected script instead of via a test
      # page to ensure that if a killed tab is reloaded it does not attempt
      # to reallocate its payload.
      actions = (JsAction.create(
          script_path=pth.LocalPath(__file__).parent / "scripts" / "alloc.js",
          replacements=Replacements.create({
              "TARGET_MB": str(blocksize),
              "TAB_INDEX": str(tab_index),
          })),)
      block = ActionBlock(actions=actions)
      action_runner.run_block(block)


class MemoryBenchmark(LoadingBenchmark):
  """
  Benchmark runner for memory stress test.
  """

  NAME: ClassVar = "memory"
  DEFAULT_STORY_CLS: ClassVar = Page
  STORY_FILTER_CLS: ClassVar = MemoryBenchmarkStoryFilter
  PROBES: ClassVar[tuple[type[MemoryProbe], ...]] = (MemoryProbe,)

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return pth.LocalPath(__file__).parent / "probe_config.hjson"

  @classmethod
  @override
  def aliases(cls) -> tuple[str, ...]:
    return ("mem",)

  @classmethod
  @override
  def stories_from_cli_args(cls, args: argparse.Namespace) -> tuple[Page, ...]:
    super().stories_from_cli_args(args)
    stories = MemoryBenchmarkStoryFilter.stories_from_cli_args(args)
    return stories

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return ()

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if browser_attributes.is_chromium_based:
      flags.set("--allow-background-interventions")
    return flags
