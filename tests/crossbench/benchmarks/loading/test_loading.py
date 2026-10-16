# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import unittest
from typing import Any, Sequence
from unittest import mock

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.base import ActionRunner
from crossbench.benchmarks.loading.config.blocks import ActionBlock, \
    ActionBlockListConfig
from crossbench.benchmarks.loading.config.login.google import GOOGLE_LOGIN_URL
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark, \
    LoadingPageFilter
from crossbench.benchmarks.loading.page.combined import CombinedPage
from crossbench.benchmarks.loading.page.interactive import InteractivePage
from crossbench.benchmarks.loading.page.live import PAGE_LIST, \
    PAGE_LIST_SMALL, LivePage
from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.browsers.settings import Settings
from crossbench.cli.config.secrets import Secrets
from crossbench.env.runner_env import EnvConfig, ValidationMode
from crossbench.runner.runner import Runner
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, BaseCrossbenchTestCase
from tests.crossbench.benchmarks.helper import SubStoryTestCase
from tests.crossbench.mock_browser import JsInvocation


class LoadingBenchmarkCliTestCaseMixin:

  def test_parser_defaults(self):
    args = self.parse_args()
    self.assertEqual(args.tabs, TabController.default())
    self.assertEqual(args.playback, PlaybackController.default())
    self.assertEqual(args.about_blank_duration, dt.timedelta())
    self.assertTrue(args.run_login)
    self.assertTrue(args.run_setup)
    self.assertEqual(args.stories, "default")
    self.assertIsNone(args.story_tags)
    self.assertIsNone(args.pages_config)
    self.assertIsNone(args.action_runner_config)

  def test_single_tab_flag(self):
    args = self.parse_args("--single-tab")
    self.assertEqual(args.tabs, TabController.single())
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.tabs, TabController.single())

  def test_multiple_tab_flag(self):
    args = self.parse_args("--multiple-tab")
    self.assertEqual(args.tabs, TabController.multiple())
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.tabs, TabController.multiple())

  def test_multiple_tab_count_flag(self):
    args = self.parse_args("--multiple-tab=5")
    self.assertEqual(args.tabs, TabController.repeat(5))
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.tabs, TabController.repeat(5))

  def test_infinite_tab_flag(self):
    args = self.parse_args("--infinite-tab")
    self.assertEqual(args.tabs, TabController.forever())
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.tabs, TabController.forever())

  def test_playback_flag(self):
    args = self.parse_args("--playback=5x")
    self.assertEqual(args.playback, PlaybackController.repeat(5))
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.playback, PlaybackController.repeat(5))

  def test_forever_flag(self):
    args = self.parse_args("--forever")
    self.assertEqual(args.playback, PlaybackController.forever())
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      self.assertEqual(story.playback, PlaybackController.forever())

  def test_about_blank_duration_flag(self):
    args = self.parse_args("--about-blank-duration=3.5s", "--separate")
    self.assertEqual(args.about_blank_duration, dt.timedelta(seconds=3.5))

  def test_skip_login_and_setup(self):
    args = self.parse_args("--skip-login", "--skip-setup")
    self.assertFalse(args.run_login)
    self.assertFalse(args.run_setup)
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)
    for story in benchmark.stories:
      if isinstance(story, InteractivePage) and not isinstance(story, LivePage):
        self.assertFalse(story.run_login)
        self.assertFalse(story.run_setup)

  def test_stories_all(self):
    args = self.parse_args("--all")
    self.assertEqual(args.stories, "all")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertGreaterEqual(len(benchmark.stories), 1)

  def test_config_not_supported(self):
    config_file = pathlib.Path("pages.json")
    self.fs.create_file(
        config_file,
        contents=json.dumps({
            "pages": {
                "p": [{
                    "action": "get",
                    "url": "https://example.com",
                }],
            },
        }))
    args = self.parse_args(f"--page-config={config_file}")
    args.config = pathlib.Path("config.hjson")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "config"):
      self.benchmark_cls.from_cli_args(args)

  def test_kwargs_from_cli(self):
    args = self.parse_args()
    kwargs = self.benchmark_cls.kwargs_from_cli(args)
    self.assertIn("stories", kwargs)
    self.assertIn("action_runner_config", kwargs)
    self.assertIsNone(kwargs["action_runner_config"])


