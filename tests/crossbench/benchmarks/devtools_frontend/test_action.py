# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.open_devtools import OpenDevToolsAction
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class ActionTestCase(CrossbenchFakeFsTestCase):

  def test_open_devtools(self):
    config_dict: dict[str, object] = {
        "action": "open_devtools",
        "panel_name": "resources",
    }
    action = OpenDevToolsAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.OPEN_DEVTOOLS)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.panel_name, "resources")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = OpenDevToolsAction.parse_dict(dict(action.to_json()))
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_open_devtools_no_panel(self):
    config_dict: dict[str, object] = {"action": "open_devtools"}
    action = OpenDevToolsAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.OPEN_DEVTOOLS)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.panel_name, "elements")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = OpenDevToolsAction.parse_dict(dict(action.to_json()))
    self.assertEqual(action, action_2)
    action_2.validate()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
