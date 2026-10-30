# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from typing import TYPE_CHECKING, Final, Iterable, Iterator

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.dump_html import DumpHtmlAction
from crossbench.action_runner.action.get import GetAction
from crossbench.benchmarks.loading.page.base import Page
from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.runner.probe_context_lookup_error import \
    ProbeContextLookupError

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner
  from crossbench.benchmarks.loading.config.blocks import ActionBlock
  from crossbench.benchmarks.loading.config.login.custom import LoginBlock
  from crossbench.cli.config.secrets import Secrets
  from crossbench.runner.run import Run
  from crossbench.types import JsonDict


class InteractivePage(Page):

  def __init__(
      self,
      name: str,
      blocks: tuple[ActionBlock, ...] = (),
      login: LoginBlock | None = None,
      setup: ActionBlock | None = None,
      teardown: ActionBlock | None = None,
      secrets: Secrets | None = None,
      playback: PlaybackController = PlaybackController.default(),
      tabs: TabController = TabController.default(),
      about_blank_duration: dt.timedelta = dt.timedelta(),
      tags: Iterable[str] = (),
      run_login: bool = True,
      run_setup: bool = True,
      run_teardown: bool = True,
  ) -> None:
    assert name, "missing name"
    self._name: str = name
    assert not any(block.is_login for block in blocks), (
        "No login blocks allowed as normal action block")
    self._login_block: Final[LoginBlock | None] = login
    self._setup_block: Final[ActionBlock | None] = setup
    assert isinstance(blocks, tuple)
    self._blocks: Final[tuple[ActionBlock, ...]] = blocks
    self._teardown_block: Final[ActionBlock | None] = teardown
    assert self.has_any_blocks, (
        "Must have at least 1 valid action in blocks, setup, or teardown")

    self._run_login: Final[bool] = run_login
    self._run_setup: Final[bool] = run_setup
    self._run_teardown: Final[bool] = run_teardown

    duration = self._get_duration()
    super().__init__(self._name, duration, playback, tabs, about_blank_duration,
                     secrets, tags)

  @property
  def login_block(self) -> ActionBlock | None:
    return self._login_block

  @property
  def setup_block(self) -> ActionBlock | None:
    return self._setup_block

  @property
  def blocks(self) -> tuple[ActionBlock, ...]:
    return self._blocks

  @property
  def run_login(self) -> bool:
    return self._run_login

  @property
  def run_setup(self) -> bool:
    return self._run_setup

  @property
  def teardown_block(self) -> ActionBlock | None:
    return self._teardown_block

  @property
  def has_any_blocks(self) -> bool:
    return bool(self._blocks or self._setup_block or self._teardown_block)

  def __bool__(self) -> bool:
    return self.has_any_blocks

  @property
  @override
  def first_url(self) -> str:
    for block in self.blocks:
      for action in block:
        if action.TYPE == ActionType.GET:
          assert isinstance(action, GetAction)
          return action.url
    raise RuntimeError("No GET action with an URL found.")

  def create_failure_artifacts(self,
                               run: Run,
                               message: str = "failure") -> None:
    action_runner = run.action_runner
    try:
      action_runner.failure_screenshot(message)
    except Exception as e:  # noqa: BLE001
      logging.error("Failed to take a failure screenshot: %s", e)

    try:
      action_runner.invoke_probe(DumpHtmlAction.create(suffix=message))
    except ProbeContextLookupError:
      pass
    except Exception as e:  # noqa: BLE001
      logging.error("Failed to dump HTML on failure: %s", e)

  @contextlib.contextmanager
  def _performance_mark_scope(self, run: Run, name: str) -> Iterator[None]:
    run.performance_mark(f"{name}-start", self._name)
    yield
    run.performance_mark(f"{name}-end", self._name)

  @override
  def setup(self, run: Run) -> None:
    action_runner = run.action_runner
    if self._run_login and (login_block := self.login_block):
      with self._performance_mark_scope(run, "login"):
        action_runner.run_login(self, login_block)
    if self._run_setup and (setup_block := self.setup_block):
      with self._performance_mark_scope(run, "setup"):
        action_runner.run_setup(self, setup_block)

  @override
  def teardown(self, run: Run) -> None:
    action_runner = run.action_runner
    if self._run_teardown and (teardown_block := self.teardown_block):
      with self._performance_mark_scope(run, "teardown"):
        action_runner.run_teardown(self, teardown_block)
    action_runner.teardown()

  def run_once(self, run: Run) -> None:
    action_runner = run.action_runner
    multiple_tabs = self.tabs.multiple_tabs
    action_runner.run_interactive_page(self, multiple_tabs)

  @override
  def run_with(self, action_runner: ActionRunner, multiple_tabs: bool) -> None:
    action_runner.run_interactive_page(self, multiple_tabs)

  @override
  def details_json(self) -> JsonDict:
    result = super().details_json()
    result["actions"] = [block.to_json() for block in self._blocks]
    return result

  def _get_duration(self) -> dt.timedelta:
    duration = dt.timedelta()
    for block in self._blocks:
      duration += block.duration
    return duration
