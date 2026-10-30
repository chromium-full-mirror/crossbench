# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import unittest
from typing import Any, Sequence

import hjson

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.get import GetAction
from crossbench.benchmarks.loading.config.login.google import GoogleLogin
from crossbench.benchmarks.loading.config.page import PageConfig
from crossbench.benchmarks.loading.config.pages import \
    DevToolsRecorderPagesConfig, ListPagesConfig, PagesConfig
from crossbench.cli.config.secrets import GoogleUsernamePassword, Secrets
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class PagesConfigTestCase(CrossbenchFakeFsTestCase):

  def test_parse_unknown_type(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse(self)
    self.assertIn("type", str(cm.exception))

  def test_parse_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse("123s,")
    self.assertIn("Duration", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse(",")
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse("http://foo.com,,")
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse("http://foo.com,123s,")
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse("http://foo.com,123s,123s")
    self.assertIn("Duration", str(cm.exception))

  def test_parse_single(self):
    config = PagesConfig.parse("http://a.com")
    self.assertEqual(len(config.pages), 1)
    page_config = config.pages[0]
    self.assertEqual(page_config.first_url, "http://a.com")
    blocks = page_config.blocks
    self.assertEqual(len(blocks), 1)
    actions = blocks[0].actions
    self.assertEqual(len(actions), 2)
    self.assertEqual(actions[0].TYPE, ActionType.GET)
    self.assertEqual(actions[1].TYPE, ActionType.WAIT_FOR_READY_STATE)
    self.assertEqual(page_config.duration, dt.timedelta())

  def test_parse_single_no_scheme(self):
    config = PagesConfig.parse("www.google.com")
    self.assertEqual(len(config.pages), 1)
    page_config = config.pages[0]
    self.assertEqual(page_config.first_url, "https://www.google.com")
    config = PagesConfig.parse("www.google.com,123s")
    self.assertEqual(len(config.pages), 1)
    page_config = config.pages[0]
    self.assertEqual(page_config.first_url, "https://www.google.com")
    self.assertEqual(page_config.duration, dt.timedelta(seconds=123))

  def test_parse_single_with_duration(self):
    config = PagesConfig.parse("http://a.com,123s")
    self.assertEqual(len(config.pages), 1)
    page_config = config.pages[0]
    self.assertEqual(page_config.first_url, "http://a.com")
    self.assertEqual(page_config.duration.total_seconds(), 123)

  def test_parse_single_url_with_comma_and_duration(self):
    url_1 = ("https://www.google.com/maps/place/Japan/"
             "@33.33,44.4,55m/data=!3m2,123s")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "Invalid"):
      PagesConfig.parse(url_1)
    url_2 = ("https://www.google.com/maps/place/Japan/"
             "@33.33,44.4,55m/data=!3m2,123s/http.google.com")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "Invalid"):
      PagesConfig.parse(url_2)

  def test_parse_multiple(self):
    config = PagesConfig.parse("http://a.com,http://b.com")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "http://a.com")
    self.assertEqual(page_config_1.first_url, "http://b.com")
    self.assertEqual(page_config_0.duration, dt.timedelta())
    self.assertEqual(page_config_1.duration, dt.timedelta())

  def test_parse_multiple_short_domain(self):
    config = PagesConfig.parse("a.com,b.com")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "https://a.com")
    self.assertEqual(page_config_1.first_url, "https://b.com")

  def test_parse_multiple_numeric_domain(self):
    config = PagesConfig.parse("111.a.com,222.b.com")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "https://111.a.com")
    self.assertEqual(page_config_1.first_url, "https://222.b.com")

  def test_parse_multiple_numeric_domain_with_duration(self):
    config = PagesConfig.parse("111.a.com,12s,222.b.com,23s")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "https://111.a.com")
    self.assertEqual(page_config_1.first_url, "https://222.b.com")
    self.assertEqual(page_config_0.duration.total_seconds(), 12)
    self.assertEqual(page_config_1.duration.total_seconds(), 23)

  def test_parse_multiple_with_duration(self):
    config = PagesConfig.parse("http://a.com,123s,http://b.com")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "http://a.com")
    self.assertEqual(page_config_1.first_url, "http://b.com")
    self.assertEqual(page_config_0.duration.total_seconds(), 123)
    self.assertEqual(page_config_1.duration, dt.timedelta())

  def test_parse_multiple_with_duration_end(self):
    config = PagesConfig.parse("http://a.com,http://b.com,123s")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "http://a.com")
    self.assertEqual(page_config_1.first_url, "http://b.com")
    self.assertEqual(page_config_0.duration, dt.timedelta())
    self.assertEqual(page_config_1.duration.total_seconds(), 123)

  def test_parse_multiple_with_duration_all(self):
    config = PagesConfig.parse("http://a.com,1s,http://b.com,123s")
    self.assertEqual(len(config.pages), 2)
    page_config_0, page_config_1 = config.pages
    self.assertEqual(page_config_0.first_url, "http://a.com")
    self.assertEqual(page_config_1.first_url, "http://b.com")
    self.assertEqual(page_config_0.duration.total_seconds(), 1)
    self.assertEqual(page_config_1.duration.total_seconds(), 123)

  def test_parse_sequence(self):
    config_list = PagesConfig.parse(["http://a.com,1s", "http://b.com,123s"])
    config_str = PagesConfig.parse("http://a.com,1s,http://b.com,123s")
    self.assertEqual(config_list, config_str)

    config_list = PagesConfig.parse(["http://a.com", "http://b.com"])
    config_str = PagesConfig.parse("http://a.com,http://b.com")
    self.assertEqual(config_list, config_str)

  def test_parse_empty_actions(self):
    config_data: dict[str, dict] = {"pages": {"Google Story": []}}
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty sequence"):
      PagesConfig.parse(config_data)

    config_data = {"pages": {"Google Story": {}}}
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty dict"):
      PagesConfig.parse(config_data)

  def test_example(self):
    config_data: dict[str, dict] = {
        "pages": {
            "Google Story": [
                {
                    "action": "get",
                    "url": "https://www.google.com",
                },
                {
                    "action": "wait",
                    "duration": 5,
                },
                {
                    "action": "scroll",
                    "direction": "down",
                    "duration": 3,
                },
            ],
        },
    }
    config = PagesConfig.parse(config_data)
    self.assert_single_google_story(config.pages)
    self.assertIsNone(config.pages[0].login)
    # Loading the same config from a file should result in the same actions.
    file = pathlib.Path("page.config.hjson")
    assert not file.exists()
    with file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    file_config = PagesConfig.parse(str(file))
    self.assertEqual(config, file_config)
    pages = file_config.pages
    self.assert_single_google_story(pages)
    self.assertIsNone(pages[0].login)

    self.assertEqual(config, PagesConfig.parse(json.dumps(config_data)))

  def test_example_with_login(self):
    config_data = {
        "pages": {
            "Google Story": {
                "login": [{
                    "action": "get",
                    "url": "https://www.google.com/login",
                }],
                "actions": [
                    {
                        "action": "get",
                        "url": "https://www.google.com",
                    },
                    {
                        "action": "wait",
                        "duration": 5,
                    },
                    {
                        "action": "scroll",
                        "direction": "down",
                        "duration": 3,
                    },
                ],
            },
        },
    }
    config = PagesConfig.parse(config_data)
    self.assert_single_google_story(config.pages)
    login = config.pages[0].login
    self.assertIsNotNone(login)
    self.assertEqual(len(login.actions), 1)
    self.assertIsInstance(login.actions[0], GetAction)
    self.assertEqual(login.actions[0].url, "https://www.google.com/login")

  def test_example_with_login_preset(self):
    config_data = {
        "pages": {
            "Google Story": {
                "login":
                    "google",
                "actions": [
                    {
                        "action": "get",
                        "url": "https://www.google.com",
                    },
                    {
                        "action": "wait",
                        "duration": 5,
                    },
                    {
                        "action": "scroll",
                        "duration": 3,
                    },
                ],
            },
        },
    }
    config = PagesConfig.parse(config_data)
    self.assert_single_google_story(config.pages)
    page = config.pages[0]
    self.assertIsInstance(page.login, GoogleLogin)
    self.assertIsNone(page.setup)

  def assert_single_google_story(self, pages: Sequence[PageConfig]):
    self.assertTrue(len(pages), 1)
    page = pages[0]
    self.assertEqual(page.label, "Google Story")
    self.assertEqual(page.first_url, "https://www.google.com")
    self.assertEqual(len(page.blocks), 1)
    block = page.blocks[0]
    self.assertSequenceEqual([str(action.TYPE) for action in block],
                             ["get", "wait", "scroll"])

  def test_secrets(self):
    config_data = {
        "secrets": {
            "google": {
                "username": "test",
                "password": "s3cr3t",
            },
        },
        "pages": {
            "Google Story": ["http://google.com"],
        },
    }
    pages = PagesConfig.parse(config_data)
    secret = GoogleUsernamePassword("test", "s3cr3t")
    self.assertEqual(pages.secrets, Secrets(google=secret))
    self.assertEqual(pages.pages[0].first_url, "http://google.com")

  def test_no_scenarios(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PagesConfig.parse_dict({})
    with self.assertRaises(argparse.ArgumentTypeError):
      PagesConfig.parse_dict({"pages": {}})

  def test_scenario_invalid_actions(self):
    invalid_actions: list[Any] = [None, "", [], {}, "invalid string", 12]
    for invalid_action in invalid_actions:
      config_dict: dict[str, object] = {"pages": {"name": invalid_action}}
      with self.subTest(invalid_action=invalid_action):
        with self.assertRaises(argparse.ArgumentTypeError):
          PagesConfig.parse_dict(config_dict)

  def test_missing_action(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PagesConfig.parse_dict(
          {"pages": {
              "TEST": [{
                  "action___": "wait",
                  "duration": 5.0,
              }],
          }})
    self.assertIn("Invalid data:", str(cm.exception))

  def test_invalid_action(self):
    invalid_actions: list[Any] = [None, "", [], {}, "unknown action name", 12]
    for invalid_action in invalid_actions:
      config_dict: dict[str, object] = {
          "pages": {
              "TEST": [{
                  "action": invalid_action,
                  "duration": 5.0,
              }],
          },
      }
      with self.subTest(invalid_action=invalid_action):
        with self.assertRaises(argparse.ArgumentTypeError):
          PagesConfig.parse_dict(config_dict)

  def test_get_action_durations(self):
    durations = [
        ("5", 5),
        ("5.5", 5.5),
        (6, 6),
        (6.1, 6.1),
        ("5.5", 5.5),
        ("170ms", 0.17),
        ("170milliseconds", 0.17),
        ("170.4ms", 0.1704),
        ("170.4 millis", 0.1704),
        ("8s", 8),
        ("8.1s", 8.1),
        ("8.1seconds", 8.1),
        ("1 second", 1),
        ("1.1 seconds", 1.1),
        ("9m", 9 * 60),
        ("9.5m", 9.5 * 60),
        ("9.5 minutes", 9.5 * 60),
        ("9.5 mins", 9.5 * 60),
        ("1 minute", 60),
        ("1 min", 60),
        ("1h", 3600),
        ("1 h", 3600),
        ("1 hour", 3600),
        ("0.5h", 1800),
        ("0.5 hours", 1800),
    ]
    for input_value, duration in durations:
      with self.subTest(duration=duration):
        page_config = PagesConfig.parse_dict({
            "pages": {
                "TEST": [
                    {
                        "action": "get",
                        "url": "google.com",
                    },
                    {
                        "action": "wait",
                        "duration": input_value,
                    },
                ],
            },
        })
        self.assertEqual(len(page_config.pages), 1)
        page = page_config.pages[0]
        self.assertEqual(len(page.blocks), 1)
        actions = page.blocks[0].actions
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[1].duration, dt.timedelta(seconds=duration))

  def test_action_invalid_duration(self):
    invalid_durations: list[Any] = [
        "1.1.1",
        None,
        "",
        -1,
        "-1",
        "-1ms",
        "1msss",
        "1ss",
        "2hh",
        "asdfasd",
        "---",
        "1.1.1",
        "1_123ms",
        "1'200h",
        (),
        [],
        {},
        "-1h",
    ]
    for invalid_duration in invalid_durations:
      with self.subTest(duration=invalid_duration), self.assertRaises(
          (AssertionError, ValueError, argparse.ArgumentTypeError)):
        PagesConfig.parse_dict({
            "pages": {
                "TEST": [
                    {
                        "action": "get",
                        "url": "google.com",
                    },
                    {
                        "action": "wait",
                        "duration": invalid_duration,
                    },
                ],
            },
        })

  def test_start_stop_browser_across_page_blocks_invalid(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "two 'start_browser' actions"):
      PagesConfig.parse_dict({
          "pages": {
              "TEST": {
                  "setup": [{
                      "action": "start_browser",
                  }],
                  "actions": [{
                      "action": "start_browser",
                  }],
              },
          },
      })

    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "two 'stop_browser' actions"):
      PagesConfig.parse_dict({
          "pages": {
              "TEST": {
                  "actions": [{
                      "action": "stop_browser",
                  }],
                  "teardown": [{
                      "action": "stop_browser",
                  }],
              },
          },
      })


