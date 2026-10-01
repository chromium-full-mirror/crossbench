# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import io
import pathlib
import unittest
from typing import TYPE_CHECKING, Any, ClassVar, Sequence
from unittest import mock

from typing_extensions import override

from crossbench import config
from crossbench import path as pth
from crossbench import plt
from crossbench.action_runner.config import ActionRunnerConfig
from crossbench.benchmarks.web_power import wpr_helpers
from crossbench.benchmarks.web_power.base import VERSION_STRING, \
    WebPowerBenchmarkBase, WebPowerSiteConfig, WebPowerStory, \
    WebPowerStoryFilter, _value_or
from crossbench.benchmarks.web_power.probe import WebPowerProbe
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.cli.config.network import NetworkConfig, NetworkType
from crossbench.cli.config.probe_list import ProbeListConfig
from crossbench.cli.parser import CBArgumentParser
from crossbench.device_config import DeviceConfigMap, DeviceConfigValueError, \
    RequiredDeviceConfig, RequiredDeviceConfigMode, check_device_config
from crossbench.env.runner_env import ValidationMode
from crossbench.network.replay.wpr import WprReplayNetwork
from crossbench.parse import ObjectParser
from crossbench.probes.bits import BitsProbe
from crossbench.probes.cb_perfetto.perfetto import PerfettoProbe, TraceConfig
from crossbench.probes.junction_temperature import JunctionTemperatureProbe
from crossbench.probes.probe import Probe, ProbeIncompatibleBrowser
from crossbench.probes.trace_processor.query_config import QUERIES_DIR
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe
from crossbench.runner.runner import Runner
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase, \
    CrossbenchFakeFsTestCase, SysExitTestException
from tests.crossbench.benchmarks.helper import BaseBenchmarkTestCase

if TYPE_CHECKING:
  from crossbench.runner.run import Run


class MockWebPowerStory(WebPowerStory):

  @classmethod
  @override
  def story_name_cls(cls) -> str:
    return "mock-story"

  def __init__(
      self,
      name_suffix: str,
      site_config: WebPowerSiteConfig,
      total_duration: dt.timedelta = dt.timedelta(seconds=123),
      stabilization_time: dt.timedelta | None = dt.timedelta(seconds=0),
  ) -> None:
    stabilization_time = _value_or(stabilization_time,
                                   site_config.default_stabilization_time)
    super().__init__(name_suffix, site_config, total_duration,
                     stabilization_time)

  def run(self, run: Run) -> None:
    pass


class MockWebPowerStoryFilter(WebPowerStoryFilter[MockWebPowerStory]):
  """Mock story filter for testing."""

  STORY_CLS = MockWebPowerStory



class MockWebPowerBenchmark(WebPowerBenchmarkBase):
  """Mock WebPowerBenchmark for testing."""

  DEFAULT_STORY_CLS: ClassVar = MockWebPowerStory
  STORY_FILTER_CLS: ClassVar = MockWebPowerStoryFilter


class ValueOrTestCase(unittest.TestCase):

  def test_value_or_with_value(self) -> None:
    self.assertEqual(_value_or(10, 5), 10)
    self.assertEqual(_value_or(0, 5), 0)
    self.assertEqual(_value_or("test", "default"), "test")
    self.assertEqual(_value_or(False, True), False)

  def test_value_or_with_none(self) -> None:
    self.assertEqual(_value_or(None, 5), 5)
    self.assertEqual(_value_or(None, "default"), "default")


class WebPowerStoryTestCase(unittest.TestCase):

  def test_from_site(self) -> None:
    youtube_story = MockWebPowerStory.from_site(
        "youtube", total_duration=dt.timedelta(seconds=123))
    self.assertEqual(youtube_story.url,
                     "https://www.youtube.com/watch?v=XITHbsUUlYI")
    self.assertEqual(youtube_story.name, "web-power-mock-story-youtube")
    self.assertEqual(youtube_story.duration, dt.timedelta(seconds=123))

    cnn_story = MockWebPowerStory.from_site(
        "cnn", total_duration=dt.timedelta(seconds=123))
    self.assertEqual(cnn_story.url, "https://www.cnn.com")
    self.assertEqual(cnn_story.name, "web-power-mock-story-cnn")
    self.assertEqual(cnn_story.duration, dt.timedelta(seconds=123))

  def test_from_invalid_site(self) -> None:
    with self.assertRaisesRegex(ValueError,
                                "Unknown web power benchmark site key"):
      MockWebPowerStory.from_site(
          "invalid-site", total_duration=dt.timedelta(seconds=123))

  def test_from_url(self) -> None:
    story = MockWebPowerStory.from_url(
        "https://www.google.com", total_duration=dt.timedelta(seconds=123))
    self.assertEqual(story.url, "https://www.google.com")
    self.assertEqual(story.name, "web-power-mock-story-custom")
    self.assertEqual(story.duration, dt.timedelta(seconds=123))

  def test_all_sites_have_valid_archive_md5_hash(self) -> None:
    for site_key, site_config in WebPowerStory.SITES.items():
      if site_config.archive:
        parsed = ObjectParser.url(site_config.archive, schemes=("gs",))
        self.assertTrue(
            parsed.fragment.isdigit(),
            f"Missing numeric GCS generation fragment for site {site_key}: "
            f"{site_config.archive}")
        self.assertEqual(
            ObjectParser.md5_hash(site_config.archive_md5_hash),
            site_config.archive_md5_hash,
            f"Invalid archive_md5_hash for site {site_key}")
        self.assertEqual(len(site_config.archive_md5_hash), 16)
      else:
        self.assertEqual(site_config.archive_md5_hash, b"")

  def test_setup_pre_recorded_site_network_sets_expected_md5_hash(self) -> None:
    args = argparse.Namespace(site="cnn", network_config=None)
    MockWebPowerBenchmark._setup_pre_recorded_site_network(args)
    self.assertIsNotNone(args.network_config)
    self.assertEqual(args.network_config.type, NetworkType.WPR)
    self.assertEqual(args.network_config.url,
                     WebPowerStory.SITES["cnn"].archive)
    self.assertEqual(args.network_config.expected_md5_hash,
                     WebPowerStory.SITES["cnn"].archive_md5_hash)

  def test_select_network_live_mode(self) -> None:
    args = argparse.Namespace(
        site=None,
        url="https://example.com",
        network_config=NetworkConfig(type=NetworkType.LIVE))
    MockWebPowerBenchmark._select_network(args)
    self.assertEqual(args.network_config.type, NetworkType.LIVE)
    self.assertEqual(args.network_config.expected_md5_hash, b"")


