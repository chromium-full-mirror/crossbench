# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pytest

from crossbench import plt
from crossbench.plt.android_adb import Adb, AndroidAdbPlatform
from crossbench.plt.remote import RemotePopen
from tests import test_helper
from tests.crossbench.plt.test_native_platform import \
    PosixNativePlatformTestCase


@pytest.fixture(scope="class")
def adb_unittest_fixtures(request, device_id, adb_path):
  request.cls.device_id = device_id
  request.cls.adb_path = adb_path


@pytest.mark.usefixtures("adb_unittest_fixtures")
class AndroidAdbPlatformTestCase(PosixNativePlatformTestCase):

  def setUp(self):
    super().setUp()
    assert hasattr(self, "device_id")
    assert hasattr(self, "adb_path")
    self.adb = Adb(plt.PLATFORM, self.device_id, self.adb_path)
    self.host_platform = plt.PLATFORM
    self.platform: AndroidAdbPlatform = AndroidAdbPlatform(
        self.host_platform, adb=self.adb)
    assert self.platform.is_android
    self.known_binary = "dumpsys"

  def test_app_version(self):
    with self.assertRaises(ValueError):
      self.platform.app_version("path/to/invalid/test/crossbench/bin")
    version = self.platform.app_version("com.android.chrome")
    self.assertTrue(version)

  def test_is_battery_powered(self):
    self.assertIs(self.platform.is_battery_powered, False)

  def test_home(self):
    if self.adb.has_root():
      self.assertTrue(self.platform.is_dir(self.platform.home()))

  def test_binary_lookup_override_home_dir(self):
    if not self.adb.has_root():
      self.skipTest("AndroidAdbPlatform requires ADB root privileges "
                    "to access the user home directory (~).")
    super().test_binary_lookup_override_home_dir()

  def test_cpu_usage(self):
    self.skipTest("Not supported yet")

  def test_remote_popen(self):
    popen = None
    try:
      popen = self.platform.popen("watch", "ls")
      self.assertIsInstance(popen, RemotePopen)
      self.assertTrue(popen.remote_pid)
      self.assertTrue(popen.pid)
      process_info = self.platform.process_info(popen.remote_pid)
      self.assertTrue(process_info)
      self.assertTrue(self.host_platform.process_info(popen.pid))
    finally:
      popen.kill()
      self.assertIsNone(self.platform.process_info(popen.remote_pid))

  def test_display_resolution(self):
    resolution = self.platform.display_resolution()
    # We don't know the display resolution of the test device, but we can check
    # that it doesn't raise and that is has some size.
    self.assertGreater(resolution.width, 0)
    self.assertGreater(resolution.height, 0)

  def test_user_id(self):
    self.assertGreaterEqual(self.platform.user_id(), 0)

  def test_android_system_details(self):
    details = self.platform.system_details()
    self.assertIn("Android", details)


del PosixNativePlatformTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
