# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import contextlib
import datetime as dt
import enum
import json
import os
import threading
from typing import TYPE_CHECKING, Final, Iterator

from typing_extensions import override

from crossbench.helper.state import BaseState, StateMachine

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner


@enum.unique
class RunnerState(BaseState):
  INITIAL = enum.auto()
  SETUP = enum.auto()
  RUNNING = enum.auto()
  TEARDOWN = enum.auto()
  INTERRUPTING = enum.auto()
  # Final states
  DONE = enum.auto()
  DONE_INTERRUPTED = enum.auto()
  DONE_ERRORED = enum.auto()


class RunnerStateMachine(StateMachine[RunnerState]):

  def __init__(self, runner: Runner) -> None:
    super().__init__(RunnerState.INITIAL)
    self._status_lock: Final[threading.Lock] = threading.Lock()
    self._status_file: Final[pth.LocalPath] = runner.out_dir / "status.json"
    self._active_runs: Final[set[int]] = set()
    self._pid: int | None = os.getpid()
    self._success_count: int = 0
    self._failed_count: int = 0
    self._total_runs: int = 0
    self._runs_dir_str: Final[str] = str(runner.runs_dir)
    self._created: Final[str] = dt.datetime.now().isoformat()
    atexit.register(self._atexit_handler)
    self._write_nolock()

  @property
  def path(self) -> pth.LocalPath:
    return self._status_file

  @contextlib.contextmanager
  def active_run(self, run: Run) -> Iterator[None]:
    self._start_run(run)
    try:
      yield
    finally:
      self._stop_run(run)

  def _start_run(self, run: Run) -> None:
    with self._status_lock:
      self._active_runs.add(run.index)
      self._write_nolock()

  def _stop_run(self, run: Run) -> None:
    with self._status_lock:
      self._active_runs.discard(run.index)
      if run.is_success:
        self._success_count += 1
      else:
        self._failed_count += 1
      self._write_nolock()

  def set_total_runs(self, total: int) -> None:
    with self._status_lock:
      self._total_runs = total
      self._write_nolock()

  @override
  def transition(self, *args: RunnerState, to: RunnerState) -> None:
    super().transition(*args, to=to)
    with self._status_lock:
      self._write_nolock()
      if to >= RunnerState.DONE:
        atexit.unregister(self._atexit_handler)

  def interrupt(self) -> None:
    with self._status_lock:
      super().transition(self.state, to=RunnerState.INTERRUPTING)
      self._write_nolock()

  def update(self) -> None:
    with self._status_lock:
      self._write_nolock()

  def _atexit_handler(self) -> None:
    with self._status_lock:
      if self._pid is None:
        return
      self._pid = None
      if self._state == RunnerState.INTERRUPTING:
        self._state = RunnerState.DONE_INTERRUPTED
      elif self._state < RunnerState.DONE:
        self._state = RunnerState.DONE_ERRORED
      self._write_nolock()

  def _write_nolock(self) -> None:
    status_data = {
        "pid": self._pid,
        "status": self.state.name,
        "created": self._created,
        "last_modified": dt.datetime.now().isoformat(),
        "runs": {
            "dir": self._runs_dir_str,
            "total": self._total_runs,
            "current": sorted(self._active_runs),
            "success": self._success_count,
            "failed": self._failed_count,
        },
    }
    with self._status_file.open("w") as f:
      json.dump(status_data, f, indent=2)
