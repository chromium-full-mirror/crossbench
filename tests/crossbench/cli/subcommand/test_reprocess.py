# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final
from unittest import mock

import pandas as pd

from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.subcommand.reprocess import ReprocessSubcommand
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, SysExitTestException

if TYPE_CHECKING:
  from crossbench import path as pth

_PROCESS_RESULT_DIR_PATCH: Final[str] = (
    "crossbench.benchmarks.web_power.probe.WebPowerProbe.process_result_dir")


class ReprocessSubcommandTest(BaseCliTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.cli_instance = CrossBenchCLI()
    self.subcommand = self.cli_instance.subcommands["reprocess"]
    self.assertIsInstance(self.subcommand, ReprocessSubcommand)
    self.test_dir = self.out_dir / "results"
    self.test_dir.mkdir(parents=True, exist_ok=True)

  def _create_sample_run(
      self,
      browser: str = "chrome",
      story: str = "s",
      run: str = "0",
      probe: str = "p",
      model: str | None = "Pixel 9",
      details_file: str = "cb.system.details.json",
  ) -> pth.LocalPath:
    run_dir = self.test_dir / browser / "stories" / story / run / probe
    run_dir.mkdir(parents=True, exist_ok=True)
    if model is not None:
      data: dict[str, Any]
      if details_file == "cb.system.details.json":
        data = {"Android": {"ro.product.model": model}}
      elif details_file == "cb.results.json":
        data = {"browser": {"os": {"model": model}}}
      else:
        raise ValueError(f"Unknown details_file: {details_file}")
      (run_dir / details_file).write_text(json.dumps(data), encoding="utf-8")
    return run_dir

  def test_subcommand_registered(self) -> None:
    self.assertIn("reprocess", self.cli_instance.subcommands)
    self.assertIs(self.cli_instance.subcommands["reprocess"], self.subcommand)

  def test_invalid_result_dir(self) -> None:
    non_existent_dir = self.out_dir / "does_not_exist"
    with self.assertRaises(SysExitTestException):
      self.run_cli("reprocess", str(non_existent_dir))

  def test_unsupported_probe(self) -> None:
    with self.assertRaises(SysExitTestException):
      self.run_cli("reprocess", str(self.test_dir), "--probe=invalid_probe")

  def test_run_success(self) -> None:
    self._create_sample_run("chrome-stable", "story1", "0", "web_power")
    mock_df = pd.DataFrame([{"odpm_total_mw": 100.0}])
    with mock.patch(_PROCESS_RESULT_DIR_PATCH, return_value=mock_df) as m:
      self.run_cli("reprocess", str(self.test_dir))
      m.assert_called_once()
      call_args = m.call_args
      self.assertEqual(call_args[0][0], self.test_dir)
      self.assertTrue(call_args[1]["reprocess"])

  def test_run_with_custom_probe(self) -> None:
    self._create_sample_run("chrome-stable", "story1", "0", "web_power")
    mock_df = pd.DataFrame([{"odpm_total_mw": 100.0}])
    with mock.patch(_PROCESS_RESULT_DIR_PATCH, return_value=mock_df) as m:
      self.run_cli("reprocess", str(self.test_dir), "--probe=web_power")
      m.assert_called_once()

  def test_get_device_model_fallback(self) -> None:
    run_dir = self._create_sample_run(
        model="Pixel 8", details_file="cb.results.json")
    model = ReprocessSubcommand._get_device_model_from_run(run_dir)
    self.assertEqual(model, "Pixel 8")

  def test_get_device_model_empty(self) -> None:
    run_dir = self._create_sample_run(model=None)
    model = ReprocessSubcommand._get_device_model_from_run(run_dir)
    self.assertEqual(model, "")

  def test_get_base_df(self) -> None:
    self._create_sample_run(
        "chrome-stable", "story1", "0", "web_power", model="Pixel 9")
    self._create_sample_run(
        "chrome-beta", "story2", "0", "web_power", model="Pixel 9")
    subcommand = ReprocessSubcommand(self.cli_instance)
    base_df = subcommand._get_base_df(self.test_dir)
    self.assertEqual(len(base_df), 2)
    self.assertIn("cb_browser", base_df.columns)
    self.assertIn("cb_story", base_df.columns)
    self.assertIn("device_model", base_df.columns)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
