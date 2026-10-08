# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
import inspect
import re
import unittest
from typing import Any, Final, cast

from crossbench.action_runner.action.action import ACTION_TIMEOUT, ACTIONS, \
    Action
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.all import ACTIONS_TUPLE
from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.close_all_tabs import CloseAllTabsAction
from crossbench.action_runner.action.close_tab import CloseTabAction
from crossbench.action_runner.action.dump_html import DumpHtmlAction
from crossbench.action_runner.action.enums import ReadyState, WindowTarget
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.inject_new_document_script import \
    InjectNewDocumentScriptAction
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.meminfo import MeminfoAction
from crossbench.action_runner.action.position import CoordinatesConfig, \
    PositionConfig, SelectorConfig
from crossbench.action_runner.action.probe import ProbeAction
from crossbench.action_runner.action.screenshot import ScreenshotAction
from crossbench.action_runner.action.scroll import ScrollAction
from crossbench.action_runner.action.swipe import SwipeAction
from crossbench.action_runner.action.switch_frame import SwitchFrameAction
from crossbench.action_runner.action.switch_tab import SwitchTabAction
from crossbench.action_runner.action.text_input import TextInputAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.action_runner.action.wait_for_condition import \
    WaitForConditionAction
from crossbench.action_runner.action.wait_for_element import \
    WaitForElementAction
from crossbench.action_runner.action.wait_for_ready_state import \
    WaitForReadyStateAction
from crossbench.action_runner.action.wait_for_url_matches import \
    WaitForUrlMatchesAction
from crossbench.benchmarks.loading.config.pages import PagesConfig
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.config import config_dir
from crossbench.probes.dump_html import DumpHtmlProbe
from crossbench.probes.js import JSProbe
from crossbench.probes.meminfo import MeminfoProbe
from crossbench.probes.screenshot import ScreenshotProbe
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase

_MOCK_CLASS_RE: Final[re.Pattern[str]] = re.compile(r"^Mock|Mock$")


