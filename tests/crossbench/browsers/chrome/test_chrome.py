# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
import unittest
from typing import Final
from unittest import mock

import selenium.common.exceptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from typing_extensions import override

from crossbench import path as pth
from crossbench.browsers.chrome.version import ChromeVersion
from crossbench.browsers.chrome.webdriver import ChromeWebDriver, \
    LocalChromeWebDriverAndroid
from crossbench.browsers.chromium.version import ChromiumVersion, \
    ChromiumVersionRange
from crossbench.browsers.chromium_based.chromium_based import \
    VERSIONED_DEFAULT_FLAGS, VersionedFlag
from crossbench.browsers.settings import Settings
from crossbench.browsers.version import BrowserVersionChannel
from crossbench.browsers.viewport import Viewport
from crossbench.browsers.webdriver import DriverException
from crossbench.flags.chrome import ChromeFlags
from tests import test_helper
from tests.crossbench import mock_browser
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.mock_helper import MacOsMockPlatform


class VersionedFlagTestCase(unittest.TestCase):

  def test_basic_int_versions(self) -> None:
    version_flag = VersionedFlag(
        min=98,
        max=100,
        flags="--disable-features=ChromeWhatsNewUI",
        comment="Disable What's New UI.")
    self.assertEqual(version_flag.min, ChromiumVersion.any(98))
    self.assertEqual(version_flag.max, ChromiumVersion.any(100))
    self.assertFalse(version_flag.min.has_channel)
    self.assertFalse(version_flag.max.has_channel)
    self.assertEqual(version_flag.version_range,
                     ChromiumVersionRange.any(98, 100))
    self.assertEqual(
        tuple(version_flag.flags), ("--disable-features=ChromeWhatsNewUI",))
    self.assertTrue(version_flag.flags.is_frozen)
    self.assertEqual(version_flag.comment, "Disable What's New UI.")
    self.assertEqual(
        str(version_flag),
        "[98 any, 100 any]: --disable-features=ChromeWhatsNewUI")

  def test_tuple_versions(self) -> None:
    version_flag = VersionedFlag(
        min=(120, 0, 1, 0),
        max=(126, 0, 2, 0),
        flags="--foo=bar",
        comment="Test tuple versions.")
    self.assertEqual(version_flag.min, ChromiumVersion.any((120, 0, 1, 0)))
    self.assertEqual(version_flag.max, ChromiumVersion.any((126, 0, 2, 0)))

  def test_flag_formats(self) -> None:
    version_flag_str = VersionedFlag(
        min=120, max=126, flags="--foo=bar --baz", comment="Test str flags.")
    self.assertEqual(tuple(version_flag_str.flags), ("--foo=bar", "--baz"))
    self.assertTrue(version_flag_str.flags.is_frozen)

    version_flag_dict = VersionedFlag(
        min=120, max=126, flags={"--foo": "bar"}, comment="Test dict flags.")
    self.assertEqual(tuple(version_flag_dict.flags), ("--foo=bar",))
    self.assertTrue(version_flag_dict.flags.is_frozen)

    version_flag_chrome_flags = VersionedFlag(
        min=120,
        max=126,
        flags=ChromeFlags(("--foo", ("--bar", "baz"))),
        comment="Test ChromeFlags object.")
    self.assertEqual(
        tuple(version_flag_chrome_flags.flags), ("--foo", "--bar=baz"))
    self.assertTrue(version_flag_chrome_flags.flags.is_frozen)

  def test_contains_int_versions(self) -> None:
    version_flag = VersionedFlag(
        min=98, max=100, flags="--foo=bar", comment="Milestone range.")
    self.assertNotIn(ChromeVersion.parse("97.0.0.0"), version_flag)
    self.assertFalse(version_flag.contains(ChromeVersion.parse("97.0.0.0")))
    self.assertIn(ChromeVersion.parse("98.0.0.0"), version_flag)
    self.assertTrue(version_flag.contains(ChromeVersion.parse("98.0.0.0")))
    self.assertIn(ChromeVersion.parse("99.0.0.0"), version_flag)
    self.assertIn(ChromeVersion.parse("100.0.0.0"), version_flag)
    self.assertNotIn(ChromeVersion.parse("101.0.0.0"), version_flag)
    self.assertFalse(version_flag.contains(ChromeVersion.parse("101.0.0.0")))

    single_milestone_flag = VersionedFlag(
        min=120, max=120, flags="--foo=bar", comment="Single milestone.")
    self.assertNotIn(ChromeVersion.parse("119.0.0.0"), single_milestone_flag)
    self.assertIn(ChromeVersion.parse("120.0.0.0"), single_milestone_flag)
    self.assertNotIn(ChromeVersion.parse("121.0.0.0"), single_milestone_flag)

  def test_contains_tuple_versions(self) -> None:
    version_flag = VersionedFlag(
        min=(120, 0, 1, 0),
        max=(126, 0, 2, 0),
        flags="--foo=bar",
        comment="Tuple version range.")
    self.assertNotIn(ChromeVersion.parse("120.0.0.99"), version_flag)
    self.assertIn(ChromeVersion.parse("120.0.1.0"), version_flag)
    self.assertIn(ChromeVersion.parse("126.0.2.0"), version_flag)
    self.assertNotIn(ChromeVersion.parse("126.0.2.1"), version_flag)

  def test_contains_all_channels(self) -> None:
    version_flag = VersionedFlag(
        min=120, max=126, flags="--foo=bar", comment="Applies to all channels.")
    for channel in BrowserVersionChannel:
      self.assertNotIn(ChromeVersion((119, 0, 0, 0), channel), version_flag)
      self.assertIn(ChromeVersion((120, 0, 0, 0), channel), version_flag)
      self.assertIn(ChromeVersion((126, 0, 0, 0), channel), version_flag)
      self.assertNotIn(ChromeVersion((127, 0, 0, 0), channel), version_flag)
      self.assertNotIn(ChromeVersion((), channel), version_flag)

  def test_keyword_only_args(self) -> None:
    with self.assertRaises(TypeError):
      VersionedFlag(98, 100, "--foo", "Comment")  # type: ignore

  def test_invalid(self) -> None:
    with self.assertRaisesRegex(ValueError, "non-empty comment"):
      VersionedFlag(min=98, max=100, flags="--foo", comment="")
    with self.assertRaisesRegex(ValueError, "non-empty comment"):
      VersionedFlag(min=98, max=100, flags="--foo", comment="   ")
    with self.assertRaisesRegex(ValueError, "Invalid version format"):
      VersionedFlag(
          min=None, max=100, flags="--foo", comment="Comment")  # type: ignore
    with self.assertRaisesRegex(ValueError, "Invalid version format"):
      VersionedFlag(
          min=98, max=None, flags="--foo", comment="Comment")  # type: ignore
    with self.assertRaisesRegex(ValueError, "empty version"):
      VersionedFlag(min=(), max=100, flags="--foo", comment="Comment")
    with self.assertRaisesRegex(ValueError, "empty version"):
      VersionedFlag(min=98, max=(), flags="--foo", comment="Comment")
    with self.assertRaisesRegex(ValueError, "min .* > max"):
      VersionedFlag(min=100, max=98, flags="--foo", comment="Comment")
    with self.assertRaisesRegex(ValueError, "positive"):
      VersionedFlag(min=-1, max=100, flags="--foo", comment="Comment")
    with self.assertRaisesRegex(ValueError, "at least one flag"):
      VersionedFlag(min=98, max=100, flags="", comment="Comment")
    with self.assertRaisesRegex(ValueError, "at least one flag"):
      VersionedFlag(min=98, max=100, flags="   ", comment="Comment")
    with self.assertRaisesRegex(ValueError, "at least one flag"):
      VersionedFlag(min=98, max=100, flags=(), comment="Comment")
    with self.assertRaisesRegex(ValueError, "at least one flag"):
      VersionedFlag(min=98, max=100, flags={}, comment="Comment")