DEVTOOLS_RECORDER_EXAMPLE = {
    "title":
        "cnn load",
    "steps": [
        {
            "type": "setViewport",
            "width": 1628,
            "height": 397,
            "deviceScaleFactor": 1,
            "isMobile": False,
            "hasTouch": False,
            "isLandscape": False,
        },
        {
            "type":
                "navigate",
            "url":
                "https://edition.cnn.com/",
            "assertedEvents": [{
                "type": "navigation",
                "url": "https://edition.cnn.com/",
                "title": "",
            }],
        },
        {
            "type": "click",
            "target": "main",
            "selectors": [["aria/Opinion"],
                          [
                              "#pageHeader > div > div > "
                              "div.header__container div:nth-of-type(5) > a",
                          ],
                          [
                              'xpath///*[@id="pageHeader"]/'
                              "div/div/div[1]/div[1]/nav/div/div[5]/a",
                          ],
                          [
                              "pierce/#pageHeader > div > div > "
                              "div.header__container div:nth-of-type(5) > a",
                          ]],
            "offsetY": 17,
            "offsetX": 22.515625,
        },
    ],
}


class DevToolsRecorderPageConfigTestCase(CrossbenchFakeFsTestCase):

  def test_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DevToolsRecorderPagesConfig.parse({})
    self.assertIn("empty", str(cm.exception))

  def test_missing_title(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DevToolsRecorderPagesConfig.parse({"foo": {}})
    self.assertIn("title", str(cm.exception))

  def test_basic_config(self):
    config = DevToolsRecorderPagesConfig.parse(DEVTOOLS_RECORDER_EXAMPLE)
    self.assertEqual(len(config.pages), 1)
    page = config.pages[0]
    self.assertEqual(page.label, "cnn load")
    self.assertEqual(page.first_url, "https://edition.cnn.com/")
    self.assertEqual(len(page.blocks), 1)
    self.assertGreater(len(page.blocks[0].actions), 1)

  def test_basic_config_from_file(self):
    config_path = pathlib.Path("devtools.config.json")
    with config_path.open("w", encoding="utf-8") as f:
      json.dump(DEVTOOLS_RECORDER_EXAMPLE, f)
    config_file = DevToolsRecorderPagesConfig.parse(config_path)
    config_dict = DevToolsRecorderPagesConfig.parse(DEVTOOLS_RECORDER_EXAMPLE)
    self.assertEqual(config_file, config_dict)

  def test_parse_click_step(self):
    config = {
        "type": "click",
        "target": "main",
        "selectors": [["aria/Search Google"]],
    }
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    actions = DevToolsRecorderPagesConfig.parse_step(config)
    self.assertEqual(len(actions), 1)
    action = actions[0]
    self.assertEqual(action.TYPE, ActionType.CLICK)
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector,
                     "[aria-label='Search Google']")

    config["selectors"] = [["aria/SIMPLE"], ["#rso > div:nth-of-type(3) h3"],
                           ['xpath///*[@id="rso"]'],
                           ["pierce/#rso > div:nth-of-type(3) h3"],
                           ["text/SIMPLE"]]
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    action = DevToolsRecorderPagesConfig.parse_step(config)[0]
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector, 'xpath///*[@id="rso"]')

    config["selectors"] = [
        ["aria/SIMPLE"],
        ["css/#rso > div:nth-of-type(3) h3"],
    ]
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    action = DevToolsRecorderPagesConfig.parse_step(config)[0]
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector,
                     "#rso > div:nth-of-type(3) h3")

    config["selectors"] = [
        ["#rso > div:nth-of-type(3) h3"],
    ]
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    action = DevToolsRecorderPagesConfig.parse_step(config)[0]
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector,
                     "#rso > div:nth-of-type(3) h3")

    config["selectors"] = [
        ["aria/SIMPLE", "area/OTHER"],
        ["#rso > div:nth-of-type(3) h3"],
    ]
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    action = DevToolsRecorderPagesConfig.parse_step(config)[0]
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector,
                     "#rso > div:nth-of-type(3) h3")

    config["selectors"] = [
        ["text/Content"],
    ]
    # DevToolsRecorderStep marks url as Required and omits target.
    # pyrefly: ignore[bad-argument-type]
    action = DevToolsRecorderPagesConfig.parse_step(config)[0]
    assert isinstance(action, ClickAction)
    self.assertIsNotNone(action.position.selector)
    self.assertEqual(action.position.selector.selector,
                     "xpath///*[text()='Content']")


