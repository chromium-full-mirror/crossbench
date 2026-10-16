# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import copy
import datetime as dt
import io
import json
import unittest
from typing import TYPE_CHECKING, Any, Final
from unittest import mock

import yaml

from crossbench import path as pth
from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.subcommand.pinpoint import PinpointHelpFormatter, \
    PinpointStatusSubcommand, PinpointWaitSubcommand, \
    collect_metrics_context
from crossbench.pinpoint.config import BisectEndVariantConfig, \
    BisectStartVariantConfig, PinpointBisectJobConfig, PinpointTryJobConfig, \
    VariantConfig
from crossbench.pinpoint.job_info import PinpointJobInfo, UrlSource
from crossbench.pinpoint.output_format import OutputFormat
from crossbench.pinpoint.user import UserEnum
from tests import test_helper

if TYPE_CHECKING:
  from crossbench.types import JsonDict

_TEST_STATUS_JOB_DATA: Final[JsonDict] = {
    "job_id":
        "123abc",
    "status":
        "Running",
    "comparison_mode":
        "try",
    "user":
        "tester@example.com",
    "created":
        "2024-01-01T12:00:00Z",
    "arguments": {
        "benchmark": "speedometer3",
        "configuration": "linux-perf",
        "story": "Speedometer3",
        "bug_id": "9999",
        "initial_attempt_count": "10",
    },
    "state": [
        {
            "attempts": [
                {
                    "executions": [{}, {
                        "completed": True,
                    }],
                },
                {
                    "executions": [{}, {
                        "completed": True,
                    }],
                },
            ],
        },
        {
            "attempts": [{
                "executions": [{}, {
                    "completed": True,
                }],
            }],
        },
    ],
}


def _test_status_job_data(**kwargs: Any) -> JsonDict:
  data = copy.deepcopy(_TEST_STATUS_JOB_DATA)
  data.update(kwargs)
  return data


