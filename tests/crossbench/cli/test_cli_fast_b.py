# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
from typing import TYPE_CHECKING, Any, Callable, Sequence
from unittest import mock

import hjson

from crossbench import path as pth
from crossbench import plt
from crossbench.benchmarks.base import Benchmark
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark
from crossbench.benchmarks.speedometer.speedometer_3_1 import \
    Speedometer31Benchmark, Speedometer31Story
from crossbench.browsers import viewport
from crossbench.browsers.splash_screen import SplashScreen, URLSplashScreen
from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.config.browser import BrowserConfig
from crossbench.cli.config.driver import DriverConfig
from crossbench.cli.config.driver_type import BrowserDriverType
from crossbench.cli.config.network import NetworkConfig, NetworkType
from crossbench.cli.subcommand.benchmark import BenchmarkSubcommand
from crossbench.env.runner_env import ValidationMode
from crossbench.network.local_file_server import LocalFileNetwork
from crossbench.parse import LateArgumentError
from crossbench.probes.internal.summary import ResultsSummaryProbe
from crossbench.probes.power_sampler import PowerSamplerProbe
from crossbench.runner.runner import Runner
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.base import BaseCliTestCase, SysExitTestException
from tests.crossbench.cli.config.base import IOS_DEVICES_SINGLE_OUTPUT
from tests.crossbench.mock_helper import MockStory

if TYPE_CHECKING:
  from crossbench.cli.parser import CBArgumentParser


