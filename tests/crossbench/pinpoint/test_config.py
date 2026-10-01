# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from typing import Final
from unittest import mock

from crossbench.cli.config.flags import FlagsConfig
from crossbench.pinpoint.config import BisectEndVariantConfig, \
    BisectStartVariantConfig, PinpointBisectJobConfig, PinpointTryJobConfig, \
    VariantConfig
from crossbench.pinpoint.list_builds import Build
from tests import test_helper
from tests.crossbench.pinpoint.http_requests_mixin import MockHttpRequestsMixin

_TEST_PATCH: Final[
    str] = "https://chromium-review.googlesource.com/c/crossbench/+/12345"
_TEST_PATCH2: Final[
    str] = "https://chromium-review.googlesource.com/c/crossbench/+/111/2"
_TEST_RECENT_COMMIT: Final[str] = "aaaabbbb"


class VariantConfigTest(MockHttpRequestsMixin):
  _get_auth_session_patch_target = "crossbench.pinpoint.auth.get_auth_session"

  def setUp(self):
    super().setUp()
    self.mock_fetch_builds = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_builds"))
    self.mock_fetch_builds.return_value = [
        Build(commit=_TEST_RECENT_COMMIT, number=1, date="2025-11-01 00:00:00"),
    ]

  def test_parse_variant(self):
    variant = VariantConfig.parse(
        json.dumps({
            "commit": "abcd1234",
            "patch": _TEST_PATCH,
            "flags": "--test-flag --js-flags=--base-js-flag",
        }))
    self.assertEqual(variant.commit, "abcd1234")
    self.assertEqual(variant.patch, _TEST_PATCH)
    self.assertDictEqual(variant.flags_as_dict(), {
        "--test-flag": None,
        "--js-flags": "--base-js-flag",
    })

  def test_parse_variant_default(self):
    variant = VariantConfig.parse("{}")
    self.assertEqual(variant.commit, "recent")
    self.assertIsNone(variant.patch)
    self.assertIsNone(variant.flags_as_str())
    self.assertDictEqual(variant.flags_as_dict(), {})

  def test_parse_commit(self):
    self.assertEqual(VariantConfig.parse_commit("HEAD"), "HEAD")
    self.assertEqual(VariantConfig.parse_commit("-HEAD"), "HEAD")
    self.assertEqual(VariantConfig.parse_commit(""), "HEAD")
    self.assertEqual(VariantConfig.parse_commit("recent"), "recent")
    self.assertEqual(VariantConfig.parse_commit("abcdef00"), "abcdef00")
    self.assertEqual(VariantConfig.parse_commit("1234ABCD"), "1234abcd")
    with self.assertRaises(ValueError):
      VariantConfig.parse_commit("invalid")
    with self.assertRaises(ValueError):
      VariantConfig.parse_commit("1234567")
    with self.assertRaises(ValueError):
      VariantConfig.parse_commit("1" * 41)

  def test_parse_patch(self):
    self.assertEqual(VariantConfig.parse_patch(_TEST_PATCH), _TEST_PATCH)

    with self.assertRaises(ValueError):
      VariantConfig.parse_patch("invalid")

  def test_override_commit(self):
    config = VariantConfig()
    config = config.override_commit("abcdef00", bot="test_bot")
    self.assertEqual(config.commit, "abcdef00")

    config = config.override_commit(None, bot="test_bot")
    self.assertEqual(config.commit, "abcdef00")

    config = config.override_commit("recent", bot="test_bot")
    self.assertEqual(config.commit, _TEST_RECENT_COMMIT)
    self.mock_fetch_builds.assert_called_once_with("test_bot")

  def test_override_patch(self):
    config = VariantConfig()
    config = config.override_patch(_TEST_PATCH)
    self.assertEqual(config.patch, _TEST_PATCH)

    config = config.override_patch(None)
    self.assertEqual(config.patch, _TEST_PATCH)

  def test_override_empty_flags(self):
    config = VariantConfig()
    config = config.override_flags(
        js_flags="--js-flag1,--js-flag2",
        enable_features="enablefeature1,enablefeature2",
        disable_features="disablefeature1,disablefeature2")
    self.assertDictEqual(
        config.flags_as_dict(), {
            "--js-flags": "--js-flag1,--js-flag2",
            "--enable-features": "enablefeature1,enablefeature2",
            "--disable-features": "disablefeature1,disablefeature2",
        })

  def test_override_blink_features(self):
    config = VariantConfig()
    config = config.override_flags(
        enable_blink_features="BlinkFeat1,BlinkFeat2",
        disable_blink_features="BlinkFeat3,BlinkFeat4")
    self.assertDictEqual(
        config.flags_as_dict(), {
            "--enable-blink-features": "BlinkFeat1,BlinkFeat2",
            "--disable-blink-features": "BlinkFeat3,BlinkFeat4",
        })

  def test_override_existing_flags(self):
    config = VariantConfig.parse(
        "{flags: '--standalone --js-flags=--js-flag0 "
        "--enable-features=enablefeature0 --disable-features=disablefeature0'}")
    config = config.override_flags(
        js_flags="--js-flag1,--js-flag2",
        enable_features="enablefeature1,enablefeature2",
        disable_features="disablefeature1,disablefeature2")
    self.assertDictEqual(
        config.flags_as_dict(), {
            "--standalone": None,
            "--js-flags": "--js-flag1,--js-flag2",
            "--enable-features": "enablefeature1,enablefeature2",
            "--disable-features": "disablefeature1,disablefeature2",
        })

  def test_override_with_none_flags(self):
    config = VariantConfig.parse(
        "{flags: '--standalone --js-flags=--js-flag0 "
        "--enable-features=enablefeature0 --disable-features=disablefeature0'}")
    config = config.override_flags()
    self.assertDictEqual(
        config.flags_as_dict(), {
            "--standalone": None,
            "--js-flags": "--js-flag0",
            "--enable-features": "enablefeature0",
            "--disable-features": "disablefeature0",
        })

  def test_override_generic_flags(self):
    config = VariantConfig()
    config = config.override_flags(flags="--no-sandbox --disable-gpu")
    self.assertDictEqual(config.flags_as_dict(), {
        "--no-sandbox": None,
        "--disable-gpu": None,
    })

  def test_override_generic_and_specific_flags(self):
    config = VariantConfig()
    config = config.override_flags(
        flags="--no-sandbox --js-flags=--old",
        js_flags="--new",
        enable_features="feature1",
    )
    self.assertDictEqual(
        config.flags_as_dict(), {
            "--no-sandbox": None,
            "--js-flags": "--new",
            "--enable-features": "feature1",
        })


