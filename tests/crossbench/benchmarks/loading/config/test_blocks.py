# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import unittest

from crossbench.action_runner.action.close_all_apps import CloseAllAppsAction
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.start_browser import StartBrowserAction
from crossbench.action_runner.action.stop_browser import StopBrowserAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.benchmarks.loading.config.blocks import ActionBlock, \
    ActionBlockListConfig
from crossbench.benchmarks.loading.config.login.custom import LoginBlock
from crossbench.benchmarks.loading.config.login.google import GoogleLogin
from crossbench.config import ConfigError
from tests import test_helper


class ActionBlockTestCase(unittest.TestCase):

  def test_create_empty_valid(self):
    block = ActionBlock()
    self.assertFalse(bool(block))
    self.assertFalse(block.is_login)
    self.assertEqual(len(block), 0)
    self.assertSequenceEqual(tuple(block), ())
    self.assertEqual(block.duration, dt.timedelta(seconds=0))
    self.assertTrue(hash(block))
    self.assertSetEqual({block}, {block, block})

  def test_single_action(self):
    action = GetAction.create(
        "http://test.com", duration=dt.timedelta(seconds=3))
    block = ActionBlock(actions=(action,))
    self.assertTrue(bool(block))
    self.assertFalse(block.is_login)
    self.assertEqual(len(block), 1)
    self.assertSequenceEqual(tuple(block), (action,))
    self.assertEqual(block.duration, dt.timedelta(seconds=3))
    self.assertTrue(hash(block))
    self.assertSetEqual({block}, {block, block})

    block = ActionBlock.parse(block.to_json())
    self.assertTrue(bool(block))
    self.assertFalse(block.is_login)
    self.assertEqual(len(block), 1)
    self.assertEqual(block.duration, dt.timedelta(seconds=3))

  def test_multi_action(self):
    action_2 = GetAction.create(
        "http://test.com/0", duration=dt.timedelta(seconds=1))
    action_1 = GetAction.create(
        "http://test.com/1", duration=dt.timedelta(seconds=2))
    block = ActionBlock(actions=(action_1, action_2))
    self.assertTrue(bool(block))
    self.assertFalse(block.is_login)
    self.assertEqual(len(block), 2)
    self.assertSequenceEqual(tuple(block), (action_1, action_2))
    self.assertEqual(block.duration, dt.timedelta(seconds=3))
    self.assertTrue(hash(block))
    self.assertSetEqual({block}, {block, block})

    block = ActionBlock.parse(block.to_json())
    self.assertTrue(bool(block))
    self.assertFalse(block.is_login)
    self.assertEqual(len(block), 2)
    self.assertEqual(block.duration, dt.timedelta(seconds=3))

  def test_multi_action_with_zero_duration(self):
    action_1 = GetAction.create(
        "http://test.com/1", duration=dt.timedelta(seconds=2))
    action_2 = JsAction.create("console.log('hi');")
    self.assertEqual(action_2.duration, dt.timedelta())
    with self.assertRaises(TypeError):
      JsAction(duration=dt.timedelta(seconds=1))  # type: ignore[call-arg]
    with self.assertRaises(TypeError):
      JsAction.create(
          duration=dt.timedelta(seconds=1))  # type: ignore[call-arg]
    block = ActionBlock(actions=(action_1, action_2))
    self.assertEqual(block.duration, dt.timedelta(seconds=2))

    block = ActionBlock.parse(block.to_json())
    self.assertEqual(block.duration, dt.timedelta(seconds=2))

  def test_start_stop_browser_interleaved_valid(self) -> None:
    start = StartBrowserAction()
    stop = StopBrowserAction()
    wait = WaitAction.create(duration=dt.timedelta(seconds=1))
    for actions in (
        (start,),
        (stop,),
        (start, wait, stop),
        (stop, wait, start),
        (start, wait, stop, wait, start),
        (stop, wait, start, wait, stop, wait, start),
    ):
      with self.subTest(actions=tuple(str(a.TYPE) for a in actions)):
        block = ActionBlock(actions=actions)
        self.assertEqual(len(block), len(actions))

  def test_start_browser_twice_in_a_row_invalid(self) -> None:
    start = StartBrowserAction()
    stop = StopBrowserAction()
    wait = WaitAction.create(duration=dt.timedelta(seconds=1))
    for actions in (
        (start, start),
        (start, wait, start),
        (start, wait, start, stop),
        (stop, start, wait, start),
    ):
      with self.subTest(actions=tuple(str(a.TYPE) for a in actions)):
        with self.assertRaisesRegex(ConfigError, "two 'start_browser' actions"):
          ActionBlock(actions=actions)

  def test_stop_browser_twice_in_a_row_invalid(self) -> None:
    start = StartBrowserAction()
    stop = StopBrowserAction()
    wait = WaitAction.create(duration=dt.timedelta(seconds=1))
    for actions in (
        (stop, stop),
        (stop, wait, stop),
        (stop, wait, stop, start),
        (start, stop, wait, stop),
    ):
      with self.subTest(actions=tuple(str(a.TYPE) for a in actions)):
        with self.assertRaisesRegex(ConfigError, "two 'stop_browser' actions"):
          ActionBlock(actions=actions)

  def test_start_stop_browser_across_blocks_invalid(self) -> None:
    start = StartBrowserAction()
    stop = StopBrowserAction()
    block_start_0 = ActionBlock(label="b0", index=0, actions=(start,))
    block_start_1 = ActionBlock(label="b1", index=1, actions=(start,))
    with self.assertRaisesRegex(ConfigError, "two 'start_browser' actions"):
      ActionBlockListConfig(blocks=(block_start_0, block_start_1))

    block_stop_0 = ActionBlock(label="b0", index=0, actions=(stop,))
    block_stop_1 = ActionBlock(label="b1", index=1, actions=(stop,))
    with self.assertRaisesRegex(ConfigError, "two 'stop_browser' actions"):
      ActionBlockListConfig(blocks=(block_stop_0, block_stop_1))

  def test_close_all_apps_stops_browser_for_validation(self) -> None:
    start = StartBrowserAction()
    stop = StopBrowserAction()
    close_all = CloseAllAppsAction()
    block = ActionBlock(actions=(start, close_all, start))
    self.assertEqual(len(block), 3)

    with self.assertRaisesRegex(ConfigError, "two 'stop_browser' actions"):
      ActionBlock(actions=(close_all, stop))