class PinpointSubcommandTest(unittest.TestCase):
  """Verifies that subcommands call the right functions."""

  def setUp(self):
    super().setUp()
    self.cli = CrossBenchCLI()
    self.mock_print = self.enterContext(mock.patch("builtins.print"))
    self.mock_init_metrics = self.enterContext(
        mock.patch("crossbench.cli.subcommand.pinpoint.init_metrics"))
    self.mock_collect_metrics = self.enterContext(
        mock.patch("crossbench.cli.subcommand.pinpoint.collect_metrics"))

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_user_metrics(self, _mock_list_job):
    self.cli.run(["pinpoint", "list", "-n", "100"])
    self.mock_init_metrics.assert_called_once_with()
    self.mock_collect_metrics.assert_called_once_with("list")

  def test_collect_metrics_context(self):
    with collect_metrics_context("custom_action"):
      pass
    self.mock_init_metrics.assert_called_once_with()
    self.mock_collect_metrics.assert_called_once_with("custom_action")

  def test_collect_metrics_context_keyboard_interrupt(self):
    with self.assertRaises(SystemExit) as cm:
      with collect_metrics_context("custom_action"):
        raise KeyboardInterrupt
    self.assertEqual(cm.exception.code, 2)

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list(self, mock_list_job):
    self.cli.run([
        "pinpoint",
        "list",
        "--user",
        "all",
        "--number",
        "100",
        "--format",
        "csv",
        "--truncate",
        "50",
        "--extra-columns",
        "bug",
        "--extra-columns",
        "story",
    ])
    mock_list_job.assert_called_once_with(
        user=UserEnum.ALL,
        number=100,
        truncate=50,
        output_format="csv",
        extra_columns=["bug", "story"],
        url_source=UrlSource.LESZEK_PERF)

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_bots")
  def test_pinpoint_bots_prints_filtered_bots(self, mock_fetch_bots):
    mock_fetch_bots.return_value = [
        "linux-r350-perf",
        "win-10-perf",
        "win-11-perf",
    ]
    self.cli.run(["pinpoint", "bots", "--filter", "win"])
    self.mock_print.assert_called_once_with("win-10-perf\nwin-11-perf")

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_benchmarks")
  def test_pinpoint_benchmarks_prints_filtered_benchmarks(
      self, mock_fetch_benchmarks):
    mock_fetch_benchmarks.return_value = [
        "speedometer2",
        "speedometer3",
        "jetstream2",
    ]
    self.cli.run(["pinpoint", "benchmarks", "--filter", "speedometer"])
    self.mock_print.assert_called_once_with("speedometer2\nspeedometer3")

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_stories")
  def test_pinpoint_benchmarks_prints_filtered_stories(self,
                                                       mock_fetch_stories):
    mock_fetch_stories.return_value = ["story1", "story2", "default"]
    self.cli.run(["pinpoint", "stories", "speedometer3", "--filter", "story"])
    mock_fetch_stories.assert_called_once_with("speedometer3")
    self.mock_print.assert_called_once_with("story1\nstory2")

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_builds")
  def test_pinpoint_list_builds(self, mock_list_builds):
    self.cli.run(["pinpoint", "builds", "linux-r350-perf", "--limit", "42"])
    mock_list_builds.assert_called_once_with("linux-r350-perf", 42)

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job(self, mock_parse_and_override, mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
        story="default",
        story_tags="tag1,tag2",
        repeat=42,
        bug="12345",
        base=VariantConfig(
            commit="HEAD",
            patch="https://base.patch",
        ),
        experiment=VariantConfig(
            commit="recent",
            patch="https://exp.patch",
        ),
    )
    mock_parse_and_override.return_value = test_config
    self.cli.run([
        *["pinpoint", "start"],
        *["--config", "{benchmark: 'speedometer3', bot: 'linux-r350-perf'}"],
        *["--benchmark", "speedometer3"],
        *["--bot", "linux-r350-perf"],
        *["--story", "default"],
        *["--story-tags", "tag1,tag2"],
        *["--repeat", "42"],
        *["--bug", "12345"],
        *["--base-commit", "HEAD"],
        *["--exp-commit", "recent"],
        *["--base-patch", "http://base.patch"],
        *["--exp-patch", "http://exp.patch"],
        "--base-flags=--base-flag",
        "--exp-flags=--exp-flag",
        "--base-js-flags=--flag1",
        "--exp-js-flags=--flag2",
        *["--base-enable-features", "base_feat"],
        *["--exp-enable-features", "exp_feat"],
        *["--base-disable-features", "base_dis"],
        *["--exp-disable-features", "exp_dis"],
    ])
    mock_parse_and_override.assert_called_once_with(
        config="{benchmark: 'speedometer3', bot: 'linux-r350-perf'}",
        benchmark="speedometer3",
        bot="linux-r350-perf",
        story="default",
        story_tags="tag1,tag2",
        repeat=42,
        bug=12345,
        base_commit="HEAD",
        exp_commit="recent",
        base_patch="http://base.patch",
        exp_patch="http://exp.patch",
        base_flags="--base-flag",
        exp_flags="--exp-flag",
        base_js_flags="--flag1",
        exp_js_flags="--flag2",
        base_enable_features="base_feat",
        exp_enable_features="exp_feat",
        base_disable_features="base_dis",
        exp_disable_features="exp_dis",
        base_enable_blink_features=None,
        exp_enable_blink_features=None,
        base_disable_blink_features=None,
        exp_disable_blink_features=None,
    )
    mock_start_job.assert_called_with(
        test_config, url_source=UrlSource.LESZEK_PERF)

  @mock.patch("crossbench.cli.subcommand.pinpoint.bisect_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointBisectJobConfig.parse_and_override")
  def test_pinpoint_bisect_job(self, mock_parse_and_override, mock_bisect_job):
    test_config = PinpointBisectJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
        chart="my_chart",
        story="default",
        story_tags="tag1,tag2",
        repeat=42,
        bug="12345",
        start=BisectStartVariantConfig(commit="HEAD"),
        end=BisectEndVariantConfig(commit="recent"),
    )
    mock_parse_and_override.return_value = test_config
    self.cli.run([
        *["pinpoint", "bisect"],
        *["--config", "{benchmark: 'speedometer3', bot: 'linux-r350-perf'}"],
        *["--benchmark", "speedometer3"],
        *["--bot", "linux-r350-perf"],
        *["--chart", "my_chart"],
        *["--story", "default"],
        *["--story-tags", "tag1,tag2"],
        *["--repeat", "42"],
        *["--bug", "12345"],
        *["--start-commit", "HEAD"],
        *["--end-commit", "recent"],
        "--flags=--bisect-flag",
        "--js-flags=--flag1",
        *["--enable-features", "base_feat"],
        *["--disable-features", "base_dis"],
    ])
    mock_parse_and_override.assert_called_once_with(
        config="{benchmark: 'speedometer3', bot: 'linux-r350-perf'}",
        benchmark="speedometer3",
        bot="linux-r350-perf",
        chart="my_chart",
        story="default",
        story_tags="tag1,tag2",
        repeat=42,
        bug=12345,
        start_commit="HEAD",
        end_commit="recent",
        flags="--bisect-flag",
        js_flags="--flag1",
        enable_features="base_feat",
        disable_features="base_dis",
        enable_blink_features=None,
        disable_blink_features=None,
    )
    mock_bisect_job.assert_called_with(
        test_config, url_source=UrlSource.LESZEK_PERF)

    mock_parse_and_override.reset_mock()
    self.cli.run([
        "pinpoint",
        "bisect",
        "--config",
        "{benchmark: 'speedometer3', bot: 'linux-r350-perf'}",
        "--chart",
        "my_chart",
        "--browser-flags=--bisect-flag",
    ])
    self.assertEqual(mock_parse_and_override.call_args.kwargs["flags"],
                     "--bisect-flag")

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_js_flags(self, mock_parse_and_override,
                                       _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--js-flags=--flag1",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_js_flags": "--flag1",
            "exp_js_flags": "--flag1",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_enable_features(self, mock_parse_and_override,
                                              _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--enable-features=Feature1",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_enable_features": "Feature1",
            "exp_enable_features": "Feature1",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_disable_features(self, mock_parse_and_override,
                                               _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--disable-features=Feature1",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_disable_features": "Feature1",
            "exp_disable_features": "Feature1",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_enable_blink_features(self,
                                                    mock_parse_and_override,
                                                    _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--enable-blink-features=BlinkFeature1",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_enable_blink_features": "BlinkFeature1",
            "exp_enable_blink_features": "BlinkFeature1",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_disable_blink_features(self,
                                                     mock_parse_and_override,
                                                     _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--disable-blink-features=BlinkFeature1",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_disable_blink_features": "BlinkFeature1",
            "exp_disable_blink_features": "BlinkFeature1",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_commit(self, mock_parse_and_override,
                                     _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--commit=1234567890",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_commit": "1234567890",
            "exp_commit": "1234567890",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_by_benchmark(self, mock_parse_and_override,
                                           mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3.1.crossbench", bot="win-11-perf")
    mock_parse_and_override.return_value = test_config
    self.cli.run(["pinpoint", "sp3", "--bot", "win-11-perf"])
    mock_parse_and_override.assert_called_once_with(
        benchmark="speedometer3.1.crossbench",
        bot="win-11-perf",
        config=None,
        story=None,
        story_tags=None,
        repeat=None,
        bug=None,
        base_commit=None,
        exp_commit=None,
        base_patch=None,
        exp_patch=None,
        base_flags=None,
        exp_flags=None,
        base_js_flags=None,
        exp_js_flags=None,
        base_enable_features=None,
        exp_enable_features=None,
        base_disable_features=None,
        exp_disable_features=None,
        base_enable_blink_features=None,
        exp_enable_blink_features=None,
        base_disable_blink_features=None,
        exp_disable_blink_features=None,
    )
    mock_start_job.assert_called_with(
        test_config, url_source=UrlSource.LESZEK_PERF)

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_flags(self, mock_parse_and_override,
                                    _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--flags=--no-sandbox",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_flags": "--no-sandbox",
            "exp_flags": "--no-sandbox",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_base_exp_flags(self, mock_parse_and_override,
                                             _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--base-flags=--flag1",
        "--exp-flags=--flag2",
    ])

    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_flags": "--flag1",
            "exp_flags": "--flag2",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_browser_flags_aliases(self,
                                                    mock_parse_and_override,
                                                    _mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--browser-flags=--no-sandbox",
    ])
    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_flags": "--no-sandbox",
            "exp_flags": "--no-sandbox",
        })

    self.cli.run([
        *["pinpoint", "start"],
        *["--benchmark", "speedometer3"],
        "--base-browser-flags=--flag1",
        "--exp-browser-flags=--flag2",
    ])
    self.assertEqual(
        {
            key: value
            for key, value in mock_parse_and_override.call_args.kwargs.items()
            if value is not None
        }, {
            "benchmark": "speedometer3",
            "base_flags": "--flag1",
            "exp_flags": "--flag2",
        })

  @mock.patch("crossbench.cli.subcommand.pinpoint.print_job_config")
  def test_pinpoint_job_config(self, mock_print_job_config):
    self.cli.run(["pinpoint", "config", "123abc", "--raw", "--full"])
    mock_print_job_config.assert_called_once_with(
        job_id="123abc", raw=True, full=True)

    mock_print_job_config.reset_mock()
    self.cli.run(["pinpoint", "config", "123abc"])
    mock_print_job_config.assert_called_once_with(
        job_id="123abc", raw=False, full=False)

  def test_pinpoint_job_config_full_without_raw(self):
    with self.assertRaises(ValueError):
      self.cli.run(["pinpoint", "config", "123abc", "--full"])

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_job(self, mock_cancel_jobs):
    self.cli.run(
        ["pinpoint", "cancel", "--job", "123abc", "--reason", "test reason"])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc"], reason="test reason")

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_job_positional_job_id(self, mock_cancel_jobs):
    self.cli.run(["pinpoint", "cancel", "123abc", "--reason", "test reason"])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc"], reason="test reason")

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_multiple_jobs_flag(self, mock_cancel_jobs):
    self.cli.run([
        "pinpoint",
        "cancel",
        "--job",
        "123abc",
        "456def",
        "--reason",
        "test reason",
    ])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc", "456def"], reason="test reason")

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_multiple_jobs_repeated_flag(self, mock_cancel_jobs):
    self.cli.run([
        "pinpoint",
        "cancel",
        "--job=123abc",
        "--job=456def",
        "--reason",
        "test reason",
    ])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc", "456def"], reason="test reason")

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_multiple_jobs_comma(self, mock_cancel_jobs):
    self.cli.run([
        "pinpoint",
        "cancel",
        "--job",
        "123abc,456def",
        "--reason",
        "test reason",
    ])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc", "456def"], reason="test reason")

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_multiple_jobs_positional(self, mock_cancel_jobs):
    self.cli.run(
        ["pinpoint", "cancel", "123abc", "456def", "--reason", "test reason"])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc", "456def"], reason="test reason")

  def test_pinpoint_cancel_job_positional_and_explicit_job_id(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run([
          "pinpoint",
          "cancel",
          "123abc",
          "--job",
          "123abc",
          "--reason",
          "test reason",
      ])
    self.assertEqual(cm.exception.code, 2)

  def test_pinpoint_cancel_without_job(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "cancel", "--reason", "test reason"])
    self.assertEqual(cm.exception.code, 2)

  @mock.patch("crossbench.cli.subcommand.pinpoint.download_results")
  def test_pinpoint_download_results(self, mock_download_results):
    self.cli.run(
        ["pinpoint", "results", "123abc", "--out-dir", "test_dir", "--force"])
    mock_download_results.assert_called_once_with(
        job_id="123abc", out_dir=pth.LocalPath("test_dir"), force=True)

  @mock.patch("crossbench.cli.subcommand.pinpoint.download_results")
  def test_pinpoint_download_results_aliases(self, mock_download_results):
    self.cli.run(["pinpoint", "download", "123abc"])
    mock_download_results.assert_called_once_with(
        job_id="123abc", out_dir=None, force=False)
    mock_download_results.reset_mock()
    self.cli.run(["pinpoint", "fetch", "123abc"])
    mock_download_results.assert_called_once_with(
        job_id="123abc", out_dir=None, force=False)

  def test_status_job_data_deep_clone(self):
    data1 = _test_status_job_data()
    data2 = _test_status_job_data()
    self.assertIsNot(data1, data2)
    self.assertIsNot(data1["arguments"], data2["arguments"])
    self.assertIsNot(data1["state"], data2["state"])
    data1["status"] = "Mutated"
    data1["arguments"]["benchmark"] = "Mutated"
    self.assertEqual(data2["status"], "Running")
    self.assertEqual(data2["arguments"]["benchmark"], "speedometer3")
    self.assertEqual(_TEST_STATUS_JOB_DATA["status"], "Running")
    self.assertEqual(_TEST_STATUS_JOB_DATA["arguments"]["benchmark"],
                     "speedometer3")

  @mock.patch("crossbench.pinpoint.job_info.fetch_job_config")
  def test_pinpoint_status(self, mock_fetch):
    mock_fetch.return_value = _test_status_job_data()
    self.cli.run(["pinpoint", "status", "123abc"])
    mock_fetch.assert_called_once_with("123abc", full=True)
    self.mock_print.assert_called_once()
    output = self.mock_print.call_args[0][0]
    self.assertIn("123abc", output)
    self.assertIn("🏃 running", output)
    self.assertIn("speedometer3", output)

    mock_fetch.reset_mock()
    self.mock_print.reset_mock()
    self.cli.run(["pinpoint", "st", "--job", "123abc", "--format", "json"])
    mock_fetch.assert_called_once_with("123abc", full=True)
    parsed = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(parsed["job_id"], "123abc")

  def test_format_job_status_formats(self):
    job_info = PinpointJobInfo.from_json(_test_status_job_data())
    formatted_table = PinpointStatusSubcommand.format_job_status(job_info)
    self.assertIn("123abc", formatted_table)
    self.assertIn("🏃 running", formatted_table)
    self.assertIn("speedometer3", formatted_table)
    self.assertIn("linux-perf", formatted_table)
    self.assertIn("Speedometer3", formatted_table)
    self.assertIn("9999", formatted_table)
    self.assertIn("tester@example.com", formatted_table)

    formatted_yaml = PinpointStatusSubcommand.format_job_status(
        job_info, OutputFormat.YAML)
    self.assertEqual(yaml.safe_load(formatted_yaml)["job_id"], "123abc")

    formatted_csv = PinpointStatusSubcommand.format_job_status(
        job_info, OutputFormat.CSV)
    self.assertIn("Property,Value", formatted_csv)
    self.assertIn("Job ID,123abc", formatted_csv)
    self.assertNotIn("\x1b]8;;", formatted_csv)

    formatted_tsv = PinpointStatusSubcommand.format_job_status(
        job_info, OutputFormat.TSV)
    self.assertIn("Property\tValue", formatted_tsv)
    self.assertIn("Job ID\t123abc", formatted_tsv)
    self.assertNotIn("\x1b]8;;", formatted_tsv)

  def test_format_job_status_bisect(self):
    bisect_info = PinpointJobInfo.from_json({
        "job_id": "98765",
        "status": "Completed",
        "comparison_mode": "performance",
        "difference_count": 1,
        "arguments": {
            "benchmark": "speedometer3",
            "configuration": "win-11-perf",
            "initial_attempt_count": "10",
        },
        "state": [
            {
                "attempts": [{
                    "executions": [{}, {
                        "completed": True,
                    }],
                }],
            },
            {
                "attempts": [{
                    "executions": [{}, {
                        "completed": True,
                    }],
                }],
            },
        ],
        "results_url": "https://storage.cloud.google.com/results.html",
    })
    formatted = PinpointStatusSubcommand.format_job_status(bisect_info)
    self.assertIn("bisect", formatted)
    self.assertIn("✅ completed", formatted)
    self.assertIn("Differences", formatted)
    self.assertIn("Results URL", formatted)
    self.assertIn("2 commits, 2 attempts", formatted)

  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait(self, mock_from_id):
    mock_job = mock.MagicMock()
    mock_job.wait.return_value = PinpointJobInfo.from_json(
        _test_status_job_data())
    mock_from_id.return_value = mock_job
    self.cli.run([
        "pinpoint",
        "wait",
        "123abc",
        "--timeout",
        "30m",
        "--poll-interval",
        "5s",
    ])
    mock_from_id.assert_called_once_with("123abc", full=True)
    mock_job.wait.assert_called_once_with(
        timeout=dt.timedelta(minutes=30),
        poll_interval=dt.timedelta(seconds=5),
        progress=mock.ANY)
    self.assertEqual(self.mock_print.call_count, 2)
    self.assertIn("123abc", self.mock_print.call_args[0][0])

  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_default(self, mock_from_id):
    mock_job = mock.MagicMock()
    mock_job.wait.return_value = PinpointJobInfo.from_json(
        _test_status_job_data())
    mock_from_id.return_value = mock_job
    self.cli.run([
        "pinpoint",
        "wait",
        "123abc",
    ])
    mock_from_id.assert_called_once_with("123abc", full=True)
    mock_job.wait.assert_called_once_with(
        timeout=dt.timedelta.max,
        poll_interval=dt.timedelta(seconds=30),
        progress=mock.ANY)
    self.assertEqual(self.mock_print.call_count, 2)

    mock_from_id.reset_mock()
    mock_job.wait.reset_mock()
    self.mock_print.reset_mock()
    self.cli.run([
        "pinpoint",
        "watch",
        "123abc",
    ])
    mock_from_id.assert_called_once_with("123abc", full=True)
    mock_job.wait.assert_called_once_with(
        timeout=dt.timedelta.max,
        poll_interval=dt.timedelta(seconds=30),
        progress=mock.ANY)
    self.assertEqual(self.mock_print.call_count, 2)

  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_keyboard_interrupt(self, mock_from_id):
    mock_job = mock.MagicMock()
    mock_job.wait.side_effect = KeyboardInterrupt()
    mock_from_id.return_value = mock_job
    with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
      with self.assertRaises(SystemExit) as cm:
        self.cli.run(["pinpoint", "wait", "123abc"])
      self.assertEqual(cm.exception.code, 2)
      self.assertIn("Aborted waiting for job 123abc", mock_stderr.getvalue())

  def test_pinpoint_wait_invalid_timeout(self):
    with self.assertRaises(SystemExit):
      self.cli.run(["pinpoint", "wait", "123abc", "--timeout", "0s"])

  def test_pinpoint_wait_invalid_poll_interval(self):
    with self.assertRaises(SystemExit):
      self.cli.run(["pinpoint", "wait", "123abc", "--poll-interval", "0s"])

  def test_pinpoint_wait_on_progress(self):
    subcommand = PinpointWaitSubcommand(mock.MagicMock())
    job_info = PinpointJobInfo.from_json(_test_status_job_data())
    mock_spinner = mock.MagicMock()

    subcommand.on_progress(
        job_info, dt.timedelta(seconds=15), spinner=mock_spinner)
    mock_spinner.write.assert_called_once()
    self.assertIn("15.0s", mock_spinner.write.call_args[0][0])
    self.assertIn(job_info.status_display, mock_spinner.write.call_args[0][0])

    subcommand._spinner = mock_spinner
    subcommand.on_progress(job_info, dt.timedelta(seconds=20))
    self.assertEqual(mock_spinner.write.call_count, 2)
    self.assertIn("20.0s", mock_spinner.write.call_args[0][0])

    subcommand._spinner = None
    subcommand.on_progress(job_info, dt.timedelta(seconds=20))
    self.assertEqual(mock_spinner.write.call_count, 2)

  @mock.patch("logging.error")
  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_failed_logging_no_fail_flag(self, mock_from_id,
                                                     mock_logging_error):
    mock_job = mock.MagicMock()
    failed_data = _test_status_job_data(status="Failed")
    mock_job.wait.return_value = PinpointJobInfo.from_json(failed_data)
    mock_from_id.return_value = mock_job
    self.cli.run(["pinpoint", "wait", "123abc"])
    mock_logging_error.assert_called_once()
    self.assertIn("123abc", mock_logging_error.call_args[0][1])
    self.assertIn("failed", mock_logging_error.call_args[0][2].lower())

  @mock.patch("logging.error")
  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_failed_with_fail_flag(self, mock_from_id,
                                               mock_logging_error):
    mock_job = mock.MagicMock()
    failed_data = _test_status_job_data(status="Failed")
    mock_job.wait.return_value = PinpointJobInfo.from_json(failed_data)
    mock_from_id.return_value = mock_job
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "wait", "123abc", "--fail"])
    self.assertEqual(cm.exception.code, 1)
    mock_logging_error.assert_called_once()
    self.assertIn("123abc", mock_logging_error.call_args[0][1])
    self.assertIn("failed", mock_logging_error.call_args[0][2].lower())

  @mock.patch("logging.error")
  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_cancelled_with_fail_flag(self, mock_from_id,
                                                  mock_logging_error):
    mock_job = mock.MagicMock()
    cancelled_data = _test_status_job_data(status="Cancelled")
    mock_job.wait.return_value = PinpointJobInfo.from_json(cancelled_data)
    mock_from_id.return_value = mock_job
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "wait", "123abc", "--fail"])
    self.assertEqual(cm.exception.code, 1)
    mock_logging_error.assert_called_once()
    self.assertIn("123abc", mock_logging_error.call_args[0][1])
    self.assertIn("cancelled", mock_logging_error.call_args[0][2].lower())

  @mock.patch("logging.error")
  @mock.patch("crossbench.pinpoint.job_info.PinpointJobInfo.from_id")
  def test_pinpoint_wait_success_with_fail_flag(self, mock_from_id,
                                                mock_logging_error):
    mock_job = mock.MagicMock()
    completed_data = _test_status_job_data(status="Completed")
    mock_job.wait.return_value = PinpointJobInfo.from_json(completed_data)
    mock_from_id.return_value = mock_job
    self.cli.run(["pinpoint", "wait", "123abc", "--fail"])
    mock_logging_error.assert_not_called()

  @mock.patch("crossbench.plt.Platform.open_url")
  @mock.patch(
      "crossbench.plt.Platform.is_headless",
      new_callable=mock.PropertyMock,
      return_value=False)
  def test_pinpoint_show(self, _mock_is_headless, mock_open_url):
    self.cli.run(["pinpoint", "show", "123abc"])
    mock_open_url.assert_called_once_with(
        "https://pinpoint-dot-chromeperf.appspot.com/job/123abc")
    mock_open_url.reset_mock()
    self.cli.run(["pinpoint", "open", "123abc"])
    mock_open_url.assert_called_once_with(
        "https://pinpoint-dot-chromeperf.appspot.com/job/123abc")

    mock_open_url.reset_mock()
    mock_open_url.return_value = False
    with mock.patch("logging.warning") as mock_warning:
      self.cli.run(["pinpoint", "show", "123abc"])
      mock_warning.assert_called_once_with(
          "Failed to open browser for %s",
          "https://pinpoint-dot-chromeperf.appspot.com/job/123abc")

  @mock.patch("logging.warning")
  @mock.patch("crossbench.plt.Platform.open_url")
  @mock.patch(
      "crossbench.plt.Platform.is_headless",
      new_callable=mock.PropertyMock,
      return_value=True)
  def test_pinpoint_show_headless(self, _mock_is_headless, mock_open_url,
                                  mock_warning):
    self.cli.run(["pinpoint", "show", "123abc"])
    mock_open_url.assert_not_called()
    mock_warning.assert_called_once_with(
        "Cannot open browser in headless environment. Job URL: %s",
        "https://pinpoint-dot-chromeperf.appspot.com/job/123abc")

  def test_help_formatter(self):
    parser = argparse.ArgumentParser(
        formatter_class=PinpointHelpFormatter, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="action")
    subparsers.add_parser("list", help="Command")
    subparsers.add_parser("speedometer_main", help="Benchmark")

    help_text = parser.format_help()

    self.assertRegex(help_text, r"(?s)list.*Benchmarks:.*speedometer_main")

  def test_pinpoint_help_contains_bug_link(self):
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      with self.assertRaises(SystemExit) as cm:
        self.cli.run(["pinpoint", "--help"])
      self.assertEqual(cm.exception.code, 0)
      self.assertIn("https://issues.chromium.org/issues/new?component=1456889",
                    mock_stdout.getvalue())

  def test_pinpoint_subcommand_help_contains_bug_link(self):
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      with self.assertRaises(SystemExit) as cm:
        self.cli.run(["pinpoint", "start", "--help"])
      self.assertEqual(cm.exception.code, 0)
      self.assertIn("https://issues.chromium.org/issues/new?component=1456889",
                    mock_stdout.getvalue())

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_bug_id_alias(
      self,
      mock_parse_and_override,
      _mock_start_job,
  ):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
    )
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--bug-id=12345",
    ])
    self.assertEqual(mock_parse_and_override.call_args.kwargs["bug"], 12345)

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_patch_url_aliases(
      self,
      mock_parse_and_override,
      _mock_start_job,
  ):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
    )
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--base-patch-url=https://crrev.com/c/100",
        "--exp-patch-url=https://crrev.com/c/200",
    ])
    self.assertEqual(
        mock_parse_and_override.call_args.kwargs["base_patch"],
        "https://crrev.com/c/100",
    )
    self.assertEqual(
        mock_parse_and_override.call_args.kwargs["exp_patch"],
        "https://crrev.com/c/200",
    )

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_job_blink_features_alias(
      self,
      mock_parse_and_override,
      _mock_start_job,
  ):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
    )
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--blink-features=BlinkFeature1",
    ])
    self.assertEqual(
        mock_parse_and_override.call_args.kwargs["base_enable_blink_features"],
        "BlinkFeature1",
    )
    self.assertEqual(
        mock_parse_and_override.call_args.kwargs["exp_enable_blink_features"],
        "BlinkFeature1",
    )

  @mock.patch("crossbench.cli.subcommand.pinpoint.bisect_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointBisectJobConfig.parse_and_override")
  def test_pinpoint_bisect_job_bug_id_alias(
      self,
      mock_parse_and_override,
      _mock_bisect_job,
  ):
    test_config = PinpointBisectJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
        chart="my_chart",
    )
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        "pinpoint",
        "bisect",
        "--benchmark=speedometer3",
        "--chart=my_chart",
        "--bug-id=12345",
    ])
    self.assertEqual(mock_parse_and_override.call_args.kwargs["bug"], 12345)

  @mock.patch("crossbench.cli.subcommand.pinpoint.bisect_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointBisectJobConfig.parse_and_override")
  def test_pinpoint_bisect_job_blink_features_alias(
      self,
      mock_parse_and_override,
      _mock_bisect_job,
  ):
    test_config = PinpointBisectJobConfig(
        benchmark="speedometer3",
        bot="linux-r350-perf",
        chart="my_chart",
    )
    mock_parse_and_override.return_value = test_config

    self.cli.run([
        "pinpoint",
        "bisect",
        "--benchmark=speedometer3",
        "--chart=my_chart",
        "--blink-features=BlinkFeature1",
    ])
    self.assertEqual(
        mock_parse_and_override.call_args.kwargs["enable_blink_features"],
        "BlinkFeature1",
    )

  @mock.patch("crossbench.cli.subcommand.pinpoint.print_job_config")
  def test_pinpoint_config_job_flag(self, mock_print_job_config):
    self.cli.run(["pinpoint", "config", "--job", "123abc"])
    mock_print_job_config.assert_called_once_with(
        job_id="123abc",
        raw=False,
        full=False,
    )

  def test_pinpoint_config_missing_job(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "config"])
    self.assertEqual(cm.exception.code, 2)

  def test_pinpoint_config_positional_and_job_flag(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "config", "123abc", "--job", "456def"])
    self.assertEqual(cm.exception.code, 2)

  @mock.patch("crossbench.cli.subcommand.pinpoint.download_results")
  def test_pinpoint_results_job_flag(self, mock_download_results):
    self.cli.run(["pinpoint", "results", "--job", "123abc"])
    mock_download_results.assert_called_once_with(
        job_id="123abc",
        out_dir=None,
        force=False,
    )

  def test_pinpoint_results_missing_job(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "results"])
    self.assertEqual(cm.exception.code, 2)

  def test_pinpoint_results_positional_and_job_flag(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "results", "123abc", "--job", "456def"])
    self.assertEqual(cm.exception.code, 2)

  def test_pinpoint_cancel_invalid_job_id(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "cancel", "invalid_job_id"])
    self.assertEqual(cm.exception.code, 2)

  @mock.patch("crossbench.cli.subcommand.pinpoint.cancel_jobs")
  def test_pinpoint_cancel_duplicate_jobs(self, mock_cancel_jobs):
    self.cli.run(["pinpoint", "cancel", "123abc", "123abc"])
    mock_cancel_jobs.assert_called_once_with(
        job_ids=["123abc"],
        reason="Cancelled via Pinpoint CLI.",
    )

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_bots")
  def test_pinpoint_bots_unfiltered(self, mock_fetch_bots):
    mock_fetch_bots.return_value = ["linux-r350-perf", "win-11-perf"]
    self.cli.run(["pinpoint", "bots"])
    self.mock_print.assert_called_once_with("linux-r350-perf\nwin-11-perf")

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_benchmarks")
  def test_pinpoint_benchmarks_unfiltered(self, mock_fetch_benchmarks):
    mock_fetch_benchmarks.return_value = ["speedometer3", "jetstream2"]
    self.cli.run(["pinpoint", "benchmarks"])
    self.mock_print.assert_called_once_with("speedometer3\njetstream2")

  @mock.patch("crossbench.cli.subcommand.pinpoint.fetch_stories")
  def test_pinpoint_stories_unfiltered(self, mock_fetch_stories):
    mock_fetch_stories.return_value = ["story1", "story2"]
    self.cli.run(["pinpoint", "stories", "speedometer3"])
    mock_fetch_stories.assert_called_once_with("speedometer3")
    self.mock_print.assert_called_once_with("story1\nstory2")

  def test_pinpoint_stories_missing_benchmark(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "stories"])
    self.assertEqual(cm.exception.code, 2)

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list_details_flag(self, mock_list_job):
    self.cli.run(["pinpoint", "list", "--details"])
    mock_list_job.assert_called_once()
    extra_columns = mock_list_job.call_args.kwargs["extra_columns"]
    self.assertIsInstance(extra_columns, list)
    self.assertIn("bug", extra_columns)
    self.assertIn("story", extra_columns)

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list_details_and_extra_columns(self, mock_list_job):
    self.cli.run(["pinpoint", "list", "--details", "-c", "bug"])
    mock_list_job.assert_called_once()
    extra_columns = mock_list_job.call_args.kwargs["extra_columns"]
    self.assertIsInstance(extra_columns, list)
    self.assertIn("bug", extra_columns)
    self.assertIn("story", extra_columns)

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list_extra_columns_and_details(self, mock_list_job):
    self.cli.run(["pinpoint", "list", "-c", "bug", "--details"])
    mock_list_job.assert_called_once()
    extra_columns = mock_list_job.call_args.kwargs["extra_columns"]
    self.assertIsInstance(extra_columns, list)
    self.assertIn("bug", extra_columns)
    self.assertIn("story", extra_columns)

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list_default_and_extending_columns(self, mock_list_job):
    self.cli.run(["pinpoint", "list"])
    mock_list_job.assert_called_once()
    extra_columns = mock_list_job.call_args.kwargs["extra_columns"]
    self.assertIsNone(extra_columns)

    mock_list_job.reset_mock()
    self.cli.run(["pinpoint", "list", "-c", "bug"])
    mock_list_job.assert_called_once()
    extra_columns = mock_list_job.call_args.kwargs["extra_columns"]
    self.assertEqual(extra_columns, ["bug"])

  @mock.patch("crossbench.cli.subcommand.pinpoint.list_jobs")
  def test_pinpoint_list_url_source(self, mock_list_job):
    self.cli.run(["pinpoint", "list", "--url-source=leszek-perf"])
    mock_list_job.assert_called_once()
    self.assertEqual(mock_list_job.call_args.kwargs["url_source"],
                     UrlSource.LESZEK_PERF)

    mock_list_job.reset_mock()
    self.cli.run(["pinpoint", "list", "--url-source=leszek-perf-dev"])
    mock_list_job.assert_called_once()
    self.assertEqual(mock_list_job.call_args.kwargs["url_source"],
                     UrlSource.LESZEK_PERF_DEV)

    mock_list_job.reset_mock()
    self.cli.run(["pinpoint", "list", "--url-source=pinpoint-classic"])
    mock_list_job.assert_called_once()
    self.assertEqual(mock_list_job.call_args.kwargs["url_source"],
                     UrlSource.PINPOINT_CLASSIC)

  @mock.patch("crossbench.cli.subcommand.pinpoint.start_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointTryJobConfig.parse_and_override")
  def test_pinpoint_start_url_source(self, mock_parse_and_override,
                                     mock_start_job):
    test_config = PinpointTryJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf")
    mock_parse_and_override.return_value = test_config
    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--url-source=leszek-perf",
    ])
    mock_start_job.assert_called_once_with(
        test_config, url_source=UrlSource.LESZEK_PERF)

    mock_start_job.reset_mock()
    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--url-source=leszek-perf-dev",
    ])
    mock_start_job.assert_called_once_with(
        test_config, url_source=UrlSource.LESZEK_PERF_DEV)

    mock_start_job.reset_mock()
    self.cli.run([
        "pinpoint",
        "start",
        "--benchmark=speedometer3",
        "--url-source=pinpoint-classic",
    ])
    mock_start_job.assert_called_once_with(
        test_config, url_source=UrlSource.PINPOINT_CLASSIC)

  @mock.patch("crossbench.cli.subcommand.pinpoint.bisect_job")
  @mock.patch(
      "crossbench.pinpoint.config.PinpointBisectJobConfig.parse_and_override")
  def test_pinpoint_bisect_url_source(self, mock_parse_and_override,
                                      mock_bisect_job):
    test_config = PinpointBisectJobConfig(
        benchmark="speedometer3", bot="linux-r350-perf", chart="my_chart")
    mock_parse_and_override.return_value = test_config
    self.cli.run([
        "pinpoint",
        "bisect",
        "--benchmark=speedometer3",
        "--chart=my_chart",
        "--url-source=leszek-perf",
    ])
    mock_bisect_job.assert_called_once_with(
        test_config, url_source=UrlSource.LESZEK_PERF)

    mock_bisect_job.reset_mock()
    self.cli.run([
        "pinpoint",
        "bisect",
        "--benchmark=speedometer3",
        "--chart=my_chart",
        "--url-source=leszek-perf-dev",
    ])
    mock_bisect_job.assert_called_once_with(
        test_config, url_source=UrlSource.LESZEK_PERF_DEV)

    mock_bisect_job.reset_mock()
    self.cli.run([
        "pinpoint",
        "bisect",
        "--benchmark=speedometer3",
        "--chart=my_chart",
        "--url-source=pinpoint-classic",
    ])
    mock_bisect_job.assert_called_once_with(
        test_config, url_source=UrlSource.PINPOINT_CLASSIC)

  def test_pinpoint_invalid_url_source(self):
    with self.assertRaises(SystemExit) as cm:
      self.cli.run(["pinpoint", "list", "--url-source=invalid"])
    self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