class TestPageLoadBenchmark(LoadingBenchmarkCliTestCaseMixin, SubStoryTestCase):

  def test_separate_and_combined_flags(self):
    args_sep = self.parse_args("--separate")
    self.assertTrue(args_sep.separate)
    bm_sep = self.benchmark_cls.from_cli_args(args_sep)
    self.assertGreater(len(bm_sep.stories), 1)
    for story in bm_sep.stories:
      self.assertIsInstance(story, LivePage)

    args_comb = self.parse_args("--combined")
    self.assertFalse(args_comb.separate)
    bm_comb = self.benchmark_cls.from_cli_args(args_comb)
    self.assertEqual(len(bm_comb.stories), 1)
    self.assertIsInstance(bm_comb.stories[0], CombinedPage)

  @property
  @override
  def benchmark_cls(self):
    return LoadingBenchmark

  @override
  def mock_args(self) -> argparse.Namespace:
    args = super().mock_args()
    args.pages_config = None
    return args

  @override
  def story_filter(self,
                   patterns: Sequence[str],
                   separate: bool = True,
                   playback: PlaybackController = PlaybackController.default(),
                   tabs: TabController = TabController.default(),
                   action_runner: ActionRunner | None = None,
                   about_blank_duration: dt.timedelta = dt.timedelta(),
                   run_login: bool = True,
                   run_setup: bool = True) -> LoadingPageFilter:
    if action_runner is None:
      action_runner = ActionRunner(self.mock_run())

    args = self.mock_args()
    args.about_blank_duration = about_blank_duration
    args.playback = playback
    args.tabs = tabs
    args.action_runner = action_runner
    args.run_login = run_login
    args.run_setup = run_setup
    story_filter = super().story_filter(patterns, args=args, separate=separate)
    assert isinstance(story_filter, LoadingPageFilter)
    return story_filter

  def test_page_list(self):
    self.assertTrue(PAGE_LIST)
    self.assertTrue(PAGE_LIST_SMALL)
    for page in PAGE_LIST:
      self.assertIsInstance(page, InteractivePage)
    for page in PAGE_LIST_SMALL:
      self.assertIsInstance(page, InteractivePage)

  def test_interactive_page_empty(self):
    with self.assertRaises(AssertionError):
      InteractivePage("test")

  def test_interactive_page_setup_only(self):
    setup = ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1))
    page = InteractivePage("test", setup=setup)
    self.assertTrue(page.has_any_blocks)
    self.assertTrue(bool(page))
    self.assertEqual(len(page.blocks), 0)

  def test_all_stories(self):
    stories = self.story_filter(["all"]).stories
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, LivePage)
    names = {story.name for story in stories}
    self.assertEqual(len(names), len(stories))
    self.assertSetEqual(names, {page.name for page in PAGE_LIST})

  def test_default_stories(self):
    stories = self.story_filter(["default"]).stories
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, LivePage)
    names = {story.name for story in stories}
    self.assertEqual(len(names), len(stories))
    self.assertSetEqual(names, {page.name for page in PAGE_LIST_SMALL})

  def test_combined_stories(self):
    stories = self.story_filter(["all"], separate=False).stories
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, CombinedPage)

  def test_filter_by_name(self):
    for preset_page in PAGE_LIST:
      stories = self.story_filter([preset_page.name]).stories
      self.assertSequenceEqual([p.url for p in stories], [preset_page.url])
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty string"):
      self.story_filter([])

  def test_filter_by_name_with_duration(self):
    pages = PAGE_LIST
    filtered_pages = self.story_filter([pages[0].name, pages[1].name,
                                        "1001"]).stories
    self.assertSequenceEqual([p.url for p in filtered_pages],
                             [pages[0].url, pages[1].url])
    self.assertEqual(filtered_pages[0].duration, pages[0].duration)
    self.assertEqual(filtered_pages[1].duration, dt.timedelta(seconds=1001))

  def test_page_by_url(self):
    url1 = "http://example.com/test1"
    url2 = "http://example.com/test2"
    stories = self.story_filter([url1, url2]).stories
    self.assertEqual(len(stories), 2)
    self.assertEqual(stories[0].first_url, url1)
    self.assertEqual(stories[1].first_url, url2)

  def test_page_by_url_www(self):
    url1 = "www.example.com/test1"
    url2 = "www.example.com/test2"
    stories = self.story_filter([url1, url2]).stories
    self.assertEqual(len(stories), 2)
    self.assertEqual(stories[0].first_url, f"https://{url1}")
    self.assertEqual(stories[1].first_url, f"https://{url2}")

  def test_page_by_url_combined(self):
    url1 = "http://example.com/test1"
    url2 = "http://example.com/test2"
    stories = self.story_filter([url1, url2], separate=False).stories
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, CombinedPage)

  def test_run_combined(self):
    stories = [CombinedPage(PAGE_LIST)]
    self._test_run(stories)
    self._assert_urls_loaded([story.url for story in PAGE_LIST])

  def test_substories_single(self):
    page = LivePage("test", "https://test.com", dt.timedelta(seconds=5))
    self.assertSequenceEqual(page.substories, ["test"])

  def test_substories_combined(self):
    page = CombinedPage(PAGE_LIST)
    self.assertSequenceEqual(page.substories,
                             [story.name for story in PAGE_LIST])
    page_0 = LivePage("test_0", "https://test.com/1", dt.timedelta(seconds=5))
    page_1 = LivePage("test_1", "https://test.com/1", dt.timedelta(seconds=5))
    page = CombinedPage([page_0, page_1])
    self.assertSequenceEqual(page.substories, ["test_0", "test_1"])

  def test_substories_nested(self):
    page_0 = LivePage("test_0", "https://test.com/1", dt.timedelta(seconds=5))
    page_1 = LivePage("test_1", "https://test.com/1", dt.timedelta(seconds=5))
    page_2 = CombinedPage([page_0, page_1])
    page_3 = LivePage("test_3", "https://test.com/3", dt.timedelta(seconds=5))
    page = CombinedPage([page_2, page_3])
    self.assertSequenceEqual(page.substories, ["test_0", "test_1", "test_3"])

  def test_substories_combined_conflicting_secrets(self):
    secrets1 = Secrets.parse(
        {"google": {
            "password": "pw1",
            "account": "user1@test.com",
        }})
    secrets2 = Secrets.parse(
        {"google": {
            "password": "pw2",
            "account": "user2@test.com",
        }})
    page_0 = InteractivePage(
        "test_0",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets1)
    page_1 = InteractivePage(
        "test_1",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets2)
    with self.assertRaisesRegex(ValueError, "Conflicting Google secrets"):
      CombinedPage([page_0, page_1])

  def test_substories_combined_same_secrets(self):
    secrets1 = Secrets.parse(
        {"google": {
            "password": "pw1",
            "account": "user1@test.com",
        }})
    secrets2 = Secrets.parse(
        {"google": {
            "password": "pw1",
            "account": "user1@test.com",
        }})
    self.assertEqual(secrets1, secrets2)
    page_0 = InteractivePage(
        "test_0",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets1)
    page_1 = InteractivePage(
        "test_1",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets2)
    combined = CombinedPage([page_0, page_1])
    self.assertEqual(combined.secrets, secrets1)
    self.assertEqual(combined.secrets, secrets2)

  def test_substories_combined_compatible_secrets(self):
    secrets1 = Secrets.parse(
        {"google": {
            "password": "pw1",
            "account": "user1@test.com",
        }})
    secrets2 = Secrets.parse({
        "bond": {
            "type": "service_account",
            "project_id": "my-project",
            "private_key_id": "0BADC0DE",
            "private_key": "-----BEGIN PRIVATE KEY-----\n...",
            "client_email": "name@example.com",
            "client_id": "7",
            "auth_uri": "https://example.com/oauth",
            "token_uri": "https://example.com/token",
            "auth_provider_x509_cert_url": "https://example.com/certs",
            "client_x509_cert_url": "https://example.com/x509/my-project.cert",
            "universe_domain": "example.com",
        },
    })
    self.assertNotEqual(secrets1, secrets2)
    page_0 = InteractivePage(
        "test_0",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets1)
    page_1 = InteractivePage(
        "test_1",
        setup=ActionBlock.from_url("http://test.com", dt.timedelta(seconds=1)),
        secrets=secrets2)
    combined = CombinedPage([page_0, page_1])
    self.assertNotEqual(combined.secrets, secrets1)
    self.assertNotEqual(combined.secrets, secrets2)
    self.assertEqual(combined.secrets.google, secrets1.google)
    self.assertEqual(combined.secrets.bond, secrets2.bond)

  def test_run_default(self):
    stories = PAGE_LIST_SMALL
    self._test_run(stories)
    self._assert_urls_loaded([story.url for story in stories])

  def test_run_throw(self):
    stories = PAGE_LIST_SMALL
    self._test_run(stories)
    self._assert_urls_loaded([story.url for story in stories])

  def test_run_repeat_with_about_blank(self):
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter(
        [url1, url2],
        separate=False,
        about_blank_duration=dt.timedelta(seconds=1)).stories
    self._test_run(stories)
    urls = [url1, "about:blank", url2, "about:blank"]
    self._assert_urls_loaded(urls)

  def test_run_repeat_with_about_blank_separate(self):
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter(
        [url1, url2],
        separate=True,
        about_blank_duration=dt.timedelta(seconds=1)).stories
    self._test_run(stories)
    urls = [url1, "about:blank", url2, "about:blank"]
    self._assert_urls_loaded(urls)

  def test_run_repeat(self):
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter([url1, url2],
                                separate=False,
                                playback=PlaybackController.repeat(3)).stories
    self._test_run(stories)
    urls = [url1, url2] * 3
    self._assert_urls_loaded(urls)

  def test_iteration_performance_marks_single_run(self):
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter([url1, url2],
                                separate=False,
                                playback=PlaybackController.repeat(1)).stories
    self._test_run(stories)

    for browser in self.browsers:
      # one mark for iteration start, one for iteration end
      self.assertSequenceEqual(
          browser.performance_marks,
          ["crossbench-iteration-start", "crossbench-iteration-end"])

  def test_iteration_performance_marks_repeat_run(self):
    repeats: int = 3
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter(
        [url1, url2],
        separate=False,
        playback=PlaybackController.repeat(repeats)).stories
    self._test_run(stories)

    for browser in self.browsers:
      self.assertSequenceEqual(
          browser.performance_marks,
          (["crossbench-iteration-start", "crossbench-iteration-end"] *
           repeats))

  def test_run_repeat_separate(self):
    url1 = "https://www.example.com/test1"
    url2 = "https://www.example.com/test2"
    stories = self.story_filter([url1, url2],
                                separate=True,
                                playback=PlaybackController.repeat(3)).stories
    self._test_run(stories)
    urls = [url1] * 3 + [url2] * 3
    self._assert_urls_loaded(urls)

  def _test_run(self, stories, throw: bool = False):
    benchmark = self.benchmark_cls(stories)

    for browser in self.browsers:
      browser.set_default_js_return(True)

    self.assertTrue(len(benchmark.describe()) > 0)
    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        throw=throw,
        in_memory_result_db=True)
    runner.run()
    self.assertTrue(runner.is_success)
    self.assertTrue(self.browsers[0].did_run)
    self.assertTrue(self.browsers[1].did_run)

  def _assert_urls_loaded(self, story_urls):
    browser_1_urls = self.filter_splashscreen_urls(self.browsers[0].url_list)
    self.assertEqual(browser_1_urls, story_urls)
    browser_2_urls = self.filter_splashscreen_urls(self.browsers[1].url_list)
    self.assertEqual(browser_2_urls, story_urls)


  def test_tab_flags_mutually_exclusive(self):
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--single-tab", "--multiple-tab")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--single-tab", "--infinite-tab")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--multiple-tab", "--infinite-tab")

  def test_playback_flag_with_interval(self):
    args = self.parse_args("--playback=2x every 3s")
    self.assertEqual(args.playback,
                     PlaybackController.periodic(2, dt.timedelta(seconds=3)))
    benchmark = self.benchmark_cls.from_cli_args(args)
    (combined_story,) = benchmark.stories
    self.assertEqual(combined_story.playback,
                     PlaybackController.periodic(2, dt.timedelta(seconds=3)))

  def test_playback_flags_mutually_exclusive(self):
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--playback=5x", "--forever")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--cycle=5x", "--forever")

  def test_about_blank_duration_invalid(self):
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--about-blank-duration=-1s")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--about-blank-duration=invalid_val")

  def test_skip_login_flag(self):
    config_file = pathlib.Path("page_config.json")
    config = {
        "pages": {
            "test_page": {
                "login": "google",
                "actions": [{
                    "action": "get",
                    "url": "https://example.com",
                }],
            },
        },
    }
    self.fs.create_file(config_file, contents=json.dumps(config))
    args = self.parse_args(f"--page-config={config_file}", "--skip-login",
                           "--separate")
    self.assertFalse(args.run_login)
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    self.assertIsInstance(story, InteractivePage)
    self.assertFalse(story.run_login)
    self.assertTrue(story.run_setup)

  def test_skip_setup_flag(self):
    config_file = pathlib.Path("page_config.json")
    config = {
        "pages": {
            "test_page": {
                "setup": [{
                    "action": "js",
                    "script": "console.log(1);",
                }],
                "actions": [{
                    "action": "get",
                    "url": "https://example.com",
                }],
            },
        },
    }
    self.fs.create_file(config_file, contents=json.dumps(config))
    args = self.parse_args(f"--page-config={config_file}", "--skip-setup",
                           "--separate")
    self.assertFalse(args.run_setup)
    benchmark = self.benchmark_cls.from_cli_args(args)
    (story,) = benchmark.stories
    self.assertIsInstance(story, InteractivePage)
    self.assertFalse(story.run_setup)
    self.assertTrue(story.run_login)

  def test_stories_default_flag(self):
    args = self.parse_args("--stories=default", "--separate")
    benchmark = self.benchmark_cls.from_cli_args(args)
    story_names = {story.name for story in benchmark.stories}
    expected_names = {story.name for story in PAGE_LIST_SMALL}
    self.assertEqual(story_names, expected_names)

  def test_stories_all_flag(self):
    args = self.parse_args("--all", "--separate")
    self.assertEqual(args.stories, "all")
    benchmark = self.benchmark_cls.from_cli_args(args)
    story_names = {story.name for story in benchmark.stories}
    expected_names = {story.name for story in PAGE_LIST}
    self.assertEqual(story_names, expected_names)

  def test_stories_named_urls(self):
    args = self.parse_args(
        "--stories=https://example.com/one,https://example.com/two",
        "--separate")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 2)
    self.assertEqual(benchmark.stories[0].first_url, "https://example.com/one")
    self.assertEqual(benchmark.stories[1].first_url, "https://example.com/two")

  def test_stories_custom_duration(self):
    args = self.parse_args("--stories=https://example.com/one,12s",
                           "--separate")
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 1)
    self.assertEqual(benchmark.stories[0].first_url, "https://example.com/one")
    self.assertEqual(benchmark.stories[0].duration, dt.timedelta(seconds=12))

  def test_story_tags_flag(self):
    args = self.parse_args("--story-tags=tag1,tag2")
    self.assertEqual(args.story_tags, "tag1,tag2")
    with self.assertRaises(ValueError):
      self.benchmark_cls.from_cli_args(args)

  def test_story_filtering_mutually_exclusive(self):
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--stories=default", "--story-tags=all")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--all", "--stories=default")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--all", "--story-tags=all")

  def test_page_config_flag(self):
    config_file = pathlib.Path("pages.json")
    config = {
        "pages": {
            "page1": [{
                "action": "get",
                "url": "https://example.com/1",
            }],
            "page2": [{
                "action": "get",
                "url": "https://example.com/2",
            }],
        },
    }
    self.fs.create_file(config_file, contents=json.dumps(config))
    args = self.parse_args(f"--page-config={config_file}", "--separate")
    self.assertIsNotNone(args.pages_config)
    benchmark = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 2)
    self.assertEqual(benchmark.stories[0].name, "page1")
    self.assertEqual(benchmark.stories[1].name, "page2")

  def test_page_config_mutually_exclusive(self):
    config_file = pathlib.Path("pages.json")
    self.fs.create_file(config_file, contents='{"pages": {}}')
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args(f"--page-config={config_file}",
                      "--urls=https://example.com")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args(f"--page-config={config_file}",
                      f"--url-file={config_file}")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args(f"--page-config={config_file}",
                      f"--devtools-recorder={config_file}")

  def test_cli_flag_aliases(self):
    args_playback = self.parse_args("--playback=10x")
    args_cycle = self.parse_args("--cycle=10x")
    self.assertEqual(args_playback, args_cycle)

    args_about_blank = self.parse_args("--about-blank-duration=500ms")
    args_about_blank_alias = self.parse_args("--about-blank=500ms")
    self.assertEqual(args_about_blank, args_about_blank_alias)

    args_action_runner = self.parse_args("--action-runner={}")
    args_action_runner_alias = self.parse_args("--action-runner-config={}")
    self.assertEqual(args_action_runner, args_action_runner_alias)