class LoginBlockTestCase(unittest.TestCase):

  def test_single_action(self):
    action = GetAction.create(
        "http://test.com", duration=dt.timedelta(seconds=3))
    block = LoginBlock(actions=(action,))
    self.assertTrue(bool(block))
    self.assertTrue(block.is_login)
    self.assertEqual(len(block), 1)
    self.assertSequenceEqual(tuple(block), (action,))
    self.assertEqual(block.duration, dt.timedelta(seconds=3))

    block = LoginBlock.parse(block.to_json())
    self.assertTrue(bool(block))
    self.assertTrue(block.is_login)
    self.assertEqual(len(block), 1)
    self.assertEqual(block.duration, dt.timedelta(seconds=3))

  def test_multi_action(self):
    action_2 = GetAction.create(
        "http://test.com/0", duration=dt.timedelta(seconds=1))
    action_1 = GetAction.create(
        "http://test.com/1", duration=dt.timedelta(seconds=2))
    block = LoginBlock(actions=(action_1, action_2))
    self.assertTrue(bool(block))
    self.assertTrue(block.is_login)
    self.assertEqual(len(block), 2)
    self.assertSequenceEqual(tuple(block), (action_1, action_2))
    self.assertEqual(block.duration, dt.timedelta(seconds=3))

    block = LoginBlock.parse(block.to_json())
    self.assertTrue(bool(block))
    self.assertTrue(block.is_login)
    self.assertEqual(len(block), 2)
    self.assertEqual(block.duration, dt.timedelta(seconds=3))


class PresetLoginBlockTestCase(unittest.TestCase):

  def test_google_login_block(self):
    block = GoogleLogin()
    self.assertTrue(bool(block))
    self.assertTrue(block.is_login)
    self.assertEqual(len(block), 1)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
