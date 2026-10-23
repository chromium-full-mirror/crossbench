# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from typing import TYPE_CHECKING, Any, Mapping
from unittest import mock

import hjson
import pytest
from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.browsers.cdp_android import CdpAndroidBrowser
from crossbench.browsers.chrome.applescript import ChromeAppleScript
from crossbench.browsers.chrome.chrome import Chrome
from crossbench.browsers.chrome.version import ChromeVersion
from crossbench.browsers.chrome.webdriver import ChromeWebDriver, \
    ChromeWebDriverAndroid, ChromeWebDriverChromeOsSsh, ChromeWebDriverSsh, \
    LocalChromeWebDriverAndroid
from crossbench.browsers.chromium.applescript import ChromiumAppleScript
from crossbench.browsers.chromium.webdriver import ChromiumWebDriver, \
    ChromiumWebDriverAndroid, ChromiumWebDriverSsh
from crossbench.browsers.safari.safari import Safari
from crossbench.browsers.safari.webdriver import SafariWdaIOS, \
    SafariWebdriverIOS
from crossbench.browsers.webkit.webdriver import WebKitWebDriver
from crossbench.browsers.webview.browser import WebviewBrowser
from crossbench.browsers.webview.embedder import WebviewEmbedder
from crossbench.cli.config.browser import BrowserConfig, BrowserType
from crossbench.cli.config.browser_variants import BaseBrowserVariantsConfig, \
    BrowserVariantsConfig, BrowserVariantsConfigDict
from crossbench.cli.config.driver import DriverConfig
from crossbench.cli.config.driver_type import BrowserDriverType
from crossbench.cli.config.env import ENV_CONFIG_PRESETS, EnvConfig
from crossbench.cli.config.network import NetworkConfig, NetworkType
from crossbench.config import ConfigError
from crossbench.helper.cwd import change_cwd
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.cli.config.base import ADB_DEVICES_SINGLE_OUTPUT, \
    BaseConfigTestCase
from tests.crossbench.mock_helper import AndroidAdbMockPlatform, MockAdb, \
    ShResult

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser


class TestBrowserVariantsConfig(BaseConfigTestCase):
  EXAMPLE_CONFIG_PATH = test_helper.config_dir() / "doc/browser.config.hjson"

  EXAMPLE_REMOTE_CONFIG_PATH = (
      test_helper.config_dir() / "doc/remote_browser.config.hjson")

  @override
  def setUp(self):
    super().setUp()
    self.browser_lookup: Mapping[str, tuple[
        type[mock_browser.MockBrowser], BrowserConfig]] = {
            "chr-stable":
                (mock_browser.MockChromeStable,
                 BrowserConfig(mock_browser.MockChromeStable.mock_app_path())),
            "chr-dev":
                (mock_browser.MockChromeDev,
                 BrowserConfig(mock_browser.MockChromeDev.mock_app_path())),
            "chrome-stable":
                (mock_browser.MockChromeStable,
                 BrowserConfig(mock_browser.MockChromeStable.mock_app_path())),
            "chrome-dev":
                (mock_browser.MockChromeDev,
                 BrowserConfig(mock_browser.MockChromeDev.mock_app_path())),
        }
    for (_, browser_config) in self.browser_lookup.values():
      self.assertTrue(browser_config.path.exists())

  @contextlib.contextmanager
  def _patch_get_browser_cls(self,
                             return_value: type[Browser] | None = None,
                             **kwargs):
    if not kwargs:
      kwargs["return_value"] = return_value or mock_browser.MockChromeStable
    with mock.patch.object(BaseBrowserVariantsConfig, "get_browser_cls",
                           **kwargs):
      yield

  def _expect_linux_ssh(self, cmd, **kwargs):
    return self.platform.expect_sh("ssh", *plt.LinuxSshPlatform.SSH_OPTIONS,
                                   "-p", "22", "user@my-linux-machine", cmd,
                                   **kwargs)

  def _expect_chromeos_ssh(self, cmd, **kwargs):
    return self.platform.expect_sh("ssh", *plt.LinuxSshPlatform.SSH_OPTIONS,
                                   "-p", "22", "root@my-chromeos-machine", cmd,
                                   **kwargs)

  def test_parse_browser_config_template(self):
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open(encoding="utf-8") as f:
      config = BrowserVariantsConfigDict(
          browser_lookup_override=self.browser_lookup)
      config.parse_text_io(f, args=self.mock_args())
    self.assertIn("flag-group-1", config.flags_config)
    self.assertGreaterEqual(len(config.flags_config), 1)
    self.assertEqual(len(config.variants), 5)
    inline_variant = config.variants[0]
    self.assertEqual(inline_variant.label, "chrome-stable-with-inline-flags")
    self.assertIn("--foo", inline_variant.flags)
    self.assertIn("--bar", inline_variant.flags)
    self.assertIsNone(inline_variant.flags["--foo"])
    self.assertEqual(inline_variant.flags["--bar"], "12")

  def _expect_sh_linux_ssh_browser_config(self):
    pass

  def _expect_sh_linux_ssh_browser_instance(self):
    self._expect_linux_ssh("'[' -e /path/to/google/chrome ']'")
    self._expect_linux_ssh("'[' -f /path/to/google/chrome ']'")
    self._expect_linux_ssh("'[' -e /path/to/google/chrome ']'")
    self._expect_linux_ssh(
        "/path/to/google/chrome --version", result="102.22.33.44")

  def _expect_sh_chromeos_ssh_browser_config(self):
    self._expect_chromeos_ssh("'[' -e /usr/local/autotest/bin/autologin.py ']'")

  def _expect_sh_chromeos_ssh_browser_instance(self):
    self._expect_chromeos_ssh("'[' -e /opt/google/chrome/chrome ']'")
    self._expect_chromeos_ssh("'[' -f /opt/google/chrome/chrome ']'")
    self._expect_chromeos_ssh("'[' -e /opt/google/chrome/chrome ']'")
    self._expect_chromeos_ssh(
        "/opt/google/chrome/chrome --version", result="125.0.6422.60")

  def test_parse_remote_browser_config_template(self):
    self.mock_platform_default_tmp_dir(plt.LinuxSshPlatform)
    self.fs.add_real_file(self.EXAMPLE_REMOTE_CONFIG_PATH)

    self._expect_sh_linux_ssh_browser_config()
    self._expect_sh_linux_ssh_browser_config()
    self._expect_sh_chromeos_ssh_browser_config()
    self._expect_sh_chromeos_ssh_browser_config()

    self._expect_sh_linux_ssh_browser_instance()
    self._expect_sh_linux_ssh_browser_instance()
    self._expect_sh_chromeos_ssh_browser_instance()
    self._expect_sh_chromeos_ssh_browser_instance()

    with self.EXAMPLE_REMOTE_CONFIG_PATH.open(encoding="utf-8") as f:
      config = BrowserVariantsConfigDict()
      config.parse_text_io(f, args=self.mock_args())
      browsers = config.browsers
      self.assertEqual(len(browsers), 4)
      for variant in browsers:
        self.assertTrue(variant.platform.is_remote)
        self.assertTrue(variant.platform.is_linux)

      self.assertIsNone(browsers[0].driver_path_raw)
      self.assertEqual(str(browsers[1].driver_path), "/path/to/chromedriver")
      self.assertIsNone(browsers[2].driver_path_raw)
      self.assertEqual(str(browsers[3].driver_path), "/path/to/chromedriver")

      self.assertEqual(browsers[0].platform.name, "linux_ssh")
      self.assertEqual(browsers[1].platform.name, "linux_ssh")
      self.assertEqual(browsers[2].platform.name, "chromeos_ssh")
      self.assertEqual(browsers[3].platform.name, "chromeos_ssh")
      self.assertEqual(browsers[0].version.parts_str, "102.22.33.44")
      self.assertEqual(browsers[1].version.parts_str, "102.22.33.44")
      self.assertEqual(browsers[2].version.parts_str, "125.0.6422.60")
      self.assertEqual(browsers[3].version.parts_str, "125.0.6422.60")

  def test_parse_remote_browser_config_template_override_driver_path(self):
    override_driver_path = pth.AnyPosixPath("/path/to/override/chromedriver")
    args = self.mock_args(remote_driver_path=override_driver_path)
    config = BrowserVariantsConfigDict()

    self.mock_platform_default_tmp_dir(plt.LinuxSshPlatform)
    self._expect_sh_linux_ssh_browser_config()
    self._expect_sh_linux_ssh_browser_config()
    config_dict = {
        "browsers": {
            "linux-ssh-chrome-auto-start-driver": {
                "path": "/path/to/google/chrome",
                "driver": {
                    "type": "ssh",
                    "path": "/path/to/chromedriver",
                    "settings": {
                        "host": "my-linux-machine",
                        "ssh_port": 22,
                        "ssh_user": "user",
                    },
                },
            },
            "linux-ssh-chrome-auto-start-driver-no-path": {
                "path": "/path/to/google/chrome",
                "driver": {
                    "type": "ssh",
                    "settings": {
                        "host": "my-linux-machine",
                        "ssh_port": 22,
                        "ssh_user": "user",
                    },
                },
            },
        },
    }
    config.parse_dict(config_dict, args)
    variants = config.variants
    self.assertEqual(len(variants), 2)
    self.assertEqual(variants[0].settings.driver_path, override_driver_path)
    self.assertEqual(variants[1].settings.driver_path, override_driver_path)

  def test_browser_labels_attributes(self):
    browsers = BrowserVariantsConfigDict(
        {
            "browsers": {
                "chrome-stable-default": {
                    "path": "chrome-stable",
                },
                "chrome-stable-noopt": {
                    "path": "chrome-stable",
                    "flags": ["--js-flags=--max-opt=0"],
                },
                "chrome-stable-custom": {
                    "label": "custom-label-property",
                    "path": "chrome-stable",
                    "flags": ["--js-flags=--max-opt=0"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args()).variants
    self.assertEqual(len(browsers), 3)
    self.assertEqual(browsers[0].label, "chrome-stable-default")
    self.assertEqual(browsers[1].label, "chrome-stable-noopt")
    self.assertEqual(browsers[2].label, "custom-label-property")

  def test_browser_label_args(self):
    self.platform.sh_results = [ADB_DEVICES_SINGLE_OUTPUT]
    args = self.mock_args()
    adb_config = BrowserConfig.parse("adb:chrome")
    desktop_config = BrowserConfig.parse("chrome")
    args.browser = [
        adb_config,
        desktop_config,
    ]
    self.assertFalse(self.platform.sh_results)
    sh_results = [ADB_DEVICES_SINGLE_OUTPUT] * 2
    if self.platform.is_macos:
      # For `brew --prefix`.
      sh_results.insert(0, ShResult(returncode=1))
    # Note: insert() on self.platform.sh_results fails, that returns a copy.
    self.platform.sh_results = sh_results

    def mock_get_browser_cls(browser_config: BrowserConfig):
      if browser_config is adb_config:
        return mock_browser.MockChromeAndroidStable
      if browser_config is desktop_config:
        return mock_browser.MockChromeStable
      raise ValueError("Unknown browser_config")

    with self._patch_get_browser_cls(
        side_effect=mock_get_browser_cls), mock.patch(
            "crossbench.plt.android_adb.AndroidAdbPlatform.machine",
            new_callable=mock.PropertyMock,
            return_value=plt.MachineArch.ARM_64):
      variants = BrowserVariantsConfig.parse_args(args).variants
    self.assertEqual(len(variants), 2)
    self.assertEqual(variants[0].label, "android.emulator-5556.777_0")
    self.assertEqual(variants[1].label, f"{self.platform}_1")

    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-stable-label": {
                      "path": "chrome-stable",
                  },
                  "chrome-stable-custom": {
                      "label": "chrome-stable-label",
                      "path": "chrome-stable",
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())
    message = str(cm.exception)
    self.assertIn("chrome-stable-label", message)
    self.assertIn("chrome-stable-custom", message)

  def test_parse_invalid_browser_type(self):
    invalid: Any
    for invalid in (None, 1, []):
      with self.assertRaises(ConfigError) as cm:
        BrowserVariantsConfigDict(
            {"browsers": {
                "chrome-stable-default": invalid,
            }},
            args=self.mock_args())
      self.assertIn("Expected str or dict", str(cm.exception))

  def test_browser_custom_driver_variants(self):
    adb_ip_devices = ShResult(
        "List of devices attached\n"
        "192.168.0.1:5555 device product:sdk model:m device:d\n")
    sh_results = [adb_ip_devices] * 7
    if self.platform.is_macos:
      # For `brew --prefix`.
      sh_results.insert(1, ShResult(returncode=1))
      sh_results.insert(4, ShResult(returncode=1))
      sh_results.append(adb_ip_devices)
    # Note: insert() on self.platform.sh_results fails, that returns a copy.
    self.platform.sh_results = sh_results

    def mock_get_browser_platform(
        browser_config: BrowserConfig) -> plt.Platform:
      if browser_config.driver.driver_type == BrowserDriverType.ANDROID:
        return AndroidAdbMockPlatform(
            self.platform,
            adb=MockAdb(
                self.platform,
                device_identifier=browser_config.driver.device_id))
      return self.platform

    with self._patch_get_browser_cls(
        mock_browser.MockChromeAndroidStable), mock.patch.object(
            BaseBrowserVariantsConfig,
            "_get_browser_platform",
            side_effect=mock_get_browser_platform):
      variants_config = BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-stable-default": "chrome-stable",
                  "chrome-stable-adb": "adb:chrome",
                  "chrome-stable-adb2": {
                      "path": "chrome",
                      "driver": "adb",
                  },
                  "chrome-stable-adb-ip": "192.168.0.1:5555:chrome",
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())
      variants = variants_config.variants
    self.assertEqual(len(variants), 4)
    self.assertEqual(variants[0].label, "chrome-stable-default")
    self.assertEqual(variants[1].label, "chrome-stable-adb")
    self.assertEqual(variants[2].label, "chrome-stable-adb2")
    self.assertEqual(variants[3].label, "chrome-stable-adb-ip")
    self.assertEqual(variants[0].browser_cls, mock_browser.MockChromeStable)
    self.assertEqual(variants[1].browser_cls,
                     mock_browser.MockChromeAndroidStable)
    self.assertEqual(variants[2].browser_cls,
                     mock_browser.MockChromeAndroidStable)
    self.assertEqual(variants[3].browser_cls,
                     mock_browser.MockChromeAndroidStable)

  def test_flag_combination_invalid(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {
                      "invalid-flag-name": [None, "", "v1"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1"],
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args()).variants
    message = str(cm.exception)
    self.assertIn("group1", message)
    self.assertIn("invalid-flag-name", message)

  def test_flag_combination_none(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {
                      "--foo": ["None,", "", "v1"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1"],
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args()).variants
    self.assertIn("None", str(cm.exception))

  def test_flag_combination_duplicate(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {
                      "--duplicate-flag": [None, "", "v1"],
                  },
                  "group2": {
                      "--duplicate-flag": [None, "", "v1"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1", "group2"],
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args()).variants
    self.assertIn("--duplicate-flag", str(cm.exception))

  def test_empty(self):
    with self.assertRaises(ConfigError):
      BrowserVariantsConfigDict({"other": {}}, args=self.mock_args()).variants
    with self.assertRaises(ConfigError):
      BrowserVariantsConfigDict({
          "browsers": {},
      }, args=self.mock_args()).variants

  def test_unknown_group(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["unknown-flag-group"],
                  },
              },
          },
          args=self.mock_args()).variants
    self.assertIn("unknown-flag-group", str(cm.exception))

  def test_duplicate_group(self):
    with self.assertRaisesRegex(ConfigError, "group1"):
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {},
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1", "group1"],
                  },
              },
          },
          args=self.mock_args()).browsers

  def test_non_list_group(self):
    BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {},
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": "group1",
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args()).variants
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {},
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": 1,
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args()).variants
    self.assertIn("chrome-stable", str(cm.exception))
    self.assertIn("flags", str(cm.exception))

    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {},
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": {
                          "group1": True,
                      },
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args()).variants
    self.assertIn("chrome-stable", str(cm.exception))
    self.assertIn("flags", str(cm.exception))

  def test_duplicate_flag_variant_value(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "group1": {
                      "--flag": ["repeated", "repeated"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": "group1",
                  },
              },
          },
          args=self.mock_args()).variants
    self.assertIn("group1", str(cm.exception))
    self.assertIn("--flag", str(cm.exception))

  def test_unknown_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "path/does/not/exist",
                  },
              },
          },
          args=self.mock_args()).variants
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-unknown",
                  },
              },
          },
          args=self.mock_args()).variants

  def test_flag_combination_simple(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 3)
    for browser in browsers:
      self.assertEqual(browser.browser_cls, mock_browser.MockChromeStable)
      self.assertDictEqual(browser.js_flags.to_dict(), {})
    self.assertDictEqual(browsers[0].flags.to_dict(), {})
    self.assertDictEqual(browsers[1].flags.to_dict(), {"--foo": None})
    self.assertDictEqual(browsers[2].flags.to_dict(), {"--foo": "v1"})

  def test_flag_list(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": [
                    "",
                    "--foo",
                    "-foo=v1",
                ],
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 3)
    for browser in browsers:
      self.assertEqual(browser.browser_cls, mock_browser.MockChromeStable)
      self.assertDictEqual(browser.js_flags.to_dict(), {})
    self.assertDictEqual(browsers[0].flags.to_dict(), {})
    self.assertDictEqual(browsers[1].flags.to_dict(), {"--foo": None})
    self.assertDictEqual(browsers[2].flags.to_dict(), {"-foo": "v1"})

  def test_flag_combination(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                    "--bar": [None, "", "v1"],
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 3 * 3)

  def test_flag_combination_mixed_inline(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "compile-hints-experiment": {
                    "--enable-features": [None, "ConsumeCompileHints"],
                },
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": ["--no-sandbox", "compile-hints-experiment"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 2)
    self.assertSequenceEqual(["--no-sandbox"], list(browsers[0].flags))
    self.assertSequenceEqual(
        ["--no-sandbox", "--enable-features=ConsumeCompileHints"],
        list(browsers[1].flags))

  def test_flag_single_inline(self):
    config = BrowserVariantsConfigDict(
        {
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": "--no-sandbox",
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 1)
    self.assertSequenceEqual(["--no-sandbox"], list(browsers[0].flags))

  def test_flag_direct_inline_list(self):
    config = BrowserVariantsConfigDict(
        {
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": ["--foo", "--bar=12"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 1)
    self.assertSequenceEqual(["--foo", "--bar=12"], list(browsers[0].flags))
    self.assertIsNone(browsers[0].flags["--foo"])
    self.assertEqual(browsers[0].flags["--bar"], "12")

  def test_flag_direct_inline_with_js_flags(self):
    config = BrowserVariantsConfigDict(
        {
            "browsers": {
                "chrome-release": {
                    "path":
                        "chrome-stable",
                    "flags": [
                        "--foo",
                        "--bar=12",
                        "--js-flags=--no-opt,--max-opt=1",
                    ],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 1)
    self.assertIsNone(browsers[0].flags["--foo"])
    self.assertEqual(browsers[0].flags["--bar"], "12")
    self.assertIsNone(browsers[0].js_flags["--no-opt"])
    self.assertEqual(browsers[0].js_flags["--max-opt"], "1")
    self.assertEqual(
        str(browsers[0].flags),
        "--foo --bar=12 --js-flags=--no-opt,--max-opt=1")

  def test_flag_combination_direct_inline_with_flag_groups(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "features-experiment": {
                    "--enable-features": [None, "ConsumeCompileHints"],
                },
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": ["--foo", "--bar=12", "features-experiment"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 2)
    self.assertSequenceEqual(["--foo", "--bar=12"], list(browsers[0].flags))
    self.assertSequenceEqual(
        ["--foo", "--bar=12", "--enable-features=ConsumeCompileHints"],
        list(browsers[1].flags))

  def test_flag_direct_inline_duplicate(self):
    with self.assertRaises(ConfigError):
      BrowserVariantsConfigDict(
          {
              "browsers": {
                  "chrome-release": {
                      "path": "chrome-stable",
                      "flags": ["--foo", "--foo"],
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())

  def test_flag_combination_mixed_fixed(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "compile-hints-experiment": {
                    "--no-sandbox": "",
                    "--enable-features": [None, "ConsumeCompileHints"],
                },
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": "compile-hints-experiment",
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    browsers = config.variants
    self.assertEqual(len(browsers), 2)
    self.assertSequenceEqual(["--no-sandbox"], list(browsers[0].flags))
    self.assertSequenceEqual(
        ["--no-sandbox", "--enable-features=ConsumeCompileHints"],
        list(browsers[1].flags))

  def test_js_flags_user_data_dir(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "custom-js-flags": {
                    "--js-flags": [None, "--no-opt"],
                },
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": ["--user-data-dir=/tmp/dir", "custom-js-flags"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 2)
    browser_a = config.variants[0]
    browser_b = config.variants[1]
    self.assertEqual(str(browser_a.flags), "--user-data-dir=/tmp/dir")
    self.assertEqual(
        str(browser_b.flags), "--user-data-dir=/tmp/dir --js-flags=--no-opt")

  def test_conflicting_chrome_features(self):
    with self.assertRaises(ConfigError) as cm:
      BrowserVariantsConfigDict(
          {
              "flags": {
                  "compile-hints-experiment": {
                      "--enable-features": [None, "ConsumeCompileHints"],
                  },
              },
              "browsers": {
                  "chrome-release": {
                      "path":
                          "chrome-stable",
                      "flags": [
                          "--disable-features=ConsumeCompileHints",
                          "compile-hints-experiment",
                      ],
                  },
              },
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())
    msg = str(cm.exception)
    self.assertIn("ConsumeCompileHints", msg)

  def test_no_flags(self):
    config = BrowserVariantsConfigDict(
        {
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                },
                "chrome-dev": {
                    "path": "chrome-dev",
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 2)
    browser_0 = config.variants[0]
    self.assertEqual(browser_0.browser_cls, mock_browser.MockChromeStable)
    browser_1 = config.variants[1]
    self.assertEqual(browser_1.browser_cls, mock_browser.MockChromeDev)

  def test_custom_driver(self):
    chromedriver = pth.LocalPath("path/to/chromedriver")
    variants_config = {
        "browsers": {
            "chrome-stable": {
                "browser": "chrome-stable",
                "driver": str(chromedriver),
            },
        },
    }
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserVariantsConfigDict(
          copy.deepcopy(variants_config),
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())
    self.assertIn(str(chromedriver), str(cm.exception))

    self.fs.create_file(chromedriver, st_size=100)
    with self._patch_get_browser_cls(mock_browser.MockChromeStable):
      config = BrowserVariantsConfigDict(
          variants_config,
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args())
    self.assertTrue(variants_config["browsers"]["chrome-stable"])
    self.assertEqual(len(config.variants), 1)
    browser_0 = config.variants[0]
    self.assertEqual(browser_0.browser_cls, mock_browser.MockChromeStable)

  def test_inline_flags(self):
    with mock.patch.object(
        ChromeWebDriver,
        "_extract_version",
        return_value=ChromeVersion.parse("101.22.333.44")), mock.patch.object(
            Chrome,
            "stable_path",
            return_value=mock_browser.MockChromeStable.mock_app_path()):

      config = BrowserVariantsConfigDict(
          {
              "browsers": {
                  "stable": {
                      "path": "chrome-stable",
                      "flags": ["--foo=bar"],
                  },
              },
          },
          args=self.mock_args())
      browsers = config.browsers
      self.assertEqual(len(browsers), 1)
      browser = browsers[0]
      # TODO: Fix once app lookup is cleaned up
      self.assertEqual(browser.app_path,
                       mock_browser.MockChromeStable.mock_app_path())
      self.assertEqual(browser.version.parts_str, "101.22.333.44")
      self.assertEqual(browser.flags["--foo"], "bar")

  def test_inline_load_safari(self):
    if not plt.PLATFORM.is_macos:
      return
    config = BrowserVariantsConfigDict(
        {"browsers": {
            "safari": {
                "path": "safari",
            },
        }}, args=self.mock_args())
    self.assertEqual(len(config.variants), 1)
    self.assertTrue(issubclass(config.variants[0].browser_cls, Safari))

  def test_safari_ios_driver_classes(self):
    with mock.patch.object(DriverConfig, "validate_ios"):
      for driver_type, browser_cls in (
          (BrowserDriverType.IOS, SafariWebdriverIOS),
          (BrowserDriverType.IOS_WDA, SafariWdaIOS),
      ):
        driver = DriverConfig(driver_type, device_id="00001111")
        config = BrowserConfig("safari", driver)
        self.assertIs(
            BrowserVariantsConfig.get_browser_cls_from_type(
                BrowserType.SAFARI, config), browser_cls)

  def test_flag_combination_with_fixed(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                    "--bar": [None, "", "w1"],
                    "--always_1": "true",
                    "--always_2": "true",
                    "--always_3": "true",
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 3 * 3)
    for variant in config.variants:
      self.assertEqual(variant.browser_cls, mock_browser.MockChromeStable)
      expected_flags = (
          "--always_1=true --always_2=true --always_3=true",
          "--bar --always_1=true --always_2=true --always_3=true",
          "--bar=w1 --always_1=true --always_2=true --always_3=true",
          "--foo --always_1=true --always_2=true --always_3=true",
          "--foo --bar --always_1=true --always_2=true --always_3=true",
          "--foo --bar=w1 --always_1=true --always_2=true --always_3=true",
          "--foo=v1 --always_1=true --always_2=true --always_3=true",
          "--foo=v1 --bar --always_1=true --always_2=true --always_3=true",
          "--foo=v1 --bar=w1 --always_1=true --always_2=true --always_3=true",
      )
    self.verify_variant_flags(config.variants, expected_flags)

  def verify_variant_flags(self, variants, expected_flags):
    self.assertEqual(len(variants), len(expected_flags))
    for index, browser_variant in enumerate(variants):
      self.assertEqual(
          str(browser_variant.flags), expected_flags[index],
          f"Unexpected flags for variant[{index}]")
      label = browser_variant.label
      self.assertLessEqual(len(label), 255, f"Too long label: {label!r}")

  def test_flag_combination_js_flags_with_fixed(self):
    flags = ("--max_maglev_inlined_bytecode_size=363",
             "--max_maglev_inlined_bytecode_size_small=32",
             "--max_maglev_inlined_bytecode_size_cumulative=892",
             "--max_inlined_bytecode_size=482",
             "--max_inlined_bytecode_size_cumulative=905",
             "--max_inlined_bytecode_size_small=3", "--no-opt")
    long_js_flags: str = ",".join(flags)
    self.assertLess(len(long_js_flags), 255)
    self.assertLess(240, len(long_js_flags))
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--js-flags": [
                        None,
                        "--max-opt=1,--trace-ic",
                        "--max-opt=2 --log-all",
                        long_js_flags,
                    ],
                },
                "group2": {
                    "default": "--bar=v1 --foo=w2",
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1", "group2"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 4)
    for variant in config.variants:
      self.assertEqual(variant.browser_cls, mock_browser.MockChromeStable)
    expected_flags = (
        "--bar=v1 --foo=w2",
        "--bar=v1 --foo=w2 --js-flags=--max-opt=1,--trace-ic",
        "--bar=v1 --foo=w2 --js-flags=--max-opt=2,--log-all",
        f"--bar=v1 --foo=w2 --js-flags={long_js_flags}",
    )
    self.verify_variant_flags(config.variants, expected_flags)

  def test_flag_combination_js_flags_combinations_invalid(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--js-flags": [
                        None,
                        "--max-opt=2,--trace-ic",
                        "--max-opt=3 --log-all",
                    ],
                },
                "group2": {
                    "default": "--js-flags=--no-sparkplug",
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1", "group2"],
                },
            },
        },
        args=self.mock_args())
    self.assertEqual(len(config.variants), 3)
    self.assertEqual(str(config.variants[0].flags), "--js-flags=--no-sparkplug")
    self.assertEqual(
        str(config.variants[1].flags),
        "--js-flags=--max-opt=2,--trace-ic,--no-sparkplug")
    self.assertEqual(
        str(config.variants[2].flags),
        "--js-flags=--max-opt=3,--log-all,--no-sparkplug")

  def test_flag_group_combination(self):
    config = BrowserVariantsConfigDict(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                },
                "group2": {
                    "--bar": [None, "", "w1"],
                },
                "group3": {
                    "--other": ["x1", "x2"],
                },
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1", "group2", "group3"],
                },
            },
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args())
    self.assertEqual(len(config.variants), 3 * 3 * 2)
    expected_flags = (
        "--other=x1",
        "--other=x2",
        "--bar --other=x1",
        "--bar --other=x2",
        "--bar=w1 --other=x1",
        "--bar=w1 --other=x2",
        "--foo --other=x1",
        "--foo --other=x2",
        "--foo --bar --other=x1",
        "--foo --bar --other=x2",
        "--foo --bar=w1 --other=x1",
        "--foo --bar=w1 --other=x2",
        "--foo=v1 --other=x1",
        "--foo=v1 --other=x2",
        "--foo=v1 --bar --other=x1",
        "--foo=v1 --bar --other=x2",
        "--foo=v1 --bar=w1 --other=x1",
        "--foo=v1 --bar=w1 --other=x2",
    )
    self.verify_variant_flags(config.variants, expected_flags)

  def test_from_cli_args_browser_config(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    browser_bin = browser_cls.mock_app_path().with_stem("Custom Google Chrome")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")
    config_data = {"browsers": {"chrome-stable": {"path": str(browser_bin)}}}
    config_file = pth.LocalPath("config/config.hjson")
    config_file.parent.mkdir()
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)

    args = self.mock_args(browser_config=config_file)
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    self.assertEqual(len(config.variants), 1)
    self.assertEqual(config.variants[0].browser_cls, browser_cls)
    browser = config.browsers[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.app_path, browser_bin)

  def test_from_cli_args_browser_config_relative_path(self):
    some_dir = pth.LocalPath("custom/test/dir")
    some_dir.mkdir(parents=True)
    with change_cwd(some_dir):
      self.test_from_cli_args_browser_config()

  def test_from_cli_args_browser(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    browser_bin = browser_cls.mock_app_path().with_stem("Custom Google Chrome")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")
    args = self.mock_args(browser=[BrowserConfig(browser_bin)])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 1)
    browser = browsers[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.app_path, browser_bin)

  def test_from_cli_args_browser_additional_flags(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[
            BrowserConfig.parse_str("chrome"),
        ],
        enable_features="feature_on",
        disable_features="feature_off",
        other_browser_args=["--no-sandbox", "--enable-logging=stderr"])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 1)
    browser = browsers[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertFalse(browser.js_flags)
    self.assertEqual(browser.flags["--enable-features"], "feature_on")
    self.assertEqual(browser.flags["--disable-features"], "feature_off")
    self.assertIn("--no-sandbox", browser.flags)
    self.assertEqual(browser.flags["--enable-logging"], "stderr")

  def test_from_cli_args_browser_js_flags(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[BrowserConfig.parse_str("chrome")], js_flags=["--max-opt=1"])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 1)
    browser = browsers[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.js_flags.to_dict(), {"--max-opt": "1"})

  def test_from_cli_args_browser_extra_browser_js_flags(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[
            BrowserConfig.parse_str("chrome"),
        ],
        js_flags=[],
        other_browser_args=["--js-flags=--max-opt=1,--log-all"])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 1)
    browser = browsers[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.js_flags.to_dict(), {
        "--max-opt": "1",
        "--log-all": None,
    })

  def test_from_cli_args_browser_multiple_js_flags_empty_base(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[
            BrowserConfig.parse_str("chrome"),
        ],
        enable_features="",
        disable_features="",
        js_flags=[" ", "--max-opt=2,--log-all"],
        other_browser_args=[])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 2)
    browser_0 = browsers[0]
    self.assertIsInstance(browser_0, browser_cls)
    self.assertEqual(browser_0.js_flags.to_dict(), {})
    browser_1 = browsers[1]
    self.assertIsInstance(browser_1, browser_cls)
    self.assertEqual(browser_1.js_flags.to_dict(), {
        "--max-opt": "2",
        "--log-all": None,
    })

  def test_from_cli_args_browser_multiple_js_flags_empty_base_defaults(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[
            BrowserConfig.parse_str("chrome"),
        ],
        enable_features="",
        disable_features="",
        js_flags=[" ", "--max-opt=2,--log-all"],
        other_browser_args=["--js-flags=--no-turbofan"])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 2)
    browser_0 = browsers[0]
    self.assertIsInstance(browser_0, browser_cls)
    self.assertEqual(browser_0.js_flags.to_dict(), {"--no-turbofan": None})
    browser_1 = browsers[1]
    self.assertIsInstance(browser_1, browser_cls)
    self.assertEqual(browser_1.js_flags.to_dict(), {
        "--no-turbofan": None,
        "--max-opt": "2",
        "--log-all": None,
    })

  def test_from_cli_args_browser_multiple_js_flags(self):
    browser_cls = mock_browser.MockChromeStable
    args = self.mock_args(
        browser=[
            BrowserConfig.parse_str("chrome"),
        ],
        enable_features="feature_on",
        disable_features="feature_off",
        js_flags=["--max-opt=1", "--max-opt=2,--log-all"],
        other_browser_args=["--no-sandbox", "--enable-logging=stderr"])
    with self._patch_get_browser_cls(browser_cls):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 2)
    browser_0 = browsers[0]
    self.assertIsInstance(browser_0, browser_cls)
    self.assertEqual(browser_0.js_flags.to_dict(), {"--max-opt": "1"})
    browser_1 = browsers[1]
    self.assertIsInstance(browser_1, browser_cls)
    self.assertEqual(browser_1.js_flags.to_dict(), {
        "--max-opt": "2",
        "--log-all": None,
    })

    for browser in config.variants:
      self.assertEqual(browser.flags["--enable-features"], "feature_on")
      self.assertEqual(browser.flags["--disable-features"], "feature_off")
      self.assertIn("--no-sandbox", browser.flags)
      self.assertEqual(browser.flags["--enable-logging"], "stderr")

  def test_from_cli_args_browser_config_js_flags(self):
    browser_config = {
        "browsers": {
            "chrome_no_tf": {
                "flags": ["--js-flags=--no-turbofan"],
                "path": "chrome",
            },
        },
    }
    with self.platform.NamedTemporaryFile() as config_file:
      with config_file.open("w", encoding="utf-8") as f:
        json.dump(browser_config, f)

      args = self.mock_args(
          browser_config=config_file, js_flags=["--max-opt=1,--log-all"])
      with self._patch_get_browser_cls():
        config = BrowserVariantsConfig.parse_args(args)

    self.assertEqual(len(config.variants), 1)
    browser = config.variants[0]
    self.assertEqual(browser.js_flags.to_dict(), {
        "--no-turbofan": None,
        "--max-opt": "1",
        "--log-all": None,
    })

  def test_from_cli_args_and_config(self):
    browser_config = {"browsers": {"chrome_no_tf": {"path": "chrome"}}}
    chrome_stable = BrowserConfig.parse_str("chrome")
    chrome_dev = BrowserConfig.parse_str("chrome-dev")

    with self.platform.NamedTemporaryFile() as config_file:
      with config_file.open("w", encoding="utf-8") as f:
        json.dump(browser_config, f)

      args = self.mock_args(browser=[chrome_dev], browser_config=config_file)

      config = BrowserVariantsConfig.parse_args(args)

    variants = config.variants
    self.assertEqual(len(variants), 2)
    self.assertEqual(variants[0].browser_config, chrome_stable)
    self.assertEqual(variants[1].browser_config, chrome_dev)

  def test_from_cli_args_browser_config_network_override(self):
    ts_proxy_path = pth.LocalPath("/tsproxy/tsproxy.py")
    self.fs.create_file(ts_proxy_path, st_size=100)
    browser_config_dict = {
        "browsers": {
            "default-network": {
                "path": "chrome-stable",
                "network": "default",
            },
            "default": "chrome-stable",
            "custom-network": {
                "path": "chrome-stable",
                "network": "4G",
            },
        },
    }
    config_file = pth.LocalPath("browsers.config.json")
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(browser_config_dict, f)
    network_3g = NetworkConfig.parse("3G-slow")
    network_4g = NetworkConfig.parse("4G")
    self.assertNotEqual(network_3g.speed.in_kbps, network_4g.speed.in_kbps)
    args = self.mock_args(browser_config=config_file, network_config=network_3g)

    with self._patch_get_browser_cls(mock_browser.MockChromeStable), mock.patch(
        "crossbench.network.traffic_shaping.ts_proxy.TsProxyFinder") as finder:
      finder.return_value = mock.Mock(
          path=ts_proxy_path, local_path=ts_proxy_path)
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 3)
    browser_1, browser_2, browser_3 = browsers
    # Browser 1 provides an explicit default override:
    self.assertTrue(browser_1.network.is_live)
    self.assertTrue(browser_1.network.traffic_shaper.is_live)
    # Browser 2: uses the default --network:
    self.assertTrue(browser_2.network.is_live)
    self.assertFalse(browser_2.network.traffic_shaper.is_live)
    self.assertEqual(browser_2.network.traffic_shaper.ts_proxy.in_kbps,
                     network_3g.speed.in_kbps)
    # Browser 3; Uses an explicit 4G override:
    self.assertTrue(browser_3.network.is_live)
    self.assertFalse(browser_3.network.traffic_shaper.is_live)
    self.assertEqual(browser_3.network.traffic_shaper.ts_proxy.in_kbps,
                     network_4g.speed.in_kbps)

  def _local_file_server_config(self,
                                is_default: bool = False) -> NetworkConfig:
    local_dir = pth.LocalPath("/benchmark")
    self.fs.create_file(local_dir / "index.html")
    if is_default:
      return NetworkConfig.default_local(local_dir)
    return NetworkConfig(type=NetworkType.LOCAL, path=local_dir)

  @contextlib.contextmanager
  def _patch_no_reverse_port_forwarding(self):
    with mock.patch.object(
        type(self.platform),
        "supports_reverse_port_forwarding",
        new_callable=mock.PropertyMock,
        return_value=False):
      yield

  def test_local_file_server_with_reverse_port_forwarding(self):
    args = self.mock_args(
        browser=[BrowserConfig(mock_browser.MockChromeStable.mock_app_path())],
        network_config=self._local_file_server_config(is_default=True))
    with self._patch_get_browser_cls(mock_browser.MockChromeStable):
      browsers = BrowserVariantsConfig.parse_args(args).browsers
    self.assertEqual(len(browsers), 1)
    self.assertTrue(browsers[0].network.is_local_file_server)

  def test_local_file_server_default_fallback_without_port_forwarding(self):
    args = self.mock_args(
        browser=[BrowserConfig(mock_browser.MockChromeStable.mock_app_path())],
        network_config=self._local_file_server_config(is_default=True))
    with self._patch_get_browser_cls(
        mock_browser.MockChromeStable), self._patch_no_reverse_port_forwarding(
        ), self.assertLogs(level="WARNING") as logs:
      browsers = BrowserVariantsConfig.parse_args(args).browsers
    self.assertEqual(len(browsers), 1)
    self.assertTrue(browsers[0].network.is_live)
    self.assertIn("reverse port forwarding", "\n".join(logs.output))

  def test_local_file_server_explicit_without_port_forwarding(self):
    args = self.mock_args(
        browser=[BrowserConfig(mock_browser.MockChromeStable.mock_app_path())],
        network_config=self._local_file_server_config(is_default=False))
    with self._patch_get_browser_cls(
        mock_browser.MockChromeStable), self._patch_no_reverse_port_forwarding(
        ), self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserVariantsConfig.parse_args(args)
    self.assertIn("reverse port forwarding", str(cm.exception))

  def test_local_file_server_browser_config_without_port_forwarding(self):
    local_config = self._local_file_server_config(is_default=True)
    browser_config_dict = {
        "browsers": {
            "local": {
                "path": "chrome-stable",
                "network": {
                    "type": str(NetworkType.LOCAL),
                    "path": str(local_config.path),
                },
            },
        },
    }
    config_file = pth.LocalPath("browsers.config.json")
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(browser_config_dict, f)
    args = self.mock_args(
        browser_config=config_file, network_config=local_config)
    with self._patch_get_browser_cls(
        mock_browser.MockChromeStable), self._patch_no_reverse_port_forwarding(
        ), self.assertRaises(argparse.ArgumentTypeError) as cm:
      BrowserVariantsConfig.parse_args(args)
    self.assertIn("reverse port forwarding", str(cm.exception))

  def test_from_cli_args_browser_config_env_override(self):
    browser_config_dict = {
        "browsers": {
            "default-env": {
                "path": "chrome-stable",
                "env": "default",
            },
            "default": "chrome-stable",
            "custom-env": {
                "path": "chrome-stable",
                "env": {
                    "cpu_max_usage_percent": 42,
                },
            },
        },
    }
    config_file = pth.LocalPath("browsers.config.json")
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(browser_config_dict, f)
    global_env = EnvConfig(cpu_max_usage_percent=99)
    args = self.mock_args(browser_config=config_file, env_config=global_env)

    with self._patch_get_browser_cls(mock_browser.MockChromeStable):
      config = BrowserVariantsConfig.parse_args(args)
    browsers = config.browsers
    self.assertEqual(len(browsers), 3)
    browser_1, browser_2, browser_3 = browsers
    self.assertEqual(browser_1.settings.env_config,
                     ENV_CONFIG_PRESETS["default"])
    self.assertEqual(browser_2.settings.env_config, global_env)
    self.assertEqual(browser_2.settings.env_config.cpu_max_usage_percent, 99)
    self.assertEqual(browser_3.settings.env_config.cpu_max_usage_percent, 42)

  def test_get_browser_cls_unsupported(self):
    variants = BrowserVariantsConfig()
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Unsupported browser"):
      config = BrowserConfig(browser=pth.AnyPath("your/custom/browser.exe"))
      variants.get_browser_cls(config)

  def test_get_browser_cls_chrome_default(self):
    variants = BrowserVariantsConfig()
    config = BrowserConfig(browser=pth.AnyPath("Chrome.app"))
    self.assertIs(variants.get_browser_cls(config), ChromeWebDriver)
    config = BrowserConfig(browser=pth.AnyPath("Chrome.exe"))
    self.assertIs(variants.get_browser_cls(config), ChromeWebDriver)

  def test_get_browser_cls_chrome_local_build(self):
    variants = BrowserVariantsConfig()
    chrome_bin = pth.LocalPath("/home/user/src/out/Release/chrome")
    args_gn = pth.LocalPath("/home/user/src/out/Release/args.gn")
    self.fs.create_file(args_gn, st_size=100)
    config = BrowserConfig(browser=chrome_bin)
    self.assertIs(variants.get_browser_cls(config), ChromiumWebDriver)

  def test_get_browser_cls_chromium_default(self):
    variants = BrowserVariantsConfig()
    config = BrowserConfig(browser=pth.AnyPath("Chromium.app"))
    self.assertIs(variants.get_browser_cls(config), ChromiumWebDriver)
    config = BrowserConfig(browser=pth.AnyPath("Chromium.exe"))
    self.assertIs(variants.get_browser_cls(config), ChromiumWebDriver)

  def test_get_browser_cls_explicit_chromium_custom_path(self):
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("Custom.app"), browser_type=BrowserType.CHROMIUM)
    self.assertIs(variants.get_browser_cls(config), ChromiumWebDriver)

  def test_browser_version_settings(self):
    path = self.create_file("/Applications/Custom.app/Contents/MacOS/Custom")
    config = BrowserVariantsConfigDict(
        {
            "browsers": {
                "custom-browser": {
                    "type": "chromium",
                    "path": str(path),
                    "version": "120.0.6099.224",
                },
            },
        },
        args=self.mock_args())
    variant = config.variants[0]
    self.assertEqual(variant.browser_config.version, "120.0.6099.224")
    self.assertEqual(variant.settings.browser_version, "120.0.6099.224")

  def test_get_browser_cls_chrome_driver_types(self):
    variants = BrowserVariantsConfig()
    expected_classes = (
        (BrowserDriverType.APPLE_SCRIPT, ChromeAppleScript),
        (BrowserDriverType.WEB_DRIVER, ChromeWebDriver),
        (BrowserDriverType.LINUX_SSH, ChromeWebDriverSsh),
    )
    for driver_type, browser_cls in expected_classes:
      config = BrowserConfig(
          browser=pth.AnyPath("Chrome.bin"),
          driver=DriverConfig(driver_type=driver_type))
      self.assertIs(variants.get_browser_cls(config), browser_cls)

  def test_get_browser_cls_chromium_driver_types(self):
    variants = BrowserVariantsConfig()
    expected_classes = (
        (BrowserDriverType.APPLE_SCRIPT, ChromiumAppleScript),
        (BrowserDriverType.WEB_DRIVER, ChromiumWebDriver),
        (BrowserDriverType.LINUX_SSH, ChromiumWebDriverSsh),
    )
    for driver_type, browser_cls in expected_classes:
      config = BrowserConfig(
          browser=pth.AnyPath("Chromium.bin"),
          driver=DriverConfig(driver_type=driver_type))
      self.assertIs(variants.get_browser_cls(config), browser_cls)

  def test_get_browser_cls_chromium_android_default(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("chromium.apk"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    self.assertIs(variants.get_browser_cls(config), ChromiumWebDriverAndroid)

  def test_get_browser_cls_chrome_android_default(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("chrome.apk"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    self.assertIs(variants.get_browser_cls(config), ChromeWebDriverAndroid)

  def test_get_browser_cls_cdp_android(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("com.android.chrome"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID_CDP))
    self.assertIs(variants.get_browser_cls(config), CdpAndroidBrowser)

  def test_get_browser_cls_chrome_android_local_helper(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    apk_helper = pth.AnyPath("/home/user/Documents/chrome/src/"
                             "out/arm64.apk/bin/chrome_public_apk")
    config = BrowserConfig(
        browser=apk_helper,
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    self.assertIs(variants.get_browser_cls(config), LocalChromeWebDriverAndroid)

  def test_get_browser_cls_chromium_android_local_helper(self):
    """Currently there is no nice way to distinguish a local build between
    chrome/chromium."""

  def test_get_browser_cls_webview_shell(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("org.chromium.webview_shell"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    # "webview" in package name should take precedence over "chromium"
    self.assertIs(variants.get_browser_cls(config), WebviewBrowser)

  def test_get_browser_cls_webview_embedder(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("webview/velvet.apk"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    # valid embedder short name should take precedence over "webview" in path
    self.assertIs(variants.get_browser_cls(config), WebviewEmbedder)

  def test_get_browser_cls_webview_embedder_short_name(self):
    self.platform.sh_results = [
        ADB_DEVICES_SINGLE_OUTPUT,
    ]
    variants = BrowserVariantsConfig()
    config = BrowserConfig(
        browser=pth.AnyPath("webview_embedder"),
        driver=DriverConfig(driver_type=BrowserDriverType.ANDROID))
    self.assertIs(variants.get_browser_cls(config), WebviewEmbedder)

  def test_get_browser_cls_chromeos_ssh_default(self):
    self.platform.sh_results = []
    variants = BrowserVariantsConfig()
    with mock.patch.object(
        DriverConfig, "validate_chromeos", return_value=None) as mock_method:
      driver = DriverConfig(driver_type=BrowserDriverType.CHROMEOS_SSH)
    mock_method.assert_called_once()
    config = BrowserConfig(browser=pth.AnyPath("chrome"), driver=driver)
    self.assertIs(variants.get_browser_cls(config), ChromeWebDriverChromeOsSsh)

  def test_cache_dir_empty(self):
    args = self.mock_args()
    config_data = {
        "browsers": {
            "chrome-release": {
                "path": "chrome-stable",
                "cache_dir": None,
            },
        },
    }
    self.assertIsNone(args.browser_cache_dir)
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertIsNone(browser.settings.cache_dir)

    args.browser_cache_dir = "/var/tmp/override/cache"
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "/var/tmp/override/cache")

  def test_cache_dir(self):
    args = self.mock_args()
    config_data = {
        "browsers": {
            "chrome-release": {
                "path": "chrome-stable",
                "cache_dir": "foo/bar/cache",
            },
        },
    }
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertTrue(browser.settings.clear_cache_dir)

    args.browser_cache_dir = "/var/tmp/override/cache"
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "/var/tmp/override/cache")
    self.assertTrue(browser.settings.clear_cache_dir)

  @pytest.mark.xfail(not plt.PLATFORM.is_macos, reason="Not supported on macos")
  def test_parse_webkit_download(self):
    args = self.mock_args(browser=[
        BrowserConfig.parse("webkit-nightly-299105@main"),
    ])
    downloaded_path = self.platform.local_cache_dir(
        "browser_bin") / "Webkit_Nightly_299105_nightly"
    app_path = downloaded_path / "Release" / "MiniBrowser.app"

    def mock_load_side_effect(name, platform, reinstall):
      del name, platform, reinstall
      self.fs.create_file(app_path, st_size=100)
      return app_path

    with mock.patch(
        "crossbench.browsers.webkit.downloader.WebKitDownloader.load",
        side_effect=mock_load_side_effect) as mock_load:
      config = BrowserVariantsConfig.parse_args(args)
      mock_load.assert_called_once_with(
          "webkit-nightly-299105@main", self.platform, reinstall=False)
    self.assertEqual(len(config.variants), 1)
    variant = config.variants[0]
    self.assertEqual(variant.browser_cls, WebKitWebDriver)
    self.assertEqual(variant.path, app_path)

  def test_clear_cache_dir(self):
    args = self.mock_args()
    config_data = {
        "browsers": {
            "chrome-release": {
                "path": "chrome-stable",
                "cache_dir": "foo/bar/cache",
                "clear_cache_dir": False,
            },
        },
    }
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertIsNone(args.clear_browser_cache_dir)
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertFalse(browser.settings.clear_cache_dir)

    args.clear_browser_cache_dir = False
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertFalse(browser.settings.clear_cache_dir)

    args.clear_browser_cache_dir = True
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertTrue(browser.settings.clear_cache_dir)

  def test_clear_cache_dir_override_positive(self):
    args = self.mock_args()
    config_data = {
        "browsers": {
            "chrome-release": {
                "path": "chrome-stable",
                "cache_dir": "foo/bar/cache",
                "clear_cache_dir": True,
            },
        },
    }
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertIsNone(args.clear_browser_cache_dir)
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertTrue(browser.settings.clear_cache_dir)

    args.clear_browser_cache_dir = False
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertFalse(browser.settings.clear_cache_dir)

    args.clear_browser_cache_dir = True
    config = BrowserVariantsConfigDict(config_data, args=args)
    browser = config.variants[0]
    self.assertEqual(str(browser.settings.cache_dir), "foo/bar/cache")
    self.assertTrue(browser.settings.clear_cache_dir)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
