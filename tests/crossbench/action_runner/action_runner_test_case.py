# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING
from unittest import mock

from crossbench.action_runner.action_runner import SCRIPTS_DIR
from tests.crossbench.base import CrossbenchFakeFsTestCase, \
    CrossbenchMockArgsMixin

if TYPE_CHECKING:
  from crossbench.cli.parser import CBNamespace
  from tests.crossbench.mock_browser import MockBrowser
  from tests.crossbench.mock_helper import MockPlatformMixin


class ActionRunnerTestCase(CrossbenchMockArgsMixin, CrossbenchFakeFsTestCase):
  platform: MockPlatformMixin
  browser: MockBrowser

  def setUp(self) -> None:
    super().setUp()
    self.fs.add_real_directory(SCRIPTS_DIR, lazy_read=True)

    init_time = dt.datetime.now()
    datetime_patcher = mock.patch("datetime.datetime", spec=dt.datetime)
    self.datetime_mock = datetime_patcher.start()
    self.addCleanup(datetime_patcher.stop)
    self.datetime_mock.now.return_value = init_time

    def sleep_side_effect(seconds):
      self.datetime_mock.now.return_value += dt.timedelta(seconds=seconds)
      logging.debug("mocked time advanced %fs to %s", seconds,
                    self.datetime_mock.now.return_value)

    self.sleep_mock.side_effect = sleep_side_effect

  def mock_args(self, **kwargs) -> CBNamespace:
    args = super().mock_args(**kwargs)
    args.stories = None
    args.story_tags = None
    args.separate = False
    args.pages_config = None
    return args

  def tearDown(self):
    expected_sh_cmds = self.platform.expected_sh_cmds
    if expected_sh_cmds is not None:
      self.assertSequenceEqual(expected_sh_cmds, [],
                               "Got additional unused shell cmds.")

    expected_js = self.browser.expected_js
    if expected_js is not None:
      self.assertSequenceEqual(expected_js, [],
                               "Got additional unused expected JS.")
