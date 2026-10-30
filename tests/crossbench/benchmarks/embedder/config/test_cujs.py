# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import pathlib
from typing import Any, Sequence

import hjson

from crossbench.benchmarks.embedder.config.cujs import CUJConfig, CUJsConfig
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class CUJsConfigTestCase(CrossbenchFakeFsTestCase):

  def test_parse_unknown_type(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CUJsConfig.parse(self)
    self.assertIn("type", str(cm.exception))

  def test_parse_empty_actions(self):
    config_data: dict[str, dict] = {"cujs": {"Google Story": []}}
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)actions.*non-empty"):
      CUJsConfig.parse(config_data)

    config_data = {"cujs": {"Google Story": {}}}
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)blocks.*non-empty"):
      CUJsConfig.parse(config_data)

  def test_example(self):
    config_data = {
        "cujs": {
            "Google Story": [
                {
                    "action": "click",
                    "source": "touch",
                    "position": {
                        "res": "com.package.name/resourceId",
                    },
                },
                {
                    "action": "wait",
                    "duration": 5,
                },
            ],
        },
    }
    config = CUJsConfig.parse(config_data)
    self.assert_single_google_story(config.cujs)
    # Loading the same config from a file should result in the same actions.
    file = pathlib.Path("cuj.config.hjson")
    assert not file.exists()
    with file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    file_config = CUJsConfig.parse(str(file))
    self.assertEqual(config, file_config)
    cujs = file_config.cujs
    self.assert_single_google_story(cujs)

  def assert_single_google_story(self, cujs: Sequence[CUJConfig]):
    self.assertTrue(len(cujs), 1)
    cuj = cujs[0]
    self.assertEqual(cuj.label, "Google Story")
    self.assertEqual(len(cuj.blocks), 1)
    block = cuj.blocks[0]
    self.assertSequenceEqual([str(action.TYPE) for action in block],
                             ["click", "wait"])

  def test_no_scenarios(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      CUJsConfig.parse_dict({})
    with self.assertRaises(argparse.ArgumentTypeError):
      CUJsConfig.parse_dict({"cujs": {}})

  def test_scenario_invalid_actions(self):
    invalid_actions: list[Any] = [None, "", [], {}, "invalid string", 12]
    for invalid_action in invalid_actions:
      config_dict: dict[str, object] = {"cujs": {"name": invalid_action}}
      with self.subTest(invalid_action=invalid_action):
        with self.assertRaises(argparse.ArgumentTypeError):
          CUJsConfig.parse_dict(config_dict)

  def test_missing_action(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CUJsConfig.parse_dict(
          {"cujs": {
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
          "cujs": {
              "TEST": [{
                  "action": invalid_action,
                  "duration": 5.0,
              }],
          },
      }
      with self.subTest(invalid_action=invalid_action):
        with self.assertRaises(argparse.ArgumentTypeError):
          CUJsConfig.parse_dict(config_dict)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