class ChromeWebDriverForTesting(ChromeWebDriver):

  @override
  def _extract_version(self) -> ChromeVersion:
    return ChromeVersion.parse(self.settings.browser_version or
                               mock_browser.MockChromeStable.VERSION)


class ChromeWebdriverTestCase(BaseCrossbenchTestCase):
  ALL_VERSION_FLAGS: Final[frozenset[str]] = frozenset({
      "--disable-features=ChromeWhatsNewUI",
      "--disable-search-engine-choice-screen",
      "--disable-optimization-guide-model-downloads-for-benchmarking",
      "--disable-crashpad-metrics",
      "--disable-ntp-theme-promo-bottom-sheet",
      "--disable-translate-trigger",
  })
  EXPECTED_VERSION_FLAGS_BY_MILESTONE: Final[tuple[tuple[int, tuple[
      str, ...]], ...]] = (
          (97, ()),
          (98, ("--disable-features=ChromeWhatsNewUI",)),
          (100, ("--disable-features=ChromeWhatsNewUI",)),
          (101, ()),
          (119, ()),
          (120, ("--disable-search-engine-choice-screen",)),
          (126, ("--disable-search-engine-choice-screen",)),
          (127, ()),
          (140, ()),
          (141,
           ("--disable-optimization-guide-model-downloads-for-benchmarking",)),
          (144,
           ("--disable-optimization-guide-model-downloads-for-benchmarking",)),
          (145, (
              "--disable-optimization-guide-model-downloads-for-benchmarking",
              "--disable-crashpad-metrics",
          )),
          (147, (
              "--disable-optimization-guide-model-downloads-for-benchmarking",
              "--disable-crashpad-metrics",
          )),
          (148, ()),
          (154, ()),
          (155, ("--disable-ntp-theme-promo-bottom-sheet",)),
          (156, (
              "--disable-ntp-theme-promo-bottom-sheet",
              "--disable-translate-trigger",
          )),
          (157, (
              "--disable-ntp-theme-promo-bottom-sheet",
              "--disable-translate-trigger",
          )),
          (158, ()),
      )

  def test_conflicting_finch_flags(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ChromeWebDriverForTesting(
          label="browser-label",
          path=mock_browser.MockChromeStable.mock_app_path(),
          settings=Settings(
              js_flags=[],
              flags=[
                  "--disable-field-trial-config",
                  "--enable-field-trial-config",
              ],
              platform=self.platform))
    msg = str(cm.exception)
    self.assertIn("--enable-field-trial-config", msg)
    self.assertIn("--disable-field-trial-config", msg)

  def test_auto_disabling_field_trials(self):
    browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(platform=self.platform))
    self.assertIn("--disable-field-trial-config", browser.flags)

    browser_field_trial = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(
            flags=["--force-fieldtrials"], platform=self.platform))
    self.assertIn("--force-fieldtrials", browser_field_trial.flags)
    self.assertNotIn("--disable-field-trial-config", browser_field_trial.flags)

  def test_auto_disabling_field_trials_all(self):
    for field_trial_flag in ChromeFlags.FIELD_TRIAL_ENABLE_FLAGS:
      if field_trial_flag == "--enable-benchmarking":
        continue
      browser = ChromeWebDriverForTesting(
          label="browser-label",
          path=mock_browser.MockChromeStable.mock_app_path(),
          settings=Settings(flags=[field_trial_flag], platform=self.platform))
      flags: ChromeFlags = browser.flags
      self.assertIn(field_trial_flag, flags)
      self.assertFalse(flags.field_trial_disable_flags)

  def test_versioned_default_flags_bounds(self) -> None:
    self.assertTrue(VERSIONED_DEFAULT_FLAGS)
    for version_flag in VERSIONED_DEFAULT_FLAGS:
      with self.subTest(version_flag=str(version_flag)):
        self._assert_valid_versioned_default_flag(version_flag)

  def _assert_valid_versioned_default_flag(self,
                                           version_flag: VersionedFlag) -> None:
    self.assertIsInstance(version_flag, VersionedFlag)
    self.assertIsNotNone(version_flag.min)
    self.assertIsNotNone(version_flag.max)
    self.assertLessEqual(version_flag.min, version_flag.max)
    self.assertFalse(version_flag.min.has_channel)
    self.assertFalse(version_flag.max.has_channel)
    self.assertGreaterEqual(version_flag.min.major, 90)
    self.assertTrue(version_flag.flags)
    self.assertTrue(version_flag.flags.is_frozen)
    self.assertTrue(version_flag.comment.strip())

  def test_versioned_default_flags_order(self) -> None:
    self.assertSequenceEqual(
        VERSIONED_DEFAULT_FLAGS,
        tuple(
            sorted(
                VERSIONED_DEFAULT_FLAGS,
                key=lambda version_flag: (version_flag.min, version_flag.max))))

  def _create_browser(
      self,
      browser_version: str | None = None,
      flags: ChromeFlags | list[str] | None = None,
  ) -> ChromeWebDriverForTesting:
    return ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(
            platform=self.platform,
            browser_version=browser_version,
            flags=flags))

  def test_versioned_default_flags_compatibility(self) -> None:
    min_milestone = VERSIONED_DEFAULT_FLAGS[0].min.major
    max_milestone = VERSIONED_DEFAULT_FLAGS[-1].max.major
    for milestone in range(min_milestone, max_milestone + 1):
      with self.subTest(milestone=milestone):
        self._assert_compatible_milestone_flags(milestone)

  def _assert_compatible_milestone_flags(self, milestone: int) -> None:
    browser = self._create_browser(f"{milestone}.0.0.0")
    browser.flags.update(browser.FLAGS_FOR_DISABLING_BACKGROUND_INTERVENTIONS)
    browser.validate_flags()

    seen_flags: set[str] = {
        *ChromeWebDriver.DEFAULT_FLAGS,
        *ChromeWebDriver.FLAGS_FOR_DISABLING_BACKGROUND_INTERVENTIONS,
        *ChromeFlags.FIELD_TRIAL_DISABLE_FLAGS,
        "--disable-extensions",
    }
    for version_flag in VERSIONED_DEFAULT_FLAGS:
      if browser.version not in version_flag:
        continue
      for flag_str in version_flag.flags:
        self.assertNotIn(flag_str, seen_flags)
        seen_flags.add(flag_str)

  def test_versioned_default_flags(self) -> None:
    for milestone, expected_flags in self.EXPECTED_VERSION_FLAGS_BY_MILESTONE:
      with self.subTest(milestone=milestone):
        self._assert_milestone_version_flags(milestone, expected_flags)

  def _assert_milestone_version_flags(self, milestone: int,
                                      expected_flags: tuple[str, ...]) -> None:
    browser = self._create_browser(f"{milestone}.0.0.0")
    browser_flags = tuple(browser.flags)
    for flag in self.ALL_VERSION_FLAGS:
      if flag in expected_flags:
        self.assertIn(flag, browser_flags)
      else:
        self.assertNotIn(flag, browser_flags)

  def test_versioned_default_flags_all_entries_and_channels(self) -> None:
    for version_flag in VERSIONED_DEFAULT_FLAGS:
      for channel in BrowserVersionChannel:
        self._assert_version_flag_channel_bounds(version_flag, channel)

  def _assert_version_flag_channel_bounds(
      self, version_flag: VersionedFlag,
      channel: BrowserVersionChannel) -> None:
    min_milestone = version_flag.min.major
    max_milestone = version_flag.max.major
    for milestone, should_contain in (
        (min_milestone - 1, False),
        (min_milestone, True),
        (max_milestone, True),
        (max_milestone + 1, False),
    ):
      version_str = str(ChromeVersion((milestone, 0, 0, 0), channel))
      with self.subTest(version_str=version_str, flags=str(version_flag.flags)):
        self._assert_browser_has_version_flag(version_str, version_flag,
                                              should_contain)

  def _assert_browser_has_version_flag(self, version_str: str,
                                       version_flag: VersionedFlag,
                                       should_contain: bool) -> None:
    browser = self._create_browser(version_str)
    browser_flags = tuple(browser.flags)
    for flag in version_flag.flags:
      if should_contain:
        self.assertIn(flag, browser_flags)
      else:
        self.assertNotIn(flag, browser_flags)

  def test_versioned_default_flags_custom_features_interaction(self) -> None:
    browser_m99 = self._create_browser(
        "99.0.0.0",
        ChromeFlags.parse("--enable-features=CustomFeatureA "
                          "--disable-features=CustomFeatureB"))
    self.assertIn("--enable-features=CustomFeatureA", tuple(browser_m99.flags))
    self.assertIn("--disable-features=ChromeWhatsNewUI,CustomFeatureB",
                  tuple(browser_m99.flags))

    with self.assertRaisesRegex(ValueError, "ChromeWhatsNewUI"):
      self._create_browser(
          "99.0.0.0", ChromeFlags.parse("--enable-features=ChromeWhatsNewUI"))

    browser_m101 = self._create_browser(
        "101.0.0.0", ChromeFlags.parse("--enable-features=ChromeWhatsNewUI"))
    self.assertIn("--enable-features=ChromeWhatsNewUI",
                  tuple(browser_m101.flags))

  def test_is_local_build_mock_browser(self):
    self.assertTrue(self.browsers)
    for browser in self.browsers:
      self.assertFalse(browser.is_local_build)

  def test_startup_error_headless_platform(self) -> None:
    browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(platform=self.platform))
    with mock.patch(
        "selenium.webdriver.Chrome",
        side_effect=selenium.common.exceptions.WebDriverException(
            "session not created")), mock.patch.object(
                type(self.platform),
                "has_display",
                new_callable=mock.PropertyMock,
                return_value=False):
      with self.assertRaises(DriverException) as cm:
        browser._create_driver(ChromeOptions(), ChromeService())
      self.assertIn("Try running with --headless", str(cm.exception))

    headless_browser = ChromeWebDriverForTesting(
        label="browser-label",
        path=mock_browser.MockChromeStable.mock_app_path(),
        settings=Settings(
            platform=self.platform, viewport=Viewport.HEADLESS))
    with mock.patch(
        "selenium.webdriver.Chrome",
        side_effect=selenium.common.exceptions.WebDriverException(
            "session not created")), mock.patch.object(
                type(self.platform),
                "has_display",
                new_callable=mock.PropertyMock,
                return_value=False):
      with self.assertRaises(DriverException) as cm:
        headless_browser._create_driver(ChromeOptions(), ChromeService())
      self.assertNotIn("Try running with --headless", str(cm.exception))


