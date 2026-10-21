# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, ClassVar, Final, Sequence

from typing_extensions import override

from crossbench import config
from crossbench.action_runner.action.enums import ReadyState
from crossbench.benchmarks.base import StoryFilter, SubStoryBenchmark
from crossbench.cli.ui.ui import timer
from crossbench.flags.base import Flags
from crossbench.parse import DurationParser
from crossbench.stories.story import Story

if TYPE_CHECKING:
  import argparse

  from crossbench import path as pth
  from crossbench.action_runner.config import ActionRunnerConfig
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.runner.run import Run

UNMUTE_AUDIO_SCRIPT: Final[str] = """
  document.getElementById('unmuteButton').click();
"""

REMUTE_AUDIO_SCRIPT: Final[str] = """
  document.getElementById('audio').muted = true;
"""


class PowerlineStory(Story):
  STORY_NAME = "podcast_vorbis_remute"
  URL_BASE = "https://chromium-workloads.web.app/web-tests/main/synthetic/powerline/"
  STORY_URLS = {
      # No activity except for the browser
      "scenario_idle": "index.html",
      # Media playback cases (screen on)
      "media_vp9_720p": "media-vp9-720p.html",
      "media_vp9_480p": "media-vp9-480p.html",
      "media_vp9_360p": "media-vp9-360p.html",
      "media_vp9_240p": "media-vp9-240p.html",
      "media_av1_1080p": "media-av1-1080p.html",
      "media_av1_720p": "media-av1-720p.html",
      "media_av1_480p": "media-av1-480p.html",
      "media_av1_360p": "media-av1-360p.html",
      "media_av1_240p": "media-av1-240p.html",
      "media_h264_1080p": "media-h264-1080p.html",
      "media_h264_720p": "media-h264-720p.html",
      "media_h265_1080p": "media-h265-1080p.html",
      "media_h265_720p": "media-h265-720p.html",
      "media_multistream_2up": "media-multistream-2up.html",
      "media_multistream_3up": "media-multistream-3up.html",
      "media_multistream_6up": "media-multistream-6up.html",
      # Media playback cases (screen off)
      "podcast_vorbis": "podcast-vorbis.html",
      "podcast_vorbis_muted": "podcast-vorbis.html",
      "podcast_opus": "podcast-opus.html",
      "podcast_mp3": "podcast-mp3.html",
      "podcast_aac": "podcast-aac.html",
  }

  def __init__(self,
               story_name: str,
               duration: dt.timedelta | None = dt.timedelta()):
    duration = (duration or dt.timedelta(seconds=60))
    super().__init__(story_name, duration)

  def run(self, run: Run) -> None:
    if self.is_podcast_story(run.story.name):
      self.run_podcast(run)
    else:
      self.run_media(run)

  def run_media(self, run: Run) -> None:
    with timer():
      with run.actions("Show URL") as actions:
        actions.show_url(self.url_from_story(run.story.name))
      with run.actions("Autoplay") as actions:
        actions.wait_for_ready_state(
            ReadyState.COMPLETE, timeout=dt.timedelta(seconds=5))
      with run.actions("Screen") as actions:
        actions.wait(self.duration)

  def run_podcast(self, run: Run) -> None:
    with timer():
      with run.actions("Show URL") as actions:
        actions.show_url(self.url_from_story(run.story.name))
      with run.actions("Autoplay") as actions:
        actions.wait_for_ready_state(
            ReadyState.COMPLETE, timeout=dt.timedelta(seconds=5))
        actions.js(UNMUTE_AUDIO_SCRIPT)
      if self.should_remute(run.story.name):
        with run.actions("Remute") as actions:
          actions.wait(dt.timedelta(seconds=5))
          actions.js(REMUTE_AUDIO_SCRIPT)
      with run.actions("Screen") as actions:
        actions.wait(dt.timedelta(seconds=5))
        with actions.platform.low_power_mode():
          # Put the screen to sleep and enter simulated Doze
          actions.wait(self.duration)

  @classmethod
  def url_from_story(cls, name: str) -> str:
    return cls.URL_BASE + cls.STORY_URLS[name]

  @classmethod
  def should_remute(cls, name: str) -> bool:
    return name.endswith("_muted")

  @classmethod
  def is_podcast_story(cls, name: str) -> bool:
    return name.startswith("podcast_")

  @classmethod
  @override
  def all_story_names(cls) -> tuple[str, ...]:
    return tuple(sorted(cls.STORY_URLS))


class PowerlineStoryFilter(StoryFilter[PowerlineStory]):
  """Story filter for the Powerline benchmark."""

  def __init__(
      self,
      story_cls: type[PowerlineStory],
      patterns: Sequence[str],
      args: argparse.Namespace,
      separate: bool = False,
      run_for: dt.timedelta | None = dt.timedelta(),
      tags: Sequence[str] = (),
  ) -> None:
    assert issubclass(story_cls, PowerlineStory)
    self._run_for: Final[dt.timedelta | None] = run_for
    super().__init__(story_cls, patterns, args, separate, tags)

  @override
  def stories_from_names(self,
                         names: Sequence[str]) -> tuple[PowerlineStory, ...]:
    return tuple(self.story_cls(name, self._run_for) for name in names)

  @classmethod
  @override
  def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["run_for"] = args.run_for
    return kwargs

  @classmethod
  @override
  def add_cli_arguments(
      cls, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = super().add_cli_arguments(parser)
    parser.add_argument(
        "--run-for",
        "--stop-after",
        "--duration",
        type=DurationParser.positive_duration,
        help="How long to run the power measurements for",
    )
    return parser


class PowerlineBenchmark(SubStoryBenchmark):
  """
  Benchmark runner for the Powerline background power-consumption test.

  This test opens different pages intended to simulate light media
  playback and idle activity and measures the on-device power rails.
  """
  NAME: ClassVar = "powerline"
  DEFAULT_STORY_CLS: ClassVar = PowerlineStory
  STORY_FILTER_CLS: ClassVar = PowerlineStoryFilter

  # TODO: we may want to check somehow that the device is a Pixel and therefore
  # has meaningful power rails we can read.

  def __init__(self,
               stories: Sequence[PowerlineStory],
               action_runner_config: ActionRunnerConfig | None = None) -> None:
    super().__init__(stories, action_runner_config)

  @classmethod
  def _base_dir(cls) -> pth.LocalPath:
    return config.config_dir() / "benchmark" / "powerline"

  @classmethod
  @override
  def default_probe_config_path(cls) -> pth.LocalPath:
    return cls._base_dir() / "probe_config.hjson"

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    del story
    # This flag is required because Chrome a) does not autoplay based on the
    #  HTML5 tag and b) it will not play from JavaScript if the user does not
    # interact with the page first. https://developer.chrome.com/blog/autoplay
    browser_attributes.assert_chromium_based()
    return Flags({
        "--autoplay-policy": "no-user-gesture-required",
        "--enable-renderer-backgrounding": None,
        "--enable-background-timer-throttling": None,
    })

  @classmethod
  @override
  def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
    super().add_cli_arguments(parser)
    cls.STORY_FILTER_CLS.add_cli_arguments(parser)
    return parser
