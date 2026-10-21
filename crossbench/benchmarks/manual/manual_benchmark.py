# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import contextlib
import datetime as dt
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Final

from typing_extensions import override

from crossbench.benchmarks.base import Benchmark
from crossbench.cli.ui import ui
from crossbench.cli.ui.ui import timer
from crossbench.helper import input_helper
from crossbench.parse import DurationParser, ObjectParser
from crossbench.probes.cdp_endpoint import CDPEndpointProbe
from crossbench.stories.story import Story

if TYPE_CHECKING:
  import argparse

  from crossbench.action_runner.config import ActionRunnerConfig
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner


class ManualStory(Story, metaclass=abc.ABCMeta):

  STORY_NAME = "manual"

  def __init__(self,
               start_after: dt.timedelta | None = dt.timedelta(),
               run_for: dt.timedelta | None = dt.timedelta(),
               url: str | None = None) -> None:
    self._start_after: Final[dt.timedelta | None] = start_after
    self._run_for: Final[dt.timedelta | None] = run_for
    self._url: Final[str | None] = url
    duration = ((start_after or dt.timedelta()) +
                (run_for or dt.timedelta(seconds=30)))
    super().__init__(self.STORY_NAME, duration)

  @override
  def setup(self, run: Run) -> None:
    if self._start_after is None:
      logging.info("-" * 80)
      ui.prompt("Press enter to start:")
    elif self._start_after.total_seconds():
      logging.critical("-" * 80)
      logging.critical(
          "The browser has launched. Measurement will start in %s"
          " (or press enter to start immediately)", self._start_after)
      with contextlib.suppress(KeyboardInterrupt):
        input_helper.input_with_timeout(timeout=self._start_after)
    logging.info("Starting Manual Benchmark...")

  def run(self, run: Run) -> None:
    with timer():
      logging.info("-" * 80)
      if url := self._url:
        with run.actions("Show URL") as actions:
          actions.show_url(url)
      self._wait_for_input()
    # Empty line to preserve timer output.
    print()
    logging.info("Stopping Manual Benchmark...")

  def _wait_for_input(self) -> None:
    if self._run_for is None:
      with contextlib.suppress(KeyboardInterrupt):
        # Print two lines so the timer does not overwrite the message
        logging.info("Press enter to stop:")
        ui.prompt()
    else:
      logging.critical(
          "Measurement has started. The browser will close in %s"
          " (or press enter to close immediately)", self._run_for)
      with contextlib.suppress(KeyboardInterrupt):
        input_helper.input_with_timeout(timeout=self._run_for)

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return (ManualStory.STORY_NAME,)


class ManualBenchmark(Benchmark, metaclass=abc.ABCMeta):
  """
  Full manual benchmark.

  Just launches the browser and lets the user perform the desired interactions.
  Optionally waits for |start_after| seconds, then runs measurements for
  |run_for| seconds, then closes the browser.
  """
  NAME: ClassVar = "manual"
  DEFAULT_STORY_CLS: ClassVar = ManualStory

  def __init__(self,
               action_runner_config: ActionRunnerConfig | None = None,
               start_after: dt.timedelta | None = None,
               run_for: dt.timedelta | None = None,
               url: str | None = None,
               expose_cdp: bool = False) -> None:
    self._expose_cdp: Final[bool] = expose_cdp
    manual_story = ManualStory(
        start_after=start_after, run_for=run_for, url=url)
    super().__init__([manual_story], action_runner_config)

  @override
  def setup(self, runner: Runner) -> None:
    super().setup(runner)
    if self._expose_cdp:
      runner.attach_probe(CDPEndpointProbe())

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    super().add_cli_arguments(parser)
    parser.add_argument(
        "--start-after",
        type=DurationParser.positive_or_zero_duration,
        help="How long to wait until measurement starts")
    parser.add_argument(
        "--run-for",
        "--stop-after",
        "--duration",
        type=DurationParser.positive_duration,
        help="How long to run measurement for")
    parser.add_argument(
        "--url",
        "--test-url",
        type=ObjectParser.url_str,
        help="Navigate to URL right after the start-after timeout.")
    parser.add_argument(
        "--expose-cdp",
        action="store_true",
        default=False,
        help=("Expose the CDP WebSocket endpoint to a file and logs. "
              "See 'cdp_endpoint' probe help for more details."))
    return parser

  @classmethod
  @override
  def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["start_after"] = args.start_after
    kwargs["run_for"] = args.run_for
    kwargs["url"] = args.url
    kwargs["expose_cdp"] = args.expose_cdp
    return kwargs
