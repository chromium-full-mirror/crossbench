# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import tempfile
from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from crossbench import path as pth
from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase, \
    WebPowerSiteConfig, WebPowerStory, WebPowerStoryFilter, _value_or
from crossbench.benchmarks.web_power.scroll_gen import GeneratorConfig, \
    generate_scroll_commands
from crossbench.parse import NumberParser

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.cli.parser import CBArgumentParser
  from crossbench.runner.run import Run


class WebPowerScrollStory(WebPowerStory):
  IS_SCENARIO_CLASS = True
  DEFAULT_SCROLL_COUNT: ClassVar[int] = 5
  DEFAULT_INPUT_RATE: ClassVar[int] = 240

  @classmethod
  @override
  def story_name_cls(cls) -> str:
    return "scroll"

  @property
  def scroll_count(self) -> int:
    return self.config.scroll_count

  @property
  def input_rate(self) -> int:
    return self.config.input_rate

  def __init__(self,
               name_suffix: str,
               site_config: WebPowerSiteConfig,
               scroll_count: int | None = None,
               input_rate: int | None = None,
               stabilization_time: dt.timedelta | None = None) -> None:
    self.config = GeneratorConfig(
        input_rate=_value_or(input_rate, self.DEFAULT_INPUT_RATE),
        scroll_count=_value_or(scroll_count, self.DEFAULT_SCROLL_COUNT))
    stabilization_time = _value_or(stabilization_time,
                                   site_config.default_stabilization_time)

    total_duration = (
        self.config.sequence_duration() + stabilization_time +
        WebPowerStory.DEFAULT_GRACE_PERIOD)
    super().__init__(name_suffix, site_config, total_duration,
                     stabilization_time)

    self.local_file: pth.LocalPath | None = None
    self.remote_file: pth.AnyPath | None = None

  @override
  def setup(self, run: Run) -> None:
    assert (self.local_file is None)
    assert (self.remote_file is None)

    if not run.browser_platform.is_android:
      raise RuntimeError(
          "The web-power-scroll benchmark is only supported on Android.")

    # Register cleanup at exit, in case an exception is raised in between
    # setup() and run() being called.
    atexit.register(self.clear_files, run)

    try:
      with run.actions("Generate_Scrolls", verbose=True):
        display_res = run.browser_platform.display_resolution()
        evemu_data = generate_scroll_commands(self.config, display_res)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".evemu", delete=False) as f:
          f.write(evemu_data)
          self.local_file = pth.LocalPath(f.name)

      with run.actions("Push_Scrolls", verbose=True):
        self.remote_file = run.browser_platform.path(
            "/data/local/tmp/scrolling_sequence.evemu")
        run.browser_platform.push(self.local_file, self.remote_file)
    except Exception:
      self.clear_files(run)
      raise

    super().setup(run)

  @override
  def run(self, run: Run) -> None:
    assert (self.local_file is not None)
    assert (self.remote_file is not None)

    try:
      with run.actions(
          "Run", verbose=True, performance_mark=WebPowerStory.MEASUREMENT_MARK):
        with run.actions("Scroll"):
          run.browser_platform.sh("uinput", f"{self.remote_file}")

    finally:
      self.clear_files(run)

  def clear_files(self, run: Run) -> None:
    atexit.unregister(self.clear_files)
    if self.local_file is not None:
      self.local_file.unlink(missing_ok=True)
      self.local_file = None
    if self.remote_file is not None:
      run.browser_platform.rm(self.remote_file, missing_ok=True)
      self.remote_file = None


class WebPowerScrollStoryFilter(WebPowerStoryFilter[WebPowerScrollStory]):
  """Story filter for Web Power scroll stories."""

  IS_SCENARIO_CLASS = True
  STORY_CLS = WebPowerScrollStory


class WebPowerScrollBenchmark(WebPowerBenchmarkBase):
  """Benchmark runner for Power Scroll scenario using legacy EVEMU emulation."""

  IS_SCENARIO_CLASS = True
  NAME: ClassVar = f"{WebPowerBenchmarkBase.NAME}-scroll"
  DEFAULT_STORY_CLS: ClassVar[type[WebPowerScrollStory]] = WebPowerScrollStory
  STORY_FILTER_CLS: ClassVar = WebPowerScrollStoryFilter

  @classmethod
  @override
  def add_scenario_cli_arguments(cls,
                                 parser: CBArgumentParser) -> CBArgumentParser:
    story_cls = cls.DEFAULT_STORY_CLS
    parser.add_argument(
        "--scrolls",
        "--scroll-count",
        dest="scroll_count",
        type=NumberParser.positive_int,
        default=None,
        help="Number of times to repeat the up/down scroll sequence "
        f"(Default: {story_cls.DEFAULT_SCROLL_COUNT})")
    parser.add_argument(
        "--input-rate",
        "--rate",
        dest="input_rate",
        type=NumberParser.positive_int,
        default=None,
        help="Frequency of synthetic scroll touch events in Hz. "
        f"(Default: {story_cls.DEFAULT_INPUT_RATE}Hz)")
    return parser

  @classmethod
  @override
  def fast_mode_default_overrides(cls) -> dict[str, object]:
    overrides = super().fast_mode_default_overrides()
    overrides["scroll_count"] = 1
    return overrides
