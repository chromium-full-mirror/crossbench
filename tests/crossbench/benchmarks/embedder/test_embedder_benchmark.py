# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from unittest import mock

from crossbench.benchmarks.embedder.config.cujs import CUJsConfig
from crossbench.benchmarks.embedder.embedder_benchmark import \
    EmbedderBenchmark, EmbedderStory
from crossbench.cli.parser import CBArgumentParser
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class EmbedderBenchmarkTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    cuj_data = {
        "cujs": {
            "agsa-notification": [{
                "action": "wait",
                "duration": "15s",
            }],
        },
    }
    self.cujs_config = CUJsConfig.parse(cuj_data)
    self.story = EmbedderStory(
        name=self.cujs_config.cujs[0].label,
        actions=self.cujs_config.cujs[0].blocks,
    )

  def _parse_cli(self, *cli_args: str) -> argparse.Namespace:
    parser = CBArgumentParser()
    EmbedderBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(cli_args)
    args.config = None
    if not args.cujs_config:
      args.cujs_config = self.cujs_config
    return args

  def _benchmark_from_cli(self, *cli_args: str) -> EmbedderBenchmark:
    args = self._parse_cli(*cli_args)
    benchmark = EmbedderBenchmark.from_cli_args(args)
    self.assertIsInstance(benchmark, EmbedderBenchmark)
    assert isinstance(benchmark, EmbedderBenchmark)
    return benchmark

  def test_default_cli_args(self) -> None:
    benchmark = self._benchmark_from_cli()
    self.assertEqual(benchmark.android_action, "GOOGLE_SEARCH")
    self.assertEqual(benchmark.android_activity, "SearchActivity")
    self.assertEqual(dict(benchmark.android_extras), {})
    self.assertFalse(benchmark.embedder_drop_caches)

  def test_cli_android_action_and_extras(self) -> None:
    benchmark = self._benchmark_from_cli(
        "--android-action=android.intent.action.WEB_SEARCH",
        "--android-extras=query=weather",
        "--android-extra=source:notification",
    )
    self.assertEqual(benchmark.android_action,
                     "android.intent.action.WEB_SEARCH")
    self.assertEqual(
        dict(benchmark.android_extras),
        {
            "query": "weather",
            "source": "notification",
        },
    )

  def test_cli_android_extras_abbrev(self) -> None:
    benchmark = self._benchmark_from_cli(
        "--android-extras=query:weather",
        "--android-extra=url=https://example.com?q=weather",
        "--android-extr=extra_key:extra_val",
    )
    self.assertEqual(
        dict(benchmark.android_extras),
        {
            "query": "weather",
            "url": "https://example.com?q=weather",
            "extra_key": "extra_val",
        },
    )

  def test_parse_android_extra(self) -> None:
    self.assertEqual(
        EmbedderBenchmark.parse_android_extra("query=weather"),
        ("query", "weather"),
    )
    self.assertEqual(
        EmbedderBenchmark.parse_android_extra("query:weather"),
        ("query", "weather"),
    )
    self.assertEqual(
        EmbedderBenchmark.parse_android_extra(
            "url=https://example.com?q=weather"),
        ("url", "https://example.com?q=weather"),
    )
    self.assertEqual(
        EmbedderBenchmark.parse_android_extra("empty_val="),
        ("empty_val", ""),
    )

  def test_invalid_android_extras(self) -> None:
    for invalid_extra in ("", "missing_separator", "=missing_key",
                          ":missing_key"):
      with self.subTest(invalid_extra=invalid_extra):
        with self.assertRaises(argparse.ArgumentTypeError):
          EmbedderBenchmark.parse_android_extra(invalid_extra)
        with self.assertRaises(argparse.ArgumentError):
          self._parse_cli(f"--android-extras={invalid_extra}")
        with self.assertRaises(argparse.ArgumentTypeError):
          EmbedderBenchmark(
              stories=[self.story],
              android_extras=[invalid_extra],
          )
    with self.assertRaises(argparse.ArgumentTypeError):
      EmbedderBenchmark(
          stories=[self.story],
          android_extras={"": "missing_key"},
      )

  def test_duplicate_android_extras(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Duplicate --android-extras key: 'query'"):
      self._benchmark_from_cli(
          "--android-extras=query=weather",
          "--android-extra=query:news",
      )
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Duplicate --android-extras key: 'query'"):
      EmbedderBenchmark(
          stories=[self.story],
          android_extras=["query=weather", "query=news"],
      )

  def test_story_setup_default(self) -> None:
    benchmark = EmbedderBenchmark(stories=[self.story])
    run = mock.MagicMock()
    run.benchmark = benchmark
    run.browser.android_package = "com.google.android.googlequicksearchbox"

    self.story.setup(run)

    run.browser_platform.sh.assert_called_once_with(
        "am",
        "start",
        "-S",
        "-W",
        "-n",
        "com.google.android.googlequicksearchbox/.SearchActivity",
        "-a",
        "com.google.android.googlequicksearchbox.GOOGLE_SEARCH",
    )

  def test_story_setup_web_search_with_extras(self) -> None:
    benchmark = EmbedderBenchmark(
        stories=[self.story],
        android_action="android.intent.action.WEB_SEARCH",
        android_extras=["query=weather"],
        embedder_drop_caches=True,
    )
    run = mock.MagicMock()
    run.benchmark = benchmark
    run.browser.android_package = "com.google.android.googlequicksearchbox"

    self.story.setup(run)

    run.browser.adb_force_stop.assert_called_once_with()
    run.browser_platform.clear_memory_page_cache.assert_called_once_with()
    self.assertEqual(
        run.browser_platform.sh.call_args_list,
        [
            mock.call("am", "kill-all"),
            mock.call(
                "am",
                "start",
                "-S",
                "-W",
                "-n",
                "com.google.android.googlequicksearchbox/.SearchActivity",
                "-a",
                "android.intent.action.WEB_SEARCH",
                "-e",
                "query",
                "weather",
            ),
        ],
    )

  def test_story_setup_empty_action_and_full_activity(self) -> None:
    benchmark = EmbedderBenchmark(
        stories=[self.story],
        android_action="",
        android_activity="com.google.android.search.core.google.GoogleSearch",
    )
    run = mock.MagicMock()
    run.benchmark = benchmark
    run.browser.android_package = "com.google.android.googlequicksearchbox"

    self.story.setup(run)

    run.browser_platform.sh.assert_called_once_with(
        "am",
        "start",
        "-S",
        "-W",
        "-n",
        "com.google.android.googlequicksearchbox/"
        "com.google.android.search.core.google.GoogleSearch",
    )


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