class LoadingBenchmarkCliTestCase(BaseCliTestCase):

  def test_invalid_duplicate_urls_stories(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      with self._patch_get_browser():
        url = "http://test.com"
        self.run_cli("loading", "run", f"--urls={url}", f"--stories={url}",
                     "--env-validation=skip", "--throw")
    self.assertIn("--urls", str(cm.exception))
    self.assertIn("--stories", str(cm.exception))

  def test_invalid_duplicate_urls_config(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      with self._patch_get_browser():
        self.run_cli("loading", "run", "--urls=https://test.com",
                     "--page-config=config.hjson", "--env-validation=skip",
                     "--throw")
    self.assertIn("--urls", str(cm.exception))
    self.assertIn("--page-config", str(cm.exception))

  def test_invalid_duplicate_stories_config(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      with self._patch_get_browser():
        self.run_cli("loading", "run", "--stories=https://test.com",
                     "--page-config=config.hjson", "--env-validation=skip",
                     "--throw")
    self.assertIn("--stories", str(cm.exception))
    self.assertIn("page config", str(cm.exception).lower())

  def test_conflicting_global_config(self):
    config_data = {
        "browsers": {
            "chrome": "chrome-stable",
        },
        "pages": {
            "google_search_result": [{
                "action": "get",
                "url": "https://www.google.com/search?q=cats",
            }],
        },
    }
    config_file = pathlib.Path("config.hjson")
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(config_data, f)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      with self._patch_get_browser():
        self.run_cli("loading", "run", "--stories=https://test.com",
                     "--config=config.hjson", "--page-config=config.hjson",
                     "--env-validation=skip", "--throw")
    error_message = str(cm.exception).lower()
    self.assertIn("conflict", error_message)
    self.assertIn("--config", error_message)
    self.assertIn("--page-config", error_message)

  def test_page_list_file(self):
    config = pathlib.Path("test/pages.txt")
    self.fs.create_file(config)
    url_1 = "http://one.test.com"
    url_2 = "http://two.test.com"
    with config.open("w", encoding="utf-8") as f:
      f.write(f"{url_1}\n{url_2}")
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--urls-file={config}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def test_page_list_file_separate(self):
    config = pathlib.Path("test/pages.txt")
    self.fs.create_file(config)
    url_1 = "http://one.test.com"
    url_2 = "http://two.test.com"
    with config.open("w", encoding="utf-8") as f:
      f.write(f"{url_1}\n{url_2}")
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--urls-file={config}",
                   "--env-validation=skip", "--separate", "--throw")
      for browser in self.browsers:
        self.assertEqual(len(browser.url_list), (self.SPLASH_URLS_LEN + 1) * 2)
        self.assertEqual(url_1, browser.url_list[self.SPLASH_URLS_LEN])
        self.assertEqual(url_2, browser.url_list[self.SPLASH_URLS_LEN * 2 + 1])

  def test_urls_single(self):
    with self._patch_get_browser():
      url = "http://test.com"
      self.run_cli("loading", "run", f"--urls={url}", "--env-validation=skip",
                   "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url], browser.url_list[self.SPLASH_URLS_LEN:])

  def test_urls_multiple(self):
    with self._patch_get_browser():
      url_1 = "http://one.test.com"
      url_2 = "http://two.test.com"
      self.run_cli("loading", "run", f"--urls={url_1},{url_2}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def test_urls_multiple_separate(self):
    with self._patch_get_browser():
      url_1 = "http://one.test.com"
      url_2 = "http://two.test.com"
      self.run_cli("loading", "run", f"--urls={url_1},{url_2}",
                   "--env-validation=skip", "--separate", "--throw")
      for browser in self.browsers:
        self.assertEqual(len(browser.url_list), (self.SPLASH_URLS_LEN + 1) * 2)
        self.assertEqual(url_1, browser.url_list[self.SPLASH_URLS_LEN])
        self.assertEqual(url_2, browser.url_list[self.SPLASH_URLS_LEN * 2 + 1])

  def test_repeat_playback(self):
    with self._patch_get_browser():
      url_1 = "http://one.test.com"
      url_2 = "http://two.test.com"
      self.run_cli("loading", "run", f"--urls={url_1},{url_2}", "--playback=2x",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url_1, url_2, url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def test_repeat_playback_separate(self):
    with self._patch_get_browser():
      url_1 = "http://one.test.com"
      url_2 = "http://two.test.com"
      self.run_cli("loading", "run", f"--urls={url_1},{url_2}", "--playback=2x",
                   "--separate", "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertEqual(len(browser.url_list), (self.SPLASH_URLS_LEN + 2) * 2)
        self.assertSequenceEqual(
            [url_1, url_1],
            browser.url_list[self.SPLASH_URLS_LEN:self.SPLASH_URLS_LEN + 2])
        self.assertSequenceEqual(
            [url_2, url_2], browser.url_list[self.SPLASH_URLS_LEN * 2 + 2:])

  def simple_pages_config(self):
    url_1 = "http://one.test.com"
    url_2 = "http://two.test.com"
    config = {
        "pages": {
            "test_one": [{
                "action": "get",
                "url": url_1,
            }, {
                "action": "get",
                "url": url_2,
            }],
        },
    }
    return url_1, url_2, config

  def test_actions_config(self):
    url_1, url_2, config = self.simple_pages_config()
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--page-config={config_file}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def multiple_pages_with_setup_and_teardown_blocks_config(self):
    config = {
        "pages": {
            "first_page": {
                "setup": [{
                    "action": "js",
                    "script": "SETUP ONE",
                }],
                "actions": [{
                    "action": "wait",
                    "duration": "1s",
                }],
                "teardown": [{
                    "action": "js",
                    "script": "TEARDOWN ONE",
                }],
            },
            "second_page": {
                "setup": [{
                    "action": "js",
                    "script": "SETUP TWO",
                }],
                "actions": [{
                    "action": "wait",
                    "duration": "1s",
                }],
                "teardown": [{
                    "action": "js",
                    "script": "TEARDOWN TWO",
                }],
            },
        },
    }
    return config

  def test_pages_with_multiple_setup_and_teardown_blocks(self):
    for browser in self.browsers:
      browser.expect_js(JsInvocation(None, "SETUP ONE"))
      browser.expect_js(JsInvocation(None, "SETUP TWO"))
      browser.expect_js(JsInvocation(None, "TEARDOWN ONE"))
      browser.expect_js(JsInvocation(None, "TEARDOWN TWO"))

    config = self.multiple_pages_with_setup_and_teardown_blocks_config()
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--page-config={config_file}",
                   "--env-validation=skip", "--throw")

    for browser in self.browsers:
      self.assertEqual(
          browser.performance_marks,
          ["crossbench-setup-start", "crossbench-setup-end"] * 2 +  # 2 pages
          ["crossbench-iteration-start", "crossbench-iteration-end"] +
          ["crossbench-teardown-start", "crossbench-teardown-end"] * 2)
      self.assertEqual(browser.performance_marks_details,
                       ["first_page"] * 2 + ["second_page"] * 2 + [0, 0] +
                       ["first_page"] * 2 + ["second_page"] * 2)

  def multiple_pages_with_setup_only_config(self):
    config = {
        "pages": {
            "setup_only_page": {
                "setup": [{
                    "action": "js",
                    "script": "SETUP ONLY",
                }],
            },
        },
    }
    return config

  def test_pages_with_setup_only(self):
    for browser in self.browsers:
      browser.expect_js(JsInvocation(None, "SETUP ONLY"))

    config = self.multiple_pages_with_setup_only_config()
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--page-config={config_file}",
                   "--env-validation=skip", "--throw")

    for browser in self.browsers:
      self.assertEqual(
          browser.performance_marks,
          ["crossbench-setup-start", "crossbench-setup-end"] +
          ["crossbench-iteration-start", "crossbench-iteration-end"])
      self.assertEqual(browser.performance_marks_details,
                       ["setup_only_page"] * 2 + [0, 0])

  def setup_expected_google_login_js(self):
    expected_scripts: list[JsInvocation] = [
        # Wait for readystate interactive
        JsInvocation(True),

        # Wait for email field
        JsInvocation(True, re.compile(r".*Email or phone.*")),
        # Click submit email
        JsInvocation(None, re.compile(r".*user@test.com.*")),

        # Wait for password field
        JsInvocation(True, re.compile(r".*passwordNext.*")),
        # Click submit password
        JsInvocation(None, re.compile(r".*s3cr3t.*")),

        # Wait for redirect after password
        JsInvocation(True, re.compile(r".*signin/challenge/pwd.*")),
        # Wait for readystate complete
        JsInvocation(True),
        # Return successful login URL
        JsInvocation("https://myaccount.google.com", re.compile(r".*URL.*")),
        # No suspicious activity
        JsInvocation(False),
    ]
    for browser in self.browsers:
      for script in expected_scripts:
        browser.expect_js(script)

  def simple_pages_with_login_config(self):
    url_1 = "http://one.test.com"
    url_2 = "http://two.test.com"
    config = {
        "pages": {
            "test_one": {
                "login":
                    "google",
                "actions": [{
                    "action": "get",
                    "url": url_1,
                }, {
                    "action": "get",
                    "url": url_2,
                }],
            },
        },
    }
    return url_1, url_2, config

  def test_actions_config_with_login_preset(self):
    url_1, url_2, config = self.simple_pages_with_login_config()
    config.update({
        "secrets": {
            "google": {
                "username": "user@test.com",
                "password": "s3cr3t",
            },
        },
    })
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    self.setup_expected_google_login_js()
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--page-config={config_file}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([GOOGLE_LOGIN_URL, url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def test_actions_config_with_login_preset_global_secrets(self):
    url_1, url_2, config = self.simple_pages_with_login_config()
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    secrets_data = {
        "google": {
            "username": "user@test.com",
            "password": "s3cr3t",
        },
    }
    secrets = Secrets.parse(secrets_data)
    self.setup_expected_google_login_js()
    with self._patch_get_browser():
      with mock.patch.object(
          Settings, "secrets",
          new_callable=mock.PropertyMock) as mock_get_secrets:
        mock_get_secrets.return_value = secrets
        self.run_cli("loading", "run", f"--page-config={config_file}",
                     "--env-validation=skip", "--throw",
                     f"--secrets={json.dumps(secrets_data)}")
        self.assertEqual(mock_get_secrets.call_count, 2)
      for browser in self.browsers:
        self.assertSequenceEqual([GOOGLE_LOGIN_URL, url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])

  def test_actions_config_with_login_preset_missing_secrets(self):
    _, _, config = self.simple_pages_with_login_config()
    config_file = pathlib.Path("test/page_config.json")
    self.fs.create_file(config_file, contents=json.dumps(config))
    self.setup_expected_google_login_js()
    with self._patch_get_browser():
      with self.assertRaises(Exception) as cm:
        self.run_cli("loading", "run", f"--page-config={config_file}",
                     "--env-validation=skip", "--throw")
      self.assertIn("google", str(cm.exception))

  def test_global_config_actions_config(self):
    url_1 = "http://one.test.com"
    url_2 = "http://two.test.com"
    global_config_file = pathlib.Path("config.hjson")
    global_config_data = {
        # Dummy entry, not actually used by the test
        "browsers": {
            "chrome": "chrome-stable",
        },
        "pages": {
            "test_one": [{
                "action": "get",
                "url": url_1,
            }, {
                "action": "get",
                "url": url_2,
            }],
        },
    }
    with global_config_file.open("w", encoding="utf-8") as f:
      json.dump(global_config_data, f)
    with self._patch_get_browser():
      self.run_cli("loading", "run", f"--config={global_config_file}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertSequenceEqual([url_1, url_2],
                                 browser.url_list[self.SPLASH_URLS_LEN:])


class ActionBlockListConfigTestCase(unittest.TestCase):

  def test_parse_invalid(self):
    invalid: Any
    for invalid in ("", (), {}, 1):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ActionBlockListConfig.parse(invalid)

  def test_parse_default_action_list(self):
    config = ActionBlockListConfig.parse([{
        "action": "get",
        "url": "http://test.com",
        "duration": "12.5s",
    }])
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "default")
    self.assertEqual(len(block.actions), 1)
    self.assertEqual(block.actions[0].TYPE, ActionType.GET)
    self.assertEqual(block.duration, dt.timedelta(seconds=12.5))

  def test_parse_default_action_list_2(self):
    config = ActionBlockListConfig.parse([{
        "action": "get",
        "url": "http://test.com",
        "duration": "12.5s",
    }, {
        "action": "wait",
        "duration": "100s",
    }])
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "default")
    self.assertEqual(len(block.actions), 2)
    self.assertEqual(block.actions[0].TYPE, ActionType.GET)
    self.assertEqual(block.actions[1].TYPE, ActionType.WAIT)
    self.assertEqual(block.duration, dt.timedelta(seconds=112.5))

  def test_parse_single_block_action_list(self):
    config = ActionBlockListConfig.parse([{
        "label": "block 1",
        "actions": [{
            "action": "get",
            "url": "http://test.com",
        }],
    }])
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(len(block.actions), 1)
    self.assertEqual(block.actions[0].TYPE, ActionType.GET)

  def test_parse_multi_block_action_list(self):
    config = ActionBlockListConfig.parse([{
        "label":
            "block 0",
        "actions": [{
            "action": "get",
            "url": "http://test.com/0",
            "duration": "10s",
        }],
    }, {
        "label":
            "block 1",
        "actions": [{
            "action": "get",
            "url": "http://test.com/1",
            "duration": "11s",
        }],
    }])
    self.assertEqual(len(config.blocks), 2)
    for index, block in enumerate(config.blocks):
      self.assertEqual(block.label, f"block {index}")
      self.assertEqual(len(block.actions), 1)
      self.assertEqual(block.actions[0].TYPE, ActionType.GET)
      self.assertEqual(block.actions[0].url, f"http://test.com/{index}")
      self.assertEqual(block.duration, dt.timedelta(seconds=10 + index))

  def test_parse_single_block_dict(self):
    config = ActionBlockListConfig.parse({
        "block 1": {
            "actions": [{
                "action": "get",
                "url": "http://test.com",
            }],
        },
    })
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(len(block.actions), 1)
    self.assertEqual(block.actions[0].TYPE, ActionType.GET)

  def test_parse_block_dict_action_list_2(self):
    config = ActionBlockListConfig.parse({
        "block 1": [{
            "action": "get",
            "url": "http://test.com",
        }, {
            "action": "wait",
            "duration": "2s",
        }],
    })
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(len(block.actions), 2)
    self.assertEqual(block.actions[0].TYPE, ActionType.GET)
    self.assertEqual(block.actions[1].TYPE, ActionType.WAIT)

  def test_parse_single_block_multi_action_dict(self):
    config = ActionBlockListConfig.parse({
        "block 1": {
            "actions": [{
                "action": "get",
                "url": "http://test.com/0",
                "duration": "1s",
            }, {
                "action": "get",
                "url": "http://test.com/1",
                "duration": "20s",
            }],
        },
    })
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(block.duration, dt.timedelta(seconds=21))
    self.assertEqual(len(block.actions), 2)
    for index, action in enumerate(block.actions):
      self.assertEqual(action.TYPE, ActionType.GET)
      self.assertEqual(action.url, f"http://test.com/{index}")

  def test_parse_single_block_empty_action_dict(self):
    config = ActionBlockListConfig.parse({"block 1": {"actions": []}})
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(block.duration, dt.timedelta(seconds=0))
    self.assertEqual(len(block.actions), 0)

  def test_parse_single_block_empty_action_list(self):
    config = ActionBlockListConfig.parse({"block 1": []})
    self.assertEqual(len(config.blocks), 1)
    block = config.blocks[0]
    self.assertEqual(block.label, "block 1")
    self.assertEqual(block.duration, dt.timedelta(seconds=0))
    self.assertEqual(len(block.actions), 0)

  def test_parse_multi_block_actions_dict(self):
    config = ActionBlockListConfig.parse({
        "block 0": {
            "actions": [{
                "action": "get",
                "url": "http://test.com/0",
            }],
        },
        "block 1": {
            "actions": [{
                "action": "get",
                "url": "http://test.com/1",
            }],
        },
    })
    self.assertEqual(len(config.blocks), 2)
    for index, block in enumerate(config.blocks):
      self.assertEqual(block.label, f"block {index}")
      self.assertEqual(len(block.actions), 1)
      self.assertEqual(block.actions[0].TYPE, ActionType.GET)
      self.assertEqual(block.actions[0].url, f"http://test.com/{index}")

  def test_parse_multi_block_actions_list(self):
    config = ActionBlockListConfig.parse({
        "block 0": [{
            "action": "get",
            "url": "http://test.com/0",
        }],
        "block 1": [{
            "action": "get",
            "url": "http://test.com/1",
        }],
    })
    self.assertEqual(len(config.blocks), 2)
    for index, block in enumerate(config.blocks):
      self.assertEqual(block.label, f"block {index}")
      self.assertEqual(len(block.actions), 1)
      self.assertEqual(block.actions[0].TYPE, ActionType.GET)
      self.assertEqual(block.actions[0].url, f"http://test.com/{index}")

  def test_parse_dict_label_conflict(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ActionBlockListConfig.parse({
          "block 1": {
              "label": "block 2",
              "actions": [{
                  "action": "get",
                  "url": "http://test.com",
              }],
          },
      })
    self.assertIn("block 2", str(cm.exception))

  def test_parse_invalid_dict_missing_actions(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ActionBlockListConfig.parse({"block 1": {}})
    self.assertIn("actions", str(cm.exception))

  def test_parse_logins(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = ActionBlockListConfig.parse({
          "login": [{
              "action": "get",
              "url": "http://test.com/login",
          }],
          "block 0": [{
              "action": "get",
              "url": "http://test.com/1",
          }],
      })
    self.assertIn("login", str(cm.exception))


# Don't expose abstract base test cases.
del SubStoryTestCase, BaseCliTestCase, BaseCrossbenchTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