class ActionTestCase(CrossbenchFakeFsTestCase):

  def test_all_configs(self):
    actions_config_path = config_dir() / "doc/action/action.config.hjson"
    self.fs.add_real_directory(actions_config_path.parent)
    actions_test_config = PagesConfig.parse(actions_config_path)
    parsed_actions: set[ActionType] = set()
    for page in actions_test_config.pages:
      for action in page.actions():
        parsed_actions.add(action.TYPE)
    self.assertGreater(len(parsed_actions), 1)
    self.assertSetEqual(
        set(ActionType), parsed_actions,
        f"Missing example action config in {actions_config_path}")

  def test_action_type_lookup(self):
    for action_type in ActionType:
      action_cls = ACTIONS[action_type]
      self.assertTrue(issubclass(action_cls, Action))
      # Ensure that all Action subclasses have cached config_parser for
      # efficiently parsing larger page configs with many actions:
      # - Use  @functools.cache for base classes
      # - Use  @functools.lru_cache(maxsize=1) for leaf classes
      self.assertIs(action_cls.config_parser().cls, action_cls)
      self.assertIs(
          action_cls.config_parser(), action_cls.config_parser(),
          f"{action_cls}: missing "
          "@functools.lru_cache decorator on config_parser() method")
      self.assertIs(action_cls.TYPE, action_type)

  def _get_concrete_action_classes(self) -> list[type[Action]]:

    def all_subclasses(cls: type[Any]):
      for sub_cls in cls.__subclasses__():
        if _MOCK_CLASS_RE.search(sub_cls.__name__):
          continue
        yield from all_subclasses(sub_cls)
        if inspect.isabstract(sub_cls):
          continue
        yield sub_cls

    return list(all_subclasses(Action))

  def test_all_actions_are_frozen_dataclasses(self):
    action_classes = self._get_concrete_action_classes()
    self.assertGreater(len(action_classes), 0)
    for action_cls in action_classes:
      with self.subTest(action_cls=action_cls.__name__):
        self.assertTrue(
            dataclasses.is_dataclass(action_cls),
            f"{action_cls.__name__} must be a dataclass")
        self.assertTrue(
            cast(Any, action_cls).__dataclass_params__.frozen,
            f"{action_cls.__name__} must be a frozen dataclass")

  def test_all_actions_have_unique_type(self):
    action_classes = self._get_concrete_action_classes()
    seen_types: set[ActionType] = set()
    for action_cls in action_classes:
      with self.subTest(action_cls=action_cls.__name__):
        self.assertIn("TYPE", action_cls.__dict__,
                      f"{action_cls.__name__} must define a TYPE ClassVar")
        action_type = action_cls.TYPE
        self.assertIsInstance(
            action_type, ActionType,
            f"{action_cls.__name__}.TYPE must be an ActionType enum value")
        self.assertNotIn(
            action_type, seen_types,
            f"{action_cls.__name__}.TYPE {action_type} is already used")
        seen_types.add(action_type)

  def test_all_actions_registered_in_actions_tuple(self):
    action_classes = set(self._get_concrete_action_classes())
    self.assertEqual(action_classes, set(ACTIONS_TUPLE))

  def test_parse_get_default(self):
    config_dict = {"action": "get", "url": "http://crossben.ch"}
    action = GetAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.GET)
    self.assertEqual(action.url, "http://crossben.ch")
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.duration, dt.timedelta())
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = GetAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_get_all(self):
    config_dict = {
        "action": "get",
        "url": "http://crossben.ch",
        "duration": "12s",
        "timeout": "34s",
        "ready_state": "any",
        "target": "_top",
    }
    action = GetAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.GET)
    self.assertEqual(action.url, "http://crossben.ch")
    self.assertEqual(action.timeout, dt.timedelta(seconds=34))
    self.assertEqual(action.duration, dt.timedelta(seconds=12))
    self.assertEqual(action.ready_state, ReadyState.ANY)
    self.assertEqual(action.target, WindowTarget.TOP)
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = GetAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_get_new_tab(self):
    config_dict = {
        "action": "get",
        "url": "http://crossben.ch",
        "target": "_new_tab",
    }
    action = GetAction.parse_dict(config_dict)
    self.assertEqual(action.target, WindowTarget.NEW_TAB)
    action.validate()

    action_2 = GetAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_get_new_window(self):
    config_dict = {
        "action": "get",
        "url": "http://crossben.ch",
        "target": "_new_window",
    }
    action = GetAction.parse_dict(config_dict)
    self.assertEqual(action.target, WindowTarget.NEW_WINDOW)
    action.validate()

    action_2 = GetAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_get_invalid_url(self):
    with self.assertRaises(ValueError) as cm:
      GetAction.parse_dict({
          "action": "get",
          "url": "",
      })
    self.assertIn("url", str(cm.exception))

  def test_parse_get_invalid_duration(self):
    with self.assertRaises(ValueError) as cm:
      GetAction.parse_dict({
          "action": "get",
          "url": "http://crossben.ch",
          "duration": "-12s",
      })
    self.assertIn("duration", str(cm.exception))

  def test_parse_get_invalid_duration_for_ready_state(self):
    with self.assertRaises(ValueError):
      GetAction.parse_dict({
          "action": "get",
          "url": "http://crossben.ch",
          "ready_state": "interactive",
          "duration": "12s",
      })

  def test_parse_wait_default(self):
    config_dict = {"action": "wait", "duration": "12s"}
    action = WaitAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT)
    self.assertEqual(action.duration, dt.timedelta(seconds=12))
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = WaitAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_missing_duration(self):
    with self.assertRaises(ValueError) as cm:
      WaitAction.parse_dict({"action": "wait"})
    self.assertIn("duration", str(cm.exception))

  def test_parse_scroll_default(self):
    config_dict = {"action": "scroll"}
    action = ScrollAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SCROLL)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.duration, dt.timedelta(seconds=1))
    self.assertEqual(action.distance, 500)
    self.assertEqual(action.input_source, InputSource.JS)
    self.assertIsNone(action.source_device)
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = ScrollAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_scroll_all(self):
    config_dict = {
        "action": "scroll",
        "distance": "123",
        "timeout": "12s",
        "duration": "34s",
        "source": "js",
        "selector": "#button",
        "required": "true",
    }
    action = ScrollAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SCROLL)
    self.assertEqual(action.timeout, dt.timedelta(seconds=12))
    self.assertEqual(action.duration, dt.timedelta(seconds=34))
    self.assertEqual(action.distance, 123)
    self.assertEqual(action.input_source, InputSource.JS)
    self.assertTrue(action.required)
    self.assertEqual(action.selector, "#button")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = ScrollAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_scroll_invalid_source(self):
    config_dict = {
        "action": "scroll",
        "source": "invalid source",
    }

    with self.assertRaises(ValueError) as cm:
      ScrollAction.parse_dict(config_dict)

    self.assertIn("source", str(cm.exception))

  def test_parse_scroll_valid_but_unsupported_source(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "scroll",
          "source": "keyboard",
      })
    self.assertIn("source", str(cm.exception))

  def test_parse_scroll_source_device(self):
    config_dict = {
        "action": "scroll",
        "source_device": "my_touch_device",
    }
    action = ScrollAction.parse_dict(config_dict)
    self.assertEqual(action.source_device, "my_touch_device")
    self.assertEqual(action.input_source, InputSource.JS)
    action_2 = ScrollAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)

  def test_parse_scroll_required_missing_selector(self):
    config_dict = {
        "action": "scroll",
        "required": "true",
    }

    with self.assertRaises(ValueError) as cm:
      ScrollAction.parse_dict(config_dict)

    self.assertIn("required", str(cm.exception))

  def test_scroll_invalid_distance(self):
    with self.assertRaises(ValueError) as cm:
      ScrollAction.parse_dict({"action": "scroll", "distance": ""})
    self.assertIn("distance", str(cm.exception))
    with self.assertRaises(ValueError) as cm:
      ScrollAction.parse_dict({"action": "scroll", "distance": "0"})
    self.assertIn("distance", str(cm.exception))

  def test_parse_click_minimal_selector(self):
    config_dict = {"action": "click", "selector": "#button"}
    action = ClickAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLICK)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.input_source, InputSource.JS)
    self.assertIsNone(action.source_device)
    self.assertEqual(action.position.selector.selector, "#button")
    self.assertTrue(action.position.selector.required)
    self.assertFalse(action.position.selector.scroll_into_view)
    self.assertIsNone(action.position.coordinates)
    self.assertTrue(action.has_timeout)
    self.assertIsNone(action.verify)
    self.assertEqual(action.attempts, 1)
    action.validate()

    action_2 = ClickAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_click_minimal_coordinates(self):
    config_dict = {
        "action": "click",
        "source": "touch",
        "position": {
            "x": 1,
            "y": 2,
        },
    }
    action = ClickAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLICK)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.input_source, InputSource.TOUCH)
    self.assertEqual(action.source_device, "default_touchscreen")
    self.assertIsNone(action.position.selector)
    self.assertEqual(action.position.coordinates.x, 1)
    self.assertEqual(action.position.coordinates.y, 2)
    self.assertTrue(action.has_timeout)
    self.assertIsNone(action.verify)
    self.assertEqual(action.attempts, 1)
    action.validate()

    action_2 = ClickAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_click_selector_all(self):
    config_dict = {
        "action": "click",
        "source": "js",
        "position": {
            "selector": "#button",
            "required": True,
            "scroll_into_view": True,
            "wait": True,
        },
        "verify": "#id",
        "attempts": 7,
        "timeout": "12s",
    }
    action = ClickAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLICK)
    self.assertEqual(action.timeout, dt.timedelta(seconds=12))
    self.assertEqual(action.input_source, InputSource.JS)
    self.assertEqual(action.position.selector.selector, "#button")
    self.assertTrue(action.position.selector.required)
    self.assertTrue(action.position.selector.scroll_into_view)
    self.assertTrue(action.position.selector.wait)
    self.assertTrue(action.has_timeout)
    self.assertEqual(action.verify, "#id")
    self.assertEqual(action.attempts, 7)
    action.validate()

    action_2 = ClickAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_click_css_selector_hjson(self):
    action = ClickAction.parse("{action:'click',selector:'#button'}")
    self.assertEqual(action.selector.selector, "#button")

  def test_parse_click_xpath_selector_hjson(self):
    action = ClickAction.parse(
        "{action:'click',selector:'//*[@id=\"rso\"]/div[2]/div[1]'}")
    self.assertEqual(action.selector.selector, '//*[@id="rso"]/div[2]/div[1]')

  def test_parse_click_invalid_source(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "invalid_source",
          "selector": "#button",
      })
    self.assertIn("source", str(cm.exception))

  def test_parse_click_valid_but_unsupported_source(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "keyboard",
          "selector": "#button",
      })
    self.assertIn("source", str(cm.exception))

  def test_parse_click_source_device(self):
    action = ClickAction.parse_dict({
        "action": "click",
        "source": "touch",
        "source_device": "my_touchscreen",
        "position": {
            "x": 1,
            "y": 2,
        },
    })
    self.assertEqual(action.source_device, "my_touchscreen")
    self.assertEqual(action.input_source, InputSource.TOUCH)
    action_2 = ClickAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)

  def test_parse_click_invalid_selector(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({"action": "click", "selector": ""})
    self.assertIn("Non-empty", str(cm.exception))

    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({"action": "click", "position": {"selector": ""}})
    self.assertIn("Non-empty string value expected", str(cm.exception))

  def test_parse_click_selector_and_coordinates(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "TOUCH",
          "position": {
              "selector": "#button",
              "x": 0,
              "y": 0,
          },
      })
    self.assertIn("contains unused properties", str(cm.exception))

  def test_parse_click_incomplete_coordinates(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "TOUCH",
          "position": {
              "x": 0,
          },
      })
    self.assertIn("is not a valid coordinate or selector", str(cm.exception))

  def test_parse_click_coordinates_with_js(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "JS",
          "position": {
              "x": 0,
              "y": 0,
          },
      })
    self.assertIn("JS", str(cm.exception))

  def test_parse_click_missing_position(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({"action": "click", "source": "TOUCH"})
    self.assertIn("required config option 'position'", str(cm.exception))

  def test_parse_click_missing_coordinates_and_selector(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "click",
          "source": "TOUCH",
          "position": {},
      })
    self.assertIn("coordinate or selector", str(cm.exception))

  def test_parse_swipe(self) -> None:
    config_dict = {
        "action": "swipe",
        "startx": 100,
        "starty": 200,
        "endx": 110,
        "endy": 220,
        "duration": "12s",
    }
    action = SwipeAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SWIPE)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.duration, dt.timedelta(seconds=12))
    self.assertEqual(action.start_x, 100)
    self.assertEqual(action.start_y, 200)
    self.assertEqual(action.end_x, 110)
    self.assertEqual(action.end_y, 220)
    self.assertEqual(action.source_device, "default_touchscreen")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = SwipeAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_swipe_source_device(self) -> None:
    config_dict = {
        "action": "swipe",
        "start_x": 10,
        "start_y": 20,
        "end_x": 30,
        "end_y": 40,
        "source_device": "custom_touch",
    }
    action = SwipeAction.parse_dict(config_dict)
    self.assertEqual(action.source_device, "custom_touch")
    action.validate()

    action_2 = SwipeAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)

  def test_parse_text_input_minimal(self):
    config_dict = {
        "action": "text_input",
        "duration": "10s",
        "text": "some text",
    }
    action = TextInputAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.TEXT_INPUT)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.input_source, InputSource.JS)
    self.assertIsNone(action.source_device)
    self.assertEqual(action.text, "some text")
    self.assertEqual(action.duration, dt.timedelta(seconds=10))
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = TextInputAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_text_input_non_default_source(self):
    config_dict = {
        "action": "text_input",
        "duration": "1s",
        "source": "keyboard",
        "text": "some text",
    }
    action = TextInputAction.parse_dict(config_dict)

    self.assertEqual(action.input_source, InputSource.KEYBOARD)
    self.assertEqual(action.source_device, "default_keyboard")

  def test_parse_text_input_invalid_source(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "text_input",
          "duration": "1s",
          "source": "invalid_source",
          "text": "some text",
      })
    self.assertIn("source", str(cm.exception))

  def test_parse_text_input_valid_but_unsupported_source(self):
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict({
          "action": "text_input",
          "duration": "1s",
          "source": "mouse",
          "text": "some text",
      })
    self.assertIn("source", str(cm.exception))

  def test_parse_text_input_source_device(self):
    action = TextInputAction.parse_dict({
        "action": "text_input",
        "duration": "1s",
        "source": "keyboard",
        "source_device": "my_keyboard",
        "text": "some text",
    })
    self.assertEqual(action.source_device, "my_keyboard")
    self.assertEqual(action.input_source, InputSource.KEYBOARD)
    action_2 = TextInputAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)

  def test_parse_text_input_negative_duration(self):
    config_dict = {
        "action": "text_input",
        "text": "some text",
        "duration": "-1s",
    }
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict(config_dict)
    self.assertIn("duration", str(cm.exception))

  def test_parse_text_input_missing_text(self):
    config_dict = {"action": "text_input", "duration": "1s"}
    with self.assertRaises(ValueError) as cm:
      ClickAction.parse_dict(config_dict)
    self.assertIn("text", str(cm.exception))

  def test_parse_text_input_keyevent(self):
    config_dict = {
        "action": "text_input",
        "source": "keyboard",
        "duration": "1s",
        "keyevent": "KEYCODE_BACK",
    }
    action = TextInputAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.TEXT_INPUT)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.input_source, InputSource.KEYBOARD)
    self.assertIsNone(action.text)
    self.assertEqual(action.keyevent, "KEYCODE_BACK")
    self.assertEqual(action.duration, dt.timedelta(seconds=1))
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = TextInputAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_text_input_both(self):
    config_dict = {
        "action": "text_input",
        "source": "keyboard",
        "duration": "1s",
        "text": "some text",
        "keyevent": "KEYCODE_BACK",
    }
    with self.assertRaisesRegex(ValueError, "Exactly one"):
      TextInputAction.parse_dict(config_dict)

  def test_parse_wait_for_condition(self):
    config_dict = {
        "action": "wait_for_condition",
        "condition": "return maybe",
    }
    action = WaitForConditionAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_CONDITION)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.condition, "return maybe")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = WaitForConditionAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_element(self):
    config_dict = {
        "action": "wait_for_element",
        "selector": "#button",
    }
    action = WaitForElementAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_ELEMENT)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.selector, "#button")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = WaitForElementAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_element_timeout(self):
    config_dict = {
        "action": "wait_for_element",
        "selector": "#button",
        "timeout": "12s",
    }
    action = WaitForElementAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_ELEMENT)
    self.assertEqual(action.timeout, dt.timedelta(seconds=12))
    self.assertEqual(action.selector, "#button")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = WaitForElementAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_element_expected_count(self):
    config_dict = {
        "action": "wait_for_element",
        "selector": "#button",
        "expected_count": "5",
    }
    action = WaitForElementAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_ELEMENT)
    self.assertEqual(action.selector, "#button")
    self.assertEqual(action.expected_count, 5)
    self.assertFalse(action.or_more)
    action.validate()

    action_2 = WaitForElementAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_element_expected_count_or_more(self):
    config_dict = {
        "action": "wait_for_element",
        "selector": "#button",
        "expected_count": "15",
        "or_more": True,
    }
    action = WaitForElementAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_ELEMENT)
    self.assertEqual(action.selector, "#button")
    self.assertEqual(action.expected_count, 15)
    self.assertTrue(action.or_more)
    action.validate()

    action_2 = WaitForElementAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_element_check_rect(self):
    config_dict = {
        "action": "wait_for_element",
        "selector": "#button",
        "check_rect": True,
    }
    action = WaitForElementAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_ELEMENT)
    self.assertEqual(action.selector, "#button")
    self.assertTrue(action.check_rect)
    action.validate()

    action_2 = WaitForElementAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_js_script(self):
    config_dict = {
        "action": "js",
        "script": "alert(1)",
    }
    action = JsAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.JS)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.script, "alert(1)")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = JsAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_js_script_path(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "js",
        "script_path": str(path),
    }
    action = JsAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.JS)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.script, "alert(2)")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = JsAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_js_script_path_with_replacements(self):
    path = self.create_file("/foo/bar.js", contents="alert($ALERT$)")
    config_dict = {
        "action": "js",
        "script_path": str(path),
        "replace": {
            "$ALERT$": "'something'",
        },
    }
    action = JsAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.JS)
    self.assertEqual(action.script, "alert('something')")
    action.validate()

    action_2 = JsAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_js_script_invalid(self):
    config_dict = {
        "action": "js",
        "script": "",
    }
    with self.assertRaises(ValueError) as cm:
      JsAction.parse_dict(config_dict)
    self.assertIn("script", str(cm.exception))

  def test_js_script_invalid_path(self):
    config_dict = {
        "action": "js",
        "script_path": "",
    }
    with self.assertRaises(ValueError) as cm:
      JsAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

    config_dict = {
        "action": "js",
        "script_path": "/does/not/exist.js",
    }
    with self.assertRaises(ValueError) as cm:
      JsAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

  def test_js_script_invalid_script_xor_path(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "js",
        "script": "alert(1)",
        "script_path": str(path),
    }
    with self.assertRaises(ValueError) as cm:
      JsAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

  def test_js_script_invalid_replacements(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "js",
        "script_path": str(path),
        "replacements": {
            1: 1,
            "one": 1,
        },
    }
    with self.assertRaises(ValueError) as cm:
      JsAction.parse_dict(config_dict)
    self.assertIn("replacements", str(cm.exception))

  def test_inject_new_document_script_script(self):
    config_dict = {
        "action": "inject_new_document_script",
        "script": "alert(1)",
    }
    action = InjectNewDocumentScriptAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.INJECT_NEW_DOCUMENT_SCRIPT)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.script, "alert(1)")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = InjectNewDocumentScriptAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_inject_new_document_script_script_path(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "inject_new_document_script",
        "script_path": str(path),
    }
    action = InjectNewDocumentScriptAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.INJECT_NEW_DOCUMENT_SCRIPT)
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    self.assertEqual(action.script, "alert(2)")
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = InjectNewDocumentScriptAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_inject_new_document_script_path_with_replacements(self):
    path = self.create_file("/foo/bar.js", contents="alert($ALERT$)")
    config_dict = {
        "action": "inject_new_document_script",
        "script_path": str(path),
        "replace": {
            "$ALERT$": "'something'",
        },
    }
    action = InjectNewDocumentScriptAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.INJECT_NEW_DOCUMENT_SCRIPT)
    self.assertEqual(action.script, "alert('something')")
    action.validate()

    action_2 = InjectNewDocumentScriptAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_inject_new_document_script_invalid(self):
    config_dict = {
        "action": "inject_new_document_script",
        "script": "",
    }
    with self.assertRaises(ValueError) as cm:
      InjectNewDocumentScriptAction.parse_dict(config_dict)
    self.assertIn("script", str(cm.exception))

  def test_inject_new_document_script_invalid_path(self):
    config_dict = {
        "action": "inject_new_document_script",
        "script_path": "",
    }
    with self.assertRaises(ValueError) as cm:
      InjectNewDocumentScriptAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

    config_dict = {
        "action": "inject_new_document_script",
        "script_path": "/does/not/exist.js",
    }
    with self.assertRaises(ValueError) as cm:
      InjectNewDocumentScriptAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

  def test_inject_new_document_script_invalid_script_xor_path(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "inject_new_document_script",
        "script": "alert(1)",
        "script_path": str(path),
    }
    with self.assertRaises(ValueError) as cm:
      InjectNewDocumentScriptAction.parse_dict(config_dict)
    self.assertIn("script_path", str(cm.exception))

  def test_inject_new_document_script_invalid_replacements(self):
    path = self.create_file("/foo/bar.js", contents="alert(2)")
    config_dict = {
        "action": "inject_new_document_script",
        "script_path": str(path),
        "replacements": {
            1: 1,
            "one": 1,
        },
    }
    with self.assertRaises(ValueError) as cm:
      InjectNewDocumentScriptAction.parse_dict(config_dict)
    self.assertIn("replacements", str(cm.exception))

  def test_parse_switch_tab_all_args(self):
    config_dict = {
        "action": "switch_tab",
        "tab_index": 17,
        "title": "^Example.*",
        "url": "http(s)?://example.com",
    }
    action = SwitchTabAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SWITCH_TAB)
    self.assertEqual(action.tab_index, 17)
    self.assertEqual(action.title.pattern, "^Example.*")
    self.assertEqual(action.url.pattern, "http(s)?://example.com")
    action.validate()

    action_2 = SwitchTabAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_switch_tab_no_args(self):
    config_dict = {
        "action": "switch_tab",
    }
    with self.assertRaisesRegex(ValueError, "tab_index, title, or url"):
      SwitchTabAction.parse_dict(config_dict)

  def test_parse_switch_tab_relative_tab_index(self):
    config_dict = {
        "action": "switch_tab",
        "relative_tab_index": 17,
        "title": "^Example.*",
        "url": "http(s)?://example.com",
    }
    action = SwitchTabAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SWITCH_TAB)
    self.assertEqual(action.relative_tab_index, 17)
    self.assertEqual(action.title.pattern, "^Example.*")
    self.assertEqual(action.url.pattern, "http(s)?://example.com")
    action.validate()

    action_2 = SwitchTabAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_switch_tab_both_tab_index_raises(self):
    config_dict = {
        "action": "switch_tab",
        "relative_tab_index": 17,
        "tab_index": 17,
    }
    with self.assertRaises(ValueError):
      SwitchTabAction.parse_dict(config_dict)

  def test_parse_switch_tab_only_relative_tab_index(self):
    config_dict = {
        "action": "switch_tab",
        "relative_tab_index": 17,
    }
    action = SwitchTabAction.parse_dict(config_dict)

    self.assertEqual(action.relative_tab_index, 17)

  def test_parse_switch_frame_default(self):
    config_dict = {"action": "switch_frame"}
    action = SwitchFrameAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SWITCH_FRAME)
    self.assertEqual(action.selector, "")
    self.assertEqual(action.timeout, ACTION_TIMEOUT)
    action.validate()

    action_2 = SwitchFrameAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_switch_frame_all(self):
    config_dict = {
        "action": "switch_frame",
        "selector": "iframe#viewer",
        "timeout": "15s",
    }
    action = SwitchFrameAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.SWITCH_FRAME)
    self.assertEqual(action.selector, "iframe#viewer")
    self.assertEqual(action.timeout, dt.timedelta(seconds=15))
    action.validate()

    action_2 = SwitchFrameAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_close_all_tabs(self):
    config_dict = {"action": "close_all_tabs"}

    action = CloseAllTabsAction.parse(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLOSE_ALL_TABS)

  def test_parse_close_tab_all_args(self):
    config_dict = {
        "action": "close_tab",
        "tab_index": 17,
        "title": "^Example.*",
        "url": "http(s)?://example.com",
    }
    action = CloseTabAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLOSE_TAB)
    self.assertEqual(action.tab_index, 17)
    self.assertEqual(action.title.pattern, "^Example.*")
    self.assertEqual(action.url.pattern, "http(s)?://example.com")
    action.validate()

    action_2 = CloseTabAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_close_tab_no_args(self):
    config_dict = {
        "action": "close_tab",
    }
    action = CloseTabAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.CLOSE_TAB)
    self.assertFalse(action.tab_index)
    self.assertFalse(action.title)
    self.assertFalse(action.url)
    action.validate()

    action_2 = CloseTabAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_ready_state(self):
    config_dict = {
        "action": "wait_for_ready_state",
    }
    action = WaitForReadyStateAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_READY_STATE)
    self.assertEqual(action.ready_state, ReadyState.COMPLETE)
    action.validate()

    action_2 = WaitForReadyStateAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_ready_state_interactive(self):
    config_dict = {
        "action": "wait_for_ready_state",
        "ready_state": "interactive",
    }
    action = WaitForReadyStateAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_READY_STATE)
    self.assertEqual(action.ready_state, ReadyState.INTERACTIVE)
    action.validate()

    action_2 = WaitForReadyStateAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_url_matches(self):
    config_dict = {
        "action": "wait_for_url_matches",
        "url_pattern": "example.com",
    }
    action = WaitForUrlMatchesAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_URL_MATCHES)
    self.assertEqual(action.url_pattern.pattern, "example.com")
    action.validate()

    action_2 = WaitForUrlMatchesAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_wait_for_url_matches_timeout(self):
    config_dict = {
        "action": "wait_for_url_matches",
        "url_pattern": "example\\.com",
        "timeout": "8s",
    }
    action = WaitForUrlMatchesAction.parse_dict(config_dict)

    self.assertEqual(action.TYPE, ActionType.WAIT_FOR_URL_MATCHES)
    self.assertEqual(action.url_pattern.pattern, "example\\.com")
    self.assertEqual(action.timeout, dt.timedelta(seconds=8))
    self.assertTrue(action.has_timeout)
    action.validate()

    action_2 = WaitForUrlMatchesAction.parse_dict(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_meminfo_default(self):
    config_dict = {"action": "meminfo"}
    action = MeminfoAction.parse(config_dict)
    action.validate()
    self.assertEqual(action.TYPE, ActionType.MEMINFO)
    self.assertEqual(action.probe_cls, MeminfoProbe)
    self.assertDictEqual(
        dict(action.kwargs), {
            "browser": True,
            "system": False,
            "packages": (),
            "title": None,
        })

    action_2 = ProbeAction.parse(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_meminfo_browser(self):
    config_dict = {"action": "meminfo", "browser": True}
    action = MeminfoAction.parse(config_dict)
    action.validate()
    self.assertEqual(action.TYPE, ActionType.MEMINFO)
    self.assertDictEqual(
        dict(action.kwargs), {
            "browser": True,
            "system": False,
            "packages": (),
            "title": None,
        })

    action_2 = ProbeAction.parse(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_meminfo_title(self):
    config_dict = {"action": "meminfo", "title": "a_title"}
    action = MeminfoAction.parse(config_dict)
    action.validate()
    self.assertEqual(action.TYPE, ActionType.MEMINFO)
    self.assertDictEqual(
        dict(action.kwargs), {
            "browser": True,
            "system": False,
            "packages": (),
            "title": "a_title",
        })

    action_2 = ProbeAction.parse(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_meminfo_packages(self):
    config_dict = {
        "action": "meminfo",
        "browser": False,
        "packages": ["netflix", "minecraft"],
    }
    action = MeminfoAction.parse(config_dict)
    action.validate()
    self.assertEqual(action.TYPE, ActionType.MEMINFO)
    self.assertDictEqual(
        dict(action.kwargs), {
            "browser": False,
            "system": False,
            "packages": ("netflix", "minecraft"),
            "title": None,
        })

    action_2 = ProbeAction.parse(action.to_json())
    self.assertEqual(action, action_2)
    action_2.validate()

  def test_parse_probe_no_probe(self):
    config_dict = {"action": "probe"}

    with self.assertRaisesRegex(ValueError, "No value"):
      ProbeAction.parse(config_dict)

  def test_parse_probe_invalid_probe(self):
    config_dict = {"action": "probe", "probe": "this is not a probe"}

    with self.assertRaisesRegex(ValueError, "Invalid"):
      ProbeAction.parse(config_dict)

  def test_parse_probe_no_kwargs(self):
    config_dict = {"action": "probe", "probe": "js"}

    action = ProbeAction.parse(config_dict)
    self.assertEqual(action.TYPE, ActionType.PROBE)
    self.assertEqual(action.probe_cls, JSProbe)
    self.assertFalse(action.kwargs)

  def test_parse_probe_with_kwargs(self):
    kwargs = {"arg_one": 1, "arg_two": "two"}
    config_dict = {"action": "probe", "probe": "js", "kwargs": kwargs}

    action = ProbeAction.parse(config_dict)
    self.assertEqual(action.TYPE, ActionType.PROBE)
    self.assertEqual(action.probe_cls, JSProbe)
    self.assertDictEqual(dict(action.kwargs), kwargs)

  def test_parse_screenshot(self):
    config_dict = {"action": "screenshot"}
    action = ScreenshotAction.parse(config_dict)
    self.assertEqual(action.TYPE, ActionType.SCREENSHOT)
    self.assertEqual(action.probe_cls, ScreenshotProbe)
    self.assertFalse(action.kwargs)

  def test_parse_dump_html(self):
    config_dict = {"action": "dump_html"}
    action = DumpHtmlAction.parse(config_dict)
    self.assertEqual(action.TYPE, ActionType.DUMP_HTML)
    self.assertEqual(action.probe_cls, DumpHtmlProbe)
    self.assertFalse(action.kwargs)

  def test_all_actions_validate_on_init(self):
    for action_cls in ACTIONS_TUPLE:
      with self.subTest(action_cls=action_cls.__name__):
        with self.assertRaises(ValueError):
          action_cls.config_parser().parse({"timeout": "-10s"})


class PositionConfigTestCase(unittest.TestCase):

  def test_parse_position_from_coordinates(self):
    position = PositionConfig.from_coordinates(123, 456)
    self.assertIsNone(position.selector)
    self.assertIsNotNone(position.coordinates)
    self.assertEqual(123, position.coordinates.x)
    self.assertEqual(456, position.coordinates.y)
    self.assertIsNone(position.ui_selector)

  def test_parse_position_from_selector_defaults(self):
    position = PositionConfig.from_selector("#id")
    self.assertIsNone(position.coordinates)
    self.assertIsNotNone(position.selector)
    self.assertEqual("#id", position.selector.selector)
    self.assertTrue(position.selector.required)
    self.assertFalse(position.selector.scroll_into_view)
    self.assertFalse(position.selector.wait)
    self.assertIsNone(position.ui_selector)

  def test_parse_position_from_selector_all(self):
    position = PositionConfig.from_selector(
        selector="#id", required=False, scroll_into_view=True, wait=True)
    self.assertIsNone(position.coordinates)
    self.assertIsNotNone(position.selector)
    self.assertEqual("#id", position.selector.selector)
    self.assertFalse(position.selector.required)
    self.assertTrue(position.selector.scroll_into_view)
    self.assertTrue(position.selector.wait)
    self.assertIsNone(position.ui_selector)

  def test_parse_position_from_ui_selector(self):
    res = "com.google.android.apps.nexuslauncher:id/search_container_hotseat"
    position = PositionConfig.from_ui_selector(res=res)
    self.assertIsNone(position.selector)
    self.assertIsNone(position.coordinates)
    self.assertIsNotNone(position.ui_selector)
    self.assertEqual(res, position.ui_selector.res)

  def test_selector_and_coordinates_raises(self):
    with self.assertRaisesRegex(ValueError, "exactly one"):
      PositionConfig(
          coordinates=CoordinatesConfig(x=123, y=456),
          selector=SelectorConfig(
              "#id", required=True, scroll_into_view=False, wait=False))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