class LocalChromeWebDriverAndroidTestCase(BaseCrossbenchTestCase):

  def test_is_apk_helper(self):
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/chrome_public_apk")))
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/"
                        "out/arm64.apk/bin/chrome_bundle")))
    self.assertTrue(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath(
                "/home/user/Documents/chrome/src/"
                "out/arm64.apk/bin/trichrome_chrome_google_64_32_bundle")))
    self.assertFalse(LocalChromeWebDriverAndroid.is_apk_helper(None))
    self.assertFalse(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("org.chromium.chrome")))
    self.assertFalse(
        LocalChromeWebDriverAndroid.is_apk_helper(
            pth.AnyPath("/home/user/Documents/chrome/src/out/arm64/chrome")))


class ChromePathMacOsTestCase(BaseCrossbenchTestCase):

  @override
  def setup_platform(self):
    return MacOsMockPlatform()

  def test_chrome_path_macos(self):
    app_path = self.platform.path("/Users/user/chrome/src/out/mac/Chrome.app")
    binary_path = app_path / "Contents" / "MacOS" / "Chrome"
    self.fs.create_file(binary_path, st_size=100)

    # Test 1: Initialize with app bundle path
    browser_app = ChromeWebDriverForTesting(
        label="browser-app",
        path=app_path,
        settings=Settings(platform=self.platform))
    self.assertEqual(browser_app.path, binary_path)
    self.assertEqual(browser_app.app_path, app_path)

    # Test 2: Initialize with direct binary path
    browser_bin = ChromeWebDriverForTesting(
        label="browser-bin",
        path=binary_path,
        settings=Settings(platform=self.platform))
    self.assertEqual(browser_bin.path, binary_path)
    self.assertEqual(browser_bin.app_path, app_path)

    # Both should be identical in terms of paths
    self.assertEqual(browser_app.path, browser_bin.path)
    self.assertEqual(browser_app.app_path, browser_bin.app_path)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