class WebPowerRequiredDeviceConfigTestCase(CrossbenchFakeFsTestCase):
  """Tests for the device config requirements shipped with WebPower."""

  # Scale factors that a compliant device reports either as unset or as an
  # explicit "1.0", depending on the OS build.
  SCALE_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (
      ("settings", "global", "window_animation_scale"),
      ("settings", "system", "font_scale"),
      ("device_config", "accessibility/font_scale"),
  )

  SCREEN_OFF_TIMEOUT: ClassVar[tuple[str, ...]] = ("settings", "system",
                                                   "screen_off_timeout")

  def setUp(self) -> None:
    super().setUp()
    self.config_path = WebPowerBenchmarkBase.required_device_config()
    self.fs.add_real_file(self.config_path)

  def discrepancies_for(self, key_path: Sequence[str],
                        value: str | None) -> str:
    """Reports discrepancies for a device reporting only key_path=value.

    Other requirements are reported as discrepancies too, so callers must
    only assert on the key under test.
    """
    actual: DeviceConfigMap = {} if value is None else self.nested(
        key_path, value)
    required = RequiredDeviceConfig.parse(self.config_path)
    try:
      check_device_config(required.platforms["android"], actual,
                          RequiredDeviceConfigMode.THROW)
    except DeviceConfigValueError as e:
      return str(e)
    return ""

  @staticmethod
  def nested(key_path: Sequence[str], value: str) -> DeviceConfigMap:
    """Wraps value in the sections named by key_path."""
    node: DeviceConfigMap = {key_path[-1]: value}
    for key in reversed(key_path[:-1]):
      node = {key: node}
    return node

  def test_parses(self) -> None:
    """Verify the shipped config is valid, with android requirements."""
    required = RequiredDeviceConfig.parse(self.config_path)
    self.assertTrue(required.platforms["android"])

  def test_scale_keys_accept_both_spellings_of_the_default(self) -> None:
    """Verify unset and an explicit "1.0" both satisfy every scale key."""
    for key_path in self.SCALE_KEYS:
      for value in (None, "1.0"):
        with self.subTest(key=".".join(key_path), value=value):
          self.assertNotIn(".".join(key_path),
                           self.discrepancies_for(key_path, value))

  def test_scale_keys_reject_a_non_default_scale(self) -> None:
    """Verify a rescaled device is still reported for every scale key."""
    for key_path in self.SCALE_KEYS:
      with self.subTest(key=".".join(key_path)):
        self.assertIn(".".join(key_path),
                      self.discrepancies_for(key_path, "2.0"))

  def test_screen_off_timeout_accepts_longer_timeouts(self) -> None:
    """Verify the bound accepts 30 mins and anything above it."""
    # 30 mins exactly, an hour, and "never".
    for value in ("1800000", "3600000", "2147483647"):
      with self.subTest(value=value):
        self.assertNotIn(".".join(self.SCREEN_OFF_TIMEOUT),
                         self.discrepancies_for(self.SCREEN_OFF_TIMEOUT, value))

  def test_screen_off_timeout_rejects_shorter_timeouts(self) -> None:
    """Verify a display that may dim mid-run is reported."""
    # The Android default of 30s, and 10 mins.
    for value in ("30000", "600000"):
      with self.subTest(value=value):
        self.assertIn(".".join(self.SCREEN_OFF_TIMEOUT),
                      self.discrepancies_for(self.SCREEN_OFF_TIMEOUT, value))


class BaseWebPowerBenchmarkTestCase(BaseBenchmarkTestCase):

  def parse_args(self, *args: str | Sequence[str]) -> argparse.Namespace:
    parsed_args = super().parse_args(*args)
    parsed_args.network_config = NetworkConfig.default()
    parsed_args.probe_config = None
    parsed_args.probe = ()
    return parsed_args


