# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
from typing import TYPE_CHECKING, Final
from unittest import mock

import hjson
from typing_extensions import override

from crossbench import __version__
from crossbench import path as pth
from crossbench import plt
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark
from crossbench.browsers.splash_screen import SplashScreen, URLSplashScreen
from crossbench.browsers.viewport import Viewport
from crossbench.cli.config.env import ValidationMode
from crossbench.cli.config.network import NetworkConfig, NetworkType
from crossbench.cli.config.probe_list import ProbeListConfig
from crossbench.cli.parser import CBArgumentParser
from crossbench.cli.subcommand.benchmark import BenchmarkSubcommand
from crossbench.device_config import RequiredDeviceConfigMode
from crossbench.runner.runner import CacheTemperature, Runner, ThreadMode
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.base import BaseCliTestCase, SysExitTestException
from tests.crossbench.mock_helper import MockCLI

if TYPE_CHECKING:
  from crossbench.cli.config.browser import BrowserConfig


class BenchmarkFlagsParserTestCase(BaseCliTestCase):

  def create_parser(self) -> CBArgumentParser:
    cli = MockCLI(platform=self.platform)
    subcommand = BenchmarkSubcommand(cli, LoadingBenchmark)
    parser = CBArgumentParser()
    subcommand.add_cli_arguments(parser)
    return parser

  def parse_args(self, *args: str) -> argparse.Namespace:
    return self.create_parser().parse_args(args)

  def test_cool_down_default(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.cool_down_time, LoadingBenchmark.DEFAULT_COOL_DOWN)
    self.assertIsNone(args.cool_down_threshold)

  def test_no_cool_down(self) -> None:
    args = self.parse_args("--no-cool-down")
    self.assertEqual(args.cool_down_time, dt.timedelta(0))

  def test_cool_down_time_aliases(self) -> None:
    for flag in (
        "--cool-down-time=5s",
        "--cool-down=5s",
        "--cooldown-time=5s",
        "--cooldown=5s",
    ):
      args = self.parse_args(flag)
      self.assertEqual(args.cool_down_time, dt.timedelta(seconds=5))

  def test_cool_down_threshold(self) -> None:
    for flag in ("--cool-down-threshold=moderate",
                 "--cooldown-threshold=moderate"):
      args = self.parse_args(flag)
      self.assertEqual(args.cool_down_threshold.name.lower(), "moderate")

  def test_cool_down_mutually_exclusive(self) -> None:
    for flag in ("--cool-down=5s", "--cool-down-threshold=moderate"):
      with self.assertRaisesRegex(argparse.ArgumentError,
                                  "--cool-down|--no-cool-down"):
        self.parse_args(flag, "--no-cool-down")

  def test_cool_down_invalid(self) -> None:
    for flag in (
        "--cool-down=invalid",
        "--cool-down-time=-1s",
        "--cool-down-threshold=invalid",
    ):
      with self.assertRaises(argparse.ArgumentError):
        self.parse_args(flag)

  def test_remote_driver_path_default(self) -> None:
    args = self.parse_args()
    self.assertIsNone(args.remote_driver_path)

  def test_remote_driver_path(self) -> None:
    args = self.parse_args("--remote-driver-path=/remote/chromedriver")
    self.assertEqual(str(args.remote_driver_path), "/remote/chromedriver")

  def test_field_trial_config_defaults(self) -> None:
    args = self.parse_args()
    self.assertIsNone(args.enable_field_trial_config)

  def test_enable_field_trial_config_aliases(self) -> None:
    for flag in ("--enable-field-trial-config", "--enable-field-trials"):
      args = self.parse_args(flag)
      self.assertIs(args.enable_field_trial_config, True)

  def test_enable_field_trial_config_benchmarking(self) -> None:
    args = self.parse_args("--enable-field-trial-config=benchmarking")
    self.assertEqual(args.enable_field_trial_config, "benchmarking")

  def test_disable_field_trial_config_aliases(self) -> None:
    for flag in ("--disable-field-trial-config", "--disable-field-trials"):
      args = self.parse_args(flag)
      self.assertIs(args.enable_field_trial_config, False)

  def test_conflicting_field_trial_flags(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "field-trial-config"):
      self.parse_args("--enable-field-trial-config",
                      "--disable-field-trial-config")

  def test_no_color(self) -> None:
    args = self.parse_args("--no-color")
    self.assertIs(args.color, False)

  @mock.patch("sys.stdout.isatty", return_value=True)
  def test_default_color_true(self, isatty_mock) -> None:
    args = self.parse_args()
    self.assertEqual(args.color, True)

  @mock.patch("sys.stdout.isatty", return_value=False)
  def test_default_color_false(self, isatty_mock) -> None:
    args = self.parse_args()
    self.assertEqual(args.color, False)

  def test_default_repetitions(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.repetitions, 1)
    self.assertEqual(args.warmup_repetitions, 0)

  def test_repetitions_aliases(self) -> None:
    for flag in ("--repetitions=3", "--repeat=3", "-r=3", "--invocations=3"):
      args = self.parse_args(flag)
      self.assertEqual(args.repetitions, 3)

  def test_warmup_repetitions_aliases(self) -> None:
    for flag in ("--warmup-repetitions=2", "--warmups=2"):
      args = self.parse_args(flag)
      self.assertEqual(args.warmup_repetitions, 2)

  def test_invalid_repetitions(self) -> None:
    for invalid in ("--repetitions=0", "--repetitions=-1", "--repeat=abc",
                    "-r=-5"):
      with self.assertRaisesRegex(argparse.ArgumentError,
                                  "repetitions|repeat|invocations"):
        self.parse_args(invalid)

  def test_invalid_warmup_repetitions(self) -> None:
    for invalid in ("--warmup-repetitions=-1", "--warmups=abc"):
      with self.assertRaisesRegex(argparse.ArgumentError, "warmup|warmups"):
        self.parse_args(invalid)

  def test_ignore_partial_failures_default(self) -> None:
    args = self.parse_args()
    self.assertFalse(args.ignore_partial_failures)

  def test_ignore_partial_failures(self) -> None:
    args = self.parse_args("--ignore-partial-failures")
    self.assertTrue(args.ignore_partial_failures)

  def test_cache_temperatures_default(self) -> None:
    args = self.parse_args()
    self.assertSequenceEqual(args.cache_temperatures,
                             [CacheTemperature.DEFAULT])

  def test_cache_temperatures(self) -> None:
    args = self.parse_args("--cache-temperatures")
    self.assertEqual(args.cache_temperatures, list(CacheTemperature.all()))

  def test_thread_mode_default(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.thread_mode, ThreadMode.NONE)

  def test_thread_mode_options(self) -> None:
    for mode in (ThreadMode.PLATFORM, ThreadMode.BROWSER, ThreadMode.SESSION):
      args = self.parse_args(f"--thread-mode={mode.value}")
      self.assertEqual(args.thread_mode, mode)

  def test_parallel_alias(self) -> None:
    args = self.parse_args("--parallel=browser")
    self.assertEqual(args.thread_mode, ThreadMode.BROWSER)

  def test_invalid_thread_mode(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "--thread-mode"):
      self.parse_args("--thread-mode=invalid")

  def test_step_by_step_mode_default(self) -> None:
    args = self.parse_args()
    self.assertFalse(args.step_by_step_mode)

  def test_step_by_step_mode(self) -> None:
    args = self.parse_args("--step-by-step-mode")
    self.assertTrue(args.step_by_step_mode)

  def test_symlinks_default(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.create_symlinks, not self.platform.is_win)

  def test_no_symlinks_aliases(self) -> None:
    for flag in ("--no-symlinks", "--nosymlinks"):
      args = self.parse_args(flag)
      self.assertFalse(args.create_symlinks)

  def test_symlinks(self) -> None:
    args = self.parse_args("--symlinks")
    self.assertTrue(args.create_symlinks)

  def test_conflicting_symlinks_flags(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "symlinks"):
      self.parse_args("--symlinks", "--no-symlinks")

  def test_out_dir_aliases(self) -> None:
    custom_dir = pth.LocalPath("/custom_results_dir")
    for flag in (
        f"--out-dir={custom_dir}",
        f"--output-directory={custom_dir}",
        f"-o={custom_dir}",
    ):
      args = self.parse_args(flag)
      self.assertEqual(args.out_dir, custom_dir)

  def test_label_aliases(self) -> None:
    for flag in ("--label=custom_label", "--name=custom_label"):
      args = self.parse_args(flag)
      self.assertEqual(args.label, "custom_label")

  def test_cache_dir(self) -> None:
    custom_cache = pth.LocalPath("/custom_cache_dir")
    args = self.parse_args(f"--cache-dir={custom_cache}")
    self.assertEqual(args.cache_dir, custom_cache)

  def test_conflicting_out_dir_and_label(self) -> None:
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--out-dir=/tmp/out", "--label=custom_label")

  def test_fast_mode_default(self) -> None:
    args = self.parse_args()
    self.assertIsNone(args.fast)

  def test_fast_mode(self) -> None:
    args = self.parse_args("--fast")
    self.assertEqual(args.fast, "warn")

  def test_fast_mode_strict(self) -> None:
    args = self.parse_args("--fast=strict")
    self.assertEqual(args.fast, "strict")

  def test_time_unit_aliases(self) -> None:
    for flag in ("--time-unit=2.5s", "--time-scale=2.5s"):
      args = self.parse_args(flag)
      self.assertEqual(args.time_unit, dt.timedelta(seconds=2.5))

  def test_timeout_unit_aliases(self) -> None:
    for flag in ("--timeout-unit=15s", "--timeout-scale=15s"):
      args = self.parse_args(flag)
      self.assertEqual(args.timeout_unit, dt.timedelta(seconds=15))

  def test_run_timeout(self) -> None:
    for flag, expected in (
        ("--run-timeout=5m", dt.timedelta(minutes=5)),
        ("--run-timeout=45s", dt.timedelta(seconds=45)),
    ):
      args = self.parse_args(flag)
      self.assertEqual(args.run_timeout, expected)

  def test_timing_invalid(self) -> None:
    for flag in (
        "--time-unit=invalid",
        "--timeout-unit=invalid",
        "--run-timeout=invalid",
    ):
      with self.assertRaisesRegex(argparse.ArgumentError,
                                  "time-unit|timeout-unit|run-timeout"):
        self.parse_args(flag)

  def test_delays(self) -> None:
    args = self.parse_args(
        "--start-delay=3s",
        "--setup-delay=2s",
        "--stop-delay=1.5s",
    )
    self.assertEqual(args.start_delay, dt.timedelta(seconds=3))
    self.assertEqual(args.setup_delay, dt.timedelta(seconds=2))
    self.assertEqual(args.stop_delay, dt.timedelta(seconds=1.5))

  def test_delay_aliases(self) -> None:
    self.assertEqual(
        self.parse_args("--startup-delay=4s").start_delay,
        dt.timedelta(seconds=4),
    )

  def test_delay_input(self) -> None:
    with mock.patch("builtins.input", return_value=""):
      args = self.parse_args(
          "--start-delay=input",
          "--setup-delay=input",
          "--stop-delay=input",
      )
      self.assertEqual(args.start_delay, dt.timedelta.max)
      self.assertEqual(args.setup_delay, dt.timedelta.max)
      self.assertEqual(args.stop_delay, dt.timedelta.max)

  def test_network_default(self) -> None:
    args = self.parse_args()
    self.assertIsNone(args.network_config)

  def test_network_inline(self) -> None:
    for flag in ("--network=default", "--network=live"):
      args = self.parse_args(flag)
      self.assertIsInstance(args.network_config, NetworkConfig)
      self.assertEqual(args.network_config.type, NetworkType.LIVE)

  def test_network_config_file(self) -> None:
    net_file = pth.LocalPath("/test_network.config.hjson")
    self.fs.create_file(net_file, contents=hjson.dumps({"type": "live"}))
    args = self.parse_args(f"--network-config={net_file}")
    self.assertIsInstance(args.network_config, NetworkConfig)
    self.assertEqual(args.network_config.type, NetworkType.LIVE)

  def test_local_file_server_aliases(self) -> None:
    mock_dir = pth.LocalPath("/mock_srv_dir")
    self.fs.create_dir(mock_dir)
    self.fs.create_file(mock_dir / "index.html")
    for flag in (
        "--local-file-server",
        "--local-fileserver",
        "--file-server",
        "--fileserver",
    ):
      args = self.parse_args(f"{flag}={mock_dir}")
      self.assertIsInstance(args.network_config, NetworkConfig)
      self.assertEqual(args.network_config.type, NetworkType.LOCAL)
      self.assertEqual(str(args.network_config.path), str(mock_dir))

  def test_wpr_aliases(self) -> None:
    wpr_file = pth.LocalPath("/archive.wprgo")
    self.fs.create_file(wpr_file, contents=b"non_empty_wpr_archive_data")
    for flag in ("--wpr", "--web-page-replay"):
      with mock.patch("crossbench.cli.config.network.LocalWprReplayNetwork"):
        args = self.parse_args(f"{flag}={wpr_file}")
        self.assertIsInstance(args.network_config, NetworkConfig)
        self.assertEqual(args.network_config.type, NetworkType.WPR)
        self.assertEqual(str(args.network_config.path), str(wpr_file))

  def test_conflicting_network_flags(self) -> None:
    wpr_file = pth.LocalPath("/archive.wprgo")
    self.fs.create_file(wpr_file, contents=b"non_empty_wpr_archive_data")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--network=live", f"--wpr={wpr_file}")

  def test_env_presets(self) -> None:
    for preset in ("strict", "battery", "power", "catan"):
      args = self.parse_args(f"--env={preset}")
      self.assertIsNotNone(args.env_config)
    self.assertFalse(args.env_config.power_use_battery)

  def test_env_config_file(self) -> None:
    env_file = pth.LocalPath("/env.config.hjson")
    self.fs.create_file(
        env_file,
        contents=hjson.dumps({"env": {
            "power_use_battery": False,
        }}),
    )
    args = self.parse_args(f"--env-config={env_file}")
    self.assertIsNotNone(args.env_config)
    self.assertFalse(args.env_config.power_use_battery)

  def test_env_validation_modes(self) -> None:
    for mode in ValidationMode:
      args = self.parse_args(f"--env-validation={mode.value}")
      self.assertEqual(args.env_validation, mode)

  def test_env_validation_invalid(self) -> None:
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--env-validation=invalid")

  def test_required_device_config_mode_default(self) -> None:
    args = self.parse_args()
    self.assertEqual(args.required_device_config_mode,
                     RequiredDeviceConfigMode.SET)
    runner_kwargs = Runner.kwargs_from_cli(args)
    self.assertEqual(runner_kwargs["required_device_config_mode"],
                     RequiredDeviceConfigMode.SET)

  def test_required_device_config_mode_modes(self) -> None:
    for mode in RequiredDeviceConfigMode:
      args = self.parse_args(f"--required-device-config-mode={mode.value}")
      self.assertEqual(args.required_device_config_mode, mode)
      runner_kwargs = Runner.kwargs_from_cli(args)
      self.assertEqual(runner_kwargs["required_device_config_mode"], mode)

  def test_required_device_config_mode_invalid(self) -> None:
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--required-device-config-mode=invalid")

  def test_conflicting_env_flags(self) -> None:
    env_file = pth.LocalPath("/env.config.hjson")
    self.fs.create_file(
        env_file,
        contents=hjson.dumps({"env": {
            "power_use_battery": False,
        }}),
    )
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--env=strict", f"--env-config={env_file}")

  def test_dry_run_default(self) -> None:
    args = self.parse_args()
    self.assertFalse(args.dry_run)

  def test_dry_run(self) -> None:
    args = self.parse_args("--dry-run")
    self.assertTrue(args.dry_run)

  def test_browser_aliases(self) -> None:
    for flag in ("--browser=chrome-stable", "-b=chrome-dev"):
      args = self.parse_args(flag)
      self.assertEqual(len(args.browser), 1)

  def test_browser_config(self) -> None:
    browser_config_file = pth.LocalPath("/browser.config.hjson")
    self.fs.create_file(
        browser_config_file,
        contents=hjson.dumps(
            {"browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                },
            }}),
    )
    args = self.parse_args(f"--browser-config={browser_config_file}")
    self.assertIsNotNone(args.browser_config)

  def test_browser_cache_dir_aliases(self) -> None:
    for flag in (
        "--browser-cache-dir=/cache",
        "--browser-cache=/cache",
        "--user-data-dir=/cache",
    ):
      args = self.parse_args(flag)
      self.assertEqual(str(args.browser_cache_dir), "/cache")

  def test_http_request_timeout(self) -> None:
    args = self.parse_args("--http-request-timeout=12.5s")
    self.assertEqual(args.http_request_timeout, dt.timedelta(seconds=12.5))

  def test_splash_screen_options(self) -> None:
    for flag in ("--splash-screen=none", "--splashscreen=none",
                 "--splash=none"):
      args = self.parse_args(flag)
      self.assertEqual(args.splash_screen, SplashScreen.NONE)

    for flag in (
        "--splash-screen=minimal",
        "--splashscreen=minimal",
        "--splash=minimal",
    ):
      args = self.parse_args(flag)
      self.assertEqual(args.splash_screen, SplashScreen.MINIMAL)

    for flag in ("--splash-screen=http://custom.com",
                 "--splash=http://custom.com"):
      args = self.parse_args(flag)
      self.assertIsInstance(args.splash_screen, URLSplashScreen)
      self.assertEqual(args.splash_screen.url, "http://custom.com")

  def test_no_splash_aliases(self) -> None:
    for flag in ("--no-splash", "--nosplash"):
      args = self.parse_args(flag)
      self.assertEqual(args.splash_screen, SplashScreen.NONE)

  def test_conflicting_splash_screen(self) -> None:
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--splash-screen=none", "--no-splash")

  def test_viewport_options(self) -> None:
    args = self.parse_args("--viewport=maximized")
    self.assertEqual(args.viewport, Viewport.MAXIMIZED)

    args = self.parse_args("--viewport=fullscreen")
    self.assertEqual(args.viewport, Viewport.FULLSCREEN)

    args = self.parse_args("--viewport=headless")
    self.assertEqual(args.viewport, Viewport.HEADLESS)

    args = self.parse_args("--viewport=1000x800,10x20")
    self.assertEqual(args.viewport.width, 1000)
    self.assertEqual(args.viewport.height, 800)
    self.assertEqual(args.viewport.x, 10)
    self.assertEqual(args.viewport.y, 20)

  def test_headless(self) -> None:
    args = self.parse_args("--headless")
    self.assertEqual(args.viewport, Viewport.HEADLESS)

  def test_conflicting_viewport_headless(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "headless|viewport"):
      self.parse_args("--viewport=fullscreen", "--headless")

  def test_viewport_invalid(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "viewport"):
      self.parse_args("--viewport=invalid_size")

  def test_clear_browser_cache_aliases(self) -> None:
    for flag in ("--clear-browser-cache", "--clear-browser-cache-dir"):
      args = self.parse_args(flag)
      self.assertTrue(args.clear_browser_cache_dir)

  def test_no_clear_browser_cache_aliases(self) -> None:
    for flag in ("--no-clear-browser-cache", "--keep-browser-cache"):
      args = self.parse_args(flag)
      self.assertFalse(args.clear_browser_cache_dir)

  def test_conflicting_clear_browser_cache(self) -> None:
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--clear-browser-cache", "--no-clear-browser-cache")

  def test_chrome_options(self) -> None:
    args = self.parse_args(
        "--js-flags=--flag1",
        "--js-flags=--flag2",
        "--enable-features=F1,F2",
        "--disable-features=F3",
    )
    self.assertSequenceEqual(args.js_flags, ["--flag1", "--flag2"])
    self.assertEqual(args.enable_features, "F1,F2")
    self.assertEqual(args.disable_features, "F3")

  def test_no_sandbox_aliases(self) -> None:
    for flag in ("--no-sandbox", "--nosandbox"):
      args = self.parse_args(flag)
      self.assertFalse(args.sandbox)

  def test_probe_flags(self) -> None:
    args = self.parse_args("--probe=js")
    self.assertEqual(len(args.probe), 1)

  def test_no_probe(self) -> None:
    args = self.parse_args("--no-probe=js", "--no-probe=v8.log")
    self.assertSequenceEqual(args.no_probe, ["js", "v8.log"])

  def test_invalid_no_probe(self) -> None:
    for invalid in ("--no-probe=", "--no-probe= "):
      with self.assertRaisesRegex(argparse.ArgumentError, "no-probe"):
        self.parse_args(invalid)

  def test_probe_config(self) -> None:
    probe_config_file = pth.LocalPath("/probes.config.hjson")
    self.fs.create_file(
        probe_config_file, contents=hjson.dumps({"probes": {
            "js": {},
        }}))
    args = self.parse_args(f"--probe-config={probe_config_file}")
    self.assertEqual(args.probe_config, probe_config_file)

  def test_quiet_aliases(self) -> None:
    for flag in ("--quiet", "-q"):
      args = self.parse_args(flag)
      self.assertEqual(args.verbosity, -1)

  def test_verbose_aliases(self) -> None:
    for flag, expected in (
        ("--verbose", 1),
        ("-v", 1),
        ("-vv", 2),
        ("-vvv", 3),
    ):
      args = self.parse_args(flag)
      self.assertEqual(args.verbosity, expected)

  def test_conflicting_quiet_verbose(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "quiet|verbose"):
      self.parse_args("--quiet", "--verbose")

  def test_throw(self) -> None:
    args = self.parse_args("--throw")
    self.assertTrue(args.throw)

  def test_debug(self) -> None:
    args = self.parse_args("--debug")
    self.assertTrue(args.throw)
    self.assertEqual(args.verbosity, 3)
    self.assertTrue(args.driver_logging)

  def test_driver_logging_aliases(self) -> None:
    for flag in ("--driver-logging", "--verbose-driver",
                 "--verbose-driver-logging"):
      args = self.parse_args(flag)
      self.assertTrue(args.driver_logging)

  def test_gdb_lldb_aliases(self) -> None:
    self.assertEqual(
        self.parse_args("--gdb").probe[0].probe_cls.NAME, "debugger")
    self.assertEqual(
        self.parse_args("--lldb").probe[0].probe_cls.NAME, "debugger")
    with self.assertRaises(argparse.ArgumentError):
      self.parse_args("--gdb", "--lldb")

  def test_bin_override_aliases(self) -> None:
    for flag in ("--bin-override=wpr=/bin/wpr",
                 "--binary-override=wpr=/bin/wpr"):
      args = self.parse_args(flag)
      self.assertSequenceEqual(args.binary_overrides, ["wpr=/bin/wpr"])

  def test_upload_results_default(self) -> None:
    args = self.parse_args()
    self.assertIsNone(args.upload_results)

  def test_upload_results(self) -> None:
    args = self.parse_args("--upload-results=gs://bucket/results")
    self.assertEqual(args.upload_results, "gs://bucket/results")

  def test_extra_browser_args(self) -> None:
    args = self.parse_args(
        "--extra-browser-args=--custom-arg1 --custom-arg2=value")
    self.assertSequenceEqual(args.extra_browser_args,
                             ["--custom-arg1 --custom-arg2=value"])

  def test_trailing_browser_args_after_separator(self) -> None:
    args = self.parse_args(
        "--",
        "--custom-trailing=123",
        "--custom-trailing-flag",
    )
    self.assertSequenceEqual(
        args.other_browser_args,
        ["--custom-trailing=123", "--custom-trailing-flag"],
    )


