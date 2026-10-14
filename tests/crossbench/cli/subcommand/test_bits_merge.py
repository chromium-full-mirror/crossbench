# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import Final
from unittest import mock

from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.subcommand.bits_merge import BitsMergeSubcommand
from crossbench.probes.internal.summary import ResultsSummaryProbe
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, SysExitTestException

_MERGE_PATCH_TARGET: Final[str] = "crossbench.probes.bits.merge.merge_results"


class BitsMergeSubcommandTest(BaseCliTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.cli_instance = CrossBenchCLI()
    self.subcommand = self.cli_instance.subcommands["bits-merge"]
    self.assertIsInstance(self.subcommand, BitsMergeSubcommand)
    self.test_dir = self.out_dir / "results"
    self.test_dir.mkdir(parents=True, exist_ok=True)
    (self.test_dir / ResultsSummaryProbe.FILE_NAME).touch()
    self.output_dir = self.out_dir / "merged"
    self.archives = [self.output_dir / "chrome_story_0.zip"]

  def test_subcommand_registered(self) -> None:
    self.assertIn("bits-merge", self.cli_instance.subcommands)

  def _run_cli_expecting_usage_error(self, *args: str) -> None:
    with (
        mock.patch(_MERGE_PATCH_TARGET) as mock_merge,
        self.assertRaises(SysExitTestException),
    ):
      self.run_cli("bits-merge", *args)
    mock_merge.assert_not_called()

  def test_run_success(self) -> None:
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits-merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_run_alias_success(self) -> None:
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits_merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_output_dir_empty(self) -> None:
    self.output_dir.mkdir()
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits-merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_output_dir_not_empty(self) -> None:
    self.output_dir.mkdir()
    (self.output_dir / "foo").touch()
    self._run_cli_expecting_usage_error(
        str(self.test_dir), str(self.output_dir))

  def test_missing_arguments(self) -> None:
    self._run_cli_expecting_usage_error()
    self._run_cli_expecting_usage_error(str(self.test_dir))

  def test_invalid_result_dir(self) -> None:
    self._run_cli_expecting_usage_error(
        str(self.out_dir / "does_not_exist"), str(self.output_dir))

  def test_run_non_result_dir_fails(self) -> None:
    non_result_dir = self.out_dir / "not_a_result_dir"
    non_result_dir.mkdir(parents=True)
    self._run_cli_expecting_usage_error(
        str(non_result_dir), str(self.output_dir))

  def test_output_dir_is_file(self) -> None:
    self.output_dir.touch()
    self._run_cli_expecting_usage_error(
        str(self.test_dir), str(self.output_dir))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
