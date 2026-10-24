# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import logging
import pathlib
import re
import sys
import tempfile
from typing import TYPE_CHECKING, Final, Iterator
from unittest import mock

import psutil
import pytest
from typing_extensions import override

from crossbench import plt
from crossbench.browsers import all as browsers
from crossbench.browsers.chrome.chrome import Chrome
from crossbench.browsers.chromium.chromium import Chromium
from crossbench.browsers.chromium.driver_finder import ChromeDriverFinder
from crossbench.cli.config.browser_variants import BrowserVariantsConfig
from crossbench.parse import PathParser
from crossbench.plt.android_adb import adb_devices
from crossbench.plt.bin import Binaries, BinaryNotFoundError
from tests.test_helper import TestEnv

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.cli.config.browser import BrowserConfig

WIN_APP_SUFFIX: Final = (".exe", ".bat")

ADB_DEVICE_ID_FLAG: Final = "--adb-device-id"
ADB_PATH_FLAG: Final = "--adb-path"
BUNDLETOOL_FLAG: Final = "--bundletool"
CAS_ARCHIVE_FLAG: Final = "--cas-archive"
TEST_BROWSER_FLAG: Final = "--test-browser-path"
TEST_DRIVER_FLAG: Final = "--test-driver-path"


def pytest_addoption(parser):
  parser.addoption(
      TEST_BROWSER_FLAG, "--browserpath", default=None, type=PathParser.path)
  parser.addoption(
      TEST_DRIVER_FLAG, "--driverpath", default=None, type=PathParser.path)
  parser.addoption(ADB_DEVICE_ID_FLAG, default=None, type=str)
  parser.addoption(ADB_PATH_FLAG, default=None, type=str)
  parser.addoption(BUNDLETOOL_FLAG, default=None, type=str)
  parser.addoption("--ignore-tests", default=None, type=str)
  parser.addoption(CAS_ARCHIVE_FLAG, default=None, type=str)


def pytest_xdist_auto_num_workers(config):
  del config
  if "linux" in sys.platform:
    return 2
  return 4


def _get_app_path(request, option_key) -> pathlib.Path | None:
  app_path = request.config.getoption(option_key)
  if app_path and plt.PLATFORM.is_win and app_path.suffix not in WIN_APP_SUFFIX:
    if (app_path.parent / (app_path.name + ".bat")).exists():
      return app_path.parent / (app_path.name + ".bat")
    if (app_path.parent / (app_path.name + ".exe")).exists():
      return app_path.parent / (app_path.name + ".exe")
  return app_path


@pytest.fixture(scope="session")
def driver_path(request) -> pathlib.Path | None:
  maybe_driver_path: pth.LocalPath | None = _get_app_path(
      request, TEST_DRIVER_FLAG)
  if maybe_driver_path:
    logging.info("driver path: %s", maybe_driver_path)
    assert maybe_driver_path.exists()
  return maybe_driver_path


@pytest.fixture(scope="session")
def browser_path(request) -> pathlib.Path | None:
  maybe_browser_path: pathlib.Path | None = _get_app_path(
      request, TEST_BROWSER_FLAG)
  if maybe_browser_path:
    logging.info("browser path: %s", maybe_browser_path)
    assert maybe_browser_path.exists()
    return maybe_browser_path
  logging.info("Trying default browser path for local runs.")
  try:
    return pathlib.Path(browsers.Chrome.stable_path(plt.PLATFORM))
  except ValueError as e:
    logging.warning("Unable to find Chrome Stable on %s, error=%s",
                    plt.PLATFORM, e)
    return None


def is_browser_path_chromium(browser_path) -> bool:
  # We support local/infra built chrome and chromium versions in the tests
  # However, the rest of crossbench is fairly strict in that regard, so we
  # manually patch the default Chrome version to match whatever flavour
  # (chrome or chromium) we want to use.
  if not browser_path:
    return False
  version_str = plt.PLATFORM.app_version(browser_path)
  return "chromium" in version_str.lower()


@pytest.fixture(scope="session")
def test_chrome_name(browser_path) -> str:
  if is_browser_path_chromium(browser_path):
    return "chromium"
  return "chrome-stable"