class BenchmarkFlagsCliTestCase(BaseCliTestCase):
  URL: Final[str] = "http://test.com"

  @override
  def setUp(self) -> None:
    super().setUp()
    self._run_counter: int = 0

  def _get_subcommand(self, cli: MockCLI) -> BenchmarkSubcommand:
    subcommand = cli.last_subcommand
    assert isinstance(subcommand, BenchmarkSubcommand)
    return subcommand

  def _get_runner(self, cli: MockCLI) -> Runner:
    return self._get_subcommand(cli).runner

  def _run_loading(
      self,
      *flags: str,
      is_dry_run: bool = True,
  ) -> tuple[MockCLI, Runner]:
    self._run_counter += 1
    if self.fs.exists("/results"):
      self.fs.remove_object("/results")
    has_out_dir = any(
        f.startswith(("--out-dir", "--output-directory", "-o", "--label",
                      "--name")) for f in flags)
    extra_flags: list[str] = []
    if not has_out_dir:
      extra_flags.append(f"--out-dir={self.out_dir}_{self._run_counter}")
    if is_dry_run and not any(f.startswith("--dry-run") for f in flags):
      extra_flags.append("--dry-run")

    with self._patch_get_browser_cls():
      cli = self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--env-validation=skip",
          *extra_flags,
          *flags,
      )
      runner = self._get_runner(cli)
      return cli, runner

  def test_cool_down_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertEqual(cli.args.cool_down_time,
                     LoadingBenchmark.DEFAULT_COOL_DOWN)
    self.assertEqual(runner.timing.cool_down_time,
                     LoadingBenchmark.DEFAULT_COOL_DOWN)

  def test_no_cool_down(self) -> None:
    cli, runner = self._run_loading("--no-cool-down")
    self.assertEqual(cli.args.cool_down_time, dt.timedelta(0))
    self.assertEqual(runner.timing.cool_down_time, dt.timedelta(0))

  def test_cool_down_time(self) -> None:
    cli, runner = self._run_loading("--cool-down-time=5s")
    self.assertEqual(cli.args.cool_down_time, dt.timedelta(seconds=5))
    self.assertEqual(runner.timing.cool_down_time, dt.timedelta(seconds=5))

  def test_cool_down_mutually_exclusive(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "--cool-down|--no-cool-down"):
      self.run_cli("loading", f"--urls={self.URL}", "--cool-down=5s",
                   "--no-cool-down", "--throw")

  def test_cool_down_invalid(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "--cool-down"):
      self.run_cli("loading", f"--urls={self.URL}", "--cool-down=invalid",
                   "--throw")

  def test_remote_driver_path_flag(self) -> None:
    remote_path = "/remote/path/to/chromedriver"
    cli, _ = self._run_loading(f"--remote-driver-path={remote_path}")
    self.assertEqual(str(cli.args.remote_driver_path), remote_path)

  def test_remote_driver_path_multiple_browser_types_conflict(self) -> None:
    mock_browsers: list[type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockFirefox,
    ]

    def mock_get_browser_cls(
        browser_config: BrowserConfig) -> type[mock_browser.MockBrowser]:
      for mock_cls in mock_browsers:
        if mock_cls.mock_app_path(self.platform) == browser_config.path:
          return mock_cls
      raise ValueError(f"Unknown browser: {browser_config.path}")

    with self._patch_get_browser_cls(side_effect=mock_get_browser_cls):
      with self.assertRaises(
          (argparse.ArgumentTypeError, SysExitTestException)):
        self.run_cli(
            "loading",
            "--browser=chrome",
            "--browser=firefox",
            "--remote-driver-path=/remote/chromedriver",
            f"--urls={self.URL}",
            "--env-validation=skip",
        )

  def test_field_trial_config_defaults(self) -> None:
    cli, _ = self._run_loading()
    self.assertIsNone(cli.args.enable_field_trial_config)

  def test_enable_field_trial_config(self) -> None:
    for flag in ("--enable-field-trial-config", "--enable-field-trials"):
      cli, runner = self._run_loading(flag)
      self.assertIs(cli.args.enable_field_trial_config, True)
      browser = runner.browsers[0]
      self.assertNotIn("--disable-field-trial-config", browser.flags)

  def test_enable_field_trial_config_benchmarking(self) -> None:
    cli, _ = self._run_loading("--enable-field-trial-config=benchmarking")
    self.assertEqual(cli.args.enable_field_trial_config, "benchmarking")

  def test_disable_field_trial_config(self) -> None:
    for flag in ("--disable-field-trial-config", "--disable-field-trials"):
      cli, runner = self._run_loading(flag)
      self.assertIs(cli.args.enable_field_trial_config, False)
      browser = runner.browsers[0]
      self.assertIn("--disable-field-trial-config", browser.flags)

  def test_conflicting_field_trial_flags(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "field-trial-config"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--enable-field-trial-config",
          "--disable-field-trial-config",
          "--throw",
      )

  def test_no_color(self) -> None:
    cli, _ = self._run_loading("--no-color")
    self.assertIs(cli.args.color, False)

  @mock.patch("sys.stdout.isatty", return_value=True)
  def test_default_color_true(self, isatty_mock) -> None:
    cli, _ = self._run_loading()
    self.assertEqual(cli.args.color, True)

  @mock.patch("sys.stdout.isatty", return_value=False)
  def test_default_color_false(self, isatty_mock) -> None:
    cli, _ = self._run_loading()
    self.assertEqual(cli.args.color, False)

  def test_version_subcommand(self) -> None:
    with self.assertRaises(SysExitTestException) as cm:
      self.run_cli("loading", "--version")
    self.assertEqual(cm.exception.exit_code, 0)
    _, stdout, stderr = self.run_cli_output(
        "loading", "--version", raises=SysExitTestException)
    self.assertFalse(stderr)
    self.assertIn(__version__, stdout)

  def test_version_root_cli(self) -> None:
    with self.assertRaises(SysExitTestException) as cm:
      self.run_cli("--version")
    self.assertEqual(cm.exception.exit_code, 0)
    _, stdout, stderr = self.run_cli_output(
        "--version", raises=SysExitTestException)
    self.assertFalse(stderr)
    self.assertIn(__version__, stdout)

  def test_default_repetitions(self) -> None:
    cli, _ = self._run_loading()
    self.assertEqual(cli.args.repetitions, 1)
    self.assertEqual(cli.args.warmup_repetitions, 0)

  def test_repetitions(self) -> None:
    cli, _ = self._run_loading("--repetitions=3")
    self.assertEqual(cli.args.repetitions, 3)

  def test_warmup_repetitions(self) -> None:
    cli, _ = self._run_loading("--warmup-repetitions=2")
    self.assertEqual(cli.args.warmup_repetitions, 2)

  def test_invalid_repetitions(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "repetitions"):
      self.run_cli("loading", f"--urls={self.URL}", "--repetitions=0",
                   "--throw")

  def test_invalid_warmup_repetitions(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "warmup-repetitions"):
      self.run_cli("loading", f"--urls={self.URL}", "--warmup-repetitions=-1",
                   "--throw")

  def test_ignore_partial_failures_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertFalse(cli.args.ignore_partial_failures)
    self.assertFalse(runner.ignore_partial_failures)

  def test_ignore_partial_failures(self) -> None:
    cli, runner = self._run_loading("--ignore-partial-failures")
    self.assertTrue(cli.args.ignore_partial_failures)
    self.assertTrue(runner.ignore_partial_failures)

  def test_cache_temperatures_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertSequenceEqual(cli.args.cache_temperatures,
                             [CacheTemperature.DEFAULT])
    self.assertSequenceEqual(runner.cache_temperatures,
                             (CacheTemperature.DEFAULT,))

  def test_cache_temperatures(self) -> None:
    cli, runner = self._run_loading("--cache-temperatures")
    self.assertEqual(cli.args.cache_temperatures, list(CacheTemperature.all()))
    self.assertEqual(runner.cache_temperatures, tuple(CacheTemperature.all()))

  def test_thread_mode_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertEqual(cli.args.thread_mode, ThreadMode.NONE)
    self.assertEqual(runner._thread_mode, ThreadMode.NONE)

  def test_thread_mode_options(self) -> None:
    for mode in (ThreadMode.PLATFORM, ThreadMode.BROWSER, ThreadMode.SESSION):
      cli, runner = self._run_loading(f"--thread-mode={mode.value}")
      self.assertEqual(cli.args.thread_mode, mode)
      self.assertEqual(runner._thread_mode, mode)

  def test_invalid_thread_mode(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "--thread-mode"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--thread-mode=invalid",
          "--throw",
      )

  def test_step_by_step_mode_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertFalse(cli.args.step_by_step_mode)
    self.assertFalse(runner._step_by_step_mode)

  def test_step_by_step_mode(self) -> None:
    cli, runner = self._run_loading("--step-by-step-mode")
    self.assertTrue(cli.args.step_by_step_mode)
    self.assertTrue(runner._step_by_step_mode)

  def test_symlinks_default(self) -> None:
    cli, runner = self._run_loading()
    self.assertEqual(cli.args.create_symlinks, not self.platform.is_win)
    self.assertEqual(runner.create_symlinks, not self.platform.is_win)

  def test_no_symlinks(self) -> None:
    cli, runner = self._run_loading("--no-symlinks")
    self.assertFalse(cli.args.create_symlinks)
    self.assertFalse(runner.create_symlinks)

  def test_symlinks(self) -> None:
    cli, runner = self._run_loading("--symlinks")
    self.assertTrue(cli.args.create_symlinks)
    self.assertTrue(runner.create_symlinks)

  def test_conflicting_symlinks_flags(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "symlinks"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--symlinks",
          "--no-symlinks",
          "--throw",
      )

  def test_out_dir(self) -> None:
    custom_dir = pth.LocalPath("/custom_results_dir")
    with mock.patch.object(Runner, "run", return_value=None):
      cli, runner = self._run_loading(
          f"--out-dir={custom_dir}", is_dry_run=False)
      self.assertEqual(cli.args.out_dir, custom_dir)
      self.assertEqual(runner.out_dir, custom_dir)

  def test_label(self) -> None:
    cli, _ = self._run_loading("--label=custom_label")
    self.assertEqual(cli.args.label, "custom_label")

  def test_cache_dir(self) -> None:
    custom_cache = pth.LocalPath("/custom_cache_dir")
    cli, _ = self._run_loading(f"--cache-dir={custom_cache}")
    self.assertEqual(cli.args.cache_dir, custom_cache)
    self.assertEqual(str(plt.PLATFORM.cache_dir()), str(custom_cache))

  def test_conflicting_out_dir_and_label(self) -> None:
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--out-dir=/tmp/out",
          "--label=custom_label",
          "--throw",
      )

  def test_fast_mode(self) -> None:
    cli, runner = self._run_loading("--fast")
    self.assertEqual(cli.args.fast, "warn")
    self.assertEqual(cli.args.cool_down_time, dt.timedelta(0))
    self.assertEqual(cli.args.splash_screen, SplashScreen.NONE)
    self.assertEqual(runner.timing.cool_down_time, dt.timedelta(0))

  def test_fast_mode_strict(self) -> None:
    cli, _ = self._run_loading("--fast=strict")
    self.assertEqual(cli.args.fast, "strict")

  def test_time_unit(self) -> None:
    cli, runner = self._run_loading("--time-unit=2.5s")
    self.assertEqual(cli.args.time_unit, dt.timedelta(seconds=2.5))
    self.assertEqual(runner.timing.unit, dt.timedelta(seconds=2.5))

  def test_timeout_unit(self) -> None:
    cli, runner = self._run_loading("--timeout-unit=15s")
    self.assertEqual(cli.args.timeout_unit, dt.timedelta(seconds=15))
    self.assertEqual(runner.timing.timeout_unit, dt.timedelta(seconds=15))

  def test_run_timeout(self) -> None:
    for flag, expected in (
        ("--run-timeout=5m", dt.timedelta(minutes=5)),
        ("--run-timeout=45s", dt.timedelta(seconds=45)),
    ):
      cli, runner = self._run_loading(flag)
      self.assertEqual(cli.args.run_timeout, expected)
      self.assertEqual(runner.timing.run_timeout, expected)

  def test_timing_invalid(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "time-unit"):
      self.run_cli("loading", f"--urls={self.URL}", "--time-unit=invalid",
                   "--throw")

  def test_delays(self) -> None:
    cli, runner = self._run_loading(
        "--start-delay=3s",
        "--setup-delay=2s",
        "--stop-delay=1.5s",
    )
    self.assertEqual(cli.args.start_delay, dt.timedelta(seconds=3))
    self.assertEqual(cli.args.setup_delay, dt.timedelta(seconds=2))
    self.assertEqual(cli.args.stop_delay, dt.timedelta(seconds=1.5))
    self.assertEqual(runner.timing.start_delay, dt.timedelta(seconds=3))
    self.assertEqual(runner.timing.setup_delay, dt.timedelta(seconds=2))
    self.assertEqual(runner.timing.stop_delay, dt.timedelta(seconds=1.5))

  def test_delay_input(self) -> None:
    with mock.patch("builtins.input", return_value=""):
      cli, runner = self._run_loading(
          "--start-delay=input",
          "--setup-delay=input",
          "--stop-delay=input",
      )
      self.assertEqual(cli.args.start_delay, dt.timedelta.max)
      self.assertEqual(cli.args.setup_delay, dt.timedelta.max)
      self.assertEqual(cli.args.stop_delay, dt.timedelta.max)
      self.assertEqual(runner.timing.start_delay, dt.timedelta.max)
      self.assertEqual(runner.timing.setup_delay, dt.timedelta.max)
      self.assertEqual(runner.timing.stop_delay, dt.timedelta.max)

  def test_network_inline_and_default(self) -> None:
    for flag in ("--network=default", "--network=live"):
      cli, _ = self._run_loading(flag)
      self.assertIsInstance(cli.args.network_config, NetworkConfig)
      self.assertEqual(cli.args.network_config.type, NetworkType.LIVE)

  def test_network_config_file(self) -> None:
    net_file = pth.LocalPath("/test_network.config.hjson")
    self.fs.create_file(net_file, contents=hjson.dumps({"type": "live"}))
    cli, _ = self._run_loading(f"--network-config={net_file}")
    self.assertIsInstance(cli.args.network_config, NetworkConfig)
    self.assertEqual(cli.args.network_config.type, NetworkType.LIVE)

  def test_local_file_server_aliases(self) -> None:
    mock_dir = pth.LocalPath("/mock_srv_dir")
    self.fs.create_dir(mock_dir)
    self.fs.create_file(mock_dir / "index.html")
    cli, _ = self._run_loading(f"--local-file-server={mock_dir}")
    self.assertIsInstance(cli.args.network_config, NetworkConfig)
    self.assertEqual(cli.args.network_config.type, NetworkType.LOCAL)
    self.assertEqual(str(cli.args.network_config.path), str(mock_dir))

  def test_wpr_aliases(self) -> None:
    wpr_file = pth.LocalPath("/archive.wprgo")
    self.fs.create_file(wpr_file, contents=b"non_empty_wpr_archive_data")
    for flag in ("--wpr", "--web-page-replay"):
      with mock.patch("crossbench.cli.config.network.LocalWprReplayNetwork"):
        cli, _ = self._run_loading(f"{flag}={wpr_file}")
        self.assertIsInstance(cli.args.network_config, NetworkConfig)
        self.assertEqual(cli.args.network_config.type, NetworkType.WPR)
        self.assertEqual(str(cli.args.network_config.path), str(wpr_file))

  def test_conflicting_network_flags(self) -> None:
    wpr_file = pth.LocalPath("/archive.wprgo")
    self.fs.create_file(wpr_file, contents=b"non_empty_wpr_archive_data")
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--network=live",
          f"--wpr={wpr_file}",
          "--throw",
      )

  def test_env_presets(self) -> None:
    for preset in ("strict", "battery", "power", "catan"):
      cli, runner = self._run_loading(f"--env={preset}")
      self.assertIsNotNone(cli.args.env_config)
      self.assertIsNotNone(runner.env)

  def test_env_config_file(self) -> None:
    env_file = pth.LocalPath("/env.config.hjson")
    self.fs.create_file(
        env_file,
        contents=hjson.dumps({"env": {
            "power_use_battery": False,
        }}),
    )
    cli, runner = self._run_loading(f"--env-config={env_file}")
    self.assertIsNotNone(cli.args.env_config)
    self.assertIsNotNone(runner.env)

  def test_env_validation_modes(self) -> None:
    for mode in ValidationMode:
      cli, runner = self._run_loading(f"--env-validation={mode.value}")
      self.assertEqual(cli.args.env_validation, mode)
      self.assertEqual(runner.env.validation_mode, mode)

  def test_env_validation_invalid(self) -> None:
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--env-validation=invalid",
          "--throw",
      )

  def test_required_device_config_mode_default(self) -> None:
    cli, runner = self._run_loading(is_dry_run=False)
    self.assertEqual(cli.args.required_device_config_mode,
                     RequiredDeviceConfigMode.SET)
    self.assertEqual(runner._required_device_config_mode,
                     RequiredDeviceConfigMode.SET)

  def test_required_device_config_mode_modes(self) -> None:
    for mode in RequiredDeviceConfigMode:
      cli, runner = self._run_loading(
          f"--required-device-config-mode={mode.value}", is_dry_run=False)
      self.assertEqual(cli.args.required_device_config_mode, mode)
      self.assertEqual(runner._required_device_config_mode, mode)

  def test_required_device_config_mode_invalid(self) -> None:
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--required-device-config-mode=invalid",
          "--throw",
      )

  def test_conflicting_env_flags(self) -> None:
    env_file = pth.LocalPath("/env.config.hjson")
    self.fs.create_file(
        env_file,
        contents=hjson.dumps({"env": {
            "power_use_battery": False,
        }}),
    )
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--env=strict",
          f"--env-config={env_file}",
          "--throw",
      )

  def test_dry_run(self) -> None:
    cli, _ = self._run_loading("--dry-run")
    self.assertTrue(cli.args.dry_run)
    self.assertIn("results", str(cli.args.out_dir))

  def test_browser_aliases(self) -> None:
    for flag in ("--browser=chrome-stable", "-b=chrome-dev"):
      cli, runner = self._run_loading(flag)
      self.assertEqual(len(cli.args.browser), 1)
      self.assertEqual(len(runner.browsers), 1)

  def test_browser_config(self) -> None:
    browser_config_file = pth.LocalPath("/browser.config.hjson")
    self.fs.create_file(
        browser_config_file,
        contents=hjson.dumps(
            {"browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                },
            }}),
    )
    cli, runner = self._run_loading(f"--browser-config={browser_config_file}")
    self.assertEqual(len(runner.browsers), 1)
    self.assertIsNotNone(cli.args.browser_config)

  def test_splash_screen_options(self) -> None:
    cli, _ = self._run_loading("--splash-screen=none")
    self.assertEqual(cli.args.splash_screen, SplashScreen.NONE)

    cli, _ = self._run_loading("--splash-screen=minimal")
    self.assertEqual(cli.args.splash_screen, SplashScreen.MINIMAL)

    cli, _ = self._run_loading("--splash-screen=http://custom.com")
    self.assertIsInstance(cli.args.splash_screen, URLSplashScreen)

  def test_no_splash(self) -> None:
    cli, _ = self._run_loading("--no-splash")
    self.assertEqual(cli.args.splash_screen, SplashScreen.NONE)

  def test_conflicting_splash_screen(self) -> None:
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--splash-screen=none",
          "--no-splash",
          "--throw",
      )

  def test_viewport_options(self) -> None:
    cli, _ = self._run_loading("--viewport=maximized")
    self.assertEqual(cli.args.viewport, Viewport.MAXIMIZED)

    cli, _ = self._run_loading("--viewport=1000x800,10x20")
    self.assertEqual(cli.args.viewport.width, 1000)
    self.assertEqual(cli.args.viewport.height, 800)
    self.assertEqual(cli.args.viewport.x, 10)
    self.assertEqual(cli.args.viewport.y, 20)

  def test_headless(self) -> None:
    cli, _ = self._run_loading("--headless")
    self.assertEqual(cli.args.viewport, Viewport.HEADLESS)

  def test_conflicting_viewport_headless(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "not allowed with argument"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--viewport=fullscreen",
          "--headless",
          "--throw",
      )

  def test_viewport_invalid(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "viewport"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--viewport=invalid_size",
          "--throw",
      )

  def test_clear_browser_cache(self) -> None:
    cli, _ = self._run_loading("--clear-browser-cache")
    self.assertTrue(cli.args.clear_browser_cache_dir)

    cli, _ = self._run_loading("--no-clear-browser-cache")
    self.assertFalse(cli.args.clear_browser_cache_dir)

  def test_conflicting_clear_browser_cache(self) -> None:
    with self.assertRaises((argparse.ArgumentError, SysExitTestException)):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--clear-browser-cache",
          "--no-clear-browser-cache",
          "--throw",
      )

  def test_probe_flags(self) -> None:
    cli, runner = self._run_loading("--probe=js")
    self.assertEqual(len(cli.args.probe), 1)
    probe_names = [probe.name for probe in runner.probes]
    self.assertIn("js", probe_names)

  def test_no_probe(self) -> None:
    cli, _ = self._run_loading("--no-probe=js")
    self.assertSequenceEqual(cli.args.no_probe, ["js"])

  def test_invalid_no_probe(self) -> None:
    for invalid in ("--no-probe=", "--no-probe= "):
      with self.assertRaisesRegex(
          (argparse.ArgumentError, SysExitTestException), "no-probe"):
        self.run_cli("loading", f"--urls={self.URL}", invalid, "--throw")

  def test_probe_config(self) -> None:
    probe_config_file = pth.LocalPath("/probes.config.hjson")
    self.fs.create_file(
        probe_config_file, contents=hjson.dumps({"probes": {
            "js": {},
        }}))
    cli, runner = self._run_loading(f"--probe-config={probe_config_file}")
    self.assertIsInstance(cli.args.probe_config, ProbeListConfig)
    probe_names = [probe.name for probe in runner.probes]
    self.assertIn("js", probe_names)

  def test_probe_and_no_probe_conflict(self) -> None:
    probe_config_file = pth.LocalPath("/probes.config.hjson")
    self.fs.create_file(
        probe_config_file, contents=hjson.dumps({"probes": {
            "js": {},
        }}))
    with self._patch_get_browser_cls():
      with self.assertRaisesRegex(
          (argparse.ArgumentTypeError, SysExitTestException),
          "Cannot both enable and disable probes",
      ):
        self.run_cli(
            "loading",
            f"--urls={self.URL}",
            f"--probe-config={probe_config_file}",
            "--probe=js",
            "--no-probe=js",
            "--throw",
        )

  def test_quiet_aliases(self) -> None:
    for flag in ("--quiet", "-q"):
      cli, _ = self._run_loading(flag)
      self.assertEqual(cli.args.verbosity, -1)

  def test_verbose(self) -> None:
    for flag, expected in (
        ("--verbose", 1),
        ("-v", 1),
        ("-vv", 2),
        ("-vvv", 3),
    ):
      cli, _ = self._run_loading(flag)
      self.assertEqual(cli.args.verbosity, expected)

  def test_conflicting_quiet_verbose(self) -> None:
    with self.assertRaisesRegex((argparse.ArgumentError, SysExitTestException),
                                "not allowed with argument"):
      self.run_cli(
          "loading",
          f"--urls={self.URL}",
          "--quiet",
          "--verbose",
          "--throw",
      )

  def test_throw(self) -> None:
    cli, runner = self._run_loading("--throw")
    self.assertTrue(cli.args.throw)
    self.assertTrue(runner.exceptions.throw)

  def test_debug(self) -> None:
    cli, runner = self._run_loading("--debug")
    self.assertTrue(cli.args.throw)
    self.assertEqual(cli.args.verbosity, 3)
    self.assertTrue(cli.args.driver_logging)
    self.assertTrue(runner.exceptions.throw)

  def test_driver_logging(self) -> None:
    cli, runner = self._run_loading("--driver-logging")
    self.assertTrue(cli.args.driver_logging)
    browser = runner.browsers[0]
    self.assertTrue(browser.settings.driver_logging)

  def test_bin_override(self) -> None:
    self.fs.create_file("/bin/wpr")
    self.assertIsNone(plt.PLATFORM.lookup_binary_override("wpr"))
    self.addCleanup(plt.PLATFORM.set_binary_lookup_override, "wpr", None)

    cli, _ = self._run_loading("--bin-override=wpr=/bin/wpr")
    self.assertSequenceEqual(cli.args.binary_overrides, ["wpr=/bin/wpr"])
    self.assertEqual(
        plt.PLATFORM.lookup_binary_override("wpr"),
        plt.PLATFORM.path("/bin/wpr"),
    )

  def test_bin_override_invalid(self) -> None:
    _, _, stderr = self.run_cli_output(
        "loading",
        f"--urls={self.URL}",
        "--bin-override=invalid_no_equals",
        raises=SysExitTestException,
    )
    self.assertIn("Invalid --bin-override format", stderr)

  def test_upload_results_dry_run(self) -> None:
    with mock.patch(
        "crossbench.uploader.results_uploader.upload") as mock_upload:
      cli, runner = self._run_loading(
          "--upload-results=gs://bucket/results",
          "--dry-run",
      )
      self.assertEqual(cli.args.upload_results, "gs://bucket/results")
      mock_upload.assert_not_called()

  def test_upload_results_no_dry_run(self) -> None:
    with (
        mock.patch("crossbench.uploader.results_uploader.upload") as
        mock_upload,
        mock.patch.object(Runner, "run", return_value=None),
    ):
      cli, runner = self._run_loading(
          "--upload-results=gs://bucket/results",
          is_dry_run=False,
      )
      self.assertEqual(cli.args.upload_results, "gs://bucket/results")
      mock_upload.assert_called_once_with(
          source=runner.out_dir, target="gs://bucket/results")

  def test_extra_browser_args(self) -> None:
    cli, runner = self._run_loading(
        "--extra-browser-args=--custom-arg1 --custom-arg2=value")
    self.assertSequenceEqual(cli.args.extra_browser_args,
                             ["--custom-arg1 --custom-arg2=value"])
    browser = runner.browsers[0]
    self.assertIn("--custom-arg1", browser.flags)
    self.assertEqual(browser.flags["--custom-arg2"], "value")

  def test_trailing_browser_args_after_separator(self) -> None:
    cli, runner = self._run_loading(
        "--",
        "--custom-trailing=123",
        "--custom-trailing-flag",
    )
    self.assertSequenceEqual(
        cli.args.other_browser_args,
        ["--custom-trailing=123", "--custom-trailing-flag"],
    )
    browser = runner.browsers[0]
    self.assertEqual(browser.flags["--custom-trailing"], "123")
    self.assertIn("--custom-trailing-flag", browser.flags)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
