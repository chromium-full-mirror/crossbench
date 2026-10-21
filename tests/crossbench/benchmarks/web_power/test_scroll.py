# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import unittest.mock as mock

from typing_extensions import override

from crossbench.benchmarks.web_power.base import WebPowerSiteConfig
from crossbench.benchmarks.web_power.scroll import WebPowerScrollBenchmark, \
    WebPowerScrollStory
from crossbench.cli.config.browser import BrowserConfig
from crossbench.cli.config.driver import DriverConfig
from crossbench.cli.config.driver_type import BrowserDriverType
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.ios import IOSPlatform
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.benchmarks.web_power.test_base import \
    BaseWebPowerBenchmarkTestCase, MockWebPowerStory


class WebPowerScrollStoryTestCase(BaseCrossbenchTestCase):

  def test_instantiate_default(self) -> None:
    story = WebPowerScrollStory(
        name_suffix="test",
        site_config=WebPowerSiteConfig(url="https://www.cnn.com"),
    )
    self.assertEqual(story.url, "https://www.cnn.com")
    self.assertEqual(story.scroll_count, story.DEFAULT_SCROLL_COUNT)
    self.assertEqual(story.input_rate, story.DEFAULT_INPUT_RATE)

  def test_instantiate_custom(self) -> None:
    story = WebPowerScrollStory(
        name_suffix="test",
        site_config=WebPowerSiteConfig(url="https://www.cnn.com"),
        scroll_count=10,
        input_rate=120,
    )
    self.assertEqual(story.url, "https://www.cnn.com")
    self.assertEqual(story.scroll_count, 10)
    self.assertEqual(story.input_rate, 120)

  def test_setup_unsupported_platform(self) -> None:
    story = WebPowerScrollStory(
        name_suffix="test",
        site_config=WebPowerSiteConfig(url="https://www.cnn.com"),
    )
    mock_run = mock.MagicMock()
    mock_run.browser_platform.is_android = False
    mock_run.browser_platform.is_ios = False
    with self.assertRaisesRegex(
        RuntimeError,
        "only supported on Android and iOS",
    ):
      story.setup(mock_run)

  def test_setup_and_run_ios(self) -> None:
    story = WebPowerScrollStory(
        name_suffix="test",
        site_config=WebPowerSiteConfig(url="https://www.cnn.com"),
    )
    mock_run = mock.MagicMock()
    mock_ios_platform = mock.MagicMock(spec=IOSPlatform)
    mock_ios_platform.is_android = False
    mock_ios_platform.is_ios = True
    mock_ios_platform.display_resolution.return_value = DisplayResolution(
        400, 800)
    mock_run.browser_platform = mock_ios_platform

    story.setup(mock_run)
    mock_ios_platform.wda.ensure_session.assert_called_once()

    story.run(mock_run)
    mock_ios_platform.display_resolution.assert_called_once()
    expected_cycle = [(200, 640, 200, 160)] * 5 + [(200, 160, 200, 640)] * 5
    mock_ios_platform.wda.swipe_sequence.assert_called_once_with(
        expected_cycle * 5,
        duration=dt.timedelta(milliseconds=750),
        settle_duration=dt.timedelta(milliseconds=150),
        lift_duration=dt.timedelta(milliseconds=100),
    )

  def test_setup_ios_warns_on_custom_input_rate(self) -> None:
    story = WebPowerScrollStory(
        name_suffix="test",
        site_config=WebPowerSiteConfig(url="https://www.cnn.com"),
        input_rate=120,
    )
    mock_run = mock.MagicMock()
    mock_run.browser_platform = mock.MagicMock(spec=IOSPlatform)
    with self.assertLogs(level="WARNING") as logs:
      story.setup(mock_run)
    self.assertTrue(any("--input-rate" in line for line in logs.output))


