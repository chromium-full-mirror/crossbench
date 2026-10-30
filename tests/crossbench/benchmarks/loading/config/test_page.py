# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import unittest
from typing import Any

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.get import GetAction
from crossbench.benchmarks.loading.config.login.google import GoogleLogin
from crossbench.benchmarks.loading.config.page import PageConfig
from tests import test_helper


class PageConfigTestsCase(unittest.TestCase):

  def test_parse_empty(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty.*url"):
      PageConfig.parse("")

  def test_parse_unknown_type(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError, r"(?i)invalid"):
      PageConfig.parse(self)

  def test_parse_blank(self):
    config = PageConfig.parse("about:blank")
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "blank")
    self.assertEqual(config.first_url, "about:blank")

  def test_parse_file(self):
    config = PageConfig.parse("file://foo/bar/custom.html")
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "custom.html")
    self.assertEqual(config.first_url, "file://foo/bar/custom.html")
    self.assertEqual(config.tags, frozenset())

  def test_parse_tags(self):
    config = PageConfig.parse({
        "actions": ["http://a.com"],
        "tags": "tag1,tag2",
    })
    self.assertEqual(config.tags, frozenset(["tag1", "tag2"]))

    config2 = PageConfig.parse({
        "actions": ["http://a.com"],
        "tags": ["tag1", "tag2"],
    })
    self.assertEqual(config2.tags, frozenset(["tag1", "tag2"]))

    with self.assertRaises(argparse.ArgumentTypeError):
      PageConfig.parse({"actions": ["http://a.com"], "tags": ["tag1", "tag1"]})

  def test_parse_url(self):
    config = PageConfig.parse("http://www.a.com")
    self.assertEqual(config.first_url, "http://www.a.com")
    self.assertEqual(config.duration, dt.timedelta())
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "a.com")
    blocks = config.blocks
    self.assertEqual(len(blocks), 1)
    actions = blocks[0].actions
    self.assertEqual(len(actions), 2)
    self.assertEqual(actions[0].TYPE, ActionType.GET)
    self.assertEqual(actions[1].TYPE, ActionType.WAIT_FOR_READY_STATE)

  def test_parse_url_ftp_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = PageConfig.parse("ftp://www.a.com")
    self.assertIn("ftp", str(cm.exception))

  def test_parse_invalid_url(self):
    for invalid in ("ssh://test.com/bar", "", "http://invalid host/"):
      with self.subTest(url=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          PageConfig.parse(invalid)

  def test_parse_url_no_protocol(self):
    config = PageConfig.parse("www.a.com")
    self.assertEqual(config.duration, dt.timedelta())
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "a.com")

  def test_parse_url_numbers(self):
    config = PageConfig.parse("123.a.com")
    self.assertEqual(config.first_url, "https://123.a.com")
    self.assertEqual(config.duration, dt.timedelta())
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "123.a.com")

  def test_parse_url_numbers_params(self):
    config = PageConfig.parse("www.123.a.com/foo?bar=1")
    self.assertEqual(config.first_url, "https://www.123.a.com/foo?bar=1")

  def test_parse_with_duration(self):
    config = PageConfig.parse("http://news.b.com,123s")
    self.assertEqual(config.first_url, "http://news.b.com")
    self.assertEqual(config.duration.total_seconds(), 123)
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "news.b.com")

  def test_parse_invalid_multiple_urls(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PageConfig.parse("111.a.com,222.b.com")
    with self.assertRaises(argparse.ArgumentTypeError):
      PageConfig.parse("111s,222.b.com")

  def test_parse_multiple_comma(self):
    # duration splitting should happen in the caller
    config = PageConfig.parse("www.b.com/foo?bar=a,b,c,d,123s")
    self.assertEqual(config.first_url, "https://www.b.com/foo?bar=a,b,c,d")
    self.assertEqual(config.duration.total_seconds(), 123)
    self.assertIsNone(config.label)
    self.assertEqual(config.any_label, "b.com")

  def test_parse_invalid(self):
    invalid: Any
    for invalid in ("", {}, [], None):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          PageConfig.parse(invalid)

  def test_parse_sequence_urls(self):
    config_urls = [
        "http://test.com/0",
        "http://test.com/0,123s",
    ]
    config_1 = PageConfig.parse(config_urls)
    self.assertIsNone(config_1.login)
    self.assertIsNone(config_1.label)
    self.assertEqual(config_1.any_label, "test.com")
    self.assertEqual(config_1.first_url, "http://test.com/0")
    self.assertEqual(len(config_1.blocks), 1)
    self.assertEqual(len(tuple(config_1.actions())), 2)
    self.assertIsInstance(config_1.blocks[0].actions[0], GetAction)
    self.assertIsInstance(config_1.blocks[0].actions[1], GetAction)
    self.assertEqual(config_1.blocks[0].actions[0].url, "http://test.com/0")
    self.assertEqual(config_1.blocks[0].actions[1].url,
                     "http://test.com/0,123s")

    config_data = {"urls": config_urls}
    config_2 = PageConfig.parse(config_data)
    self.assertEqual(config_1, config_2)
    config_data = {"actions": config_urls}
    config_3 = PageConfig.parse(config_data)
    self.assertEqual(config_1, config_3)
    self.assertEqual(config_2, config_3)

  def test_parse_sequence_preset_urls(self):
    # Known url names only work at PageConfig level at this point.
    config_urls = [
        "cnn",
    ]
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "cnn"):
      PageConfig.parse(config_urls)

  def test_parse_action_sequence(self):
    config = PageConfig.parse([{
        "action": "get",
        "url": "http://test.com/click",
    }, {
        "action": "click",
        "selector": "#foo",
    }])
    self.assertEqual(config.first_url, "http://test.com/click")
    self.assertIsNone(config.login)
    self.assertIsNone(config.setup)
    self.assertIsNone(config.teardown)
    self.assertEqual(len(tuple(config.actions())), 2)

  def test_parse_actions_dict(self):
    config_data = {
        "actions": [{
            "action": "get",
            "url": "http://test.com/click",
        }, {
            "action": "click",
            "selector": "#foo",
        }],
    }
    config_1 = PageConfig.parse(config_data)
    self.assertIsNone(config_1.login)
    self.assertIsNone(config_1.setup)
    self.assertIsNone(config_1.teardown)
    self.assertEqual(config_1.first_url, "http://test.com/click")
    self.assertEqual(len(tuple(config_1.actions())), 2)

    config_data = {"blocks": config_data["actions"]}
    config_2 = PageConfig.parse(config_data)
    self.assertEqual(config_1, config_2)

  def test_parse_login_block(self):
    config_data = {
        "login": [{
            "action": "get",
            "url": "http://test.com/login",
        }, {
            "action": "click",
            "selector": "#foo",
        }],
        "urls": ["http://test.com/charts"],
    }
    config = PageConfig.parse(config_data)
    login = config.login
    assert login
    self.assertTrue(login.is_login)
    self.assertIsNone(config.setup)
    self.assertIsNone(config.teardown)
    self.assertFalse(config.blocks[0].is_login)
    self.assertEqual(config.first_url, "http://test.com/charts")
    self.assertEqual(len(config.blocks), 1)
    self.assertEqual(len(tuple(config.actions())), 1)
    self.assertEqual(len(login), 2)
    self.assertIsInstance(login.actions[0], GetAction)
    self.assertEqual(login.actions[0].url, "http://test.com/login")

  def test_parse_setup_block(self):
    config_data = {
        "login": ["http://test.com/login"],
        "setup": [{
            "action": "get",
            "url": "http://test.com/setup",
        }, {
            "action": "click",
            "selector": "#foo",
        }],
        "actions": ["http://test.com/charts"],
    }
    config = PageConfig.parse(config_data)
    self.assertIsNotNone(config.login)
    self.assertIsNotNone(config.setup)
    self.assertEqual(len(config.login), 1)
    self.assertEqual(len(config.setup), 2)
    self.assertIsNone(config.teardown)
    self.assertEqual(len(config.blocks), 1)
    self.assertEqual(config.login.first_url, "http://test.com/login")
    self.assertEqual(config.setup.first_url, "http://test.com/setup")
    self.assertEqual(config.blocks[0].first_url, "http://test.com/charts")

  def test_parse_login_block_preset(self):
    config_data = {"login": "google", "urls": ["http://test.com/charts"]}
    config = PageConfig.parse(config_data)
    login = config.login
    assert login
    self.assertTrue(login.is_login)
    self.assertIsInstance(login, GoogleLogin)
    self.assertIsNone(config.setup)
    self.assertFalse(config.blocks[0].is_login)
    self.assertEqual(config.first_url, "http://test.com/charts")
    self.assertEqual(len(config.blocks), 1)
    self.assertEqual(len(tuple(config.actions())), 1)

  def test_parse_teardown_block(self):
    config_data = {
        "actions": ["http://test.com/charts"],
        "teardown": [{
            "action": "get",
            "url": "http://test.com/teardown",
        }, {
            "action": "click",
            "selector": "#foo",
        }],
    }

    config = PageConfig.parse(config_data)
    self.assertIsNone(config.setup)
    self.assertEqual(len(config.blocks), 1)
    self.assertEqual(config.blocks[0].first_url, "http://test.com/charts")
    self.assertIsNotNone(config.teardown)
    self.assertEqual(len(config.teardown), 2)
    self.assertEqual(config.teardown.first_url, "http://test.com/teardown")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
