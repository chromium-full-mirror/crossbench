# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import contextlib
import pathlib
from unittest import mock

from crossbench.helper import input_helper
from crossbench.network.replay.web_page_replay import _WPR_PORT_RE, \
    WprReplayServer, WprStartupError
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase


class TestWprLogLineRegex(BaseCrossbenchTestCase):

  def test_no_match(self):
    line = "2025/10/13 10:26:23 ScriptInjector(https://www.google.com/search?q=cats): succesfully injected"
    match = _WPR_PORT_RE.match(line)
    self.assertIsNone(match)

  def test_ipv4_line(self):
    line = "2025/10/13 10:26:29 Starting server on https://127.0.0.1:36013"
    match = _WPR_PORT_RE.match(line)
    self.assertIsNotNone(match)
    self.assertEqual(match["protocol"], "https")
    self.assertEqual(match["host"], "127.0.0.1")
    self.assertEqual(match["port"], "36013")

  def test_ipv6_line(self):
    line = "2025/10/13 10:26:29 Starting server on http://[::]:80"
    match = _WPR_PORT_RE.match(line)
    self.assertIsNotNone(match)
    self.assertEqual(match["protocol"], "http")
    self.assertEqual(match["host"], "[::]")
    self.assertEqual(match["port"], "80")


class WprReplayServerTestCase(BaseCrossbenchTestCase):

  def setUp(self):
    super().setUp()
    self.wpr_root = pathlib.Path("/wpr")
    self.archive_path = self.wpr_root / "archive.wprgo"
    self.wpr_go_bin = self.wpr_root / "wpr.go"
    self.log_path = pathlib.Path("/out/network.wpr.log")
    self.fs.create_dir("/out")
    self.fs.create_file(self.archive_path, contents=b"archive")
    self.fs.create_file(self.wpr_go_bin, contents=b"binary")
    self.fs.create_file(self.wpr_root / "ecdsa_key.pem", contents=b"key")
    self.fs.create_file(self.wpr_root / "ecdsa_cert.pem", contents=b"cert")
    self.fs.create_file(self.wpr_root / "deterministic.js", contents=b"js")
    self.enterContext(
        mock.patch(
            "crossbench.network.replay.web_page_replay.WprGoFinder.local_path",
            new_callable=mock.PropertyMock,
            return_value=self.wpr_root))

  def _create_server(self, run_as_root: bool = True) -> WprReplayServer:
    return WprReplayServer(
        archive_path=self.archive_path,
        bin_path=self.wpr_go_bin,
        http_port=80,
        https_port=443,
        log_path=self.log_path,
        run_as_root=run_as_root,
        platform=self.platform)

  def test_start_suspends_input_helper_until_startup_completes(self):
    server = self._create_server(run_as_root=True)
    events: list[str] = []

    @contextlib.contextmanager
    def fake_suspend():
      events.append("suspend_enter")
      try:
        yield
      finally:
        events.append("suspend_exit")

    with mock.patch.object(
        input_helper, "suspend", side_effect=fake_suspend), \
         mock.patch.object(
             server,
             "_start_wpr",
             side_effect=lambda: events.append("start_wpr")), \
         mock.patch.object(
             server,
             "_wait_for_startup",
             side_effect=lambda: events.append("wait_for_startup")):
      server.start()

    self.assertEqual(
        events,
        ["suspend_enter", "start_wpr", "wait_for_startup", "suspend_exit"])

  def _start_with_startup_error(self, server: WprReplayServer,
                                poll_result: int | None) -> mock.Mock:
    mock_proc = mock.Mock(pid=1234)
    mock_proc.poll.return_value = poll_result
    with mock.patch.object(self.platform, "popen", return_value=mock_proc), \
         mock.patch.object(
             server,
             "_wait_for_startup",
             side_effect=WprStartupError("startup failed")), \
         mock.patch.object(self.platform, "sh") as mock_sh, \
         self.assertRaises(WprStartupError):
      server.start()
    return mock_sh

  def test_failed_start_as_root_skips_kill_when_already_exited(self):
    server = self._create_server(run_as_root=True)
    mock_sh = self._start_with_startup_error(server, poll_result=1)
    mock_sh.assert_not_called()

  def test_failed_start_as_root_kills_running_process(self):
    server = self._create_server(run_as_root=True)
    with mock.patch.object(
        input_helper, "suspend", wraps=input_helper.suspend) as mock_suspend:
      mock_sh = self._start_with_startup_error(server, poll_result=None)
    mock_sh.assert_called_once_with("sudo", "kill", "1234")
    # Once around startup and once around `sudo kill`.
    self.assertEqual(mock_suspend.call_count, 2)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