class WebPowerBenchmarkBaseTestCase(BaseWebPowerBenchmarkTestCase):

  def setUp(self) -> None:
    super().setUp()
    mapping_file = QUERIES_DIR / "web_power" / "mapping.hjson"
    self.fs.create_file(mapping_file, contents='{"pixels": "test"}')
    # Required as the missing cpu_time.sql otherwise crashes config parsing
    self.fs.create_file(mapping_file.parent / "cpu_time.sql")
    self.fs.create_file(
        mapping_file.parent.parent / "test.sql", contents="SELECT 1;")
    self.fs.create_file(
        config.config_dir() / "probe/perfetto/trace_config/default.txtpb",
        contents="duration_ms: 1000",
    )
    self.fs.create_file(
        config.config_dir() / "benchmark/web_power/perfetto_basic.txtpb",
        contents="duration_ms: 1000",
    )
    self.bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"

  @property
  @override
  def benchmark_cls(self) -> type[MockWebPowerBenchmark]:
    return MockWebPowerBenchmark

  def test_default_repetitions(self) -> None:
    self.assertEqual(MockWebPowerBenchmark.DEFAULT_REPETITIONS, 5)

  def test_default_cool_down(self) -> None:
    self.assertEqual(MockWebPowerBenchmark.DEFAULT_COOL_DOWN,
                     dt.timedelta(minutes=2))

  def test_default_action_runner_config_no_virtual_devices(self) -> None:
    args = self.parse_args("--site", "cnn")
    benchmark = MockWebPowerBenchmark.from_cli_args(args)
    self.assertEqual(benchmark.action_runner_config.virtual_devices, ())

    run = self.mock_run()
    with mock.patch.object(self.platform,
                           "setup_virtual_devices") as mock_setup_devices:
      benchmark.new_action_runner(self.platform, run)
      mock_setup_devices.assert_called_once_with(())

  def test_custom_action_runner_config(self) -> None:
    story = MockWebPowerStory.from_site("cnn")
    custom_config = ActionRunnerConfig()
    benchmark = MockWebPowerBenchmark(
        stories=[story], action_runner_config=custom_config)
    self.assertEqual(benchmark.action_runner_config, custom_config)

  def test_kwargs_from_cli_site(self) -> None:
    args = self.parse_args("--site", "cnn")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.url, "https://www.cnn.com")
    self.assertEqual(story.name, "web-power-mock-story-cnn")

  def test_kwargs_from_cli_url(self) -> None:
    args = self.parse_args("--url", "https://www.google.com")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.name, "web-power-mock-story-custom")
    self.assertEqual(story.url, "https://www.google.com")

  def test_kwargs_from_cli_help(self) -> None:
    # Passing --help should bypass validation and raise SystemExit natively
    with self.assertRaises(SystemExit):
      self.parse_args("--help")

  def test_kwargs_from_cli_site_wpr_default(self) -> None:
    args = self.parse_args("--site", "cnn")
    # Simulate CLI runner parsing network defaults
    args.network_config = None

    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.name, "web-power-mock-story-cnn")
    # args.network_config should be mapped to WPR with the canonical
    # cnn archive URL
    self.assertIsInstance(args.network_config, NetworkConfig)
    self.assertEqual(args.network_config.type, NetworkType.WPR)
    self.assertEqual(args.network_config.url,
                     WebPowerStory.SITES["cnn"].archive)

  def test_kwargs_from_cli_url_live_default(self) -> None:
    args = self.parse_args("--url", "https://www.google.com")
    # Simulate CLI runner parsing network defaults
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.name, "web-power-mock-story-custom")
    self.assertEqual(args.network_config.type, NetworkType.LIVE)

  def test_kwargs_from_cli_url_with_explicit_network(self) -> None:
    args = self.parse_args("--url", "https://www.google.com")
    # Simulate explicit WPR network config
    args.network_config = NetworkConfig(
        type=NetworkType.WPR, url="gs://some/other.wprgo")

    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.name, "web-power-mock-story-custom")
    self.assertEqual(args.network_config.type, NetworkType.WPR)
    self.assertEqual(args.network_config.url, "gs://some/other.wprgo")

  def test_kwargs_from_cli_site_with_explicit_network_fails(self) -> None:
    args = self.parse_args("--site", "cnn")
    # Simulate conflicting explicit network config
    args.network_config = NetworkConfig(
        type=NetworkType.WPR, url="gs://some/other.wprgo")

    with self.assertRaisesRegex(
        ValueError, "Specifying '--site' is mutually exclusive with explicit"):
      MockWebPowerBenchmark.kwargs_from_cli(args)

  def test_kwargs_from_cli_benchmark_version(self) -> None:
    parser = MockWebPowerBenchmark.add_cli_arguments(CBArgumentParser())
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      with self.assertRaises((SystemExit, SysExitTestException)):
        parser.parse_args(["--benchmark-version"])
      self.assertIn(VERSION_STRING, mock_stdout.getvalue())

  def test_kwargs_from_cli_stabilization(self) -> None:
    args = self.parse_args("--site", "cnn", "--stabilization=10s")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.stabilization_time, dt.timedelta(seconds=10))

    args = self.parse_args("--site", "cnn", "--stabilization-time=15s")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.stabilization_time, dt.timedelta(seconds=15))

    with self.assertRaisesRegex(argparse.ArgumentError, "--stabilization"):
      self.parse_args("--site=cnn", "--stabilization=-5s")
    with self.assertRaisesRegex(argparse.ArgumentError, "--stabilization"):
      self.parse_args("--site=cnn", "--stabilization=invalid")

  def test_kwargs_from_cli_site_invalid(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError, "--site"):
      self.parse_args("--site=non_existent_site")

  def test_kwargs_from_cli_site_and_url_mutually_exclusive(self) -> None:
    with self.assertRaisesRegex(argparse.ArgumentError,
                                "not allowed with argument"):
      self.parse_args("--site=cnn", "--url=https://example.com")

  def test_kwargs_from_cli_bits_invalid(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)
    with self.assertRaisesRegex(argparse.ArgumentError, "--bits-duration"):
      self.parse_args("--site=cnn", "--bits-path", str(bits_path),
                      "--bits-duration=-5s")
    with self.assertRaisesRegex(argparse.ArgumentError, "--bits-duration"):
      self.parse_args("--site=cnn", "--bits-path", str(bits_path),
                      "--bits-duration=0s")
    with self.assertRaisesRegex(argparse.ArgumentError, "--bits-port"):
      self.parse_args("--site=cnn", "--bits-path", str(bits_path),
                      "--bits-port=invalid")


  def test_kwargs_from_cli_bits(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)

    args = self.parse_args("--site", "cnn", "--bits-path", str(bits_path),
                           "--bits-out", "custom_bits_run", "--bits-duration",
                           "5m")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    [story] = kwargs["stories"]
    self.assertEqual(story.name, "web-power-mock-story-cnn")

    bits_probe = kwargs["bits_probe"]
    self.assertIsInstance(bits_probe, BitsProbe)
    self.assertEqual(bits_probe.bits_path, bits_path)
    self.assertEqual(bits_probe.bits_out, "custom_bits_run")
    self.assertEqual(bits_probe.duration, dt.timedelta(minutes=5))
    self.assertEqual(bits_probe.bits_device, "")
    self.assertEqual(bits_probe.port, BitsProbe.DEFAULT_PORT)

  def test_kwargs_from_cli_bits_with_device(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)

    args = self.parse_args("--site", "cnn", "--bits-path", str(bits_path),
                           "--bits-out", "custom_bits_run", "--bits-device",
                           "dev_123", "--bits-duration", "5m")
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    bits_probe = kwargs["bits_probe"]
    self.assertEqual(bits_probe.bits_device, "dev_123")

  def test_kwargs_from_cli_bits_with_port(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)

    args, kwargs = self._parse_and_get_kwargs("--site", "cnn", "--bits-path",
                                              str(bits_path), "--bits-out",
                                              "custom_bits_run", "--bits-port",
                                              "1234", "--bits-duration", "5m")
    bits_probe = kwargs["bits_probe"]
    self.assertEqual(bits_probe.port, 1234)

  def test_bits_probe_property(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)

    bits_probe = BitsProbe(
        bits_path=bits_path,
        bits_out="run_id",
        duration=dt.timedelta(seconds=120),
    )
    story = MockWebPowerStory.from_site(
        "cnn", total_duration=dt.timedelta(seconds=123))
    benchmark = MockWebPowerBenchmark(
        stories=[story],
        bits_probe=bits_probe,
    )
    self.assertIs(benchmark.bits_probe, bits_probe)

  def test_teardown_stops_bits_probe(self) -> None:
    bits_probe = mock.MagicMock(spec=BitsProbe)
    story = MockWebPowerStory.from_site("cnn")
    benchmark = MockWebPowerBenchmark(
        stories=[story],
        bits_probe=bits_probe,
    )
    runner = mock.MagicMock()
    benchmark.teardown(runner)
    bits_probe.teardown.assert_called_once()

  def test_kwargs_from_cli_bits_only_path(self) -> None:
    bits_path = pth.LocalPath(self.platform.default_tmp_dir) / "bits"
    self.fs.create_file(bits_path)

    args = self.parse_args("--site", "cnn", "--bits-path", str(bits_path))

    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)

    bits_probe = kwargs["bits_probe"]
    self.assertIsInstance(bits_probe, BitsProbe)
    self.assertEqual(bits_probe.bits_path, bits_path)
    self.assertEqual(bits_probe.bits_out, "")

    run = self.mock_run()
    now = dt.datetime(2026, 7, 2, 17, 0, 55)
    with mock.patch("crossbench.probes.bits.dt.datetime") as mock_datetime:
      mock_datetime.now.return_value = now
      context = bits_probe.create_context(run)
      self.assertEqual(context.bits_out_id, "20260702_170055")

  def test_kwargs_from_cli_bits_only_out_fails(self) -> None:
    args = self.parse_args("--site", "cnn", "--bits-out", "run_id")
    with self.assertRaises(argparse.ArgumentTypeError):
      MockWebPowerBenchmark.kwargs_from_cli(args)

  def _parse_and_get_kwargs(
      self, *cli_args: str) -> tuple[argparse.Namespace, dict[str, Any]]:
    parser = MockWebPowerBenchmark.add_cli_arguments(CBArgumentParser())
    parser.add_argument(
        "--probe-config",
        type=pathlib.Path,
        default=MockWebPowerBenchmark.default_probe_config_path(),
    )
    # Add necessary arguments that would have been added by parent CLI commands.
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument("--no-probe", action="store_true", default=False)
    parser.add_argument(
        "--network",
        dest="network_config",
        type=NetworkConfig.parse,
        default=NetworkConfig.default())
    args = parser.parse_args(["--site", "cnn", *cli_args])
    kwargs = MockWebPowerBenchmark.kwargs_from_cli(args)
    return args, kwargs

  def test_kwargs_from_cli_probe_config_default(self) -> None:
    # Verify that the default probe config is NOT loaded into args (it is now
    # loaded in setup()).
    args, kwargs = self._parse_and_get_kwargs()
    self.assertIsNone(args.probe_config)
    self.assertNotIn("bits_probe", kwargs)

  def test_kwargs_from_cli_probe_config_override(self) -> None:
    # Verify that explicitly providing --probe-config overrides the default.
    custom_path = pathlib.Path("/path/to/custom.hjson")
    self.fs.create_file(custom_path, contents='{"probes": {"v8.log": {}}}')
    args, kwargs = self._parse_and_get_kwargs("--probe-config",
                                              str(custom_path))
    self.assertEqual(args.probe_config, custom_path)
    self.assertNotIn("bits_probe", kwargs)
    probe_names = [p.name for p in ProbeListConfig.parse_args(args).probes]
    self.assertIn("v8.log", probe_names)
    self.assertNotIn("perfetto", probe_names)

  def test_kwargs_from_cli_probe_config_with_bits_probe(self) -> None:
    # Verify that using BITS prevents the default probe config (and Perfetto)
    # from loading.
    bits_path = pathlib.Path("/path/to/bits")
    self.fs.create_file(bits_path)
    args, kwargs = self._parse_and_get_kwargs("--bits-path", str(bits_path))
    self.assertIsNone(args.probe_config)
    self.assertIn("bits_probe", kwargs)
    probe_names = [p.name for p in ProbeListConfig.parse_args(args).probes]
    self.assertNotIn("perfetto", probe_names)

  def _verify_junction_temperature_setup(
      self, is_supported: bool, already_has_probe: bool) -> mock.MagicMock:
    with mock.patch(
        "crossbench.probes.junction_temperature."
        "JunctionTemperatureProbe.validate_browser") as mock_validate:
      if not is_supported:
        mock_validate.side_effect = ProbeIncompatibleBrowser(
            JunctionTemperatureProbe(), mock.MagicMock(), "Not supported")
      story = MockWebPowerStory.from_site(
          "cnn", total_duration=dt.timedelta(seconds=123))
      benchmark = MockWebPowerBenchmark(stories=[story])

      runner = mock.MagicMock()
      self._mock_has_probe(runner, JunctionTemperatureProbe.NAME,
                           already_has_probe)
      runner.browsers = [mock.MagicMock()]

      benchmark.setup(runner)
      return runner

  def test_setup_junction_temperature_probe_supported(self) -> None:
    runner = self._verify_junction_temperature_setup(
        is_supported=True, already_has_probe=False)
    runner.attach_probe.assert_called_once()
    attached_probe = runner.attach_probe.call_args.args[0]
    self.assertIsInstance(attached_probe, JunctionTemperatureProbe)
    self.assertTrue(
        runner.attach_probe.call_args.kwargs.get("matching_browser_only"))

  def test_setup_junction_temperature_probe_already_has_probe(self) -> None:
    runner = self._verify_junction_temperature_setup(
        is_supported=True, already_has_probe=True)
    runner.attach_probe.assert_not_called()

  def _mock_has_probe(self, runner: mock.MagicMock, probe_name: str,
                      already_has_probe: bool) -> None:
    """Isolate the test by explicitly controlling the mock for one probe and
    defaulting the others to True (already attached), preventing unrelated
    probes from being inadvertently attached by the benchmark."""
    runner.has_probe.side_effect = (lambda name: already_has_probe
                                    if name == probe_name else True)

  def _verify_trace_processor_get_extra_probes(
      self, already_has_probe: bool) -> TraceProcessorProbe | None:
    story = MockWebPowerStory.from_site(
        "cnn", total_duration=dt.timedelta(seconds=123))
    benchmark = MockWebPowerBenchmark(stories=[story])
    probe = WebPowerProbe(benchmark=benchmark)

    runner = mock.MagicMock()
    self._mock_has_probe(runner, "trace_processor", already_has_probe)
    runner.browsers = [mock.MagicMock()]

    extra_probes = tuple(probe.get_extra_probes(runner))
    if not extra_probes:
      return None
    self.assertEqual(len(extra_probes), 1)
    tp_probe = extra_probes[0]
    self.assertIsInstance(tp_probe, TraceProcessorProbe)
    assert isinstance(tp_probe, TraceProcessorProbe)
    return tp_probe

  def test_setup_trace_processor_probe(self) -> None:
    """Verify that the benchmark attaches a TraceProcessorProbe by default."""
    self.assertIsNotNone(
        self._verify_trace_processor_get_extra_probes(already_has_probe=False))

  def test_setup_trace_processor_probe_mapping(self) -> None:
    """Verify that the benchmark configures the TraceProcessorProbe with a
    mapping.hjson that correctly applies different queries to different
    devices."""
    # Overwrite the dummy mapping.hjson from setUp with device-specific queries.
    mapping_file = QUERIES_DIR / "web_power" / "mapping.hjson"
    mapping_file.write_text(
        '{"Pixel 9\\\\b.*": "query_p9", "Pixel 10\\\\b.*": "query_p10"}')
    self.fs.create_file(QUERIES_DIR / "query_p9.sql", contents="SELECT p9;")
    self.fs.create_file(QUERIES_DIR / "query_p10.sql", contents="SELECT p10;")

    tp_probe = self._verify_trace_processor_get_extra_probes(
        already_has_probe=False)
    self.assertIsNotNone(tp_probe)
    query = tp_probe.queries[0]

    platform_p9 = mock.MagicMock()
    platform_p9.model = "Pixel 9 Pro"
    resolved_p9 = query.resolve_for_platform(platform_p9)
    self.assertIsNotNone(resolved_p9)
    self.assertEqual(resolved_p9.sql, "SELECT p9;")

    platform_p10 = mock.MagicMock()
    platform_p10.model = "Pixel 10 Pro XL"
    resolved_p10 = query.resolve_for_platform(platform_p10)
    self.assertIsNotNone(resolved_p10)
    self.assertEqual(resolved_p10.sql, "SELECT p10;")

  def test_setup_trace_processor_probe_already_has_probe(self) -> None:
    """Verify that the benchmark skips attaching a TraceProcessorProbe if one
    is already present."""
    tp_probe = self._verify_trace_processor_get_extra_probes(
        already_has_probe=True)
    self.assertIsNone(tp_probe)

  def test_probe_teardown_and_merge_ordering(self) -> None:
    """Verify that probes are ordered such that TraceProcessorProbe merges data
    before WebPowerProbe attempts to read it, and PerfettoProbe tears down
    before TraceProcessorProbe."""

    if not self.fs.exists(TraceConfig.preset_dir() / "default.txtpb"):
      self.fs.create_file(
          TraceConfig.preset_dir() / "default.txtpb",
          contents="duration_ms: 1000")

    story = MockWebPowerStory.from_site(
        "cnn", total_duration=dt.timedelta(seconds=1))
    benchmark = MockWebPowerBenchmark(stories=[story])

    browser = mock.MagicMock()
    browser.unique_name = "mock_browser"
    browser.driver_logging = False
    browser.label = "mock_label"
    browser.attributes.return_value = BrowserAttributes.CHROMIUM_BASED

    runner = Runner(
        out_dir=self.out_dir,
        browsers=[browser],
        benchmark=benchmark,
        probes=[PerfettoProbe()],
        env_validation_mode=ValidationMode.SKIP,
        in_memory_result_db=True,
    )

    benchmark.setup(runner)

    probe_classes = [type(p) for p in runner.probes]

    perfetto_idx = probe_classes.index(PerfettoProbe)
    tp_idx = probe_classes.index(TraceProcessorProbe)
    wp_idx = probe_classes.index(WebPowerProbe)

    self.assertGreater(
        perfetto_idx, tp_idx,
        "PerfettoProbe must be sorted after TraceProcessorProbe "
        "so that it tears down first")
    self.assertGreater(
        tp_idx, wp_idx,
        "TraceProcessorProbe must be sorted after WebPowerProbe "
        "so that it merges first")


