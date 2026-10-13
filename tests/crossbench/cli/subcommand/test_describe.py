# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import unittest
from unittest import mock

from typing_extensions import override

from crossbench.cli.cli import CrossBenchCLI
from tests import test_helper


class DescribeSubcommandTest(unittest.TestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.cli = CrossBenchCLI()
    self.mock_print = self.enterContext(mock.patch("builtins.print"))

  def test_describe_benchmark_includes_argparse_groups(self) -> None:
    describe_subcommand = self.cli.describe_subcommand
    data = describe_subcommand.help_data("benchmark", "speedometer_3.0")
    benchmarks = data.get("benchmarks", {})
    self.assertIn("speedometer_3.0", benchmarks)

    sp3 = benchmarks["speedometer_3.0"]
    self.assertIn("flags", sp3)
    groups = sp3["flags"]
    self.assertIsInstance(groups, list)
    self.assertGreater(len(groups), 0)

    group_names = [g["name"] for g in groups]
    self.assertIn("Run & Repetition Options", group_names)
    self.assertIn("Browser Options", group_names)

    # Verify arguments structure inside group
    repeat_group = next(
        g for g in groups if g["name"] == "Run & Repetition Options")
    self.assertIn("arguments", repeat_group)
    flag_names = [f["name"] for f in repeat_group["arguments"]]
    self.assertIn("--repetitions", flag_names)

  def test_describe_benchmark_json_output(self) -> None:
    self.cli.run(["describe", "benchmark", "speedometer_3.0", "--json"])
    self.mock_print.assert_called_once()
    printed_text = self.mock_print.call_args[0][0]
    parsed_json = json.loads(printed_text)
    self.assertIn("speedometer_3.0", parsed_json)
    sp3 = parsed_json["speedometer_3.0"]
    self.assertIn("flags", sp3)

  def test_describe_benchmark_table_output(self) -> None:
    self.cli.run(["describe", "benchmark", "speedometer_3.0"])
    self.mock_print.assert_called_once()
    printed_text = self.mock_print.call_args[0][0]
    self.assertNotIn("flags", printed_text)
    self.assertNotIn("Run & Repetition Options", printed_text)
    self.assertIn("speedometer_3.0", printed_text)
    self.assertIn("See `speedometer_3.0 --help`", printed_text)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
