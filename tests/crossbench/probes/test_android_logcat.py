# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from unittest import mock

from crossbench.plt.android_adb import AndroidAdbPlatform
from crossbench.probes.android_logcat import AndroidLogcatProbeContext, \
    LogcatAndroidProbe
from crossbench.probes.probe import ProbeIncompatibleBrowser
from crossbench.probes.results import LocalProbeResult
from tests import test_helper
from tests.crossbench.probes.helper import BaseProbeTestCase


class LogcatAndroidProbeTestCase(BaseProbeTestCase):

  def test_parse_config(self):
    probe = LogcatAndroidProbe.config_parser().parse(
        {"filterspec": "ActivityManager:V"})
    self.assertSequenceEqual(probe.filterspec, ("ActivityManager:V",))

  def test_validate_browser_incompatible(self):
    probe = LogcatAndroidProbe(())
    browser = self.magic_mock_browser
    browser.platform.is_android = False
    env = mock.MagicMock()
    with self.assertRaises(ProbeIncompatibleBrowser):
      probe.validate_browser(env, browser)

  def test_probe_lifecycle_and_teardown(self):
    probe = LogcatAndroidProbe(("Tag:V",))
    run = self.mock_run()
    platform = mock.MagicMock(spec=AndroidAdbPlatform)
    run.browser_session.browser.platform = platform
    platform.is_android = True
    platform.sh_stdout.return_value = "2026-05-20 12:00:00\n"

    context = probe.create_context(run)
    self.assertIsInstance(context, AndroidLogcatProbeContext)

    context.start()
    platform.sh_stdout.assert_called_with("date", "+%Y-%m-%d %H:%M:%S")
    platform.sh.assert_called_with("log", "-t", "crossbench",
                                   "logcat probe start")
    context.stop()
    platform.sh.assert_called_with("log", "-t", "crossbench",
                                   "logcat probe end")

    result = context.teardown()
    self.assertIsInstance(result, LocalProbeResult)
    self.assertEqual(len(result.file_list), 1)
    self.assertTrue(result.file.exists())
    self.assertEqual(result.file.suffix, ".txt")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