class ListPageConfigTestCase(CrossbenchFakeFsTestCase):

  def test_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ListPagesConfig.parse({})
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ListPagesConfig.parse({"foo": {}})
    self.assertIn("pages", str(cm.exception))

    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ListPagesConfig.parse_dict({"pages": None})
    self.assertIn("None", str(cm.exception))

    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ListPagesConfig.parse_dict({"pages": []})
    self.assertIn("empty", str(cm.exception))

  def test_direct_string_single(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ListPagesConfig.parse("http://foo.bar.com,23s")
    self.assertIn("http://foo.bar.com,23s", str(cm.exception))

  def test_direct_string_single_dict(self):
    config_dict = ListPagesConfig.parse({"pages": "http://foo.bar.com,23s"})
    config_str = PagesConfig(
        pages=(PageConfig.parse("http://foo.bar.com,23s"),))
    self.assertIsInstance(config_dict, ListPagesConfig)
    self.assertIsInstance(config_str, PagesConfig)
    self.assertEqual(config_dict, config_str)

  @unittest.skip("Combined pages per line not supported yet")
  def test_direct_string_multiple(self):
    config = ListPagesConfig.parse_dict(
        {"pages": "http://a.com,12s,http://b.com,13s"})
    pages = config.pages
    self.assertEqual(len(pages), 2)
    story_1 = pages[0]
    story_2 = pages[1]
    self.assertEqual(story_1.first_url, "http://a.com")
    self.assertEqual(story_2.first_url, "http://b.com")
    self.assertEqual(story_1.duration.total_seconds(), 12)
    self.assertEqual(story_2.duration.total_seconds(), 13)

  def test_list(self):
    page_configs = ["http://a.com,12s", "http://b.com,13s"]
    config_str = PagesConfig.parse("http://a.com,12s,http://b.com,13s")
    config_dict_list = ListPagesConfig.parse({"pages": page_configs})
    config_list = ListPagesConfig.parse(page_configs)
    self.assertEqual(config_str, config_dict_list)
    self.assertEqual(config_str, config_list)

  def test_parse_file(self):
    page_configs = ["http://a.com,12s", "http://b.com,13s"]
    config_file = pathlib.Path("page_list.txt")
    with config_file.open("w", encoding="utf-8") as f:
      f.write("\n".join(page_configs))
    config_file = ListPagesConfig.parse(config_file)
    config_list = ListPagesConfig.parse(page_configs)
    self.assertEqual(config_file, config_list)

  def test_parse_file_empty_lines(self):
    page_configs = ["http://a.com,12s", "http://b.com,13s"]
    config_file = pathlib.Path("page_list.txt")
    with config_file.open("w", encoding="utf-8") as f:
      f.write("\n")
      f.write(page_configs[0])
      f.write("\n\n")
      f.write(page_configs[1])
      f.write("\n\n")
    config_file = ListPagesConfig.parse(config_file)
    config_list = ListPagesConfig.parse(page_configs)
    self.assertEqual(config_file, config_list)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