@pytest.fixture(scope="session")
def test_chrome_version(browser_path) -> int:
  if not browser_path:
    return "unknown"
  # extract the first number from the version string
  version_str = plt.PLATFORM.app_version(browser_path)
  return int(version_str.split(".")[0].split(" ")[-1])


def session_patch_chrome_driver_finder(driver_path, browser_path):
  if not driver_path:
    yield
    return

  class MockChromeDriverFinder(ChromeDriverFinder):

    @override
    def download(self):
      if self.browser.path == browser_path:
        # The CQ uses the latest canary, which might not have a easily publicly
        # accessible chromedriver available.
        return driver_path
      return super().download()

  with mock.patch(
      "crossbench.browsers.chromium_based.webdriver.ChromeDriverFinder",
      new=MockChromeDriverFinder):
    yield


@pytest.fixture(scope="session", autouse=True)
def session_patch_chrome_stable(browser_path):
  if is_browser_path_chromium(browser_path):
    with mock.patch.object(Chromium, "default_path", return_value=browser_path):
      yield
      return
  with mock.patch.object(Chrome, "stable_path", return_value=browser_path):
    yield


@contextlib.contextmanager
def mock_patch_chrome_stable(browser_path) -> Iterator[None]:
  is_chromium = is_browser_path_chromium(browser_path)
  original_get_browser_cls = BrowserVariantsConfig.get_browser_cls

  def mock_get_browser_cls(browser_config: BrowserConfig):
    nonlocal is_chromium
    path_str = str(browser_config.path).lower()
    if "chrome" not in path_str and "chromium" not in path_str:
      return original_get_browser_cls(browser_config)
    if is_chromium:
      return BrowserVariantsConfig.get_chromium_browser_cls(browser_config)
    return BrowserVariantsConfig.get_chrome_browser_cls(browser_config)

  with mock.patch.object(
      Chrome, "stable_path", return_value=browser_path), mock.patch.object(
          BrowserVariantsConfig,
          "get_browser_cls",
          side_effect=mock_get_browser_cls):
    yield


def _kill_lingering_chromedriver() -> None:
  if not plt.PLATFORM.is_win:
    return
  for proc in psutil.process_iter():
    with contextlib.suppress(psutil.Error):
      if "chromedriver" in proc.name().lower():
        proc.kill()


@pytest.fixture
def test_env(request):
  test_name = re.sub(r"[\[\]\\/*?:\"<>|]", "_", request.node.name)
  maybe_cas_archive: str | None = request.config.getoption(CAS_ARCHIVE_FLAG)
  if maybe_cas_archive:
    cas_test_env = TestEnv(pathlib.Path(maybe_cas_archive), test_name)
    try:
      yield cas_test_env
    finally:
      _kill_lingering_chromedriver()
      cas_test_env.remove_non_result()
  else:
    with tempfile.TemporaryDirectory() as tmp_dirname:
      tmp_test_env = TestEnv(pathlib.Path(tmp_dirname), test_name)
      try:
        yield tmp_test_env
      finally:
        _kill_lingering_chromedriver()


@pytest.fixture(scope="session")
def device_id(request, adb_path) -> str | None:
  maybe_device_id: str | None = request.config.getoption(ADB_DEVICE_ID_FLAG)
  if maybe_device_id:
    logging.info("adb device id: %s", maybe_device_id)
    return maybe_device_id
  if adb_path:
    devices = adb_devices(plt.PLATFORM, adb_path)
    if len(devices) == 1:
      device_id, _ = devices.popitem()
      logging.info("Auto selecting android device: %s", device_id)
      return device_id
  logging.info("No Android device detected.")
  return None


@pytest.fixture(scope="session")
def adb_path(request) -> str | None:
  maybe_adb_path: str | None = request.config.getoption(ADB_PATH_FLAG)
  if maybe_adb_path:
    logging.info("adb path: %s", maybe_adb_path)
    return maybe_adb_path
  try:
    adb_path = Binaries.ADB.resolve(plt.PLATFORM)
    logging.info("Using default local adb: %s", adb_path)
    return str(adb_path)
  except BinaryNotFoundError:
    logging.info("No custom adb path.")
    return None


@pytest.fixture(scope="session")
def bundletool(request) -> str | None:
  maybe_bundletool: str | None = request.config.getoption(BUNDLETOOL_FLAG)
  logging.info("bundletool: %s", maybe_bundletool)
  return maybe_bundletool