class FastCliTestCasePartB(BaseCliTestCase):
  """These tests are run as part of the presubmit and should be
  reasonably fast.
  Slow tests run on the CQ are in CliSlowTestCase.

  Keep FastCliTestCasePartA and FastCliTestCasePartB balanced for faster local
  presubmit checks.
  """

  def _expect_mock_browsers(
      self,
      mock_browsers: Sequence[type[mock_browser.MockBrowser]],
  ) -> Callable[[BrowserConfig], type[mock_browser.MockBrowser]]:

    def mock_get_browser_cls(
        browser_config: BrowserConfig) -> type[mock_browser.MockBrowser]:
      self.assertEqual(browser_config.driver.driver_type,
                       BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.mock_app_path(self.platform) == browser_config.path:
          return mock_browser_cls
      raise ValueError(f"Unknown browser path: {browser_config.path}")

    return mock_get_browser_cls

  def test_custom_chrome_browser_binary(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    browser_bin = browser_cls.mock_app_path(
        self.platform).with_stem("Custom Google Chrome")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")

    with self._patch_get_browser_cls(browser_cls) as get_browser_cls:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--env-validation=skip")
    get_browser_cls.assert_called_once_with(
        BrowserConfig(browser_bin, DriverConfig.default()))

  def test_custom_chrome_browser_binary_custom_flags(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    browser_bin = browser_cls.mock_app_path(
        self.platform).with_stem("Custom Google Chrome")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")

    with self._patch_get_browser_cls(browser_cls), mock.patch.object(
        BenchmarkSubcommand, "_run_benchmark") as run_benchmark:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--env-validation=skip", "--",
                   "--chrome-flag1=value1", "--chrome-flag2")
    run_benchmark.assert_called_once()
    runner = run_benchmark.call_args[0][1]
    self.assertIsInstance(runner, Runner)
    self.assertEqual(len(runner.browsers), 1)
    browser = runner.browsers[0]
    self.assertSequenceEqual(["--chrome-flag1=value1", "--chrome-flag2"],
                             list(browser.flags))

  def test_browser_identifiers_duplicate(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      self.run_cli("loading", "--browser=chrome", "--browser=chrome",
                   "--urls=http://test.com", "--env-validation=skip", "--throw")

  def _run_speedometer_cli(self, *args: str) -> Runner:
    with self._patch_get_browser_cls(
        mock_browser.MockChromeStable), mock.patch.object(
            BenchmarkSubcommand, "_run_benchmark") as run_benchmark:
      self.run_cli("sp3.1", "--browser=chrome", "--env-validation=skip", *args)
    run_benchmark.assert_called_once()
    runner = run_benchmark.call_args[0][1]
    self.assertIsInstance(runner, Runner)
    return runner

  def _create_speedometer_checkout(self) -> pth.LocalPath:
    assert Speedometer31Benchmark.LOCAL_DIR
    local_dir = pth.LocalPath(pth.ROOT_DIR) / Speedometer31Benchmark.LOCAL_DIR
    self.fs.create_file(local_dir / "index.html")
    return local_dir

  def test_speedometer_default_local_file_server(self):
    self._create_speedometer_checkout()
    runner = self._run_speedometer_cli()
    benchmark = runner.benchmark
    self.assertIsInstance(benchmark, Speedometer31Benchmark)
    self.assertIsNone(benchmark.custom_url)
    self.assertTrue(runner.browsers[0].network.is_local_file_server)

  def test_speedometer_default_no_checkout(self):
    with self._patch_get_browser_cls(mock_browser.MockChromeStable):
      with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                  "local-serve dir"):
        self.run_cli("sp3.1", "--browser=chrome", "--env-validation=skip",
                     "--throw")
      _, _, stderr = self.run_cli_output(
          "sp3.1",
          "--browser=chrome",
          "--env-validation=skip",
          raises=SysExitTestException)
    self.assertIn("local-serve dir", stderr)

  def test_speedometer_live_url_explicit(self):
    self._create_speedometer_checkout()
    runner = self._run_speedometer_cli("--live")
    benchmark = runner.benchmark
    self.assertIsInstance(benchmark, Speedometer31Benchmark)
    self.assertEqual(benchmark.custom_url, Speedometer31Story.URL)
    self.assertTrue(runner.browsers[0].network.is_live)

  def test_speedometer_explicit_network_wins(self):
    self._create_speedometer_checkout()
    other_dir = pth.LocalPath("/other/benchmark")
    self.fs.create_file(other_dir / "index.html")
    runner = self._run_speedometer_cli(f"--local-file-server={other_dir}")
    self.assertIsNone(runner.benchmark.custom_url)
    network = runner.browsers[0].network
    assert isinstance(network, LocalFileNetwork)
    self.assertEqual(network.path, other_dir)

  def test_browser_identifiers_multiple(self):
    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockChromeBeta,
        mock_browser.MockChromeDev,
    ]

    with self._patch_get_browser_cls(
        side_effect=self._expect_mock_browsers(
            mock_browsers)) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-beta",
                   "--browser=chrome-stable", "--browser=chrome-dev",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}", "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      # Example:  BROWSER / "cb.results.json"
      result_files = list(
          self.out_dir.glob(f"*/*/{ResultsSummaryProbe.NAME}.json"))
      self.assertEqual(len(result_files), 3)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 3)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_and_browser_config(self) -> None:
    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockChromeDev,
    ]

    browser_config_data = {
        "browsers": {
            "chrome_stable_config": {
                "path": "chrome-stable",
                "flags": ["--no-sandbox"],
            },
        },
    }
    config_file = pth.LocalPath("/browser_config.hjson")
    config_file.write_text(hjson.dumps(browser_config_data), encoding="utf-8")

    with self._patch_get_browser_cls(
        side_effect=self._expect_mock_browsers(
            mock_browsers)) as get_browser_cls:
      url = "http://test.com"
      cli = self.run_cli("loading", "--browser=chrome-dev",
                         f"--browser-config={config_file}", f"--urls={url}",
                         "--js-flags=--log-maps", "--env-validation=skip",
                         f"--out-dir={self.out_dir}", "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()

      browsers = cli.last_subcommand.runner.browsers
      self.assertEqual(len(browsers), 2)
      self.assertEqual(browsers[0].label, "chrome_stable_config")
      self.assertIsInstance(browsers[0], mock_browser.MockChromeStable)
      self.assertIn("--no-sandbox", browsers[0].flags)
      self.assertNotIn("--log-maps", browsers[0].js_flags)

      self.assertIsInstance(browsers[1], mock_browser.MockChromeDev)
      self.assertIn("--log-maps", browsers[1].js_flags)
      self.assertNotIn("--no-sandbox", browsers[1].flags)

  def test_browser_browser_config_browser(self) -> None:
    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockChromeDev,
        mock_browser.MockChromeBeta,
    ]

    browser_config_data = {
        "browsers": {
            "chrome_stable_config": {
                "path": "chrome-stable",
                "flags": ["--disable-gpu"],
            },
        },
    }
    config_file = pth.LocalPath("/browser_config_multi.hjson")
    config_file.write_text(hjson.dumps(browser_config_data), encoding="utf-8")

    with self._patch_get_browser_cls(
        side_effect=self._expect_mock_browsers(
            mock_browsers)) as get_browser_cls:
      url = "http://test.com"
      cli = self.run_cli("loading", "--browser=chrome-dev",
                         f"--browser-config={config_file}",
                         "--browser=chrome-beta", f"--urls={url}",
                         "--js-flags=--log-deopt", "--env-validation=skip",
                         f"--out-dir={self.out_dir}", "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()

      browsers = cli.last_subcommand.runner.browsers
      self.assertEqual(len(browsers), 3)
      self.assertEqual(browsers[0].label, "chrome_stable_config")
      self.assertIsInstance(browsers[0], mock_browser.MockChromeStable)
      self.assertIn("--disable-gpu", browsers[0].flags)
      self.assertNotIn("--log-deopt", browsers[0].js_flags)

      self.assertIsInstance(browsers[1], mock_browser.MockChromeDev)
      self.assertIn("--log-deopt", browsers[1].js_flags)
      self.assertNotIn("--disable-gpu", browsers[1].flags)

      self.assertIsInstance(browsers[2], mock_browser.MockChromeBeta)
      self.assertIn("--log-deopt", browsers[2].js_flags)
      self.assertNotIn("--disable-gpu", browsers[2].flags)

  def test_browser_identifiers_multiple_same_major_version(self):

    class MockChromeBeta2(mock_browser.MockChromeBeta):
      VERSION = "100.22.33.100"

    class MockChromeDev2(mock_browser.MockChromeDev):
      VERSION = "100.22.33.200"

    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        MockChromeBeta2,
        MockChromeDev2,
    ]

    with self._patch_get_browser_cls(
        side_effect=self._expect_mock_browsers(
            mock_browsers)) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-dev", "--browser=chrome-beta",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}", "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      # Example:  BROWSER / "cb.results.json"
      result_files = list(
          self.out_dir.glob(f"*/*/{ResultsSummaryProbe.NAME}.json"))
      self.assertEqual(len(result_files), 2)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 2)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_identifiers_multiple_same_version(self):

    class MockChromeBeta2(mock_browser.MockChromeBeta):
      VERSION = "100.22.33.999"

    class MockChromeDev2(mock_browser.MockChromeDev):
      VERSION = "100.22.33.999"

    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        MockChromeBeta2,
        MockChromeDev2,
    ]

    with self._patch_get_browser_cls(
        side_effect=self._expect_mock_browsers(
            mock_browsers)) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-dev", "--browser=chrome-beta",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}", "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      # Example:  BROWSER / "cb.results.json"
      result_files = list(
          self.out_dir.glob(f"*/*/{ResultsSummaryProbe.NAME}.json"))
      self.assertEqual(len(result_files), 2)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 1)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_different_drivers(self):

    def mock_get_browser_cls(browser_config: BrowserConfig):
      if browser_config.driver.driver_type == BrowserDriverType.IOS:
        self.assertEqual(
            browser_config.path,
            mock_browser.MockChromeStable.mock_app_path(self.platform))
        return mock_browser.MockChromeStable
      if browser_config.driver.driver_type == BrowserDriverType.WEB_DRIVER:
        self.assertEqual(
            browser_config.path,
            mock_browser.MockChromeBeta.mock_app_path(self.platform))
        return mock_browser.MockChromeBeta
      self.assertEqual(browser_config.driver.driver_type,
                       BrowserDriverType.APPLE_SCRIPT)
      self.assertEqual(browser_config.path,
                       mock_browser.MockChromeDev.mock_app_path(self.platform))
      return mock_browser.MockChromeDev

    with (mock.patch(
        "crossbench.cli.config.driver.ios_devices",
        return_value=IOS_DEVICES_SINGLE_OUTPUT),
          mock.patch(
              "crossbench.plt.ios.ios_devices",
              return_value=IOS_DEVICES_SINGLE_OUTPUT),
          self._patch_get_browser_cls(side_effect=mock_get_browser_cls) as
          get_browser_cls):
      url = "http://test.com"
      self.run_cli("loading", "--browser=ios:chrome-stable",
                   "--browser=selenium:chrome-beta",
                   "--browser=applescript:chrome-dev", f"--urls={url}",
                   "--env-validation=skip", f"--out-dir={self.out_dir}",
                   "--no-symlinks")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      # Example:  BROWSER / "cb.results.json"
      result_files = list(
          self.out_dir.glob(f"*/*/{ResultsSummaryProbe.NAME}.json"))
      self.assertEqual(len(result_files), 3)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 1)
      self.assertIn(mock_browser.MockChromeStable.VERSION, versions)
      self.assertIn(mock_browser.MockChromeBeta.VERSION, versions)
      self.assertIn(mock_browser.MockChromeDev.VERSION, versions)

  def test_probe_invalid_inline_json_config(self):
    with self.assertRaises(
        argparse.ArgumentError) as cm, self._patch_get_browser():
      self.run_cli("loading", "--probe=v8.log{invalid json: d a t a}",
                   "--urls=cnn", "--env-validation=skip", "--throw")
    message = str(cm.exception)
    self.assertIn("{invalid json: d a t a}", message)

  def test_probe_empty_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    with self._patch_get_browser():
      url = "http://test.com"
      self.run_cli("loading", "--probe=v8.log{}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertSequenceEqual([url], browser.url_list[self.SPLASH_URLS_LEN:])
        for flag in js_flags:
          self.assertNotIn(flag, browser.js_flags)

  def test_probe_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    json_config = json.dumps({"js_flags": js_flags})
    with self._patch_get_browser():
      url = "http://test.com"
      self.run_cli("loading", f"--probe=v8.log{json_config}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertSequenceEqual([url], browser.url_list[self.SPLASH_URLS_LEN:])
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_env_config_name(self):
    with self._patch_get_browser():
      self.run_cli("loading", "--env=strict", "--urls=http://test.com",
                   "--env-validation=skip", "--throw")

  def test_env_config_inline_hjson(self):
    with self._patch_get_browser():
      self.run_cli("loading", '--env={"power_use_battery":false}',
                   "--urls=http://test.com", "--env-validation=skip")

  def test_env_config_inline_invalid(self):
    with self.cli() as cli:
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            "--env=not a valid name",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            "--env={not valid hjson}",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            "--env={unknown_property:1}",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])

  def test_conflicting_driver_path(self):
    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockFirefox,
    ]

    def mock_get_browser_cls(browser_config: BrowserConfig):
      self.assertEqual(browser_config.driver.driver_type,
                       BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.mock_app_path(self.platform) == browser_config.path:
          return mock_browser_cls
      raise ValueError("Unknown browser path")

    driver_path = self.out_dir / "driver"
    self.fs.create_file(driver_path, st_size=1024)
    with self.assertRaises(LateArgumentError) as cm:
      with self._patch_get_browser_cls(side_effect=mock_get_browser_cls):
        self.run_cli("loading", "--browser=chrome", "--browser=firefox",
                     f"--driver-path={driver_path}", "--urls=http://test.com",
                     "--env-validation=skip", "--throw")
    self.assertIn("--driver-path", str(cm.exception))

  def test_env_config_invalid_file(self):
    config = pathlib.Path("/test.config.hjson")
    with self.cli() as cli:
      # No "env" property
      with config.open("w", encoding="utf-8") as f:
        hjson.dump({}, f)
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            f"--env-config={config}",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])
      # "env" not a dict
      with config.open("w", encoding="utf-8") as f:
        hjson.dump({"env": []}, f)
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            f"--env-config={config}",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])
      with config.open("w", encoding="utf-8") as f:
        hjson.dump({"env": {"unknown_property_name": 1}}, f)
      with self.assertRaises(SysExitTestException):
        cli.run([
            "loading",
            f"--env-config={config}",
            "--urls=http://test.com",
            "--env-validation=skip",
        ])

  def test_parse_env_config_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": {}}, f)
    with self._patch_get_browser():
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_env_invalid_inline_and_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": {}}, f)
    with self.assertRaises(SysExitTestException):
      self.run_cli("loading", "--env=strict", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_invalid_splashscreen(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", "--browser=chrome", "--urls=http://test.com",
                   "--env-validation=skip", "--splash-screen=unknown-value",
                   "--throw")
    message = str(cm.exception)
    self.assertIn("--splash-screen", message)
    self.assertIn("unknown-value", message)

  def test_splash_screen_none(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--env-validation=skip",
                         "--throw", "--splash-screen=none")
      for browser in cli.last_subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.settings.splash_screen, SplashScreen.NONE)
        self.assertSequenceEqual([url], browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_splash_screen_minimal(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--env-validation=skip",
                         "--throw", "--splash-screen=minimal")
      for browser in cli.last_subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.settings.splash_screen, SplashScreen.MINIMAL)
        self.assertEqual(len(browser.url_list), 3)
        self.assertIn(url, browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_splash_screen_url(self):
    with self._patch_get_browser_cls():
      splash_url = "http://splash.com"
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--env-validation=skip",
                         "--throw", f"--splash-screen={splash_url}")
      for browser in cli.last_subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertIsInstance(browser.settings.splash_screen, URLSplashScreen)
        self.assertEqual(len(browser.url_list), 3)
        self.assertEqual(splash_url, browser.url_list[0])
        self.assertEqual(len(browser.js_flags), 0)

  def test_viewport_invalid(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", "--browser=chrome", "--urls=http://test.com",
                   "--env-validation=skip", "--viewport=-123", "--throw")
    message = str(cm.exception)
    self.assertIn("--viewport", message)
    self.assertIn("-123", message)

  def test_viewport_maximized(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--env-validation=skip",
                         "--throw", "--viewport=maximized")
      for browser in cli.last_subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.viewport, viewport.Viewport.MAXIMIZED)
        self.assertEqual(len(browser.url_list), 3)
        self.assertEqual(len(browser.js_flags), 0)

  def test_powersampler_invalid_multiple_runs(self):
    powersampler_bin = self.out_dir / "powersampler"
    config_str = json.dumps({"bin_path": str(powersampler_bin)})
    with self._patch_get_browser_cls(), mock.patch.object(
        PowerSamplerProbe, "validate_browser"):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        self.run_cli("loading", "--browser=chrome",
                     f"--probe=powersampler:{config_str}", "--repeat=10",
                     "--urls=http://test.com", "--env-validation=skip",
                     "--throw")
      self.assertIn("powersampler", str(cm.exception))

  def _test_fast(self, fast_flag: str, expected_validation: ValidationMode):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--throw", fast_flag,
                         f"--out-dir={self.out_dir / fast_flag}")
      self.assertEqual(cli.args.splash_screen, SplashScreen.NONE)
      self.assertEqual(cli.args.cool_down_time, dt.timedelta(0))
      subcommand = cli.last_subcommand
      assert isinstance(subcommand, BenchmarkSubcommand)
      self.assertEqual(
          subcommand._get_env_validation_mode(cli.args), expected_validation)
      for browser in subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertIs(browser.settings.splash_screen, SplashScreen.NONE)
        self.assertSequenceEqual(browser.url_list, [url])
        self.assertEqual(len(browser.js_flags), 0)

  def test_fast_implicit_mode(self):
    self._test_fast("--fast", ValidationMode.WARN)

  def test_fast_strict(self):
    self._test_fast("--fast=strict", ValidationMode.THROW)

  def test_fast_explicit_mode(self):
    for mode in ValidationMode:
      self._test_fast(f"--fast={mode.value}", mode)

  def test_fast_invalid(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self._test_fast("--fast=invalid", ValidationMode.THROW)
    self.assertIn("invalid choice: 'invalid'", str(cm.exception))

  def _test_fast_calls_fast_mode_default_overrides(self,
                                                   flag: str) -> ValidationMode:
    with mock.patch(
        "crossbench.benchmarks.loading.loading_benchmark.LoadingBenchmark"
        ".fast_mode_default_overrides",
        return_value={}) as fast_mode_default_overrides_mock:
      with self._patch_get_browser_cls():
        url = "http://test.com"
        suffix = flag.replace("=", "_").replace("-", "_")
        cli = self.run_cli("loading", f"--urls={url}", "--throw", flag,
                           f"--out-dir={self.out_dir / 'fast_mode' / suffix}")
        fast_mode_default_overrides_mock.assert_called_once_with()
        subcommand = cli.last_subcommand
        assert isinstance(subcommand, BenchmarkSubcommand)
        return subcommand._get_env_validation_mode(cli.args)

  def test_fast_calls_fast_mode_default_overrides_implicit(self):
    self.assertEqual(
        self._test_fast_calls_fast_mode_default_overrides("--fast"),
        ValidationMode.WARN)

  def test_fast_calls_fast_mode_default_overrides_strict(self):
    self.assertEqual(
        self._test_fast_calls_fast_mode_default_overrides("--fast=strict"),
        ValidationMode.THROW)

  def test_fast_calls_fast_mode_default_overrides_explicit(self):
    for mode in ValidationMode:
      self.assertEqual(
          self._test_fast_calls_fast_mode_default_overrides(
              f"--fast={mode.value}"), mode)

  def test_fast_startup_delay_input(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      with mock.patch("builtins.input", return_value="") as mock_input:
        cli = self.run_cli("loading", "--startup-delay=input", f"--urls={url}",
                           "--throw", "--fast")
        self.assertEqual(len(mock_input.call_args_list), 1)
        self.assertIn("Press enter to continue...", mock_input.call_args[0][0])
      self.assertEqual(cli.args.cool_down_time, dt.timedelta(0))
      self.assertEqual(cli.args.start_delay, dt.timedelta.max)
      self.assertEqual(cli.args.stop_delay, dt.timedelta(0))

  def test_fast_custom_input_delays(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      with mock.patch("builtins.input", return_value="") as mock_input:
        cli = self.run_cli("loading", "--startup-delay=input",
                           "--stop-delay=input", f"--urls={url}", "--throw",
                           "--fast")
        self.assertEqual(len(mock_input.call_args_list), 2)
        self.assertIn("Press enter to continue...",
                      mock_input.call_args_list[0].args[0])
        self.assertIn("Press enter to continue...",
                      mock_input.call_args_list[1].args[0])
      self.assertEqual(cli.args.cool_down_time, dt.timedelta(0))
      self.assertEqual(cli.args.start_delay, dt.timedelta.max)
      self.assertEqual(cli.args.stop_delay, dt.timedelta.max)

  def _test_flag_precedence_hierarchy(self, flags: list[str]) -> None:
    # This tests the exact precedence hierarchy of argparse variables:
    # 1. Explicit CLI arguments (e.g. `--arg1=explicit`) take highest priority.
    # 2. Rapid defaults (if `--fast`) override regular defaults.
    # 3. Regular defaults apply if no explicit argument or rapid default is set.
    # We use a MockBenchmark with 3 generic arguments to verify all 3 levels of
    # precedence in a single CLI run.

    class MockBenchmark(LoadingBenchmark):
      """Mock Benchmark for testing arg precedence."""
      NAME = "mock_benchmark"

      @classmethod
      def add_cli_arguments(cls, parser: CBArgumentParser) -> CBArgumentParser:
        parser = super().add_cli_arguments(parser)
        parser.add_argument("--arg1", default="default")
        parser.add_argument("--arg2", default="default")
        parser.add_argument("--arg3", default="default")
        return parser

      @classmethod
      def fast_mode_default_overrides(cls) -> dict[str, Any]:
        defaults = super().fast_mode_default_overrides()
        defaults["arg1"] = "rapid-default"
        defaults["arg2"] = "rapid-default"
        return defaults

    with mock.patch("crossbench.cli.cli.CrossBenchCLI.BENCHMARKS",
                    (MockBenchmark,)), self._patch_get_browser_cls():
      url = "http://test.com"

      args = ["mock_benchmark", f"--urls={url}", "--throw", "--arg1=explicit"]
      args.extend(flags)

      cli = self.run_cli(*args, f"--out-dir={self.out_dir}/test")

      # arg1: User explicitly provided. Takes precedence.
      self.assertEqual(cli.args.arg1, "explicit")

      # arg2: No explicit user flag. Overridden by rapid defaults (if passed).
      expected_arg2 = "rapid-default" if flags else "default"
      self.assertEqual(cli.args.arg2, expected_arg2)

      # arg3: No explicit user flag, no rapid default. Uses regular default.
      self.assertEqual(cli.args.arg3, "default")

  def test_flag_precedence_hierarchy_fast(self):
    self._test_flag_precedence_hierarchy(["--fast"])

  def test_flag_precedence_hierarchy_none(self):
    self._test_flag_precedence_hierarchy([])

  def _test_fast_mode_explicit_override(self, flags: list[str],
                                        dest_property: str) -> Any:
    with self._patch_get_browser_cls():
      url = "http://test.com"
      value = None
      for i, args in enumerate((flags, list(reversed(flags)))):
        cli = self.run_cli("loading", f"--urls={url}", "--throw", *args,
                           f"--out-dir={self.out_dir}_{i}")
        if i == 0:
          value = getattr(cli.args, dest_property)
        else:
          self.assertEqual(value, getattr(cli.args, dest_property))
      return value

  def test_fast_explicit_override(self):
    value: dt.timedelta = self._test_fast_mode_explicit_override(
        ["--fast", "--cool-down=123ms"], "cool_down_time")
    self.assertEqual(value, dt.timedelta(milliseconds=123))

  def test_fast_splash_screen_override(self):
    value: SplashScreen = self._test_fast_mode_explicit_override(
        ["--fast", "--splash-screen=detailed"], "splash_screen")
    self.assertEqual(value, SplashScreen.DETAILED)

  def test_fast_env_validation_override(self):
    value: ValidationMode = self._test_fast_mode_explicit_override(
        ["--fast", "--env-validation=prompt"], "env_validation")
    self.assertEqual(value, ValidationMode.PROMPT)

  def test_create_symlinks(self):
    with self._patch_get_browser_cls():
      out_dir = self.out_dir / "create_symlinks"
      self.assertFalse(out_dir.exists())
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--throw", "--fast",
                         f"--out-dir={out_dir}")
      self.assertTrue(cli.args.create_symlinks)
      links = list(out_dir.glob("*/sessions/*"))
      self.assertEqual(len(links), 1)
      self.assertTrue(links[0].is_symlink())
      links = list(out_dir.glob("*/stories/**/session"))
      self.assertEqual(len(links), 1)
      self.assertTrue(links[0].is_symlink())

  def test_no_symlinks(self):
    with self._patch_get_browser_cls():
      out_dir = self.out_dir / "no_symlinks"
      self.assertFalse(out_dir.exists())
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--throw", "--fast",
                         "--no-symlinks", f"--out-dir={out_dir}")
      self.assertFalse(cli.args.create_symlinks)
      for dirpath, dirnames, filenames in os.walk(out_dir):
        dirpath = pathlib.Path(dirpath)
        for name in dirnames + filenames:
          self.assertFalse((dirpath / name).is_symlink())

  def test_debug(self):
    with self._patch_get_browser_cls():
      url = "http://test.com"
      cli = self.run_cli("loading", f"--urls={url}", "--debug")
      self.assertTrue(cli.args.throw)
      self.assertEqual(cli.args.verbosity, 3)
      for browser in cli.last_subcommand.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(len(browser.url_list), 3)
        self.assertEqual(len(browser.js_flags), 0)

  def test_debugger_not_found(self):
    searched_binaries = []
    original_search_binary = plt.PLATFORM.search_binary

    def mock_search_binary(binary) -> pth.AnyPath | None:
      searched_binaries.append(binary)
      if "gdb" in str(binary) or "lldb" in str(binary):
        return None
      return original_search_binary(binary)

    for debugger in ("lldb", "gdb", "lldb"):
      searched_binaries = []
      with self._patch_get_browser_cls(), mock.patch.object(
          plt.PLATFORM, "search_binary", side_effect=mock_search_binary):
        with self.assertRaises(ValueError) as cm:
          self.run_cli("loading", "--urls=cnn", f"--{debugger}", "--throw")
        self.assertIn(debugger, str(cm.exception))
        _, _, stderr = self.run_cli_output(
            "loading",
            "--urls=cnn",
            f"--{debugger}",
            raises=SysExitTestException)
        self.assertIn(f"Unknown binary: {debugger}", stderr)
        self.assertIn(pathlib.Path(debugger), searched_binaries)

  def test_benchmark_overrides_network(self):

    class MockCustomNetworkBenchmark(Benchmark):
      """Mock custom network benchmark docstring."""
      NAME = "custom-network-benchmark"
      DEFAULT_STORY_CLS = MockStory

      @classmethod
      def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
        if args.network_config.is_default():
          args.network_config = NetworkConfig(
              type=NetworkType.LOCAL, path=pth.LocalPath("/mock/dir"))
        return {"stories": (MockStory("story_1"),)}

    mock_dir = pth.LocalPath("/mock/dir")
    self.fs.create_dir(mock_dir)
    self.fs.create_file(mock_dir / "index.html")

    with mock.patch.object(CrossBenchCLI, "BENCHMARKS",
                           (MockCustomNetworkBenchmark,)):
      with self._patch_get_browser_cls():
        cli = self.run_cli(
            "custom-network-benchmark",
            "--browser=chrome",
        )
        runner = cli.last_subcommand.runner
        self.assertEqual(len(runner.browsers), 1)
        browser = runner.browsers[0]
        self.assertIsInstance(browser.network, LocalFileNetwork)

  def test_benchmark_custom_default_probe_config_path(self):
    probe_config_file = pth.LocalPath("/custom_probe_config.hjson")
    self.fs.create_file(
        probe_config_file, contents=hjson.dumps({"probes": {
            "js": {},
        }}))

    class MockCustomProbeBenchmark(Benchmark):
      """Mock custom probe benchmark docstring."""
      NAME = "custom-probe-benchmark"
      DEFAULT_STORY_CLS = MockStory

      @classmethod
      def default_probe_config_path(cls) -> pth.LocalPath | None:
        return probe_config_file

      @classmethod
      def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
        return {"stories": (MockStory("story_1"),)}

    with mock.patch.object(CrossBenchCLI, "BENCHMARKS",
                           (MockCustomProbeBenchmark,)):
      with self._patch_get_browser_cls():
        cli = self.run_cli(
            "custom-probe-benchmark",
            "--browser=chrome",
        )
        runner = cli.last_subcommand.runner
        probe_names = {p.name for p in runner.probes}
        self.assertIn("js", probe_names)

  def test_benchmark_custom_default_network_config_path(self):
    mock_dir = pth.LocalPath("/mock/dir")
    self.fs.create_dir(mock_dir)
    self.fs.create_file(mock_dir / "index.html")

    network_config_file = pth.LocalPath("/custom_network_config.hjson")
    self.fs.create_file(
        network_config_file,
        contents=hjson.dumps({
            "type": "local",
            "path": str(mock_dir),
            "url": "http://localhost:0/",
        }))

    class MockCustomNetworkConfigBenchmark(Benchmark):
      """Mock custom network config benchmark docstring."""
      NAME = "custom-network-config-benchmark"
      DEFAULT_STORY_CLS = MockStory

      @classmethod
      def default_network_config_path(cls) -> pth.LocalPath | None:
        return network_config_file

      @classmethod
      def kwargs_from_cli(cls, args: argparse.Namespace) -> dict[str, Any]:
        return {"stories": (MockStory("story_1"),)}

    with mock.patch.object(CrossBenchCLI, "BENCHMARKS",
                           (MockCustomNetworkConfigBenchmark,)):
      with self._patch_get_browser_cls():
        cli = self.run_cli(
            "custom-network-config-benchmark",
            "--browser=chrome",
        )
        runner = cli.last_subcommand.runner
        self.assertEqual(len(runner.browsers), 1)
        browser = runner.browsers[0]
        network = browser.network
        self.assertIsInstance(network, LocalFileNetwork)
        self.assertEqual(network.path, mock_dir)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
