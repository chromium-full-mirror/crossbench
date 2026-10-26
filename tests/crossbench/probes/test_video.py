# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
import unittest
import unittest.mock as mock

from crossbench import path as pth
from crossbench import plt
from crossbench.helper import wait
from crossbench.plt.ios import IOSPlatform
from crossbench.probes.probe_error import ProbeIncompatibleBrowser
from crossbench.probes.video import Orientation, VideoProbe, VideoProbeContext
from tests import test_helper


def _has_swift_toolchain() -> bool:
  # The recorder needs AVFoundation, and stock macOS ships /usr/bin/swiftc as
  # a shim that only works once a toolchain is installed.
  if not plt.PLATFORM.is_macos:
    return False
  try:
    plt.PLATFORM.sh("swiftc", "--version", quiet=True)
  except plt.SubprocessError:
    return False
  return True


class VideoProbeTestCase(unittest.TestCase):

  def test_default(self):
    probe = VideoProbe.parse_dict({})
    self.assertEqual(probe.primary_orientation, Orientation.HORIZONTAL)
    self.assertEqual(probe.secondary_orientation, Orientation.VERTICAL)

  def test_from_config(self):
    probe = VideoProbe.parse_dict({"orientation": "vertical"})
    self.assertEqual(probe.primary_orientation, Orientation.VERTICAL)
    self.assertEqual(probe.secondary_orientation, Orientation.HORIZONTAL)

    probe = VideoProbe.parse_dict({"dir": "horizontal"})
    self.assertEqual(probe.primary_orientation, Orientation.HORIZONTAL)
    self.assertEqual(probe.secondary_orientation, Orientation.VERTICAL)

  def test_ios_usb_recorder_source_exists(self):
    self.assertTrue(VideoProbe.IOS_USB_RECORDER_SOURCE.is_file())

  def test_validate_browser_rejects_simulators(self):
    probe = VideoProbe.parse_dict({})
    browser = mock.MagicMock()
    browser.platform = mock.MagicMock(spec=IOSPlatform, is_simulator=False)
    probe.attach(browser)
    probe.validate_browser(mock.MagicMock(), browser)
    browser.platform.is_simulator = True
    with self.assertRaises(ProbeIncompatibleBrowser):
      probe.validate_browser(mock.MagicMock(), browser)

  def test_setup_compiles_recorder_for_ios(self):
    probe = VideoProbe.parse_dict({})
    runner = mock.MagicMock()
    runner.out_dir = pth.LocalPath("/out")
    browser = mock.MagicMock()
    browser.platform.is_ios = False
    probe.attach(browser)
    probe.setup(runner)
    runner.platform.sh.assert_not_called()
    with self.assertRaises(AssertionError):
      _ = probe.ios_usb_recorder

    browser.platform.is_ios = True
    probe.setup(runner)
    binary = pth.LocalPath("/out/ios_usb_screen_recorder")
    runner.platform.sh.assert_called_once_with(
        "swiftc", "-O", VideoProbe.IOS_USB_RECORDER_SOURCE, "-o", binary)
    self.assertEqual(probe.ios_usb_recorder, binary)

  @unittest.skipIf(not _has_swift_toolchain(), "needs a macOS Swift toolchain")
  def test_ios_usb_recorder_source_typechecks(self):
    # Only runs on developer Macs; a full compile would take a few seconds,
    # type-checking catches the same mistakes without generating code.
    plt.PLATFORM.sh("swiftc", "-typecheck", VideoProbe.IOS_USB_RECORDER_SOURCE)


