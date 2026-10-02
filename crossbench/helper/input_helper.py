# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Centralized access to `sys.stdin` for interactive terminal features.

Use module-level `prompt()` and `input_with_timeout()` to read user input and
`shared().register_key()` / `shared().unregister_key()` for single-key
callbacks instead of reading `sys.stdin` directly.
"""

from __future__ import annotations

import atexit
import contextlib
import datetime as dt
import logging
import os
import select
import sys
import threading
from typing import Any, Callable, Final

from typing_extensions import override

try:
  import termios
  import tty
except ImportError:
  termios = None  # type: ignore
  tty = None  # type: ignore

KeyHandler = Callable[[], None]
_POLL_INTERVAL_SEC: Final[float] = 0.05
_JOIN_TIMEOUT_SEC: Final[float] = 0.5
_DEFAULT_TIMEOUT: Final[dt.timedelta] = dt.timedelta(seconds=10)


def shared() -> StdinCoordinator:
  """Returns the process-wide coordinator that owns `sys.stdin`."""
  return _SHARED


def prompt(message: str) -> str:
  """Suspends the key listener, prints `message`, and reads a line."""
  return _SHARED.prompt(message)


def input_with_timeout(timeout: dt.timedelta = _DEFAULT_TIMEOUT) -> str | None:
  """Suspends the key listener and reads a line within `timeout`.

  Returns None on timeout or EOF (Ctrl-D).
  """
  return _SHARED.input_with_timeout(timeout)


class StdinCoordinator:
  """Coordinates interactive `sys.stdin` access."""

  def __init__(self) -> None:
    self._reader: Final[_StdinReader] = _StdinReader()

  def prompt(self, message: str) -> str:
    return input(message)

  def input_with_timeout(
      self,
      timeout: dt.timedelta = _DEFAULT_TIMEOUT,
  ) -> str | None:
    timeout_s = max(0.0, timeout.total_seconds())
    return self._reader.read_line_threaded(timeout_s)

  def register_key(self, key: str, handler: KeyHandler) -> None:
    del key, handler
    logging.debug("StdinCoordinator: no cbreak support, listener disabled.")

  def unregister_key(self, key: str) -> None:
    del key


class PosixStdinCoordinator(StdinCoordinator):
  """`StdinCoordinator` with a background `cbreak` key listener.

  Because concurrent `sys.stdin` readers split keystrokes arbitrarily, this
  class acts as the single reader: it runs a background `cbreak` listener
  while handlers are registered, and suspends it to restore canonical terminal
  mode during line prompts.
  """

  def __init__(self) -> None:
    super().__init__()
    self._handlers: Final[dict[str, KeyHandler]] = {}
    self._terminal: Final[_TerminalModeController] = _TerminalModeController()
    self._stop_event: Final[threading.Event] = threading.Event()
    self._thread: threading.Thread | None = None
    atexit.register(self._stop)

  @override
  def prompt(self, message: str) -> str:
    """Suspends the key listener, prints `message`, and reads a line."""
    self._stop_listener()
    try:
      return super().prompt(message)
    finally:
      self._start_listener()

  @override
  def input_with_timeout(
      self,
      timeout: dt.timedelta = _DEFAULT_TIMEOUT,
  ) -> str | None:
    """Suspends the key listener and reads a line within `timeout`.

    Returns None on timeout or EOF (Ctrl-D).
    """
    timeout_s = max(0.0, timeout.total_seconds())
    self._stop_listener()
    try:
      return self._reader.read_line(timeout_s)
    finally:
      self._start_listener()

  @override
  def register_key(self, key: str, handler: KeyHandler) -> None:
    """Registers `handler` for `key` and starts listening on stdin."""
    if not key:
      raise ValueError("Key must not be empty.")
    if key in self._handlers:
      raise ValueError(f"Key {key!r} is already registered.")
    self._handlers[key] = handler
    self._start_listener()

  @override
  def unregister_key(self, key: str) -> None:
    """Unregisters `key` and stops listening if no handlers remain."""
    self._handlers.pop(key, None)
    if not self._handlers:
      self._stop_listener()

  def _stop(self) -> None:
    """Clears all key handlers, stops listening, and restores the terminal."""
    atexit.unregister(self._stop)
    self._handlers.clear()
    self._stop_listener()

  def _start_listener(self) -> None:
    if not self._handlers or self._thread:
      return
    if (fd := self._terminal.enable_cbreak()) is None:
      return

    self._stop_event.clear()
    self._thread = threading.Thread(
        target=self._listen_loop,
        args=(fd,),
        name="crossbench-stdin-listener",
        daemon=True,
    )
    self._thread.start()

  def _stop_listener(self) -> None:
    self._stop_event.set()
    if thread := self._thread:
      thread.join(timeout=_JOIN_TIMEOUT_SEC)
      if thread.is_alive():
        logging.debug("StdinCoordinator: key listener did not stop in time.")
      else:
        self._thread = None
    self._terminal.restore()

  def _listen_loop(self, fd: int) -> None:
    """Forwards keypresses to registered handlers until stopped."""
    try:
      while not self._stop_event.is_set():
        if not (char := self._reader.read_key(fd)):
          continue
        if handler := self._handlers.get(char):
          handler()
    except (OSError, ValueError) as e:
      logging.debug("StdinCoordinator: key listener stopped: %s", e)


class _TerminalModeController:
  """Enables cbreak mode on stdin and restores it later."""

  def __init__(self) -> None:
    self._old_termios: list[Any] | None = None

  def enable_cbreak(self) -> int | None:
    assert termios and tty
    try:
      fd = sys.stdin.fileno()
      old_termios = termios.tcgetattr(fd)
      tty.setcbreak(fd)
    except Exception as e:  # noqa: BLE001
      logging.debug("Failed to enable cbreak mode: %s", e)
      return None
    if self._old_termios is None:
      self._old_termios = old_termios
    return fd

  def restore(self) -> None:
    if not self._old_termios or not termios:
      return
    with contextlib.suppress(Exception):
      termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                        self._old_termios)
    self._old_termios = None


class _StdinReader:
  """Reads keys and lines from `sys.stdin`."""

  def read_key(self, fd: int) -> str | None:
    if not self._has_input(_POLL_INTERVAL_SEC):
      return None
    return os.read(fd, 1).decode("ascii", errors="ignore")

  def read_line(self, timeout_s: float) -> str | None:
    if not self._has_input(timeout_s):
      return None
    try:
      return input()
    except EOFError:
      return None

  def read_line_threaded(self, timeout_s: float) -> str | None:
    result: list[str | None] = [None]

    def read_target() -> None:
      result[0] = input()

    thread = threading.Thread(
        target=read_target, name="crossbench-stdin-input", daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)
    return result[0]

  def _has_input(self, timeout_s: float) -> bool:
    readable, _, _ = select.select([sys.stdin], [], [], timeout_s)
    return bool(readable)


_SHARED: Final[StdinCoordinator] = (
    PosixStdinCoordinator() if termios and tty else StdinCoordinator())
