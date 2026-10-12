# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import abc
import argparse
from typing import Sequence

from typing_extensions import override

from crossbench.benchmarks import base as benchmark_module
from crossbench.cli.parser import CBArgumentParser
from tests.crossbench.base import BaseCrossbenchTestCase


class BaseBenchmarkTestCase(BaseCrossbenchTestCase, metaclass=abc.ABCMeta):
  @property
  @abc.abstractmethod
  def benchmark_cls(self) -> type[benchmark_module.Benchmark]:
    pass

  @property
  def story_cls(self):
    return self.benchmark_cls.DEFAULT_STORY_CLS

  @override
  def setUp(self):
    super().setUp()
    self.assertTrue(
        issubclass(self.benchmark_cls, benchmark_module.Benchmark),
        f"Expected Benchmark subclass, but got: BENCHMARK={self.benchmark_cls}",
    )

  def create_parser(self) -> CBArgumentParser:
    parser = CBArgumentParser()
    parser.set_defaults(config=None)
    self.benchmark_cls.add_cli_arguments(parser)
    return parser

  def parse_args(self, *args: str | Sequence[str]) -> argparse.Namespace:
    flattened_args: list[str] = [
        item for arg in args
        for item in ([arg] if isinstance(arg, str) else arg)
    ]
    return self.create_parser().parse_args(flattened_args)

  def test_describe(self):
    self.assertIsInstance(self.benchmark_cls.describe(), dict)

  def test_aliases(self):
    self.assertNotIn(self.benchmark_cls.NAME, self.benchmark_cls.aliases())


class SubStoryTestCase(BaseBenchmarkTestCase, metaclass=abc.ABCMeta):
  @property
  def story_filter_cls(self) -> type[benchmark_module.StoryFilter]:
    return self.benchmark_cls.STORY_FILTER_CLS

  def story_filter(self,
                   patterns: Sequence[str],
                   args: argparse.Namespace | None = None,
                   **kwargs) -> benchmark_module.StoryFilter:
    if args is None:
      args = self.namespace()
    return self.story_filter_cls(
        story_cls=self.story_cls, patterns=patterns, args=args, **kwargs)

  def namespace(self) -> argparse.Namespace:
    return argparse.Namespace()

  def test_instantiate_no_stories(self):
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories=[])
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories="")
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories=["", ""])

  def test_stories_creation(self):
    for name in self.story_cls.all_story_names():
      stories = self.story_filter([name]).stories
      self.assertTrue(len(stories) == 1)
      story = stories[0]
      self.assertIsInstance(story, self.story_cls)
      self.assertIsInstance(story.details_json(), dict)
      self.assertTrue(len(str(story)) > 0)

  def test_instantiate_single_story(self):
    any_story_name = self.story_cls.all_story_names()[0]
    any_story = self.story_filter([any_story_name]).stories[0]
    # Instantiate with single story,
    with self.assertRaises(TypeError):
      self.benchmark_cls(any_story)
    # with single story array
    self.benchmark_cls([any_story])
    with self.assertRaises(AssertionError):
      # Accidentally nested array.
      self.benchmark_cls([[any_story]])

  def test_instantiate_all_stories(self):
    stories = self.story_filter(self.story_cls.all_story_names()).stories
    self.benchmark_cls(stories)


