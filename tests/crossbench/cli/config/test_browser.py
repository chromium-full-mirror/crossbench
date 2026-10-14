# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
import unittest
from typing import TYPE_CHECKING

import hjson
from immutabledict import immutabledict

from crossbench import path as pth
from crossbench import plt
from crossbench.browsers.apk_config import ApkConfig
from crossbench.browsers.chrome.chrome import Chrome
from crossbench.browsers.safari.safari import Safari
from crossbench.cli.config.browser import ENV_PRESETS, NETWORK_PRESETS, \
    BrowserConfig, BrowserType
from crossbench.cli.config.driver import DriverConfig
from crossbench.cli.config.driver_type import BrowserDriverType
from crossbench.cli.config.env import ENV_CONFIG_PRESETS
from crossbench.cli.config.network import NetworkConfig
from crossbench.cli.config.network_speed import NetworkSpeedPreset
from crossbench.exception import MultiException
from crossbench.helper.cwd import change_cwd
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.cli.config.base import ADB_DEVICES_OUTPUT, \
    ADB_DEVICES_SINGLE_OUTPUT, IOS_DEVICES_OUTPUT, IOS_DEVICES_SINGLE_OUTPUT, \
    BaseConfigTestCase
from tests.crossbench.mock_helper import ShResult

if TYPE_CHECKING:
  from crossbench.types import JsonDict