class VideoProbeContextIOSTestCase(unittest.TestCase):
  """The iOS device branches of the probe context, on a mocked context."""

  def setUp(self) -> None:
    self.tmp_dir = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp_dir.cleanup)
    self.result_path = pth.LocalPath(self.tmp_dir.name) / "video.mp4"
    self.context = mock.MagicMock(spec=VideoProbeContext)
    self.context.IOS_RECORDER_READY_WAIT = wait.WaitRange(
        min=dt.timedelta(milliseconds=10),
        max=dt.timedelta(milliseconds=10),
        timeout=dt.timedelta(milliseconds=300))
    self.context.IOS_RECORDER_STOP_TIMEOUT = dt.timedelta(seconds=1)
    self.context.result_path = self.result_path
    self.context.local_result_path = self.result_path
    self.context._recorder_log_path = self.result_path.with_suffix(
        ".recorder.log")
    self.context.host_platform = mock.MagicMock()
    self.context.probe = mock.MagicMock(
        FRAMERATE=60, ios_usb_recorder=pth.LocalPath("/out/recorder"))
    self.context._record_process = mock.MagicMock()
    self.context._record_process.poll.return_value = None
    self.context._recorder_log_file = None
    self.context._ios_recorder_is_ready = (
        lambda: VideoProbeContext._ios_recorder_is_ready(self.context))
    self.context._stop_ios_recorder = (
        lambda: VideoProbeContext._stop_ios_recorder(self.context))

  def _ios_platform(self, is_simulator: bool) -> mock.MagicMock:
    platform = mock.MagicMock(spec=IOSPlatform)
    platform.is_ios = True
    platform.is_linux = platform.is_macos = platform.is_android = False
    platform.is_simulator = is_simulator
    platform.model = "iPhone 18 - 3"
    return platform

  def test_default_result_path_is_local_on_ios(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context.run.get_local_probe_result_path.return_value = (
        self.result_path)
    path = VideoProbeContext.get_default_result_path(self.context)
    self.assertEqual(path, self.result_path)
    self.context.run.get_local_probe_result_path.assert_called_once_with(
        self.context.probe)

  def test_recorder_platform(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.assertIs(
        VideoProbeContext._recorder_platform.fget(self.context),
        self.context.host_platform)
    self.context.browser_platform = mock.MagicMock(is_ios=False)
    self.assertIs(
        VideoProbeContext._recorder_platform.fget(self.context),
        self.context.browser_platform)

  def test_start_waits_for_ready_on_ios(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._recorder_platform = mock.MagicMock(is_remote=False)
    self.context._recorder_platform.popen.return_value.poll.return_value = None
    VideoProbeContext.start(self.context)
    self.context._recorder_platform.popen.assert_called_once()
    self.context._wait_for_ios_recorder_ready.assert_called_once_with()
    self.context.host_platform.sleep.assert_not_called()

  def test_teardown_does_not_copy_from_browser_on_ios(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._recorder_platform = mock.MagicMock()
    self.context._recorder_platform.is_file.return_value = True
    self.context.probe.generate_timestrip = False
    self.result_path.touch()
    result = VideoProbeContext.teardown(self.context)
    self.context.stop_process.assert_called_once_with()
    self.context.browser_result.assert_not_called()
    self.assertEqual(result.file, self.result_path)

  def test_record_cmd_device(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    cmd = VideoProbeContext._record_cmd(self.context, mock.MagicMock())
    self.assertEqual(
        cmd, ("/out/recorder", "iPhone 18 - 3", str(self.result_path), "60"))

  def test_wait_for_ios_recorder_ready(self):
    self.context._recorder_log_path.write_text(
        "starting\nREADY\n", encoding="utf-8")
    VideoProbeContext._wait_for_ios_recorder_ready(self.context)
    self.context.host_platform.terminate_gracefully.assert_not_called()

  def test_wait_for_ios_recorder_ready_needs_whole_line(self):
    self.context._recorder_log_path.write_text(
        "NOT READY YET\n", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "not ready after"):
      VideoProbeContext._wait_for_ios_recorder_ready(self.context)

  def test_wait_for_ios_recorder_ready_timeout_stops_recorder(self):
    with self.assertRaisesRegex(RuntimeError, "not ready after"):
      VideoProbeContext._wait_for_ios_recorder_ready(self.context)
    self.context.stop_process.assert_called_once_with()

  def test_wait_for_ios_recorder_ready_exited(self):
    self.context._record_process.poll.return_value = 1
    with self.assertRaisesRegex(RuntimeError, "exited before"):
      VideoProbeContext._wait_for_ios_recorder_ready(self.context)
    self.context.stop_process.assert_called_once_with()

  def test_stop_and_teardown_after_failed_start(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._record_process = None
    VideoProbeContext.stop(self.context)
    self.assertTrue(VideoProbeContext.teardown(self.context).is_empty)
    self.context.stop_process.assert_not_called()

  def test_stop_device_closes_stdin(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    # Running when stop() checks, exited cleanly once stdin was closed.
    self.context._record_process.poll.side_effect = [None, 0]
    VideoProbeContext.stop(self.context)
    self.context._record_process.communicate.assert_called_once_with(
        timeout=1.0)
    self.context.host_platform.terminate_gracefully.assert_not_called()
    self.context.stop_process.assert_not_called()

  def test_stop_device_reports_failed_recorder(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._record_process.poll.side_effect = [None, 1]
    with self.assertRaisesRegex(RuntimeError, "exit code 1"):
      VideoProbeContext.stop(self.context)
    # The unfinished file must not reach teardown().
    self.context.stop_process.assert_called_once_with()

  def test_stop_device_terminates_when_stuck(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._record_process.communicate.side_effect = (
        subprocess.TimeoutExpired("recorder", 1))
    self.context._record_process.poll.side_effect = [None, -9]
    with self.assertRaisesRegex(RuntimeError, "exit code -9"):
      VideoProbeContext.stop(self.context)
    self.context.host_platform.terminate_gracefully.assert_called_once_with(
        self.context._record_process)
    self.context.stop_process.assert_called_once_with()

  def test_stop_device_keeps_file_finished_during_grace_period(self):
    self.context.browser_platform = self._ios_platform(is_simulator=False)
    self.context._record_process.communicate.side_effect = (
        subprocess.TimeoutExpired("recorder", 1))
    # SIGTERM let it finish after all.
    self.context._record_process.poll.side_effect = [None, 0]
    VideoProbeContext.stop(self.context)
    self.context.stop_process.assert_not_called()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