class PressBaseBenchmarkTestCase(SubStoryTestCase, metaclass=abc.ABCMeta):
  def test_invalid_story_names(self):
    # Only StoryFilter can filter stories by regexp
    with self.assertRaises(ValueError):
      self.story_cls.from_names(".*", separate=True)
    with self.assertRaises(ValueError):
      self.story_cls.from_names([".*"], separate=True)
    with self.assertRaises(ValueError):
      self.story_cls.from_names([".*", "name does not exist"], separate=True)
    with self.assertRaises(ValueError):
      self.story_cls.from_names([""], separate=True)

  def test_all(self):
    all_stories = [story.name for story in self.story_cls.all(separate=True)]
    all_regexp = [
        story.name for story in self.story_filter([".*"], separate=True).stories
    ]
    all_string = [
        story.name
        for story in self.story_filter(["all"], separate=True).stories
    ]
    self.assertListEqual(all_stories, all_regexp)
    self.assertListEqual(all_stories, all_string)

  def test_default(self):
    default_stories = [
        story.name for story in self.story_cls.default(separate=True)
    ]
    default_string = [
        story.name
        for story in self.story_filter(["default"], separate=True).stories
    ]
    self.assertListEqual(default_stories, default_string)

  def test_remove(self):
    assert len(self.story_cls.all_story_names()) > 1
    story_name = self.story_cls.all_story_names()[0]
    all_stories = [story.name for story in self.story_cls.all(separate=True)]
    filtered_stories = [
        story.name for story in self.story_filter([".*", f"-{story_name}"],
                                                  separate=True).stories
    ]
    self.assertEqual(len(filtered_stories) + 1, len(all_stories))
    for name in filtered_stories:
      self.assertIn(name, all_stories)

  def test_remove_invalid(self):
    assert len(self.story_cls.all_story_names()) > 1
    story_name = self.story_cls.all_story_names()[0]
    with self.assertRaises(ValueError):
      self.story_filter(["-"])
    with self.assertRaises(ValueError):
      self.story_filter(["--"])
    with self.assertRaises(ValueError):
      self.story_filter(["-.*"])
    with self.assertRaises(ValueError):
      self.story_filter(["-all"])
    with self.assertRaises(ValueError):
      self.story_filter(["-does not exist name"])
    with self.assertRaises(ValueError):
      self.story_filter([f"-{story_name}"])

  def test_invalid_remove_all(self):
    assert len(self.story_cls.all_story_names()) > 1
    story_name = self.story_cls.all_story_names()[0]
    with self.assertRaises(ValueError):
      self.story_filter([story_name, f"-{story_name}"])
    with self.assertRaises(ValueError):
      self.story_filter([story_name, "-[^ ]+"])

  def test_invalid_add_all(self):
    assert len(self.story_cls.all_story_names()) > 1
    story_name = self.story_cls.all_story_names()[0]
    with self.assertRaises(ValueError):
      # Add all stories again after filtering out some
      self.story_filter([".*", f"-{story_name}", ".*|[^ ]+"])

  def test_remove_non_existent(self):
    assert len(self.story_cls.all_story_names()) > 1
    story_name = self.story_cls.all_story_names()[0]
    other_story_name = self.story_cls.all_story_names()[1]
    with self.assertRaises(ValueError):
      self.story_filter([other_story_name, f"-{story_name}"])

  def test_cli_flag_live(self):
    args = self.parse_args("--live")
    self.assertIsNone(args.custom_benchmark_url)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertIsNone(benchmark_instance.custom_url)
    for story in benchmark_instance.stories:
      self.assertEqual(story.url, self.story_cls.URL)

  def test_cli_flag_official(self):
    args = self.parse_args("--official")
    self.assertEqual(args.custom_benchmark_url, self.story_cls.URL_OFFICIAL)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(benchmark_instance.custom_url, self.story_cls.URL_OFFICIAL)
    for story in benchmark_instance.stories:
      self.assertEqual(story.url, self.story_cls.URL_OFFICIAL)

  def test_cli_flag_local(self):
    args = self.parse_args("--local")
    self.assertEqual(args.custom_benchmark_url, self.story_cls.URL_LOCAL)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(benchmark_instance.custom_url, self.story_cls.URL_LOCAL)
    for story in benchmark_instance.stories:
      self.assertEqual(story.url, self.story_cls.URL_LOCAL)

  def test_cli_flag_custom_benchmark_url(self):
    custom_url = "http://test.example.com/custom_benchmark"
    args = self.parse_args(f"--custom-benchmark-url={custom_url}")
    self.assertEqual(args.custom_benchmark_url, custom_url)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(benchmark_instance.custom_url, custom_url)
    for story in benchmark_instance.stories:
      self.assertEqual(story.url, custom_url)

  def test_cli_flag_aliases(self):
    live_expected = self.parse_args("--live")
    for alias in ("--live-url", "--browser-ben", "--browserben"):
      self.assertEqual(self.parse_args(alias), live_expected)

    official_expected = self.parse_args("--official")
    for alias in ("--official-url",):
      self.assertEqual(self.parse_args(alias), official_expected)

    local_expected = self.parse_args("--local")
    for alias in ("--local-url", "--url"):
      self.assertEqual(self.parse_args(alias), local_expected)

    custom_url = "http://test.example.com/custom_benchmark"
    custom_expected = self.parse_args(f"--custom-benchmark-url={custom_url}")
    for alias in ("--url", "--local", "--local-url"):
      self.assertEqual(
          self.parse_args(f"{alias}={custom_url}"), custom_expected)

    story_name = self.story_cls.default_story_names()[0]
    stories_expected = self.parse_args(f"--stories={story_name}")
    self.assertEqual(self.parse_args(f"--story={story_name}"), stories_expected)

    tags_expected = self.parse_args("--story-tags=all")
    self.assertEqual(self.parse_args("--story-tag=all"), tags_expected)

  def test_cli_flag_url_mutually_exclusive(self):
    parser = self.create_parser()
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--live", "--official"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--official", "--local"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--live", "--custom-benchmark-url=http://example.com"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(
          ["--official", "--custom-benchmark-url=http://example.com"])

  def test_cli_flag_stories_all(self):
    args = self.parse_args("--stories=all")
    self.assertEqual(args.stories, "all")
    self.assertIsNone(args.story_tags)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark_instance.stories)

  def test_cli_flag_stories_default(self):
    args = self.parse_args("--stories=default")
    self.assertEqual(args.stories, "default")
    self.assertIsNone(args.story_tags)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark_instance.stories)

  def test_cli_flag_story_single(self):
    story_name = self.story_cls.default_story_names()[0]
    args = self.parse_args(f"--stories={story_name}")
    self.assertEqual(args.stories, story_name)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(len(benchmark_instance.stories), 1)

  def test_cli_flag_all(self):
    args = self.parse_args("--all")
    self.assertEqual(args.stories, "all")
    self.assertIsNone(args.story_tags)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertTrue(benchmark_instance.stories)

  def test_cli_flag_story_tags(self):
    args = self.parse_args("--story-tags=all")
    self.assertEqual(args.story_tags, "all")

  def test_cli_flag_stories_mutually_exclusive(self):
    parser = self.create_parser()
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--all", "--stories=default"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--all", "--story-tags=all"])
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--stories=default", "--story-tags=all"])

  def test_cli_flag_combined_and_separate(self):
    args = self.parse_args()
    self.assertFalse(args.separate)

    args = self.parse_args("--combined")
    self.assertFalse(args.separate)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(len(benchmark_instance.stories), 1)

    args = self.parse_args("--separate")
    self.assertTrue(args.separate)
    benchmark_instance = self.benchmark_cls.from_cli_args(args)
    self.assertEqual(
        len(benchmark_instance.stories),
        len(self.story_cls.default_story_names()))

    parser = self.create_parser()
    with self.assertRaises(argparse.ArgumentError):
      parser.parse_args(["--combined", "--separate"])