class BrowserConfigTestCase(BaseConfigTestCase):

  def test_validate(self):
    with self.assertRaises(ValueError):
      BrowserConfig(browser=None)
    with self.assertRaises(ValueError):
      BrowserConfig(browser=Chrome.stable_path(self.platform), driver=None)

  def test_preset_no_overlap(self):
    # make sure we have unique names between the two preset names so we
    # can have simple short version browser specs
    network_preset_names = NETWORK_PRESETS.split("|")
    env_preset_names = ENV_PRESETS.split("|")
    self.assertFalse(set(network_preset_names).intersection(env_preset_names))

  def test_equal(self):
    path = Chrome.stable_path(self.platform)
    self.assertEqual(
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())),
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())))
    self.assertNotEqual(
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())),
        BrowserConfig(
            path,
            DriverConfig(
                BrowserDriverType.default(), settings=immutabledict(custom=1))))
    self.assertNotEqual(
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())),
        BrowserConfig(
            pth.AnyPath("foo"), DriverConfig(BrowserDriverType.default())))

  def test_hashable(self):
    _ = hash(BrowserConfig.default())
    _ = hash(
        BrowserConfig(
            pth.AnyPath("foo"),
            DriverConfig(
                BrowserDriverType.default(), settings=immutabledict(custom=1))))

  def test_parse_name_or_path(self):
    path = Chrome.stable_path(self.platform)
    self.assertEqual(
        BrowserConfig.parse("chrome"),
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())))
    self.assertEqual(
        BrowserConfig.parse(str(path)),
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())))

  def test_parse_reinstall(self):
    config = BrowserConfig.parse({"browser": "chrome", "reinstall": True})
    self.assertTrue(config.reinstall)
    config = BrowserConfig.parse({"browser": "chrome", "reinstall": False})
    self.assertFalse(config.reinstall)
    config = BrowserConfig.parse({"browser": "chrome"})
    self.assertIsNone(config.reinstall)
    config = BrowserConfig.parse("{browser:'chrome', reinstall: true}")
    self.assertTrue(config.reinstall)
    config = BrowserConfig.parse("{browser:'chrome', reinstall: false}")
    self.assertFalse(config.reinstall)

  def test_reinstall_apk_mutually_exclusive(self):
    path = Chrome.stable_path(self.platform)
    apk_path = self.create_file("foo.apk", contents="non-empty")
    apk = ApkConfig(path=apk_path)
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      BrowserConfig(path, apk=apk, reinstall=True)

    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "mutually exclusive"):
      BrowserConfig.parse({
          "browser": "chrome",
          "reinstall": True,
          "apk": {
              "path": str(apk_path),
          },
      })

  def test_parse_invalid_name(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("a-random-name")
    self.assertIn("a-random-name", str(cm.exception))

  def test_parse_invalid_path(self):
    path = pth.AnyPath("foo/bar")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse(str(path))
    self.assertIn(str(path), str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("selenium/bar")
    self.assertIn("selenium", str(cm.exception))
    self.assertIn("bar", str(cm.exception))

  def test_parse_explicit_browser_type_custom_path(self):
    path = self.create_file("/Applications/Custom.app/Contents/MacOS/Custom")
    config = BrowserConfig.parse({"path": str(path), "type": "chromium"})
    self.assertEqual(config.path, path)
    self.assertEqual(config.browser_type, BrowserType.CHROMIUM)

  def test_parse_explicit_browser_version(self):
    path = Chrome.stable_path(self.platform)
    config = BrowserConfig.parse({
        "path": str(path),
        "version": "120.0.6099.224",
    })
    self.assertEqual(config.path, path)
    self.assertEqual(config.version, "120.0.6099.224")

  def test_parse_empty_browser_version(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse({"path": "chrome", "version": ""})

  def test_parse_invalid_windows_path(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("selenium\\bar")
    self.assertIn("selenium\\\\bar", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("C:\\selenium\\bar")
    self.assertIn("C:\\\\selenium\\\\bar", str(cm.exception))

  def test_parse_config_path(self):
    browser_path = Chrome.stable_path(self.platform)
    config: JsonDict = {"browser": str(browser_path)}
    config_a = BrowserConfig.parse(config)
    with self.platform.NamedTemporaryFile(
        "browser_config.hjson") as config_file:
      with config_file.open("w", encoding="utf-8") as f:
        json.dump(config, f)
      config_b = BrowserConfig.parse(config_file)
    self.assertEqual(config_a, config_b)
    config_c = BrowserConfig.parse(browser_path)
    self.assertEqual(config_a, config_c)
    config_d = BrowserConfig.parse(str(browser_path))
    self.assertEqual(config_a, config_d)

  def test_parse_relative_browser_path(self):
    with self.platform.TemporaryDirectory() as tmp_dir:
      cwd = tmp_dir / "crossbench"
      cwd.mkdir()
      with change_cwd(cwd):
        browser_path = pth.LocalPath("../out/Release/chrome")
        self.fs.create_file(browser_path, st_size=100)
        self.assertTrue((tmp_dir / "out").is_dir())
        config = BrowserConfig.parse(str(browser_path))
        self.assertEqual(config.path, browser_path.resolve())
        config = BrowserConfig.parse(browser_path)
        self.assertEqual(config.path, browser_path.resolve())
      with change_cwd(tmp_dir):
        browser_path = pth.LocalPath("out/Release/chrome")
        config = BrowserConfig.parse(str(browser_path))
        self.assertEqual(config.path, browser_path.resolve())
        config = BrowserConfig.parse(browser_path)
        self.assertEqual(config.path, browser_path.resolve())
        browser_path = pth.LocalPath("./out/Release/chrome")
        config = BrowserConfig.parse(str(browser_path))
        self.assertEqual(config.path, browser_path.resolve())

  def test_home_dir_expansion(self):
    if not self.platform.is_posix:
      return
    home = pth.LocalPath.home()
    browser_path = home / "chromium/src/out/Release/chrome"
    self.fs.create_file(browser_path, st_size=100)
    home_browser_path: str = "~/chromium/src/out/Release/chrome"
    config_a = BrowserConfig.parse(home_browser_path)
    self.assertEqual(config_a.browser, browser_path)
    self.assertTrue(config_a.browser.is_absolute())
    config_dict = {"browser": home_browser_path}
    config_b = BrowserConfig.parse(config_dict)
    self.assertEqual(config_a, config_b)

  def test_parse_simple_missing_driver(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse(":chrome")
    self.assertIn("driver", str(cm.exception))

  def test_parse_invalid_network_preset(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("selenium:chrome:1xx2")
    self.assertIn("network", str(cm.exception))
    self.assertIn("1xx2", str(cm.exception))

  def test_parse_simple_with_driver(self):
    self.assertEqual(
        BrowserConfig.parse("selenium:chrome"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER)))
    self.assertEqual(
        BrowserConfig.parse("webdriver:chrome"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER)))
    self.assertEqual(
        BrowserConfig.parse("applescript:chrome"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.APPLE_SCRIPT)))
    self.assertEqual(
        BrowserConfig.parse("osa:chrome"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.APPLE_SCRIPT)))

  def test_parse_simple_with_driver_with_network(self):
    self.assertEqual(
        BrowserConfig.parse("chrome:4G"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G)))
    self.assertEqual(
        BrowserConfig.parse("selenium:chrome:4G"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G)))

  def test_parse_simple_with_driver_with_env(self):
    self.assertEqual(
        BrowserConfig.parse("chrome:battery"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            env=ENV_CONFIG_PRESETS["battery"]))
    self.assertEqual(
        BrowserConfig.parse("selenium:chrome:battery"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            env=ENV_CONFIG_PRESETS["battery"]))

  def test_parse_simple_with_driver_with_network_and_env(self):
    self.assertEqual(
        BrowserConfig.parse("chrome:4G:battery"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G),
            ENV_CONFIG_PRESETS["battery"]))
    self.assertEqual(
        BrowserConfig.parse("selenium:chrome:4G:battery"),
        BrowserConfig(
            Chrome.stable_path(self.platform),
            DriverConfig(BrowserDriverType.WEB_DRIVER),
            NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G),
            ENV_CONFIG_PRESETS["battery"]))

  def test_parse_simple_ambiguous_with_driver_ios(self):
    with unittest.mock.patch(
        "crossbench.cli.config.browser.ios_devices",
        return_value=IOS_DEVICES_OUTPUT):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        _ = BrowserConfig.parse("ios:chrome")
    self.assertIn("devices", str(cm.exception))

  def test_parse_simple_with_driver_ios(self):
    with unittest.mock.patch(
        "crossbench.cli.config.driver.ios_devices",
        return_value=IOS_DEVICES_SINGLE_OUTPUT):
      config = BrowserConfig.parse("ios:chrome")
      self.assertEqual(
          config,
          BrowserConfig(
              Chrome.stable_path(self.platform),
              DriverConfig(BrowserDriverType.IOS)))
      self.assertIsNone(config.network)
      config = BrowserConfig.parse("ios:chrome:live")
      self.assertEqual(config.network, NetworkConfig.default())

  def test_parse_simple_with_driver_ios_with_network(self):
    with unittest.mock.patch(
        "crossbench.cli.config.driver.ios_devices",
        return_value=IOS_DEVICES_SINGLE_OUTPUT):
      config = BrowserConfig.parse("ios:chrome:4G")
      self.assertEqual(
          config,
          BrowserConfig(
              Chrome.stable_path(self.platform),
              DriverConfig(BrowserDriverType.IOS),
              NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G)))
      self.assertEqual(config.network,
                       NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G))

  def test_parse_simple_ambiguous_with_driver_android(self):
    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = BrowserConfig.parse("adb:chrome")
    self.assertIn("devices", str(cm.exception))

  def test_parse_simple_with_driver_android(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:chrome"),
        BrowserConfig(
            pth.AnyPosixPath("com.android.chrome"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("android:com.chrome.beta"),
        BrowserConfig(
            pth.AnyPosixPath("com.chrome.beta"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

  def test_parse_cdp_android(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("cdp:chrome"),
        BrowserConfig(
            pth.AnyPosixPath("com.android.chrome"),
            DriverConfig(BrowserDriverType.ANDROID_CDP)))
    self.assertListEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("cdp:chrome-beta"),
        BrowserConfig(
            pth.AnyPosixPath("com.chrome.beta"),
            DriverConfig(BrowserDriverType.ANDROID_CDP)))
    self.assertListEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("android:chrome-beta"),
        BrowserConfig(
            pth.AnyPosixPath("com.chrome.beta"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:chrome-dev"),
        BrowserConfig(
            pth.AnyPosixPath("com.chrome.dev"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("android:chrome-app"),
        BrowserConfig(
            pth.AnyPosixPath("com.google.android.apps.chrome"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("android:app")
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("android:chrome-canary"),
        BrowserConfig(
            pth.AnyPosixPath("com.chrome.canary"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("android:chromium"),
        BrowserConfig(
            pth.AnyPosixPath("org.chromium.chrome"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:webview"),
        BrowserConfig(
            pth.AnyPosixPath("org.chromium.webview_shell"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:org.chromium.webview_shell"),
        BrowserConfig(
            pth.AnyPosixPath("org.chromium.webview_shell"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:webview_embedder"),
        BrowserConfig(
            pth.AnyPosixPath("webview_embedder"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:com.google.android.googlequicksearchbox"),
        BrowserConfig(
            pth.AnyPosixPath("com.google.android.googlequicksearchbox"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    package = "com.google.android.libraries.ads.mobile.maitier.testapps.webview"
    self.assertEqual(
        BrowserConfig.parse(f"adb:{package}"),
        BrowserConfig(
            pth.AnyPosixPath(package), DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

  def test_parse_simple_with_local_apk(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:/chrome/src/out/Release/chromium.apk"),
        BrowserConfig(
            pth.LocalPosixPath("/chrome/src/out/Release/chromium.apk"),
            DriverConfig(BrowserDriverType.ANDROID)))

  def test_parse_simple_with_local_built_apk_helper(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    self.assertEqual(
        BrowserConfig.parse("adb:/chrome/src/out/Release/chrome_public_apk"),
        BrowserConfig(
            pth.LocalPosixPath("/chrome/src/out/Release/chrome_public_apk"),
            DriverConfig(BrowserDriverType.ANDROID)))

  def test_parse_adb_custom_apk(self):
    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    path_str = "/test/my_custom_apk"
    path = pth.LocalPath(path_str)
    self.fs.create_file(path)
    config = BrowserConfig.parse(f"adb:{path_str}")
    self.assertEqual(config.path, path)
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Unsupported browser"):
      BrowserConfig.parse(path_str)

  def test_parse_adb_custom_bundle(self):
    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    path_str = "/test/my_custom_bundle"
    path = pth.LocalPath(path_str)
    self.fs.create_file(path)
    config = BrowserConfig.parse(f"adb:{path_str}")
    self.assertEqual(config.path, path)
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Unsupported browser"):
      BrowserConfig.parse(path_str)

  def test_parse_arbitrary_apk_no_prefix(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    path_str = "/test/my_app.apk"
    path = pth.LocalPath(path_str)
    self.fs.create_file(path)
    config = BrowserConfig.parse(path_str)
    self.assertEqual(config.path, path)
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    explicit_config = BrowserConfig.parse(f"adb:{path_str}")
    self.assertEqual(config, explicit_config)

  def test_parse_apk_colon_in_path_fails(self):
    path_str = "/test/my:app.apk"
    path = pth.LocalPath(path_str)
    self.fs.create_file(path)
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Invalid browser short form"):
      BrowserConfig.parse(f"adb:{path_str}")

  def test_parse_simple_with_local_built_apk_helper_no_prefix(self):
    paths = (
        "/chrome/src/out/Release/chrome_public_apk",
        "/chrome/src/out/Release/chrome_apk",
        "/out/android-arm64-release/bin/chrome_public_bundle",
    )
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ] * len(paths)
    for path_str in paths:
      with self.subTest(path=path_str):
        path = pth.LocalPath(path_str)
        self.fs.create_file(path)
        auto_config = BrowserConfig.parse(path_str)
        adb_config = BrowserConfig(path.resolve(),
                                   DriverConfig(BrowserDriverType.ANDROID))
        self.assertEqual(auto_config.path, adb_config.path)
        self.assertEqual(auto_config.driver.driver_type,
                         BrowserDriverType.ANDROID)
        self.assertEqual(auto_config, adb_config)

  @unittest.skip("Non-path browser short names are not yet supported "
                 "in complex configs.")
  def test_parse_inline_hjson_android(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    config_dict: JsonDict = {
        "browser": "com.android.chrome",
        "driver": "android",
    }
    self.assertEqual(
        BrowserConfig.parse(config_dict),
        BrowserConfig(
            pth.AnyPath("com.android.chrome"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertSequenceEqual(self.platform.sh_results, [])

  def test_parse_invalid_android_package(self):
    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse("adb:com.Foo .bar. com")
    self.assertIn("com.Foo .bar. com", str(cm.exception))

  def test_parse_fail_android_browser_string_not_dict(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse({"browser": "adb:chrome"})
    self.assertIn("browser", str(cm.exception))
    self.assertIn("short-form", str(cm.exception))

  @unittest.skipIf(plt.PLATFORM.is_win,
                   "Chrome downloading not supported on windows.")
  def test_parse_chrome_version(self):
    self.assertEqual(
        BrowserConfig.parse("applescript:chrome-m100"),
        BrowserConfig("chrome-m100",
                      DriverConfig(BrowserDriverType.APPLE_SCRIPT)))
    self.assertEqual(
        BrowserConfig.parse("selenium:chrome-116.0.5845.4"),
        BrowserConfig("chrome-116.0.5845.4",
                      DriverConfig(BrowserDriverType.WEB_DRIVER)))

  def test_parse_invalid_chrome_version(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = BrowserConfig.parse("applescript:chrome-m1")
    self.assertIn("m1", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = BrowserConfig.parse("selenium:chrome-116.845.4.3.2.1.0")
    self.assertIn("116.845.4.3.2.1.0", str(cm.exception))

  def test_parse_adb_phone_serial(self):
    self.platform.sh_results = [ADB_DEVICES_OUTPUT, ADB_DEVICES_OUTPUT]
    config = BrowserConfig.parse("0a388e93:chrome")
    assert isinstance(config, BrowserConfig)
    self.assertSequenceEqual(self.platform.sh_results, [])
    self.assertEqual(len(self.platform.sh_cmds), 2)

    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    expected_driver = DriverConfig(
        BrowserDriverType.ANDROID, device_id="0a388e93")
    self.assertEqual(len(self.platform.sh_results), 0)
    self.assertEqual(len(self.platform.sh_cmds), 3)
    self.assertEqual(
        config,
        BrowserConfig(pth.AnyPosixPath("com.android.chrome"), expected_driver))

  def test_parse_adb_phone_serial_invalid_macos(self):
    if not plt.PLATFORM.is_macos:
      return
    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = BrowserConfig.parse("0XXXXXX:chrome")
    self.assertIn("0XXXXXX", str(cm.exception))
    self.assertEqual(len(self.platform.sh_cmds), 2)

  def test_parse_adb_phone_serial_invalid_non_macos(self):
    if plt.PLATFORM.is_macos:
      return
    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      _ = BrowserConfig.parse("0XXXXXX:chrome")
    self.assertIn("0XXXXXX", str(cm.exception))
    self.assertEqual(len(self.platform.sh_cmds), 1)

  def test_parse_invalid_driver(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("____:chrome")
    with self.assertRaises(argparse.ArgumentTypeError):
      # This has to be dealt with in users of DriverConfig.parse.
      BrowserConfig.parse("::chrome")

  def test_parse_invalid_hjson(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("{:::}")
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("{}")
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("}")
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("{path:something}")

  def test_parse_inline_hjson(self):
    config_dict: JsonDict = {"browser": "chrome", "driver": {"type": "adb"}}

    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    with self.assertRaises(MultiException) as cm:
      _ = BrowserConfig.parse(hjson.dumps(config_dict))
    self.assertIn("devices", str(cm.exception))

    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    config_1 = BrowserConfig.parse(hjson.dumps(config_dict))
    assert isinstance(config_1, BrowserConfig)
    self.assertEqual(config_1.driver.driver_type, BrowserDriverType.ANDROID)

    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    config_2 = BrowserConfig.parse_dict(config_dict)
    assert isinstance(config_2, BrowserConfig)
    self.assertEqual(config_2.driver.driver_type, BrowserDriverType.ANDROID)
    self.assertEqual(config_1, config_2)

    short_config_dict: JsonDict = {
        "browser": "chrome",
        "driver": "adb",
    }
    self.platform.sh_results = [ADB_DEVICES_OUTPUT]
    with self.assertRaises(MultiException) as cm:
      _ = BrowserConfig.parse(hjson.dumps(short_config_dict))
    self.assertIn("devices", str(cm.exception))

    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    config_3 = BrowserConfig.parse_dict(short_config_dict)
    assert isinstance(config_3, BrowserConfig)
    self.assertEqual(config_3.driver.driver_type, BrowserDriverType.ANDROID)
    self.assertEqual(config_1, config_3)

  def test_parse_inline_hjson_short_string(self):
    # We cannot easily configure the driver property from within the browser
    # config property.
    config_dict: JsonDict = {
        "browser": "adb:chrome",
    }
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse_dict(config_dict)

  def test_parse_inline_driver_browser(self):
    driver_path = pth.LocalPath("/custom/chromedriver")
    config_dict: JsonDict = {
        "browser": "chrome",
        "driver": str(driver_path),
    }
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "custom/chromedriver"):
      BrowserConfig.parse(hjson.dumps(config_dict))
    self.fs.create_file(driver_path, st_size=100)
    config = BrowserConfig.parse(hjson.dumps(config_dict))
    assert isinstance(config, BrowserConfig)
    self.assertEqual(config.browser,
                     mock_browser.MockChromeStable.mock_app_path())
    self.assertEqual(config.driver.driver_type, BrowserDriverType.WEB_DRIVER)
    self.assertEqual(config.driver.path, driver_path)

  def test_parse_with_range_simple(self):
    versions = BrowserConfig.parse_with_range("chrome-m100")
    self.assertSequenceEqual(versions, (BrowserConfig.parse("chrome-m100"),))

  def test_parse_with_range(self):
    result = (BrowserConfig.parse("chrome-m99"),
              BrowserConfig.parse("chrome-m100"),
              BrowserConfig.parse("chrome-m101"),
              BrowserConfig.parse("chrome-m102"))
    versions = BrowserConfig.parse_with_range("chrome-m99...chrome-m102")
    self.assertSequenceEqual(versions, result)
    versions = BrowserConfig.parse_with_range("chrome-m99...m102")
    self.assertSequenceEqual(versions, result)
    versions = BrowserConfig.parse_with_range("chrome-m99...102")
    self.assertSequenceEqual(versions, result)

  def test_parse_with_range_invalid_empty(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse_with_range("")
    self.assertIn("empty", str(cm.exception))

  def test_parse_with_range_invalid_prefix(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse_with_range("chr-m100...chrome-m200")
    msg = str(cm.exception)
    self.assertIn("'chr-m'", msg)
    self.assertIn("'chrome-m'", msg)

  def test_parse_with_range_invalid_limit(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse_with_range("chr-m100...chr-m90")
    msg = str(cm.exception).lower()
    self.assertIn("larger", msg)
    self.assertIn("chr-m100...chr-m90", msg)

  def test_parse_with_range_missing_digits(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse_with_range("chr-m...chrome-m90")
    msg = str(cm.exception).lower()
    self.assertIn("start", msg)
    self.assertIn("'chr-m'", msg)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserConfig.parse_with_range("chr-m100...chr")
    msg = str(cm.exception).lower()
    self.assertIn("limit", msg)
    self.assertIn("'chr'", msg)

  def test_parse_with_multiple_android_devices(self):
    adb_devices = ShResult("List of devices attached\n"
                           "1111 device usb:1 product:p1 model:m1 device:d1\n"
                           "2222 device usb:2 product:p2 model:m2 device:d2\n"
                           "3333 device usb:3 product:p3 model:m3 device:d3\n")
    self.platform.sh_results = [adb_devices] * 13
    self.assertSequenceEqual(
        BrowserConfig.parse_with_range("adb-all:chrome"),
        (BrowserConfig.parse("1111:chrome"), BrowserConfig.parse("2222:chrome"),
         BrowserConfig.parse("3333:chrome")))

  @unittest.skipUnless(plt.PLATFORM.is_macos,
                       "Running on iOS is only possible in mac hosts")
  def test_parse_with_multiple_ios_devices(self):
    adb_devices = ShResult("List of devices attached\n\n")
    self.platform.sh_results = ([adb_devices] * 6)
    ios_devices = {
        "ID-1": plt.ios.IOSDeviceInfo("ID-1", "device1", "26.0"),
        "ID-2": plt.ios.IOSDeviceInfo("ID-2", "device2", "26.0"),
        "ID-3": plt.ios.IOSDeviceInfo("ID-3", "device3", "26.0"),
    }
    with (unittest.mock.patch(
        "crossbench.cli.config.browser.ios_devices", return_value=ios_devices),
          unittest.mock.patch(
              "crossbench.cli.config.driver.ios_devices",
              return_value=ios_devices)):
      self.assertSequenceEqual(
          BrowserConfig.parse_with_range("ios-all:safari"),
          (BrowserConfig.parse("ID-1:safari"),
           BrowserConfig.parse("ID-2:safari"),
           BrowserConfig.parse("ID-3:safari")))

  def test_parse_safari_variants(self):
    config = BrowserConfig.parse("safari")
    self.assertEqual(config.path, Safari.default_path(self.platform))
    for name in ("sf", "sf-stable", "safari-stable"):
      config_b = BrowserConfig.parse(name)
      self.assertEqual(config, config_b)

  def test_parse_safari_tech_preview_variants(self):
    config = BrowserConfig.parse("safari-technology-preview")
    self.assertEqual(config.path, Safari.technology_preview_path(self.platform))
    for name in ("safari-tp", "safari-tech-preview", "sf-tp", "stp", "tp"):
      config_b = BrowserConfig.parse(name)
      self.assertEqual(config, config_b)

  def test_parse_local_d8(self):
    v8_path = "/Documents/v8/v8/out/release/d8"
    self.fs.create_file(v8_path, st_size=100)
    self.assertEqual(
        BrowserConfig.parse(v8_path),
        BrowserConfig(pth.LocalPosixPath(v8_path)))

  def test_parse_webkit_download(self):
    if not self.platform.is_macos:
      self.skipTest("Unsupported platform")
    version_str = "webkit-nightly-299105@main"
    config = BrowserConfig.parse(version_str)
    self.assertEqual(config.browser, version_str)

  def test_parse_adb_all_no_devices_error(self):
    adb_devices = ShResult("List of devices attached\n\n")
    self.platform.sh_results = [adb_devices]
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse_with_range("adb-all:chrome")

  def test_parse_ios_all_no_devices_error(self):
    with unittest.mock.patch(
        "crossbench.cli.config.browser.ios_devices", return_value={}), \
         unittest.mock.patch(
             "crossbench.cli.config.driver.ios_devices", return_value={}):
      with self.assertRaises(argparse.ArgumentTypeError):
        BrowserConfig.parse_with_range("ios-all:safari")

  def test_parse_adb_ip_serial(self):
    adb_devices = ShResult(
        "List of devices attached\n"
        "192.168.0.1:5555 device product:sdk model:m device:d\n")
    self.platform.sh_results = [adb_devices, adb_devices]
    config = BrowserConfig.parse("192.168.0.1:5555:chrome")
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    self.assertEqual(config.driver.device_id, "192.168.0.1:5555")

  def test_parse_adb_ip_serial_with_network(self):
    adb_devices = ShResult(
        "List of devices attached\n"
        "192.168.0.1:5555 device product:sdk model:m device:d\n")
    self.platform.sh_results = [adb_devices, adb_devices]
    config = BrowserConfig.parse("192.168.0.1:5555:chrome:4G")
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    self.assertEqual(config.driver.device_id, "192.168.0.1:5555")
    self.assertEqual(config.network,
                     NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G))

  def test_parse_adb_ip_serial_with_network_and_env(self):
    adb_devices = ShResult(
        "List of devices attached\n"
        "192.168.0.1:5555 device product:sdk model:m device:d\n")
    self.platform.sh_results = [adb_devices, adb_devices]
    config = BrowserConfig.parse("192.168.0.1:5555:chrome:4G:battery")
    self.assertEqual(config.driver.driver_type, BrowserDriverType.ANDROID)
    self.assertEqual(config.driver.device_id, "192.168.0.1:5555")
    self.assertEqual(config.network,
                     NetworkConfig.parse_live(NetworkSpeedPreset.MOBILE_4G))
    self.assertEqual(config.env, ENV_CONFIG_PRESETS["battery"])

  def test_parse_adb_all_multiple_ip_devices(self):
    adb_devices = ShResult(
        "List of devices attached\n"
        "192.168.0.1:5555 device product:p1 model:m1 device:d1\n"
        "192.168.0.1:5556 device product:p2 model:m2 device:d2\n")
    self.platform.sh_results = [adb_devices] * 9
    self.assertSequenceEqual(
        BrowserConfig.parse_with_range("adb-all:chrome"),
        (BrowserConfig.parse("192.168.0.1:5555:chrome"),
         BrowserConfig.parse("192.168.0.1:5556:chrome")))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
