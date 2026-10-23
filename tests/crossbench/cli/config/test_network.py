# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import json
import unittest
import urllib.parse as urlparse

from crossbench import path as pth
from crossbench.cli.config.network import NetworkConfig, NetworkSpeedConfig, \
    NetworkType
from crossbench.cli.config.network_speed import NetworkSpeedPreset
from tests import test_helper
from tests.crossbench.cli.config.base import BaseConfigTestCase


class NetworkSpeedConfigTestCase(BaseConfigTestCase):

  def test_parse_invalid(self):
    for invalid in ("", None, "---"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          NetworkSpeedConfig.parse(invalid)
        with self.assertRaises(argparse.ArgumentTypeError):
          NetworkSpeedConfig.parse_str(str(invalid))
      with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                  r"(?i)choices are"):
        NetworkSpeedConfig.parse("not a speed preset value")

  def test_parse_default(self):
    config = NetworkSpeedConfig.parse("default")
    self.assertEqual(config, NetworkSpeedConfig.default())

  def test_default(self):
    config = NetworkSpeedConfig.default()
    self.assertIsNone(config.rtt_ms)
    self.assertIsNone(config.in_kbps)
    self.assertIsNone(config.out_kbps)
    self.assertIsNone(config.window)

  def test_parse_speed_preset(self):
    config = NetworkSpeedConfig.parse("4G")
    self.assertNotEqual(config, NetworkSpeedConfig.default())

    for preset in NetworkSpeedPreset:
      config = NetworkSpeedConfig.parse(str(preset))
      self.assertEqual(config, NetworkSpeedConfig.parse_preset(preset))

  def test_parse_invalid_preset(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkSpeedConfig.parse("1xx4")
    self.assertIn("1xx4", str(cm.exception))
    self.assertIn("Choices are", str(cm.exception))

  def test_parse_dict(self):
    config = NetworkSpeedConfig.parse({
        "rtt_ms": 100,
        "in_kbps": 200,
        "out_kbps": 300,
        "window": 400,
    })
    self.assertIsNone(config.ts_proxy)
    self.assertEqual(config.rtt_ms, 100)
    self.assertEqual(config.in_kbps, 200)
    self.assertEqual(config.out_kbps, 300)
    self.assertEqual(config.window, 400)

  def test_parse_invalid_dict(self):
    for int_property in ("rtt_ms", "in_kbps", "out_kbps", "window"):
      with self.subTest(config_property=int_property):
        with self.assertRaises(argparse.ArgumentTypeError) as cm:
          _ = NetworkSpeedConfig.parse({int_property: -100})
        self.assertIn(int_property, str(cm.exception))

  def test_parse_ts_proxy_path(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = NetworkSpeedConfig.parse({"ts_proxy": "/some/random/path"})
    self.assertIn("ts_proxy", str(cm.exception))
    ts_proxy = pth.LocalPath("/python/ts_proxy.py")
    self.fs.create_file(ts_proxy, st_size=100)
    config = NetworkSpeedConfig.parse({"ts_proxy": str(ts_proxy)})
    self.assertEqual(config.ts_proxy, ts_proxy)


class NetworkConfigTestCase(BaseConfigTestCase):

  def test_default_is_frozen(self):
    # NetworkConfig.default relies on a frozen immutable state for proper
    # default network detection.
    config = NetworkConfig.default()
    with self.assertRaises(dataclasses.FrozenInstanceError):
      config.foo = "bar"

  def test_parse_invalid(self):
    for invalid in ("", None, "---", "something"):
      with self.assertRaises(argparse.ArgumentTypeError):
        NetworkConfig.parse(invalid)
      with self.assertRaises(argparse.ArgumentTypeError):
        NetworkConfig.parse_str(str(invalid))

  def test_parse_args_empty(self):
    args = self.mock_args(network_config=None)
    config = NetworkConfig.parse_args(args)
    self.assertIs(config, NetworkConfig.default())

  def test_parse_args_str(self):
    args = self.mock_args(network_config="default")
    config = NetworkConfig.parse_args(args)
    self.assertIs(config, NetworkConfig.default())
    args = self.mock_args(network_config="live")
    config = NetworkConfig.parse_args(args)
    self.assertIsNot(config, NetworkConfig.default())
    self.assertEqual(config.type, NetworkType.LIVE)

  def test_parse_default(self):
    config = NetworkConfig.parse("default")
    self.assertEqual(config, NetworkConfig.default())

  def test_default(self):
    config = NetworkConfig.default()
    self.assertEqual(config.type, NetworkType.LIVE)
    self.assertEqual(config.speed, NetworkSpeedConfig.default())
    config_1 = NetworkConfig.parse({})
    self.assertEqual(config, config_1)
    config_2 = NetworkConfig.parse("{}")
    self.assertEqual(config, config_2)

  def test_is_default(self):
    self.assertIs(NetworkConfig.default(), NetworkConfig.default())
    with self.assertRaises(argparse.ArgumentTypeError):
      NetworkConfig.parse_str("default", type=NetworkType.WPR)
    with self.assertRaises(argparse.ArgumentTypeError):
      NetworkConfig.parse_str("default", type=NetworkType.LOCAL)
    with self.assertRaises(TypeError):
      NetworkConfig.default(NetworkType.LIVE)  # type: ignore[call-arg]
    self.assertTrue(NetworkConfig.default().is_default())
    self.assertTrue(NetworkConfig.parse("default").is_default())
    self.assertEqual(NetworkConfig.default(), NetworkConfig.parse("live"))
    self.assertIsNot(NetworkConfig.default(), NetworkConfig.parse("live"))
    self.assertFalse(NetworkConfig.parse("live").is_default())
    self.assertFalse(NetworkConfig(type=NetworkType.LIVE).is_default())
    self.assertFalse(NetworkConfig.parse("4G").is_default())
    self.assertFalse(
        NetworkConfig(
            type=NetworkType.LIVE,
            speed=NetworkSpeedConfig.parse("4G")).is_default())
    self.assertFalse(
        NetworkConfig(type=NetworkType.LOCAL,
                      path=pth.LocalPath(".")).is_default())
    default_local = NetworkConfig.default_local(pth.LocalPath("."))
    self.assertTrue(default_local.is_default())
    self.assertEqual(
        default_local,
        NetworkConfig(type=NetworkType.LOCAL, path=pth.LocalPath(".")))

  def test_help(self):
    help_text = NetworkConfig.help()
    self.assertTrue(help_text)
    self.assertIn("type", help_text)
    self.assertIn("speed", help_text)

  def test_parse_local_type_mismatch(self):
    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Expected local file server"):
      NetworkConfig.parse_local(str(path))

  def test_parse_str_type_mismatch(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "expected LIVE"):
      NetworkConfig.parse_str("4G", type=NetworkType.LOCAL)

  def test_parse_url_type_mismatch(self):
    url = urlparse.urlparse("gs://bucket/wprgo.archive")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "expected WPR"):
      NetworkConfig.parse_url(url, type=NetworkType.LIVE)

  def test_parse_path_fallback(self):
    path = pth.LocalPath("/test/config.json")
    self.fs.create_file(path, contents='{"type": "live"}')
    config = NetworkConfig.parse(path)
    self.assertEqual(config.type, NetworkType.LIVE)

  def test_validate(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Missing NetworkConfig.type"):
      NetworkConfig(type=None)

    class FalsyNetworkSpeedConfig(NetworkSpeedConfig):

      def __bool__(self):
        return False

    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Missing NetworkConfig.speed"):
      NetworkConfig(type=NetworkType.LIVE, speed=FalsyNetworkSpeedConfig())

    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "archive path.*download url"):
      NetworkConfig(
          type=NetworkType.WPR, path=path, url="gs://bucket/wprgo.archive")

    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "cross_platform_mode.*run_on_device"):
      NetworkConfig(
          type=NetworkType.WPR,
          path=path,
          cross_platform_mode=True,
          run_on_device=True)

  def test_parse_dict_wpr_response_transformations(self):
    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    rules_file = pth.LocalPath("/test/rules.json")
    self.fs.create_file(rules_file, contents="{}")

    config = NetworkConfig.parse({
        "type": "wpr",
        "path": str(path),
        "response_transformations_file": str(rules_file),
    })
    self.assertEqual(config.type, NetworkType.WPR)
    self.assertEqual(config.path, path)
    self.assertEqual(config.response_transformations_file, rules_file.resolve())

  def test_parse_replay_archive_invalid(self):
    path = pth.LocalPath("/foo/bar/wprgo.archive")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse(str(path))
    message = str(cm.exception)
    self.assertIn(str(path), message)
    self.assertIn("exist", message)

    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse(path)
    message = str(cm.exception)
    self.assertIn(str(path), message)
    self.assertIn("exist", message)

    self.fs.create_file(path)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse(str(path))
    message = str(cm.exception)
    self.assertIn("webpagereplay archive", message)
    self.assertIn("empty", message)

  def test_parse_invalid_port_for_cross_platform_mode(self):
    path = pth.LocalPath("/foo/bar/wprgo.archive")
    self.fs.create_file(path, st_size=1024)
    with self.assertRaisesRegex(
        argparse.ArgumentTypeError,
        "http_port and https_port cannot be set in cross_platform_mode"):
      _ = NetworkConfig.parse({
          "type": "wpr",
          "path": str(path),
          "cross_platform_mode": True,
          "http_port": 1234,
      })
    with self.assertRaisesRegex(
        argparse.ArgumentTypeError,
        "http_port and https_port cannot be set in cross_platform_mode"):
      _ = NetworkConfig.parse({
          "type": "wpr",
          "path": str(path),
          "cross_platform_mode": True,
          "https_port": 5678,
      })

  def test_parse_invalid_port_for_local_file_network(self):
    path = pth.LocalPath("/foo/bar/dir")
    self.fs.create_dir(path)
    self.fs.create_file(path / "index.html")
    with self.assertRaisesRegex(
        argparse.ArgumentTypeError,
        "http_port can only be used for the WPR replay network"):
      _ = NetworkConfig.parse({
          "type": "local",
          "path": str(path),
          "http_port": 1234,
      })
    with self.assertRaisesRegex(
        argparse.ArgumentTypeError,
        "https_port can only be used for the WPR replay network"):
      _ = NetworkConfig.parse({
          "type": "local",
          "path": str(path),
          "https_port": 5678,
      })

  def test_parse_wpr_ports(self):
    path = pth.LocalPath("/foo/bar/wprgo.archive")
    self.fs.create_file(path, st_size=1024)
    config = NetworkConfig.parse({
        "type": "wpr",
        "path": str(path),
        "http_port": 8080,
        "https_port": 8081,
    })
    self.assertEqual(config.type, NetworkType.WPR)
    self.assertEqual(config.path, path)
    self.assertEqual(config.http_port, 8080)
    self.assertEqual(config.https_port, 8081)

  def test_parse_wprgo_archive(self):
    path = pth.LocalPath("/foo/bar/wprgo.archive")
    self.fs.create_file(path, st_size=1024)
    config = NetworkConfig.parse(str(path))
    assert isinstance(config, NetworkConfig)
    self.assertEqual(config.type, NetworkType.WPR)
    self.assertEqual(config.path, path)
    self.assertEqual(config.speed, NetworkSpeedConfig.default())

  def test_parse_wprgo_archive_url(self):
    url = "gs://bucket/wprgo.archive"
    config = NetworkConfig.parse(url)
    assert isinstance(config, NetworkConfig)
    self.assertEqual(config.type, NetworkType.WPR)
    self.assertEqual(config.url, url)
    self.assertEqual(config.speed, NetworkSpeedConfig.default())

  def test_parse_invalid_wprgo_archive_url(self):
    url = "http://bucket/wprgo.archive"
    with self.assertRaisesRegex(argparse.ArgumentTypeError, url):
      _ = NetworkConfig.parse(url)
    url = "://bucket/wprgo.archive"
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "bucket/wprgo.archive"):
      _ = NetworkConfig.parse(url)

  def test_invalid_constructor_params(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = NetworkConfig(path=pth.LocalPath("foo/bar"))
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = NetworkConfig(type=NetworkType.LOCAL, path=None)
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = NetworkConfig(type=NetworkType.WPR, path=None)

  def test_parse_speed_preset(self):
    for preset in NetworkSpeedPreset:
      config = NetworkConfig.parse_str(preset.value)
      self.assertEqual(config.speed, NetworkSpeedConfig.parse_preset(preset))

  def test_parse_live_preset(self):
    live_a = NetworkConfig.parse_live("4G")
    live_b = NetworkConfig.parse_live(NetworkSpeedConfig.parse("4G"))
    live_c = NetworkConfig.parse_live(
        NetworkSpeedConfig.parse(NetworkSpeedPreset.MOBILE_4G))
    live_d = NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G)
    self.assertEqual(live_a, live_b)
    self.assertEqual(live_a, live_c)
    self.assertEqual(live_a, live_d)

  def test_parse_wpr_invalid(self):
    dir_path = pth.LocalPath("test/dir")
    dir_path.mkdir(parents=True)
    for invalid in ("", "default", "4G", dir_path, str(dir_path)):
      with self.assertRaises(argparse.ArgumentTypeError):
        NetworkConfig.parse_wpr(invalid)

  def test_parse_wpr(self):
    archive_path = pth.LocalPath("/test/archive.wprgo")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse_wpr(archive_path)
    self.assertIn(str(archive_path), str(cm.exception))
    self.fs.create_file(archive_path, st_size=100)
    config = NetworkConfig.parse_wpr(archive_path)
    self.assertEqual(config.type, NetworkType.WPR)
    self.assertEqual(config.speed, NetworkSpeedConfig.default())
    self.assertEqual(config.path, archive_path)
    self.assertEqual(config, NetworkConfig.parse(archive_path))
    config_2 = NetworkConfig.parse_wpr("test/archive.wprgo")
    self.assertEqual(config, config_2)
    config_2 = NetworkConfig.parse_wpr(pth.LocalPath("test/archive.wprgo"))
    self.assertEqual(config, config_2)

  def test_parse_dict_default(self):
    config = NetworkConfig.parse({})
    self.assertEqual(config, NetworkConfig.default())

  def test_parse_local_dict_default(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      # Missing path
      NetworkConfig.parse_local({})

  def test_parse_dict_speed(self):
    config_dict = {"speed": "4G"}
    config: NetworkConfig = NetworkConfig.parse(dict(config_dict))
    self.assertNotEqual(config, NetworkConfig.default())
    self.assertEqual(config.type, NetworkType.LIVE)
    self.assertEqual(
        config.speed,
        NetworkSpeedConfig.parse_preset(NetworkSpeedPreset.MOBILE_4G))
    self.assertIsNone(config.path)
    self.assertTrue(config_dict)
    config_1 = NetworkConfig.parse(json.dumps(config_dict))
    self.assertEqual(config, config_1)

  def test_parse_dict_wpr(self):
    archive_path = pth.LocalPath("/test/archive.wprgo")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "wpr", "path": archive_path})
    self.assertIn(str(archive_path), str(cm.exception))
    self.fs.create_file(archive_path, st_size=100)
    config_dict = {"type": "wpr", "path": str(archive_path)}
    config = NetworkConfig.parse(dict(config_dict))
    self.assertEqual(config, NetworkConfig.parse_wpr(archive_path))
    self.assertTrue(config_dict)
    config_1 = NetworkConfig.parse(json.dumps(config_dict))
    self.assertEqual(config, config_1)

  def test_parse_dict_wpr_only_flags(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "live", "persist_server": True})
    self.assertIn("can only be used for the WPR", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "live", "run_on_device": True})
    self.assertIn("can only be used for the WPR", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({
          "type": "live",
          "skip_deterministic_script_injection": True,
      })
    self.assertIn("can only be used for the WPR", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "live", "host": "localhost"})
    self.assertIn("can only be used for the WPR", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "live", "cross_platform_mode": True})
    self.assertIn("can only be used for the WPR", str(cm.exception))

  def test_parse_dict_local(self):
    benchmark_folder = pth.LocalPath("third_party/speedometer/v3.0")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse({"type": "local", "path": benchmark_folder})
    self.assertIn(str(benchmark_folder), str(cm.exception))
    self.fs.create_file(benchmark_folder / "index.html", st_size=100)
    url = "http://foo:1234"
    config_dict = {"type": "local", "path": str(benchmark_folder), "url": url}
    config = NetworkConfig.parse(dict(config_dict))
    self.assertEqual(config.type, NetworkType.LOCAL)
    self.assertEqual(config.path, benchmark_folder.resolve())
    self.assertEqual(config.url, url)
    self.assertTrue(config_dict)
    config_1 = NetworkConfig.parse(json.dumps(config_dict))
    self.assertEqual(config, config_1)
    local_config_dict = dict(config_dict)
    del local_config_dict["type"]
    config_local = NetworkConfig.parse_local(dict(local_config_dict))
    self.assertEqual(config, config_local)
    config_local = NetworkConfig.parse_local(json.dumps(local_config_dict))
    self.assertEqual(config, config_local)

  def test_parse_local_file(self):
    benchmark_folder = pth.LocalPath("third_party/speedometer/v3.0").resolve()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse(benchmark_folder)
    self.assertIn(str(benchmark_folder), str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NetworkConfig.parse_local(benchmark_folder)
    self.assertIn(str(benchmark_folder), str(cm.exception))
    self.fs.create_file(benchmark_folder / "index.html", st_size=100)
    config = NetworkConfig.parse(str(benchmark_folder))
    self.assertEqual(config.type, NetworkType.LOCAL)
    self.assertEqual(config.path, benchmark_folder)
    self.assertIsNone(config.url)
    self.assertEqual(config, NetworkConfig.parse(benchmark_folder))
    self.assertEqual(config, NetworkConfig.parse_local(str(benchmark_folder)))
    self.assertEqual(config, NetworkConfig.parse_local(benchmark_folder))


class NetworkConfigCreateTestCase(BaseConfigTestCase):

  def test_create_live(self):
    config = NetworkConfig(type=NetworkType.LIVE)
    mock_platform = unittest.mock.MagicMock()
    with unittest.mock.patch(
        "crossbench.cli.config.network.LiveNetwork") as mock_live:
      config.create_network(mock_platform)
      mock_live.assert_called_once()

  def test_create_local(self):
    path = pth.LocalPath("/test/dir")
    self.fs.create_dir(path)
    self.fs.create_file(path / "index.html")
    config = NetworkConfig(type=NetworkType.LOCAL, path=path)
    mock_platform = unittest.mock.MagicMock()
    with unittest.mock.patch(
        "crossbench.cli.config.network.LocalFileNetwork") as mock_local:
      config.create_network(mock_platform)
      mock_local.assert_called_once()

  def test_create_wpr_local(self):
    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    config = NetworkConfig(type=NetworkType.WPR, path=path)
    mock_platform = unittest.mock.MagicMock()
    mock_platform.is_remote = False
    with unittest.mock.patch(
        "crossbench.cli.config.network.LocalWprReplayNetwork") as mock_wpr:
      config.create_network(mock_platform)
      mock_wpr.assert_called_once()

  def test_create_wpr_remote(self):
    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    config = NetworkConfig(type=NetworkType.WPR, path=path, run_on_device=True)
    mock_platform = unittest.mock.MagicMock()
    mock_platform.is_remote = True
    with unittest.mock.patch(
        "crossbench.cli.config.network.RemoteWprReplayNetwork") as mock_wpr:
      mock_wpr.is_compatible.return_value = True
      config.create_network(mock_platform)
      mock_wpr.assert_called_once()

  def test_create_wpr_remote_incompatible(self):
    path = pth.LocalPath("/test/archive.wprgo")
    self.fs.create_file(path, st_size=100)
    config = NetworkConfig(type=NetworkType.WPR, path=path, run_on_device=True)
    mock_platform = unittest.mock.MagicMock()
    mock_platform.is_remote = True
    with unittest.mock.patch(
        "crossbench.cli.config.network.RemoteWprReplayNetwork") as mock_wpr:
      mock_wpr.is_compatible.return_value = False
      with self.assertRaisesRegex(ValueError, "run_on_device is unsupported"):
        config.create_network(mock_platform)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