class WebPowerSetupProbesTestCase(WebPowerBenchmarkBaseTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.mock_browser = mock.Mock()
    self.mock_browser.unique_name = "mock_browser"
    self.mock_browser.driver_logging = False
    self.mock_browser.label = "mock_label"
    self.mock_browser.attributes.return_value = BrowserAttributes.CHROMIUM_BASED

  def _setup_runner(
      self,
      with_bits: bool = False,
      probes: Sequence[Probe] = (),
      disabled_probes: Sequence[str] = (),
  ) -> Runner:
    self.mock_browser.platform.is_android = with_bits
    if with_bits and not self.fs.exists(self.bits_path):
      self.fs.create_file(self.bits_path)
    bits_probe = (
        BitsProbe(bits_path=self.bits_path, bits_out="run_id")
        if with_bits else None)
    story = MockWebPowerStory.from_site(
        "cnn", total_duration=dt.timedelta(seconds=1))
    benchmark = MockWebPowerBenchmark(stories=[story], bits_probe=bits_probe)

    runner = Runner(
        out_dir=self.out_dir,
        browsers=[self.mock_browser],
        benchmark=benchmark,
        probes=list(probes),
        disabled_probes=list(disabled_probes),
        env_validation_mode=ValidationMode.SKIP,
        in_memory_result_db=True,
    )

    with mock.patch("crossbench.probes.junction_temperature."
                    "JunctionTemperatureProbe.validate_browser"):
      benchmark.setup(runner)
    return runner

  def test_setup_probes_default_no_bits_no_perfetto(self) -> None:
    runner = self._setup_runner()
    probe_names = [p.name for p in runner.probes]
    self.assertIn("perfetto", probe_names)
    self.assertIn("trace_processor", probe_names)
    self.assertNotIn("bits", probe_names)

  def test_setup_probes_only_perfetto(self) -> None:
    perfetto = PerfettoProbe()
    runner = self._setup_runner(probes=[perfetto])
    probe_names = [p.name for p in runner.probes]
    self.assertEqual(probe_names.count("perfetto"), 1)
    self.assertIn("trace_processor", probe_names)
    self.assertNotIn("bits", probe_names)

  def test_setup_probes_only_bits(self) -> None:
    runner = self._setup_runner(with_bits=True)
    probe_names = [p.name for p in runner.probes]
    self.assertIn("bits", probe_names)
    self.assertNotIn("perfetto", probe_names)
    self.assertNotIn("trace_processor", probe_names)

  def test_setup_probes_both_bits_and_perfetto(self) -> None:
    perfetto = PerfettoProbe()
    runner = self._setup_runner(with_bits=True, probes=[perfetto])
    probe_names = [p.name for p in runner.probes]
    self.assertIn("bits", probe_names)
    self.assertIn("perfetto", probe_names)
    self.assertIn("trace_processor", probe_names)

  def test_setup_probes_skips_disabled_perfetto(self) -> None:
    runner = self._setup_runner(disabled_probes=["perfetto"])
    probe_names = [p.name for p in runner.probes]
    self.assertNotIn("perfetto", probe_names)
    self.assertNotIn("trace_processor", probe_names)
    self.assertNotIn("bits", probe_names)
    self.assertTrue(runner.is_probe_disabled("perfetto"))


class FakeWprReplayNetwork(WprReplayNetwork):

  def __init__(self, archive_path: pth.LocalPath,
               platform: plt.Platform) -> None:
    super().__init__(
        archive=archive_path,
        traffic_shaper=mock.MagicMock(),
        browser_platform=platform,
        persist_server=False,
        inject_deterministic_script=False,
        no_archive_certificates=True,
        response_transformations_file=None,
        cross_platform_mode=False,
        host=None,
    )
    self._server = None

  def _create_server(self, log_dir: Any) -> Any:
    return mock.MagicMock()

  @property
  @override
  def _wpr_platform(self) -> Any:
    return mock.MagicMock()


class WebPowerBenchmarkSetupSessionTestCase(BaseCrossbenchTestCase):

  def setUp(self) -> None:
    super().setUp()
    # Mock WprGoFinder.httparchive() to point to /tmp/httparchive
    wpr_go_finder_patcher = mock.patch(
        "crossbench.benchmarks.web_power.base.WprGoFinder")
    self.mock_finder = wpr_go_finder_patcher.start()
    self.addCleanup(wpr_go_finder_patcher.stop)
    self.mock_finder.return_value.httparchive.return_value = self.platform.path(
        "/tmp/httparchive")
    self.fs.create_file(self.platform.path("/tmp/httparchive"))

    # Mock prepare_gcs_request and download_gcs_file
    prepare_gcs_patcher = mock.patch.object(self.platform,
                                            "prepare_gcs_request")
    self.mock_prepare = prepare_gcs_patcher.start()
    self.addCleanup(prepare_gcs_patcher.stop)

    mock_blob = mock.MagicMock()
    mock_blob.md5_hash = "mock_hash"
    self.mock_prepare.return_value = mock_blob

    download_gcs_patcher = mock.patch.object(self.platform, "download_gcs_file")
    self.mock_download = download_gcs_patcher.start()
    self.addCleanup(download_gcs_patcher.stop)
    self.mock_download.side_effect = (
        lambda url, path: self.fs.create_file(path))

  def _create_session(
      self,
      site_key: str | None = None,
      url: str | None = None,
  ) -> tuple[MockWebPowerBenchmark, FakeWprReplayNetwork, mock.MagicMock]:
    archive_path = pth.LocalPath("/tmp/archive.wprgo")
    if not self.fs.exists(str(archive_path)):
      self.fs.create_file(archive_path)

    with mock.patch("crossbench.network.replay.wpr.WprGoFinder") as mock_finder:
      mock_finder.return_value.wpr.return_value = pth.LocalPath("/tmp/wpr")
      network = FakeWprReplayNetwork(archive_path, self.platform)
    browser = mock.MagicMock()
    browser.network = network

    if site_key:
      story = MockWebPowerStory.from_site(
          site_key, total_duration=dt.timedelta(seconds=10))
    else:
      self.assertIsNotNone(url)
      story = MockWebPowerStory.from_url(
          url, total_duration=dt.timedelta(seconds=10))
    benchmark = MockWebPowerBenchmark(stories=[story])
    run = mock.MagicMock()
    run.story = story
    run.browser = browser

    session = mock.MagicMock()
    session.runs = [run]
    session.first_run = run
    session.is_single_run = True
    session.host_platform = self.platform
    session.network = network
    session.browser = browser

    return benchmark, network, session

  def test_setup_session_network(self) -> None:
    benchmark, network, session = self._create_session(site_key="cnn")
    self.fs.create_file(self.platform.path("/tmp/cnn_archive.wprgo"))

    with mock.patch.object(
        self.platform, "sh_stdout", return_value='{"Metadata": {}}'):
      benchmark.setup_session_network(session)
      expected_archive_path = self.platform.local_cache_dir(
          "wpr") / "cnn_20260513_mock_hash.wprgo"
      self.assertEqual(network.archive_path, expected_archive_path)
      self.assertIsNone(network._response_transformations_file)

  def test_setup_session_network_with_cookie_banner(self) -> None:
    benchmark, network, session = self._create_session(site_key="cnn")
    self.fs.create_file(self.platform.path("/tmp/cnn_archive.wprgo"))
    dismisser_file = pathlib.Path(wpr_helpers.__file__).parent / "dismisser.js"
    self.fs.add_real_file(dismisser_file)

    with mock.patch.object(
        self.platform,
        "sh_stdout",
        return_value=('Dismisser target: button,button,"Accept All",'
                      'https://www.cnn.com')):
      benchmark.setup_session_network(session)
      expected_archive_path = self.platform.local_cache_dir(
          "wpr") / "cnn_20260513_mock_hash.wprgo"
      self.assertEqual(network.archive_path, expected_archive_path)
      self.assertIsNotNone(network._response_transformations_file)
      rules_file = network._response_transformations_file
      self.assertIsNotNone(rules_file)
      self.assertTrue(pathlib.Path(rules_file).exists())

  def test_setup_session_network_with_cookie_banner_no_role(self) -> None:
    benchmark, network, session = self._create_session(site_key="cnn")
    self.fs.create_file(self.platform.path("/tmp/cnn_archive.wprgo"))
    dismisser_file = pathlib.Path(wpr_helpers.__file__).parent / "dismisser.js"
    self.fs.add_real_file(dismisser_file)

    with mock.patch.object(
        self.platform,
        "sh_stdout",
        return_value=('Dismisser target: button,,"Accept All",'
                      'https://www.cnn.com'),
    ):
      benchmark.setup_session_network(session)
      expected_archive_path = (
          self.platform.local_cache_dir("wpr")
          / "cnn_20260513_mock_hash.wprgo"
      )
      self.assertEqual(network.archive_path, expected_archive_path)
      self.assertIsNotNone(network._response_transformations_file)
      rules_file = network._response_transformations_file
      self.assertIsNotNone(rules_file)
      assert rules_file is not None
      self.assertTrue(pathlib.Path(rules_file).exists())

  def test_setup_session_network_twice(self) -> None:
    benchmark, network, session1 = self._create_session(site_key="cnn")
    _, _, session2 = self._create_session(site_key="cnn")
    session2.network = network

    cnn_archive = self.platform.path("/tmp/cnn_archive.wprgo")
    self.fs.create_file(cnn_archive)

    with mock.patch.object(
        self.platform, "sh_stdout", return_value='{"Metadata": {}}'):
      benchmark.setup_session_network(session1)
      with network.open(session1):
        self.assertIsNotNone(network._server)
      self.assertIsNone(network._server)

      benchmark.setup_session_network(session2)
      with network.open(session2):
        self.assertIsNotNone(network._server)
      self.assertIsNone(network._server)

  def test_setup_session_network_different_predefined_sites(self) -> None:
    benchmark1, network, session1 = self._create_session(site_key="cnn")
    benchmark2, _, session2 = self._create_session(site_key="youtube")
    session2.network = network

    self.fs.create_file(self.platform.path("/tmp/cnn_archive.wprgo"))
    self.fs.create_file(self.platform.path("/tmp/youtube_archive.wprgo"))

    with mock.patch.object(
        self.platform, "sh_stdout", return_value='{"Metadata": {}}'):
      # Setup and run cnn
      benchmark1.setup_session_network(session1)
      expected_cnn_path = self.platform.local_cache_dir(
          "wpr") / "cnn_20260513_mock_hash.wprgo"
      self.assertEqual(network.archive_path, expected_cnn_path)
      with network.open(session1):
        self.assertIsNotNone(network._server)
      self.assertIsNone(network._server)

      # Setup and run youtube (should update archive path!)
      benchmark2.setup_session_network(session2)
      expected_youtube_path = self.platform.local_cache_dir(
          "wpr") / "youtube_2026_05_18_mock_hash.wprgo"
      self.assertEqual(network.archive_path, expected_youtube_path)
      with network.open(session2):
        self.assertIsNotNone(network._server)
      self.assertIsNone(network._server)

  def test_setup_session_network_custom_wpr(self) -> None:
    archive_path = pth.LocalPath("/tmp/custom_archive.wprgo")
    self.fs.create_file(archive_path)

    benchmark, network, session = self._create_session(
        url="https://www.google.com")
    network.set_archive_path(archive_path)

    dismisser_file = pathlib.Path(wpr_helpers.__file__).parent / "dismisser.js"
    self.fs.add_real_file(dismisser_file)

    with mock.patch.object(
        self.platform,
        "sh_stdout",
        return_value=('Dismisser target: button,button,"Accept All",'
                      'https://www.google.com')):
      benchmark.setup_session_network(session)
      self.assertEqual(network.archive_path, archive_path)
      self.assertIsNotNone(network._response_transformations_file)
      rules_file = network._response_transformations_file
      self.assertIsNotNone(rules_file)
      self.assertTrue(pathlib.Path(rules_file).exists())


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