class PinpointTryJobConfigTest(MockHttpRequestsMixin):
  _get_auth_session_patch_target = "crossbench.pinpoint.auth.get_auth_session"

  def setUp(self):
    super().setUp()
    self.mock_fetch_benchmarks = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_benchmarks"))
    self.mock_fetch_benchmarks.return_value = ["test_benchmark"]
    self.mock_fetch_bots = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_bots"))
    self.mock_fetch_bots.return_value = ["test_bot"]
    self.mock_fetch_stories = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_stories"))
    self.mock_fetch_stories.return_value = ["test_story"]
    self.mock_fetch_builds = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_builds"))
    self.mock_fetch_builds.return_value = [
        Build(commit=_TEST_RECENT_COMMIT, number=1, date="2025-11-02 00:00:00"),
    ]
    self.mock_show_warnings = self.enterContext(
        mock.patch("crossbench.pinpoint.config.show_warnings"))

    self.response_dict = {
        "comparison_mode": "try",
        "job_id": "1234567890",
        "arguments": {
            "comparison_mode": "try",
            "target": "performance_test_suite",
            "base_git_hash": "HEAD",
            "end_git_hash": "HEAD",
            "initial_attempt_count": "20",
            "configuration": "win-11-perf",
            "benchmark": "speedometer3",
            "story": "Speedometer3",
            "story_tags": "",
            "chart": "",
            "extra_test_args": "",
            "commit": "on,on",
            "base_patch": "",
            "experiment_patch": "",
            "base_extra_args": "",
            "experiment_extra_args": "",
            "project": "",
            "bug_id": "",
            "batch_id": "",
        },
        "name": "Try job on win-11-perf/speedometer3",
    }

  def test_parse_minimal_config(self):
    config = PinpointTryJobConfig.parse_and_override(
        config=json.dumps({
            "benchmark": "test_benchmark",
            "bot": "test_bot",
            "story": "test_story",
        }))
    self.assertEqual(
        config,
        PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            base=VariantConfig(commit=_TEST_RECENT_COMMIT),
            experiment=VariantConfig(commit=_TEST_RECENT_COMMIT),
        ))

  def test_parse_all_fields(self):
    config = PinpointTryJobConfig.parse_and_override(
        config=json.dumps({
            "benchmark": "test_benchmark",
            "bot": "test_bot",
            "story": "test_story",
            "story_tags": "tag1,tag2",
            "repeat": 42,
            "bug": 67890,
            "base": {
                "commit": "abcdef00",
                "patch": _TEST_PATCH,
                "flags": "--js-flags=--base-js-flag",
            },
            "experiment": {
                "commit": _TEST_RECENT_COMMIT,
                "patch": _TEST_PATCH2,
                "flags": "--js-flags=--exp-js-flag",
            },
        }))
    self.assertEqual(
        config,
        PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            story_tags="tag1,tag2",
            repeat=42,
            bug=67890,
            base=VariantConfig(
                commit="abcdef00",
                patch=_TEST_PATCH,
                flags=FlagsConfig.parse("--js-flags=--base-js-flag"),
            ),
            experiment=VariantConfig(
                commit=_TEST_RECENT_COMMIT,
                patch=_TEST_PATCH2,
                flags=FlagsConfig.parse("--js-flags=--exp-js-flag"),
            )))

  def test_override_all_fields(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        story_tags="tag1,tag2",
        repeat=42,
        bug=67890,
        base_commit="abcdef00",
        exp_commit="12345678",
        base_patch=_TEST_PATCH,
        exp_patch=_TEST_PATCH2,
        base_js_flags="--base-js-flag",
        exp_js_flags="--exp-js-flag",
        base_enable_features="enable1,enable2",
        exp_enable_features="enable3,enable4",
        base_disable_features="disable1,disable2",
        exp_disable_features="disable3,disable4",
    )
    self.assertEqual(
        config,
        PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            story_tags="tag1,tag2",
            repeat=42,
            bug=67890,
            base=VariantConfig(
                commit="abcdef00",
                patch=_TEST_PATCH,
                flags=FlagsConfig.parse("--js-flags=--base-js-flag "
                                        "--enable-features=enable1,enable2 "
                                        "--disable-features=disable1,disable2"),
            ),
            experiment=VariantConfig(
                commit="12345678",
                patch=_TEST_PATCH2,
                flags=FlagsConfig.parse("--js-flags=--exp-js-flag "
                                        "--enable-features=enable3,enable4 "
                                        "--disable-features=disable3,disable4"),
            )))

  def test_parse_and_override_missing_benchmark(self):
    with self.assertRaises(ValueError) as cm:
      PinpointTryJobConfig.parse_and_override(config="{bot: 'test_bot'}")
    self.assertIn(
        "Benchmark is required. "
        "Run 'cb pp benchmarks' to list all available benchmarks.",
        str(cm.exception),
    )
    with self.assertRaises(ValueError) as cm:
      PinpointTryJobConfig.parse_and_override(bot="test_bot")
    self.assertIn(
        "Benchmark is required. "
        "Run 'cb pp benchmarks' to list all available benchmarks.",
        str(cm.exception),
    )

  def test_parse_and_override_missing_bot(self):
    with self.assertRaises(ValueError) as cm:
      PinpointTryJobConfig.parse_and_override(
          config="{benchmark: 'test_benchmark'}")
    self.assertIn("Bot is required. Run 'cb pp bots'", str(cm.exception))
    with self.assertRaises(ValueError) as cm:
      PinpointTryJobConfig.parse_and_override(benchmark="test_benchmark")
    self.assertIn("Bot is required. Run 'cb pp bots'", str(cm.exception))

  def test_parse_and_override_missing_story_and_tags(self):
    self.mock_fetch_stories.return_value = []
    with self.assertRaises(ValueError):
      PinpointTryJobConfig.parse_and_override(
          benchmark="test_benchmark", bot="test_bot")

  def test_to_request_dict(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        story_tags="tag1,tag2",
        repeat=42,
        bug=12345,
        base_commit="abcdef00",
        exp_commit="12345678",
        base_patch=_TEST_PATCH,
        exp_patch=_TEST_PATCH2,
        base_js_flags="--base-js-flag",
        exp_js_flags="--exp-js-flag",
        base_enable_features="enable1,enable2",
        exp_enable_features="enable3,enable4",
        base_disable_features="disable1,disable2",
        exp_disable_features="disable3,disable4",
    )
    self.assertDictEqual(
        config.to_request_dict(), {
            "comparison_mode": "try",
            "benchmark": "test_benchmark",
            "configuration": "test_bot",
            "story": "test_story",
            "story_tags": "tag1,tag2",
            "initial_attempt_count": 42,
            "bug_id": 12345,
            "base_git_hash": "abcdef00",
            "end_git_hash": "12345678",
            "base_patch": _TEST_PATCH,
            "experiment_patch": _TEST_PATCH2,
            "base_extra_args":
                '--extra-browser-args="--js-flags=--base-js-flag '
                '--enable-features=enable1,enable2 '
                '--disable-features=disable1,disable2"',
            "experiment_extra_args":
                '--extra-browser-args="--js-flags=--exp-js-flag '
                '--enable-features=enable3,enable4 '
                '--disable-features=disable3,disable4"',
            "tags": '{"origin": "pinpoint_cli"}',
        })

  def test_to_request_dict_blink_features(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        base_enable_blink_features="BlinkFeat1,BlinkFeat2",
        exp_enable_blink_features="BlinkFeat3,BlinkFeat4",
        base_disable_blink_features="BlinkFeat5,BlinkFeat6",
        exp_disable_blink_features="BlinkFeat7,BlinkFeat8",
    )
    self.assertDictEqual(
        config.to_request_dict(), {
            "comparison_mode": "try",
            "benchmark": "test_benchmark",
            "configuration": "test_bot",
            "story": "test_story",
            "story_tags": None,
            "initial_attempt_count": 30,
            "bug_id": None,
            "base_git_hash": _TEST_RECENT_COMMIT,
            "end_git_hash": _TEST_RECENT_COMMIT,
            "base_patch": None,
            "experiment_patch": None,
            "base_extra_args":
                '--extra-browser-args="--enable-blink-features='
                'BlinkFeat1,BlinkFeat2 '
                '--disable-blink-features=BlinkFeat5,BlinkFeat6"',
            "experiment_extra_args":
                '--extra-browser-args="--enable-blink-features='
                'BlinkFeat3,BlinkFeat4 '
                '--disable-blink-features=BlinkFeat7,BlinkFeat8"',
            "tags": '{"origin": "pinpoint_cli"}',
        })

  def test_to_request_dict_with_generic_flags(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        base_commit="abcdef00",
        exp_commit="12345678",
        base_flags="--no-sandbox",
        exp_flags="--disable-gpu",
    )
    self.assertEqual(config.to_request_dict()["base_extra_args"],
                     '--extra-browser-args="--no-sandbox"')
    self.assertEqual(config.to_request_dict()["experiment_extra_args"],
                     '--extra-browser-args="--disable-gpu"')

  def test_to_request_dict_no_flags(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
    )
    self.assertDictEqual(
        config.to_request_dict(), {
            "comparison_mode": "try",
            "benchmark": "test_benchmark",
            "configuration": "test_bot",
            "story": "test_story",
            "story_tags": None,
            "initial_attempt_count": 30,
            "bug_id": None,
            "base_git_hash": _TEST_RECENT_COMMIT,
            "end_git_hash": _TEST_RECENT_COMMIT,
            "base_patch": None,
            "experiment_patch": None,
            "base_extra_args": None,
            "experiment_extra_args": None,
            "tags": '{"origin": "pinpoint_cli"}',
        })

  def test_parse_and_override_recent_commit(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        base_commit="recent",
        exp_commit="recent")
    self.assertEqual(config.base.commit, _TEST_RECENT_COMMIT)
    self.assertEqual(config.experiment.commit, _TEST_RECENT_COMMIT)
    self.mock_fetch_builds.assert_called_with("test_bot")

  def test_parse_and_override_empty_commit_to_recent_hash(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        base_commit="",
        exp_commit="")
    self.assertEqual(config.base.commit, _TEST_RECENT_COMMIT)
    self.assertEqual(config.experiment.commit, _TEST_RECENT_COMMIT)

  def test_parse_and_override_story_auto_fetch_signle_story(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark", bot="test_bot")
    self.assertEqual(config.story, "test_story")
    self.mock_fetch_stories.assert_called_once_with("test_benchmark")

  def test_parse_and_override_story_auto_fetch_multiple_stories(self):
    self.mock_fetch_stories.return_value = ["story1", "story2"]
    with self.assertRaises(ValueError):
      PinpointTryJobConfig.parse_and_override(
          benchmark="test_benchmark", bot="test_bot")
    self.mock_fetch_stories.assert_called_once_with("test_benchmark")

  def test_parse_and_override_story_auto_fetch_no_story(self):
    self.mock_fetch_stories.return_value = []
    with self.assertRaises(ValueError):
      PinpointTryJobConfig.parse_and_override(
          benchmark="test_benchmark", bot="test_bot")
    self.mock_fetch_stories.assert_called_once_with("test_benchmark")

  def test_parse_and_override_empty_benchmarks_fails(self):
    self.mock_fetch_benchmarks.side_effect = ValueError(
        "Could not fetch benchmarks from Pinpoint: empty list received.")
    with self.assertRaises(ValueError) as cm:
      PinpointTryJobConfig.parse_and_override(
          benchmark="test_benchmark", bot="test_bot", story="test_story")
    self.assertIn("Could not fetch benchmarks from Pinpoint", str(cm.exception))

  def test_parse_and_override_unknown_benchmark_show_warning(self):
    self.mock_fetch_benchmarks.return_value = ["other_benchmark"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark", bot="test_bot", story="test_story")
    self.mock_show_warnings.assert_called_once_with([
        "Invalid benchmark: 'test_benchmark'. Did you mean 'other_benchmark'?\n"
        "Run 'cb pp benchmarks' to list all available benchmarks.",
    ])

  def test_parse_and_override_unknown_benchmark_no_match_show_warning(self):
    self.mock_fetch_benchmarks.return_value = ["something_else"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="x", bot="test_bot", story="test_story")
    self.mock_show_warnings.assert_called_once_with([
        "Invalid benchmark: 'x'. Choices are something_else\n"
        "Run 'cb pp benchmarks' to list all available benchmarks.",
    ])

  def test_parse_and_override_unknown_bot_show_warning(self):
    self.mock_fetch_bots.return_value = ["other_bot"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark", bot="test_bot", story="test_story")
    self.mock_show_warnings.assert_called_once_with([
        "Invalid bot: 'test_bot'. Did you mean 'other_bot'?\n"
        "Run 'cb pp bots' to list all available bots.",
    ])

  def test_parse_and_override_unknown_bot_no_match_show_warning(self):
    self.mock_fetch_bots.return_value = ["something_else"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark", bot="x", story="test_story")
    self.mock_show_warnings.assert_called_once_with([
        "Invalid bot: 'x'. Choices are something_else\n"
        "Run 'cb pp bots' to list all available bots.",
    ])

  def test_parse_and_override_unknown_story_show_warning(self):
    self.mock_fetch_stories.return_value = ["other_story"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="test_benchmark", bot="test_bot", story="test_story")
    self.mock_show_warnings.assert_called_once_with(
        ["Unknown story: test_story"])

  def test_parse_and_override_crossbench_benchmark_no_warning(self):
    self.mock_fetch_benchmarks.return_value = ["speedometer3.0.crossbench"]
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="speedometer3.0.crossbench", bot="test_bot")
    self.mock_show_warnings.assert_called_once_with([])
    self.assertEqual(config.story, "default")

  def test_parse_and_override_crossbench_benchmark_not_on_server(self):
    self.mock_fetch_benchmarks.return_value = ["speedometer3"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="jetstream3.crossbench", bot="test_bot")
    self.mock_show_warnings.assert_called_once_with([
        "Invalid benchmark: 'jetstream3.crossbench'. Choices are speedometer3\n"
        "Run 'cb pp benchmarks' to list all available benchmarks.",
    ])

  def test_parse_and_override_crossbench_benchmark_valid_story(self):
    self.mock_fetch_benchmarks.return_value = ["speedometer3.0.crossbench"]
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="speedometer3.0.crossbench",
        bot="test_bot",
        story="TodoMVC-JavaScript-ES5")
    self.mock_show_warnings.assert_called_once_with([])
    self.assertEqual(config.story, "TodoMVC-JavaScript-ES5")

  def test_parse_and_override_crossbench_benchmark_invalid_story(self):
    self.mock_fetch_benchmarks.return_value = ["speedometer3.0.crossbench"]
    PinpointTryJobConfig.parse_and_override(
        benchmark="speedometer3.0.crossbench",
        bot="test_bot",
        story="invalid_story")
    self.mock_show_warnings.assert_called_once_with(
        ["Unknown story: invalid_story"])

  def test_parser_raw_config_minimal(self):
    config = PinpointTryJobConfig.from_response_dict(self.response_dict)
    expectation = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="win-11-perf",
        story="Speedometer3",
        story_tags=None,
        repeat=20,
        bug=None,
        base=VariantConfig(commit="HEAD"),
        experiment=VariantConfig(commit="HEAD"),
    )
    self.assertEqual(config, expectation)
    self.assertEqual(config.parse_and_override(config.to_dict()), expectation)

  def test_parser_raw_config(self):
    arguments = self.response_dict["arguments"]
    arguments["base_git_hash"] = "abcdef00"
    arguments["end_git_hash"] = "1234abcd"
    arguments["story_tags"] = "tag1,tag2"
    arguments["bug_id"] = 12345
    arguments["base_patch"] = _TEST_PATCH
    arguments["experiment_patch"] = _TEST_PATCH2
    arguments[
        "base_extra_args"] = '--extra-browser-args="--js-flags=--base-js-flag"'
    arguments["experiment_extra_args"] = (
        '--extra-browser-args="--js-flags=--exp-js-flag"')

    config = PinpointTryJobConfig.from_response_dict(self.response_dict)
    expectation = PinpointTryJobConfig(
        benchmark="speedometer3",
        bot="win-11-perf",
        story="Speedometer3",
        story_tags="tag1,tag2",
        repeat=20,
        bug=12345,
        base=VariantConfig(
            commit="abcdef00",
            patch=_TEST_PATCH,
            flags=FlagsConfig.parse("--js-flags=--base-js-flag"),
        ),
        experiment=VariantConfig(
            commit="1234abcd",
            patch=_TEST_PATCH2,
            flags=FlagsConfig.parse("--js-flags=--exp-js-flag"),
        ),
    )
    self.assertEqual(config, expectation)
    self.assertEqual(config.parse_and_override(config.to_dict()), expectation)

  def test_parser_raise_if_not_try_job(self):
    self.response_dict["comparison_mode"] = "bisect"
    with self.assertRaises(ValueError):
      PinpointTryJobConfig.from_response_dict(self.response_dict)

  def test_no_extra_browser_args_for_crossbench(self):
    config = PinpointTryJobConfig.parse_and_override(
        benchmark="speedometer3.0.crossbench",
        bot="win-11-perf",
        story="default",
        base_js_flags="--base-js-flag",
        exp_js_flags="--exp-js-flag",
        base_enable_features="--base-enabled-feature",
        exp_enable_features="--exp-enabled-feature",
        base_disable_features="--base-disabled-feature",
        exp_disable_features="--exp-disabled-feature",
    )
    request_dict = config.to_request_dict()
    self.assertEqual(
        request_dict, {
            "comparison_mode": "try",
            "benchmark": "speedometer3.0.crossbench",
            "configuration": "win-11-perf",
            "story": "default",
            "story_tags": None,
            "initial_attempt_count": 30,
            "bug_id": None,
            "base_git_hash": "aaaabbbb",
            "end_git_hash": "aaaabbbb",
            "base_patch": None,
            "experiment_patch": None,
            "base_extra_args": "--js-flags=--base-js-flag "
                               "--enable-features=--base-enabled-feature "
                               "--disable-features=--base-disabled-feature",
            "experiment_extra_args":
                "--js-flags=--exp-js-flag "
                "--enable-features=--exp-enabled-feature "
                "--disable-features=--exp-disabled-feature",
            "tags": '{"origin": "pinpoint_cli"}',
        })


class PinpointBisectJobConfigTest(MockHttpRequestsMixin):
  _get_auth_session_patch_target = "crossbench.pinpoint.auth.get_auth_session"

  def setUp(self):
    super().setUp()
    self.mock_fetch_benchmarks = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_benchmarks"))
    self.mock_fetch_benchmarks.return_value = ["test_benchmark"]
    self.mock_fetch_bots = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_bots"))
    self.mock_fetch_bots.return_value = ["test_bot"]
    self.mock_fetch_stories = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_stories"))
    self.mock_fetch_stories.return_value = ["test_story"]
    self.mock_fetch_builds = self.enterContext(
        mock.patch("crossbench.pinpoint.config.fetch_builds"))
    self.mock_fetch_builds.return_value = [
        Build(commit=_TEST_RECENT_COMMIT, number=1, date="2025-11-02 00:00:00"),
    ]
    self.mock_show_warnings = self.enterContext(
        mock.patch("crossbench.pinpoint.config.show_warnings"))

  def test_parse_minimal_config(self):
    config = PinpointBisectJobConfig.parse_and_override(
        config=json.dumps({
            "benchmark": "test_benchmark",
            "bot": "test_bot",
            "story": "test_story",
            "chart": "test_chart",
        }))
    self.assertEqual(
        config,
        PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            chart="test_chart",
            start=BisectStartVariantConfig(commit=_TEST_RECENT_COMMIT),
            end=BisectEndVariantConfig(commit=_TEST_RECENT_COMMIT),
        ))

  def test_parse_all_fields(self):
    config = PinpointBisectJobConfig.parse_and_override(
        config=json.dumps({
            "benchmark": "test_benchmark",
            "bot": "test_bot",
            "story": "test_story",
            "chart": "test_chart",
            "story_tags": "tag1,tag2",
            "repeat": 42,
            "bug": 67890,
            "start": {
                "commit": "abcdef00",
                "flags": "--js-flags=--start-js-flag",
            },
            "end": {
                "commit": _TEST_RECENT_COMMIT,
            },
        }))
    self.assertEqual(
        config,
        PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            chart="test_chart",
            story_tags="tag1,tag2",
            repeat=42,
            bug=67890,
            start=BisectStartVariantConfig(
                commit="abcdef00",
                flags=FlagsConfig.parse("--js-flags=--start-js-flag"),
            ),
            end=BisectEndVariantConfig(commit=_TEST_RECENT_COMMIT)))

  def test_override_all_fields(self):
    config = PinpointBisectJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        chart="test_chart",
        story_tags="tag1,tag2",
        repeat=42,
        bug=67890,
        start_commit="abcdef00",
        end_commit="12345678",
        js_flags="--start-js-flag",
        enable_features="enable1,enable2",
        disable_features="disable1,disable2",
    )
    self.assertEqual(
        config,
        PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            story="test_story",
            chart="test_chart",
            story_tags="tag1,tag2",
            repeat=42,
            bug=67890,
            start=BisectStartVariantConfig(
                commit="abcdef00",
                flags=FlagsConfig.parse("--js-flags=--start-js-flag "
                                        "--enable-features=enable1,enable2 "
                                        "--disable-features=disable1,disable2"),
            ),
            end=BisectEndVariantConfig(commit="12345678")))

  def test_override_generic_flags(self):
    config = PinpointBisectJobConfig.parse_and_override(
        benchmark="test_benchmark",
        bot="test_bot",
        story="test_story",
        chart="test_chart",
        start_commit="abcdef00",
        end_commit="12345678",
        flags="--no-sandbox",
    )
    self.assertEqual(config.to_request_dict()["extra_test_args"],
                     '--extra-browser-args="--no-sandbox"')


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
