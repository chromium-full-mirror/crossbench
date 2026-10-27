# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import io
from typing import Final
from unittest import mock

from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench.benchmarks.web_power.base import VERSION_STRING
from crossbench.benchmarks.web_power.consolidated import WebPowerBenchmark, \
    WebPowerConsolidatedStoryFilter
from crossbench.benchmarks.web_power.idle import WebPowerIdleStory
from crossbench.benchmarks.web_power.media_playback import AmbientMode, \
    WebPowerMediaPlaybackStory
from crossbench.benchmarks.web_power.page_load import WebPowerPageLoadStory
from crossbench.benchmarks.web_power.probe import WebPowerProbe
from crossbench.benchmarks.web_power.scroll import WebPowerScrollStory
from crossbench.benchmarks.web_power.volume_helper import VolumeMode
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.cli.parser import CBArgumentParser
from crossbench.cli.subcommand.benchmark import BenchmarkSubcommand
from crossbench.probes.bits import BitsProbe
from crossbench.probes.trace_processor.query_config import QUERIES_DIR
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, BaseCrossbenchTestCase, \
    SysExitTestException
from tests.crossbench.benchmarks.web_power.test_base import \
    BaseWebPowerBenchmarkTestCase


class WebPowerConsolidatedStoryFilterTestCase(BaseCrossbenchTestCase):

  def test_stories_from_names_explicit(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(
        ["--stories=idle-msn,scroll-cnn,media-playback-youtube"])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    stories = story_filter.stories

    self.assertEqual(len(stories), 3)
    self.assertEqual(stories[0].name, "web-power-idle-msn")
    self.assertEqual(stories[0].url, "https://msn.com/en-us")
    self.assertEqual(stories[1].name, "web-power-scroll-cnn")
    self.assertEqual(stories[1].url, "https://www.cnn.com")
    self.assertEqual(stories[2].name, "web-power-media-playback-youtube")
    self.assertEqual(stories[2].url,
                     "https://www.youtube.com/watch?v=XITHbsUUlYI")

  def test_stories_from_names_tag_idle(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(["--stories=#idle"])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    stories = story_filter.stories

    self.assertEqual(len(stories), 3)
    self.assertEqual(stories[0].name, "web-power-idle-ajnews")
    self.assertEqual(stories[1].name, "web-power-idle-cnn")
    self.assertEqual(stories[2].name, "web-power-idle-msn")

  def test_stories_from_names_tag_site(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(["--stories=#cnn"])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    stories = story_filter.stories

    self.assertEqual(len(stories), 3)
    self.assertEqual(stories[0].name, "web-power-idle-cnn")
    self.assertEqual(stories[1].name, "web-power-page-load-cnn")
    self.assertEqual(stories[2].name, "web-power-scroll-cnn")

  def test_stories_from_names_non_canonical(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(["--stories=idle-yahoo"])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    stories = story_filter.stories

    self.assertEqual(len(stories), 1)
    self.assertEqual(stories[0].name, "web-power-idle-yahoo")
    self.assertEqual(stories[0].url, "https://www.yahoo.com")

  def _expected_canonical_stories(self) -> set[str]:
    return {
        "web-power-idle-msn",
        "web-power-idle-cnn",
        "web-power-idle-ajnews",
        "web-power-scroll-msn",
        "web-power-scroll-cnn",
        "web-power-scroll-ajnews",
        "web-power-page-load-msn",
        "web-power-page-load-cnn",
        "web-power-page-load-ajnews",
        "web-power-media-playback-youtube",
    }

  def test_stories_from_names_tag_canonical(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args(["--stories=#canonical"])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    self.assertEqual({story.name for story in story_filter.stories},
                     self._expected_canonical_stories())

  def test_stories_from_names_default(self) -> None:
    parser = CBArgumentParser()
    parser = WebPowerBenchmark.add_cli_arguments(parser)
    args = parser.parse_args([])
    story_filter = WebPowerConsolidatedStoryFilter.from_cli_args(
        WebPowerBenchmark.DEFAULT_STORY_CLS, args)
    self.assertEqual({story.name for story in story_filter.stories},
                     self._expected_canonical_stories())


class WebPowerBenchmarkTestCase(BaseWebPowerBenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self) -> type[WebPowerBenchmark]:
    return WebPowerBenchmark

  def test_kwargs_from_cli_defaults_instantiates_all_types(self) -> None:
    args = self.parse_args()
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)
    stories = kwargs["stories"]
    self.assertEqual(len(stories), 10)

    counts = {
        WebPowerIdleStory: 0,
        WebPowerScrollStory: 0,
        WebPowerPageLoadStory: 0,
        WebPowerMediaPlaybackStory: 0,
    }
    for story in stories:
      story_type = type(story)
      counts[story_type] += 1

    self.assertEqual(counts[WebPowerIdleStory], 3)
    self.assertEqual(counts[WebPowerScrollStory], 3)
    self.assertEqual(counts[WebPowerPageLoadStory], 3)
    self.assertEqual(counts[WebPowerMediaPlaybackStory], 1)

  def test_kwargs_from_cli_defaults_idle(self) -> None:
    kwargs = WebPowerBenchmark.kwargs_from_cli(self.parse_args())
    # We do not assert that a WebPowerIdleStory was found here;
    # test_kwargs_from_cli_defaults_instantiates_all_types ensures
    # we have at least one.
    for story in kwargs["stories"]:
      if not isinstance(story, WebPowerIdleStory):
        continue
      self.assertEqual(story.idle_duration, WebPowerIdleStory.DEFAULT_DURATION)
      self.assertEqual(story.stabilization_time,
                       story.site_config.default_stabilization_time)

  def test_kwargs_from_cli_defaults_scroll(self) -> None:
    kwargs = WebPowerBenchmark.kwargs_from_cli(self.parse_args())
    # test_kwargs_from_cli_defaults_instantiates_all_types ensures
    # we have at least one.
    for story in kwargs["stories"]:
      if not isinstance(story, WebPowerScrollStory):
        continue
      self.assertEqual(story.scroll_count,
                       WebPowerScrollStory.DEFAULT_SCROLL_COUNT)
      self.assertEqual(story.input_rate, WebPowerScrollStory.DEFAULT_INPUT_RATE)
      self.assertEqual(story.stabilization_time,
                       story.site_config.default_stabilization_time)

  def test_kwargs_from_cli_defaults_page_load(self) -> None:
    kwargs = WebPowerBenchmark.kwargs_from_cli(self.parse_args())
    # test_kwargs_from_cli_defaults_instantiates_all_types ensures
    # we have at least one.
    for story in kwargs["stories"]:
      if not isinstance(story, WebPowerPageLoadStory):
        continue
      expected_count = (
          WebPowerPageLoadStory.DEFAULT_CNN_PAGE_LOAD_COUNT
          if story.name.endswith("cnn") else
          WebPowerPageLoadStory.DEFAULT_PAGE_LOAD_COUNT)
      self.assertEqual(story.page_load_count, expected_count)
      self.assertEqual(story.interval, WebPowerPageLoadStory.DEFAULT_INTERVAL)
      self.assertEqual(story.stabilization_time,
                       story.site_config.default_stabilization_time)

  def test_kwargs_from_cli_defaults_media_playback(self) -> None:
    kwargs = WebPowerBenchmark.kwargs_from_cli(self.parse_args())
    # test_kwargs_from_cli_defaults_instantiates_all_types ensures
    # we have at least one.
    for story in kwargs["stories"]:
      if not isinstance(story, WebPowerMediaPlaybackStory):
        continue
      self.assertEqual(story.playback_duration,
                       WebPowerMediaPlaybackStory.DEFAULT_DURATION)
      self.assertEqual(story.stabilization_time,
                       story.site_config.default_stabilization_time)
      self.assertEqual(story.stats, WebPowerMediaPlaybackStory.DEFAULT_STATS)
      self.assertEqual(story.volume, WebPowerMediaPlaybackStory.DEFAULT_VOLUME)
      self.assertEqual(story.ambient_mode,
                       WebPowerMediaPlaybackStory.DEFAULT_AMBIENT_MODE)

  def test_kwargs_from_cli_custom_duration_override(self) -> None:
    # Specifying an explicit --duration should override duration for all tests
    # that support this flag. (Pick a value that would avoid false positives.)
    expected_duration: Final[int] = 42
    self.assertNotEqual(expected_duration,
                        WebPowerIdleStory.DEFAULT_DURATION.total_seconds())
    self.assertNotEqual(
        expected_duration,
        WebPowerMediaPlaybackStory.DEFAULT_DURATION.total_seconds())
    args = self.parse_args(f"--duration={expected_duration}s")
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)

    self.assertEqual(len(kwargs["stories"]), 10)
    for story in kwargs["stories"]:
      match story:
        case WebPowerIdleStory():
          self.assertEqual(story.idle_duration,
                           dt.timedelta(seconds=expected_duration))
        case WebPowerMediaPlaybackStory():
          self.assertEqual(story.playback_duration,
                           dt.timedelta(seconds=expected_duration))

  def test_kwargs_from_cli_custom_scenario_arguments(self) -> None:
    args = self.parse_args(
        "--stories=idle-msn,scroll-cnn,page-load-cnn,media-playback-youtube",
        "--duration=45s",
        "--stabilization-time=5s",
        "--scrolls=12",
        "--input-rate=120",
        "--page-loads=15",
        "--interval=4s",
        "--stats",
        "--volume=off",
        "--ambient-mode=unchanged",
    )
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)

    stories = kwargs["stories"]
    self.assertEqual(len(stories), 4)

    # 1. WebPowerIdleStory
    self.assertEqual(stories[0].name, "web-power-idle-msn")
    self.assertIsInstance(stories[0], WebPowerIdleStory)
    self.assertEqual(stories[0].idle_duration, dt.timedelta(seconds=45))
    self.assertEqual(stories[0].stabilization_time, dt.timedelta(seconds=5))

    # 2. WebPowerScrollStory
    self.assertEqual(stories[1].name, "web-power-scroll-cnn")
    self.assertIsInstance(stories[1], WebPowerScrollStory)
    self.assertEqual(stories[1].scroll_count, 12)
    self.assertEqual(stories[1].input_rate, 120)
    self.assertEqual(stories[1].stabilization_time, dt.timedelta(seconds=5))

    # 3. WebPowerPageLoadStory
    self.assertEqual(stories[2].name, "web-power-page-load-cnn")
    self.assertIsInstance(stories[2], WebPowerPageLoadStory)
    self.assertEqual(stories[2].page_load_count, 15)
    self.assertEqual(stories[2].interval, dt.timedelta(seconds=4))
    self.assertEqual(stories[2].stabilization_time, dt.timedelta(seconds=5))

    # 4. WebPowerMediaPlaybackStory
    self.assertEqual(stories[3].name, "web-power-media-playback-youtube")
    self.assertIsInstance(stories[3], WebPowerMediaPlaybackStory)
    self.assertEqual(stories[3].playback_duration, dt.timedelta(seconds=45))
    self.assertEqual(stories[3].stabilization_time, dt.timedelta(seconds=5))
    self.assertTrue(stories[3].stats)
    self.assertEqual(stories[3].volume, VolumeMode.OFF)
    self.assertEqual(stories[3].ambient_mode, AmbientMode.UNCHANGED)

  def test_extra_flags_story_autoplay_assignment(self) -> None:
    args = self.parse_args(
        "--stories=idle-msn,page-load-cnn,media-playback-youtube")
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)
    benchmark = WebPowerBenchmark(**kwargs)

    for story in benchmark.stories:
      flags = benchmark.extra_flags(BrowserAttributes.CHROMIUM_BASED, story)
      is_playback = isinstance(story, WebPowerMediaPlaybackStory)
      self.assertEqual("--autoplay-policy" in flags, is_playback)
      if is_playback:
        self.assertEqual(flags["--autoplay-policy"], "no-user-gesture-required")

  def test_kwargs_from_cli_fullscreen(self) -> None:
    args = self.parse_args(
        "--stories=media-playback-youtube",
        "--fullscreen",
    )
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertTrue(story.fullscreen)

    args = self.parse_args(
        "--stories=media-playback-youtube",
        "--no-fullscreen",
    )
    kwargs = WebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertFalse(story.fullscreen)

  def test_kwargs_from_cli_benchmark_version(self) -> None:
    parser = WebPowerBenchmark.add_cli_arguments(CBArgumentParser())
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      with self.assertRaises((SystemExit, SysExitTestException)):
        parser.parse_args(["--benchmark-version"])
      self.assertIn(VERSION_STRING, mock_stdout.getvalue())

  def test_from_cli_args_combined_options(self) -> None:
    args = self.parse_args(
        "--stories=idle-msn,scroll-cnn,page-load-cnn,media-playback-youtube",
        "--duration=50s",
        "--stabilization-time=8s",
        "--scrolls=14",
        "--input-rate=110",
        "--page-loads=16",
        "--interval=5s",
        "--stats",
        "--volume=off",
        "--ambient-mode=on",
        "--no-fullscreen",
    )
    benchmark = WebPowerBenchmark.from_cli_args(args)
    stories = benchmark.stories
    self.assertEqual(len(stories), 4)

    self.assertIsInstance(stories[0], WebPowerIdleStory)
    self.assertEqual(stories[0].name, "web-power-idle-msn")
    self.assertEqual(stories[0].idle_duration, dt.timedelta(seconds=50))
    self.assertEqual(stories[0].stabilization_time, dt.timedelta(seconds=8))

    self.assertIsInstance(stories[1], WebPowerScrollStory)
    self.assertEqual(stories[1].name, "web-power-scroll-cnn")
    self.assertEqual(stories[1].scroll_count, 14)
    self.assertEqual(stories[1].input_rate, 110)
    self.assertEqual(stories[1].stabilization_time, dt.timedelta(seconds=8))

    self.assertIsInstance(stories[2], WebPowerPageLoadStory)
    self.assertEqual(stories[2].name, "web-power-page-load-cnn")
    self.assertEqual(stories[2].page_load_count, 16)
    self.assertEqual(stories[2].interval, dt.timedelta(seconds=5))
    self.assertEqual(stories[2].stabilization_time, dt.timedelta(seconds=8))

    self.assertIsInstance(stories[3], WebPowerMediaPlaybackStory)
    self.assertEqual(stories[3].name, "web-power-media-playback-youtube")
    self.assertEqual(stories[3].playback_duration, dt.timedelta(seconds=50))
    self.assertEqual(stories[3].stabilization_time, dt.timedelta(seconds=8))
    self.assertTrue(stories[3].stats)
    self.assertEqual(stories[3].volume, VolumeMode.OFF)
    self.assertEqual(stories[3].ambient_mode, AmbientMode.ON)
    self.assertFalse(stories[3].fullscreen)


class WebPowerConsolidatedCliTestCase(BaseCliTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.setup_config_dir(QUERIES_DIR / "web_power")
    perfetto_basic = (
        config.config_dir() / "benchmark/web_power/perfetto_basic.txtpb")
    if not self.fs.exists(perfetto_basic):
      self.fs.create_file(perfetto_basic, contents="duration_ms: 1000")
    self.fs.add_real_file(WebPowerProbe.METRIC_DEFINITIONS_FILE)
    self.fs.add_real_file(WebPowerBenchmark.required_device_config())
    mock_archive = pth.LocalPath("/mock/archive.wprgo")
    self.fs.create_file(mock_archive)
    archive_patcher = mock.patch(
        "crossbench.network.replay.base.ReplayNetwork.ensure_archive",
        return_value=mock_archive)
    self.addCleanup(archive_patcher.stop)
    archive_patcher.start()
    wpr_patcher = mock.patch(
        "crossbench.network.replay.wpr.WprGoFinder.wpr",
        return_value=pth.LocalPath("/mock/wpr.go"))
    self.addCleanup(wpr_patcher.stop)
    wpr_patcher.start()
    tp_validate_patcher = mock.patch.object(
        TraceProcessorProbe, "validate_env", return_value=None)
    self.addCleanup(tp_validate_patcher.stop)
    tp_validate_patcher.start()
    # Prevent BitsProbe from enforcing Android or attempting to launch the
    # BITS daemon / query devices during mock CLI dry-runs.
    bits_validate_patcher = mock.patch.object(
        BitsProbe, "validate_browser", return_value=None)
    self.addCleanup(bits_validate_patcher.stop)
    bits_validate_patcher.start()
    bits_setup_patcher = mock.patch.object(
        BitsProbe, "setup", return_value=None)
    self.addCleanup(bits_setup_patcher.stop)
    bits_setup_patcher.start()

  def _get_runner_probe_names(self, *extra_args: str) -> tuple[str, ...]:
    with self._patch_get_browser_cls():
      cli = self.run_cli(
          "web-power",
          "--stories=idle-cnn",
          "--browser=chrome",
          "--fast",
          "--dry-run",
          *extra_args,
      )
      subcommand = cli.last_subcommand
      assert isinstance(subcommand, BenchmarkSubcommand)
      return tuple(p.name for p in subcommand.runner.probes)

  def test_default_probe_setup(self) -> None:
    probe_names = self._get_runner_probe_names()
    self.assertIn("perfetto", probe_names)
    self.assertIn("trace_processor", probe_names)
    self.assertIn("web_power_probe", probe_names)

  def test_no_probe_flag(self) -> None:
    probe_names = self._get_runner_probe_names("--no-probe=perfetto")
    self.assertNotIn("perfetto", probe_names)
    self.assertNotIn("trace_processor", probe_names)

  def test_bits_path_suppresses_perfetto(self) -> None:
    bits_path = pth.LocalPath("/mock/bits")
    self.fs.create_file(bits_path)
    probe_names = self._get_runner_probe_names(f"--bits-path={bits_path}")
    self.assertIn("bits", probe_names)
    self.assertNotIn("perfetto", probe_names)

  def test_explicit_perfetto_probe(self) -> None:
    probe_names = self._get_runner_probe_names("--probe=perfetto")
    self.assertEqual(probe_names.count("perfetto"), 1)
    self.assertIn("trace_processor", probe_names)

  def test_bits_path_with_explicit_perfetto_probe(self) -> None:
    bits_path = pth.LocalPath("/mock/bits")
    self.fs.create_file(bits_path)
    probe_names = self._get_runner_probe_names(f"--bits-path={bits_path}",
                                               "--probe=perfetto")
    self.assertIn("bits", probe_names)
    self.assertIn("perfetto", probe_names)
    self.assertIn("trace_processor", probe_names)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
