# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

from crossbench.action_runner.action.enums import ReadyState
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.meet_create import MeetCreateAction
from crossbench.action_runner.action.meet_script import MeetScriptAction
from crossbench.action_runner.action_runner import ActionRunner
from crossbench.action_runner.bond_action_runner import BondActionRunner
from crossbench.cli.config.secrets import ServiceAccount
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase

NOW_EPOCH = dt.datetime.now()


class BondActionRunnerTestCase(BaseCrossbenchTestCase):

  SECRET = ServiceAccount.parse_dict({
      "type": "fake",
      "project_id": "My Project",
      "private_key_id": "0badc0de",
      "private_key": "-----BEGIN PRIVATE KEY-----\n...",
      "client_email": "name@example.com",
      "client_id": "3",
      "auth_uri": "https://accounts.example.com/oauth2/auth",
      "token_uri": "https://oath2.example.com/token",
      "auth_provider_x509_cert_url": "https://example.com/oauth2/certs",
      "client_x509_cert_url": "https://example.com/x509",
      "universe_domain": "example.com",
  })

  def _make_mock_run(self):
    mock_run = MagicMock(name="Mock Run")
    mock_run.secrets = MagicMock(name="Mock Secrets")
    mock_run.secrets.bond = self.SECRET
    return mock_run

  def _make_meet_create_mocks(self,
                              mock_datetime,
                              mock_bond_client_cls,
                              create_meeting_duration=dt.timedelta(seconds=1),
                              add_bots_duration=dt.timedelta(seconds=2),
                              timeout=dt.timedelta(seconds=30)):
    mock_datetime.now.side_effect = [
        NOW_EPOCH,  # deadline init
        NOW_EPOCH + create_meeting_duration,  # get timeout after create_meeting
        NOW_EPOCH + create_meeting_duration +
        add_bots_duration,  # get timeout after add_bots
    ]
    mock_run = self._make_mock_run()
    mock_action_runner = MagicMock(name="Mock ActionRunner")
    mock_action_runner.run = mock_run
    mock_action_runner.get.side_effect = [None]

    bond_action_runner = BondActionRunner(mock_action_runner)

    mock_bond_client = mock_bond_client_cls.return_value
    mock_bond_client.create_meeting.side_effect = ["mock-conference-code"]
    mock_bond_client.add_bots.side_effect = [
        [1, 2, 3],
    ]
    action = MeetCreateAction.parse_dict({
        "action": "meet_create",
        "bots": {
            "num_of_bots": 3,
            "ttl_secs": 123,
        },
        "timeout": timeout,
    })
    return (mock_run, mock_bond_client, mock_action_runner, bond_action_runner,
            action)

  def test_get_current_conference_code(self):
    mock_run = self._make_mock_run()
    action_runner = ActionRunner(mock_run)
    bond_action_runner = BondActionRunner(action_runner)
    for browser in self.browsers:
      browser.set_current_url("https://meet.google.com/abc-def-ghi")
      code = bond_action_runner.get_current_conference_code(browser=browser)
      self.assertEqual(code, "abc-def-ghi")

  def test_get_current_conference_code_invalid(self):
    mock_run = self._make_mock_run()
    action_runner = ActionRunner(mock_run)
    bond_action_runner = BondActionRunner(action_runner)
    for browser in self.browsers:
      browser.set_current_url("https://www.google.com")
      with self.assertRaisesRegex(RuntimeError,
                                  "Unsupported URL for Bond action"):
        bond_action_runner.get_current_conference_code(browser=browser)

  @patch(
      "crossbench.action_runner.bond_action_runner.BondClient", autospec=True)
  @patch("crossbench.action_runner.bond_action_runner.dt.datetime")
  def test_meet_create(self, mock_datetime, mock_bond_client_cls):
    (mock_run, mock_bond_client, mock_action_runner, bond_action_runner,
     action) = self._make_meet_create_mocks(mock_datetime, mock_bond_client_cls)

    bond_action_runner.meet_create(action)

    mock_bond_client.create_meeting.assert_called_once_with(
        timeout=dt.timedelta(seconds=30))
    mock_bond_client.add_bots.assert_called_once_with(
        "mock-conference-code", action.bots, timeout=dt.timedelta(seconds=29))
    mock_action_runner.get.assert_called_once_with(
        GetAction.create(
            "https://meet.google.com/mock-conference-code",
            ready_state=ReadyState.COMPLETE,
            target=action.target,
            timeout=dt.timedelta(seconds=27)))

  @patch(
      "crossbench.action_runner.bond_action_runner.BondClient", autospec=True)
  @patch("crossbench.action_runner.bond_action_runner.dt.datetime")
  def test_meet_create_create_meeting_timeout(self, mock_datetime,
                                              mock_bond_client_cls):
    (mock_run, mock_bond_client, mock_action_runner, bond_action_runner,
     action) = self._make_meet_create_mocks(
         mock_datetime,
         mock_bond_client_cls,
         create_meeting_duration=dt.timedelta(seconds=30))

    with self.assertRaises(TimeoutError):
      bond_action_runner.meet_create(action)

    mock_bond_client.create_meeting.assert_called_once_with(
        timeout=dt.timedelta(seconds=30))
    mock_bond_client.add_bots.assert_not_called()
    mock_action_runner.get.assert_not_called()

  @patch(
      "crossbench.action_runner.bond_action_runner.BondClient", autospec=True)
  @patch("crossbench.action_runner.bond_action_runner.dt.datetime")
  def test_meet_create_add_bots_timeout(self, mock_datetime,
                                        mock_bond_client_cls):
    (mock_run, mock_bond_client, mock_action_runner, bond_action_runner,
     action) = self._make_meet_create_mocks(
         mock_datetime,
         mock_bond_client_cls,
         create_meeting_duration=dt.timedelta(seconds=1),
         add_bots_duration=dt.timedelta(seconds=29))

    with self.assertRaises(TimeoutError):
      bond_action_runner.meet_create(action)

    mock_bond_client.create_meeting.assert_called_once_with(
        timeout=dt.timedelta(seconds=30))
    mock_bond_client.add_bots.assert_called_once_with(
        "mock-conference-code", action.bots, timeout=dt.timedelta(seconds=29))
    mock_action_runner.get.assert_not_called()

  @patch(
      "crossbench.action_runner.bond_action_runner.BondClient", autospec=True)
  def test_meet_script(self, mock_bond_client_cls):
    mock_run = self._make_mock_run()
    mock_action_runner = MagicMock(name="Mock ActionRunner")
    mock_action_runner.run = mock_run
    bond_action_runner = BondActionRunner(mock_action_runner)

    mock_run.browser.current_url = "https://meet.google.com/abc-def-ghi"

    action = MeetScriptAction.parse_dict({
        "action": "meet_script",
        "script": "test script",
        "timeout": 17,
    })

    mock_bond_client = mock_bond_client_cls.return_value
    mock_bond_client.run_script.side_effect = [None]

    bond_action_runner.meet_script(action)

    mock_bond_client.run_script.assert_called_once_with(
        "abc-def-ghi", "test script", dt.timedelta(seconds=17))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
