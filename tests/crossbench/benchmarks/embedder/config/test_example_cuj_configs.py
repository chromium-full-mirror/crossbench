# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench import hjson as cb_hjson
from crossbench.benchmarks.embedder.config.cujs import CUJsConfig
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class TestExampleCUJConfig(CrossbenchFakeFsTestCase):

  def test_parse_embedder_cuj_config_file(self):
    example_config_file = (
        test_helper.config_dir() / "team/woa/embedder_cuj_config.hjson")
    self.fs.add_real_file(example_config_file)
    file_config = CUJsConfig.parse(example_config_file)
    with example_config_file.open(encoding="utf-8") as f:
      data = cb_hjson.load_unique_keys(f)
    dict_config = CUJsConfig.parse_dict(data)
    self.assertTrue(dict_config.cujs)
    self.assertTrue(file_config.cujs)
    for cuj in dict_config.cujs:
      self.assertEqual(len(cuj.blocks), 1)
      self.assertGreater(len(cuj.blocks[0].actions), 1)

  def test_parse_notification_cuj_config_file(self):
    example_config_file = (
        test_helper.config_dir() / "team/woa/notification_cuj_config.hjson")
    self.fs.add_real_file(example_config_file)
    file_config = CUJsConfig.parse(example_config_file)
    with example_config_file.open(encoding="utf-8") as f:
      data = cb_hjson.load_unique_keys(f)
    dict_config = CUJsConfig.parse_dict(data)
    self.assertTrue(dict_config.cujs)
    self.assertTrue(file_config.cujs)
    for cuj in dict_config.cujs:
      self.assertEqual(cuj.label, "agsa-notification")
      self.assertEqual(len(cuj.blocks), 1)
      self.assertEqual(len(cuj.blocks[0].actions), 1)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
