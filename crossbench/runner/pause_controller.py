# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import enum
import logging
import threading
from typing import TYPE_CHECKING, Final

from crossbench.helper import input_helper, terminal
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from types import TracebackType

  from typing_extensions import Self


@enum.unique
class ResumeMode(enum.Enum):
  """How the runner should proceed after a pause or a failed run."""
  CONTINUE = "C"
  STOP = "S"


_PAUSE_KEY: Final[str] = "\x10"  # Ctrl+P


class PauseController:
  """Pause controls for a running benchmark.

  Pressing Ctrl+P (or failing a run when `pause_on_error` is enabled) pauses
  after the current run completes and prompts the user for a `ResumeMode`.
  """

  def __init__(self, pause_on_error: bool) -> None:
    self._pause_on_error: Final[bool] = pause_on_error
    self._pause_requested: Final[threading.Event] = threading.Event()

  def __enter__(self) -> Self:
    input_helper.shared().register_key(_PAUSE_KEY, self.request_pause)
    return self

  def __exit__(
      self,
      exc_type: type[BaseException] | None,
      exc_val: BaseException | None,
      exc_tb: TracebackType | None,
  ) -> None:
    input_helper.shared().unregister_key(_PAUSE_KEY)

  @property
  def is_pause_requested(self) -> bool:
    """Whether a pause was requested and not yet consumed."""
    return self._pause_requested.is_set()

  def request_pause(self) -> None:
    """Requests a pause after the current run completes."""
    self._pause_requested.set()
    logging.warning("\r%s⏸️  Runner will pause after current run.",
                    terminal.CLEAR_END)

  def check_pause(self, is_success: bool) -> ResumeMode:
    """Pauses and prompts for a `ResumeMode` if requested or on error."""
    should_pause = self.is_pause_requested or (not is_success and
                                               self._pause_on_error)
    if not should_pause:
      return ResumeMode.CONTINUE
    self._pause_requested.clear()
    logging.info("=" * 80)
    prefix = "" if is_success else "Benchmark failed. "

    while True:
      try:
        user_input = input_helper.prompt(
            f"{prefix}Runner paused between runs. Continue or stop? [C/S]: ")
      except EOFError:
        return ResumeMode.STOP
      if resume_mode := self._parse_resume_mode(user_input):
        return resume_mode

  @staticmethod
  def _parse_resume_mode(user_input: str) -> ResumeMode | None:
    try:
      return ObjectParser.enum("action", ResumeMode,
                               user_input.strip().upper(), ResumeMode)
    except argparse.ArgumentTypeError as e:
      logging.warning(e)
      return None
