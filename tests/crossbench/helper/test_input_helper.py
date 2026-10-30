# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import os
import sys
import threading
import unittest
from unittest import mock

from crossbench.helper import input_helper
from crossbench.helper.input_helper import PosixStdinCoordinator, \
    StdinCoordinator
from tests import test_helper


class InputHelperTestCase(unittest.TestCase):

  def _make_tty_coordinator(self) -> tuple[PosixStdinCoordinator, int]:
    stdin_r, stdin_w = os.pipe()
    self.addCleanup(self._close_fd, stdin_r)
    self.addCleanup(self._close_fd, stdin_w)
    mock_stdin = self.enterContext(mock.patch("sys.stdin"))
    mock_stdin.fileno.return_value = stdin_r
    self.enterContext(mock.patch("termios.tcgetattr", return_value=[1, 2, 3]))
    self._mock_tcsetattr = self.enterContext(mock.patch("termios.tcsetattr"))
    self._mock_setcbreak = self.enterContext(mock.patch("tty.setcbreak"))
    coordinator = PosixStdinCoordinator()
    self.addCleanup(coordinator._stop)
    return coordinator, stdin_w

  @staticmethod
  def _close_fd(fd: int) -> None:
    with contextlib.suppress(OSError):
      os.close(fd)

  def test_module_helpers_delegate_to_shared(self) -> None:
    self.assertIsInstance(input_helper._SHARED,
                          StdinCoordinator)  # noqa: SLF001
    timeout = dt.timedelta(seconds=3)
    with mock.patch.object(
        input_helper._SHARED,  # noqa: SLF001
        "prompt",
        return_value="ok") as mock_prompt, \
         mock.patch.object(
             input_helper._SHARED,  # noqa: SLF001
             "input_with_timeout",
             return_value="timed") as mock_timed:
      self.assertEqual(input_helper.prompt("msg:"), "ok")
      mock_prompt.assert_called_once_with("msg:")
      self.assertEqual(input_helper.input_with_timeout(timeout), "timed")
      mock_timed.assert_called_once_with(timeout)
    with mock.patch.object(input_helper.shared(), "suspend") as mock_suspend:
      with input_helper.suspend():
        pass
      mock_suspend.assert_called_once_with()

  def test_register_and_stop_without_cbreak(self) -> None:
    with mock.patch("sys.stdin") as mock_stdin, \
         mock.patch("tty.setcbreak") as mock_setcbreak, \
         mock.patch("termios.tcsetattr") as mock_tcsetattr:
      mock_stdin.fileno.return_value = 0
      coordinator = PosixStdinCoordinator()
      with mock.patch("termios.tcgetattr", side_effect=OSError("bad tty")):
        coordinator.register_key("p", lambda: None)
      mock_setcbreak.assert_not_called()
      coordinator._stop()
      mock_tcsetattr.assert_not_called()

  def test_register_key_validation_and_collision(self) -> None:
    coordinator, _ = self._make_tty_coordinator()
    with self.assertRaises(ValueError):
      coordinator.register_key("", lambda: None)
    coordinator.register_key("p", lambda: None)
    with self.assertRaises(ValueError):
      coordinator.register_key("p", lambda: None)
    coordinator.unregister_key("p")
    coordinator.register_key("p", lambda: None)

  def test_multiple_keys_and_partial_unregister(self) -> None:
    coordinator, stdin_w = self._make_tty_coordinator()
    received: list[str] = []
    done_event = threading.Event()

    def on_ctrl_p() -> None:
      received.append("ctrl_p")
      if len(received) == 3:
        done_event.set()

    def on_q() -> None:
      received.append("q")

    coordinator.register_key("\x10", on_ctrl_p)
    coordinator.register_key("q", on_q)
    self._mock_setcbreak.assert_called_once()
    os.write(stdin_w, b"\x10xq")
    # Wait until "q" is processed before unregistering "q".
    while "q" not in received:
      threading.Event().wait(0.01)
    coordinator.unregister_key("q")
    # Unregistering "q" keeps the listener active for "\x10".
    self._mock_tcsetattr.assert_not_called()
    os.write(stdin_w, b"q\x10")
    self.assertTrue(done_event.wait(timeout=2.0))
    self.assertEqual(received, ["ctrl_p", "q", "ctrl_p"])
    coordinator.unregister_key("\x10")
    self._mock_tcsetattr.assert_called_once()

  def test_prompt_suspends_and_restarts_active_listener(self) -> None:
    coordinator, stdin_w = self._make_tty_coordinator()
    received: list[str] = []
    key_event = threading.Event()

    def on_ctrl_p() -> None:
      received.append("\x10")
      key_event.set()

    coordinator.register_key("\x10", on_ctrl_p)
    self._mock_setcbreak.assert_called_once()
    with mock.patch("builtins.input", return_value="hello") as mock_input:
      self.assertEqual(coordinator.prompt("question:"), "hello")
    mock_input.assert_called_once_with("question:")
    self._mock_tcsetattr.assert_called_once()
    with self.assertRaises(ValueError):
      with mock.patch("builtins.input", side_effect=ValueError("boom")):
        coordinator.prompt("question:")
    os.write(stdin_w, b"\x10")
    self.assertTrue(key_event.wait(timeout=2.0))
    self.assertEqual(received, ["\x10"])

  def test_suspend_stops_listener_from_consuming_stdin_and_nests(self) -> None:
    coordinator, stdin_w = self._make_tty_coordinator()
    received: list[str] = []
    key_event = threading.Event()

    def on_ctrl_p() -> None:
      received.append("\x10")
      key_event.set()

    coordinator.register_key("\x10", on_ctrl_p)
    self._mock_setcbreak.assert_called_once()
    with coordinator.suspend():
      self._mock_tcsetattr.assert_called_once()
      with coordinator.suspend():
        os.write(stdin_w, b"secret_password\n")
        # Inner suspend exit must not restart the listener yet.
      self.assertEqual(self._mock_setcbreak.call_count, 1)
      # Another process (e.g. sudo) can read the full password intact.
      self.assertEqual(os.read(sys.stdin.fileno(), 16), b"secret_password\n")
    # Exiting the outer suspend restarts the listener.
    self.assertEqual(self._mock_setcbreak.call_count, 2)
    os.write(stdin_w, b"\x10")
    self.assertTrue(key_event.wait(timeout=2.0))
    self.assertEqual(received, ["\x10"])

  def test_input_with_timeout(self) -> None:
    timeout = dt.timedelta(seconds=5)
    self.enterContext(mock.patch("sys.stdin"))
    coordinator = PosixStdinCoordinator()
    self.addCleanup(coordinator._stop)
    with mock.patch("select.select", return_value=([object()], [], [])), \
         mock.patch("builtins.input", return_value="hello"):
      self.assertEqual(coordinator.input_with_timeout(timeout), "hello")
    with mock.patch("select.select", return_value=([object()], [], [])), \
         mock.patch("builtins.input", return_value=""):
      self.assertEqual(coordinator.input_with_timeout(timeout), "")
    with mock.patch("select.select", return_value=([object()], [], [])), \
         mock.patch("builtins.input", side_effect=EOFError):
      self.assertIsNone(coordinator.input_with_timeout(timeout))
    with mock.patch("select.select", return_value=([], [], [])), \
         mock.patch("builtins.input") as mock_input:
      self.assertIsNone(coordinator.input_with_timeout(timeout))
      mock_input.assert_not_called()

  def test_non_posix_coordinator(self) -> None:
    timeout = dt.timedelta(seconds=5)
    self.enterContext(mock.patch("sys.stdin"))
    coordinator = StdinCoordinator()
    coordinator.register_key("p", lambda: None)
    coordinator.unregister_key("p")
    with mock.patch("builtins.input", return_value="hello"):
      self.assertEqual(coordinator.prompt("question:"), "hello")
      self.assertEqual(coordinator.input_with_timeout(timeout), "hello")
    with mock.patch("builtins.input", return_value=""):
      self.assertEqual(coordinator.input_with_timeout(timeout), "")
    blocked = threading.Event()
    self.addCleanup(blocked.set)
    with mock.patch(
        "builtins.input", side_effect=lambda: blocked.wait() and "late"):
      self.assertIsNone(
          coordinator.input_with_timeout(dt.timedelta(milliseconds=1)))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