class WebPowerScrollBenchmarkTestCase(BaseWebPowerBenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self) -> type[WebPowerScrollBenchmark]:
    return WebPowerScrollBenchmark

  def test_kwargs_from_cli_defaults(self) -> None:
    args = self.parse_args("--site", "cnn")
    kwargs = WebPowerScrollBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.url, "https://www.cnn.com")
    self.assertEqual(story.scroll_count,
                     WebPowerScrollStory.DEFAULT_SCROLL_COUNT)
    self.assertEqual(story.input_rate, WebPowerScrollStory.DEFAULT_INPUT_RATE)
    self.assertEqual(story.stabilization_time,
                     story.site_config.default_stabilization_time)

  def test_kwargs_from_cli_custom(self) -> None:
    args = self.parse_args(
        "--site=cnn",
        "--scrolls=12",
        "--input-rate=100",
        "--stabilization-time=15s",
    )
    kwargs = WebPowerScrollBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.url, "https://www.cnn.com")
    self.assertEqual(story.scroll_count, 12)
    self.assertEqual(story.input_rate, 100)
    self.assertEqual(story.stabilization_time, dt.timedelta(seconds=15))

  def test_kwargs_from_cli_aliases(self) -> None:
    args = self.parse_args(
        "--site=cnn",
        "--scroll-count=15",
        "--rate=90",
    )
    kwargs = WebPowerScrollBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.scroll_count, 15)
    self.assertEqual(story.input_rate, 90)

  def test_kwargs_from_cli_scrolls_invalid(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "--scrolls"):
      self.parse_args("--scrolls=-1")
    with self.assertRaisesRegex(argparse.ArgumentError, "--scrolls"):
      self.parse_args("--scrolls=0")
    with self.assertRaisesRegex(argparse.ArgumentError, "--scrolls"):
      self.parse_args("--scrolls=foo")
    with self.assertRaisesRegex(argparse.ArgumentError, "--scroll-count"):
      self.parse_args("--scroll-count=-1")
    with self.assertRaisesRegex(argparse.ArgumentError, "--scroll-count"):
      self.parse_args("--scroll-count=0")
    with self.assertRaisesRegex(argparse.ArgumentError, "--scroll-count"):
      self.parse_args("--scroll-count=foo")

  def test_kwargs_from_cli_input_rate_invalid(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "--input-rate"):
      self.parse_args("--input-rate=-100")
    with self.assertRaisesRegex(argparse.ArgumentError, "--input-rate"):
      self.parse_args("--input-rate=0")
    with self.assertRaisesRegex(argparse.ArgumentError, "--input-rate"):
      self.parse_args("--input-rate=bar")
    with self.assertRaisesRegex(argparse.ArgumentError, "--rate"):
      self.parse_args("--rate=-100")
    with self.assertRaisesRegex(argparse.ArgumentError, "--rate"):
      self.parse_args("--rate=0")
    with self.assertRaisesRegex(argparse.ArgumentError, "--rate"):
      self.parse_args("--rate=bar")

  def test_from_cli_args(self) -> None:
    args = self.parse_args(
        "--site=cnn",
        "--scroll-count=8",
        "--rate=60",
    )
    benchmark = WebPowerScrollBenchmark.from_cli_args(args)
    self.assertEqual(len(benchmark.stories), 1)
    story = benchmark.stories[0]
    self.assertIsInstance(story, WebPowerScrollStory)
    self.assertEqual(story.scroll_count, 8)
    self.assertEqual(story.input_rate, 60)

  def test_configure_ios_browsers_upgrades_to_wda(self) -> None:
    args = self.parse_args("--site=cnn")
    with mock.patch.object(DriverConfig, "validate_ios"):
      ios_driver = DriverConfig(BrowserDriverType.IOS, device_id="00001111")
      args.browser = [BrowserConfig("safari", ios_driver)]
      WebPowerScrollBenchmark.kwargs_from_cli(args)
    self.assertEqual(args.browser[0].driver.driver_type,
                     BrowserDriverType.IOS_WDA)

  def test_configure_ios_browsers_mixed_wda_raises(self) -> None:
    args = self.parse_args("--site=cnn")
    with mock.patch.object(DriverConfig, "validate_ios"):
      ios_driver = DriverConfig(BrowserDriverType.IOS, device_id="00001111")
    args.browser = [BrowserConfig("safari", ios_driver)]
    site_cfg = WebPowerSiteConfig(url="https://www.cnn.com")
    stories = [
        WebPowerScrollStory("cnn", site_cfg),
        MockWebPowerStory("cnn", site_cfg),
    ]
    with self.assertRaisesRegex(ValueError,
                                "Cannot mix WDA and non-WDA stories on iOS."):
      WebPowerScrollBenchmark._configure_ios_browsers(args, stories)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
