# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
from unittest import mock

from crossbench import path as pth
from crossbench.exception import ArgumentTypeMultiException
from crossbench.probes.probe_error import ProbeIncompatibleBrowser, \
    ProbeValidationError
from crossbench.probes.profiling.enum import TargetMode
from crossbench.probes.xcode_instruments.recorder import XctraceRecorder
from crossbench.probes.xcode_instruments.xcode_instruments import \
    XcodeInstrumentsProbe
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class TargetPlatform(enum.Enum):
  MACOS = "macOS"
  IOS = "iOS"
  OTHER = "other"


def _mock_browser(target_platform: TargetPlatform, host_is_macos: bool,
                  has_xctrace: bool) -> mock.Mock:
  browser = mock.Mock()
  browser.platform.is_macos = (target_platform == TargetPlatform.MACOS)
  browser.platform.is_ios = (target_platform == TargetPlatform.IOS)
  browser.host_platform.is_macos = host_is_macos
  browser.host_platform.which.return_value = ("/usr/bin/xctrace"
                                              if has_xctrace else None)
  return browser


class XcodeInstrumentsProbeTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.template = pth.LocalPath("/tmp/counters.tracetemplate")
    self.fs.create_file(self.template)
    self.template = self.template.resolve()

  def test_default_target(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    self.assertEqual(probe.target, TargetMode.SYSTEM_WIDE)

  def test_template_is_required(self):
    with self.assertRaises(ArgumentTypeMultiException):
      XcodeInstrumentsProbe.parse_dict({})

  def test_parse_dict(self):
    probe = XcodeInstrumentsProbe.parse_dict({
        "template": str(self.template),
        "target": "browser_app_only",
    })
    self.assertEqual(probe.template, self.template)
    self.assertEqual(probe.target, TargetMode.BROWSER_APP_ONLY)

  def test_parse_str(self):
    probe = XcodeInstrumentsProbe.parse_str(str(self.template))
    self.assertEqual(probe.template, self.template)
    self.assertEqual(probe.target, TargetMode.SYSTEM_WIDE)

  def test_parse_dict_missing_template_file(self):
    with self.assertRaises(ArgumentTypeMultiException):
      XcodeInstrumentsProbe.parse_dict({"template": "/does/not/exist.xyz"})

  def test_key_differs_by_template(self):
    probe_a = XcodeInstrumentsProbe(template=self.template)
    other = pth.LocalPath("/tmp/other.tracetemplate")
    self.fs.create_file(other)
    probe_b = XcodeInstrumentsProbe(template=other)
    self.assertNotEqual(probe_a.key, probe_b.key)

  def test_key_differs_by_target(self):
    probe_a = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.SYSTEM_WIDE)
    probe_b = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.BROWSER_APP_ONLY)
    self.assertNotEqual(probe_a.key, probe_b.key)

  def test_validate_macos_ok(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    probe.validate_browser(
        mock.Mock(),
        _mock_browser(
            TargetPlatform.MACOS, host_is_macos=True, has_xctrace=True))

  def test_validate_ios_ok(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    probe.validate_browser(
        mock.Mock(),
        _mock_browser(TargetPlatform.IOS, host_is_macos=True, has_xctrace=True))

  def test_validate_rejects_other_platform(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    with self.assertRaisesRegex(ProbeIncompatibleBrowser, "(?i)macOS and iOS"):
      probe.validate_browser(
          mock.Mock(),
          _mock_browser(
              TargetPlatform.OTHER, host_is_macos=True, has_xctrace=True))

  def test_validate_rejects_non_macos_host(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    with self.assertRaisesRegex(ProbeIncompatibleBrowser, "(?i)macOS host"):
      probe.validate_browser(
          mock.Mock(),
          _mock_browser(
              TargetPlatform.IOS, host_is_macos=False, has_xctrace=True))

  def test_validate_rejects_missing_xctrace(self):
    probe = XcodeInstrumentsProbe(template=self.template)
    with self.assertRaisesRegex(ProbeValidationError, "(?i)install Xcode"):
      probe.validate_browser(
          mock.Mock(),
          _mock_browser(
              TargetPlatform.MACOS, host_is_macos=True, has_xctrace=False))

  def test_validate_rejects_invalid_targets(self):
    browser = _mock_browser(
        TargetPlatform.MACOS, host_is_macos=True, has_xctrace=True)
    probe_auto = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.AUTO)
    with self.assertRaisesRegex(
        ProbeIncompatibleBrowser,
        f"(?i)Unsupported target mode: {TargetMode.AUTO}"):
      probe_auto.validate_browser(mock.Mock(), browser)

    probe_renderer_main = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.RENDERER_MAIN_ONLY)
    with self.assertRaisesRegex(
        ProbeIncompatibleBrowser,
        f"(?i)Unsupported target mode: {TargetMode.RENDERER_MAIN_ONLY}"):
      probe_renderer_main.validate_browser(mock.Mock(), browser)


class XcodeInstrumentsContextTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.template = pth.LocalPath("/tmp/counters.tracetemplate")
    self.fs.create_file(self.template)
    self.template = self.template.resolve()

  def _create_context(self, probe, browser):
    run = mock.Mock()
    run.browser = browser
    run.get_default_probe_result_path.return_value = pth.LocalPath(
        "/tmp/result")
    return probe.create_context(run)

  def test_get_attach_pid_system_wide(self):
    probe = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.SYSTEM_WIDE)
    browser = _mock_browser(
        TargetPlatform.MACOS, host_is_macos=True, has_xctrace=True)
    context = self._create_context(probe, browser)
    self.assertIsNone(context.get_attach_pid())

  def test_get_attach_pid_browser_app_only(self):
    probe = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.BROWSER_APP_ONLY)
    browser = _mock_browser(
        TargetPlatform.MACOS, host_is_macos=True, has_xctrace=True)
    browser.pid = 1234
    context = self._create_context(probe, browser)
    self.assertEqual(context.get_attach_pid(), 1234)

    browser.pid = None
    context = self._create_context(probe, browser)
    with self.assertRaisesRegex(ValueError, "(?i)browser-app tracing"):
      context.get_attach_pid()

  def test_get_attach_pid_renderer_process_only(self):
    probe = XcodeInstrumentsProbe(
        template=self.template, target=TargetMode.RENDERER_PROCESS_ONLY)
    browser = _mock_browser(
        TargetPlatform.MACOS, host_is_macos=True, has_xctrace=True)
    browser.get_renderer_pid.return_value = 5678
    context = self._create_context(probe, browser)
    self.assertEqual(context.get_attach_pid(), 5678)

    browser.get_renderer_pid.return_value = None
    context = self._create_context(probe, browser)
    with self.assertRaisesRegex(ValueError, "(?i)renderer-only tracing"):
      context.get_attach_pid()


class XctraceRecorderTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.template = pth.LocalPath("/tmp/counters.tracetemplate")
    self.output_path = pth.LocalPath("/tmp/result/trace.trace")
    self.fs.create_file(self.template)
    self.fs.create_dir(self.output_path.parent)

  def test_request_stop_signals_sigint(self):
    mock_platform = mock.Mock()
    mock_platform.is_file.return_value = True
    mock_platform.exists.return_value = True
    mock_process = mock.Mock()
    mock_process.poll.return_value = None
    mock_platform.popen.return_value = mock_process
    mock_platform.signals.SIGINT = 2

    recorder = XctraceRecorder(mock_platform, self.template, self.output_path)
    recorder.start()
    recorder.request_stop()
    mock_platform.send_signal.assert_called_once_with(mock_process, 2)

  def test_finalize_waits_and_unregisters(self):
    mock_platform = mock.Mock()
    mock_platform.is_file.return_value = True
    mock_platform.exists.return_value = True
    mock_process = mock.Mock()
    mock_process.poll.return_value = None
    mock_platform.popen.return_value = mock_process
    mock_platform.signals.SIGINT = 2

    recorder = XctraceRecorder(mock_platform, self.template, self.output_path)
    recorder.start()
    recorder.finalize()
    mock_platform.terminate_gracefully.assert_called_once()
    self.assertFalse(recorder.is_recording)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
