# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import pathlib

from typing_extensions import override

from crossbench.plt.chromeos_ssh import ChromeOsSshPlatform
from crossbench.plt.display_info import DisplayResolution
from tests import test_helper
from tests.crossbench.plt.test_linux_ssh import LinuxSshMockPlatformTestCase


class ChromeOsSshMockPlatformTestCase(LinuxSshMockPlatformTestCase):
  SSH_USER = "chronos"
  platform: ChromeOsSshPlatform

  @override
  def setup_platform(self, enable_arc=False) -> ChromeOsSshPlatform:
    return ChromeOsSshPlatform(
        self.host_platform,
        host=self.HOST,
        port=self.PORT,
        ssh_port=self.SSH_PORT,
        ssh_user=self.SSH_USER,
        enable_arc=enable_arc)

  def test_name(self):
    self.assertEqual(self.platform.name, "chromeos_ssh")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "chromeos")

  def test_is_chromeos(self):
    self.assertTrue(self.platform.is_chromeos)

  def test_basic_properties(self):
    super().test_basic_properties()
    self.assertEqual(self.platform.default_tmp_dir,
                     pathlib.PurePosixPath("/usr/local/tmp/"))

  def test_display_resolution(self):
    cros_health_tool_out = """
    {
      "embedded_display": {
        "display_height": "140",
        "display_name": "NV116WHM-T14",
        "display_width": "260",
        "edid_version": "1.4",
        "input_type": "Digital",
        "manufacture_week": 1,
        "manufacture_year": 2019,
        "manufacturer": "BOE",
        "model_id": 2303,
        "privacy_screen_enabled": false,
        "privacy_screen_supported": false,
        "refresh_rate": 59.99822202162979,
        "resolution_horizontal": "1366",
        "resolution_vertical": "768"
      }
    }"""
    self._expect_sh_ssh(
        "cros-health-tool telem --category=display",
        result=cros_health_tool_out)
    resolution = self.platform.display_resolution()
    self.assertEqual(resolution, DisplayResolution(1366, 768))
    self.assertEqual(resolution.width, 1366)
    self.assertEqual(resolution.height, 768)

  def test_create_debugging_session(self):
    expected_port = 80

    self._expect_sh_ssh(
        "/usr/local/autotest/bin/autologin.py -u username -p password")
    self._expect_sh_ssh(
        "cat /home/chronos/DevToolsActivePort", result=f"{expected_port}")
    port = self.platform.create_debugging_session(
        browser_flags=(), username="username", password="password")

    self.assertEqual(port, expected_port)

  def test_create_debugging_session_arc(self):
    self.platform = self.setup_platform(enable_arc=True)
    expected_port = 80

    self._expect_sh_ssh(
        "/usr/local/autotest/bin/autologin.py --arc -u username -p password")
    self._expect_sh_ssh(
        "cat /home/chronos/DevToolsActivePort", result=f"{expected_port}")
    port = self.platform.create_debugging_session(
        browser_flags=(), username="username", password="password")

    self.assertEqual(port, expected_port)

  def test_create_debugging_session_arc_removes_disable_extensions(self):
    self.platform = self.setup_platform(enable_arc=True)
    expected_port = 80

    self._expect_sh_ssh("/usr/local/autotest/bin/autologin.py --arc"
                        " -u username -p password -- --another-flag")
    self._expect_sh_ssh(
        "cat /home/chronos/DevToolsActivePort", result=f"{expected_port}")
    port = self.platform.create_debugging_session(
        browser_flags=("--disable-extensions", "--another-flag"),
        username="username",
        password="password")

    self.assertEqual(port, expected_port)

  def test_system_details(self):
    self.platform = self.setup_platform()

    self._expect_sh_ssh("uname -m", result="x86_64")
    self._expect_sh_ssh("uname", result="Linux")
    self._expect_sh_ssh("uname -r", result="1.0")
    self._expect_sh_ssh("uname -v", result="definitely 1.0")
    self._expect_sh_ssh("uname -a", result="still definitely 1.0")
    self._expect_sh_ssh("which python3", result="/bin/python3.0")
    self._expect_sh_ssh("'[' -e /bin/python3.0 ']'", result="")
    self._expect_sh_ssh("/bin/python3.0 --version", result="Python 3.0")
    self._expect_sh_ssh(
        "/bin/python3.0 -c 'import sys; "
        "print(64 if sys.maxsize > 2**32 else 32)'",
        result="64")
    self._expect_sh_ssh("cat /proc/cpuinfo", result="crossbench")
    self._expect_sh_ssh(
        "grep -E 'processor|core id|physical id' /proc/cpuinfo",
        result="processor: 0\nphysical id: 0\ncore id: 0")
    self._expect_sh_ssh(
        "grep -E 'processor|core id|physical id' /proc/cpuinfo",
        result="processor: 0\nphysical id: 0\ncore id: 0")

    display_info = {
        "embedded_display": {
            "resolution_horizontal": 1,
            "resolution_vertical": 2,
        },
    }
    self._expect_sh_ssh(
        "cros-health-tool telem --category=display",
        result=json.dumps(display_info))
    self._expect_sh_ssh("which lscpu", result="/bin/lscpu")
    self._expect_sh_ssh("'[' -e /bin/lscpu ']'", result="")
    self._expect_sh_ssh("/bin/lscpu", result="definitely a real cpu")
    self._expect_sh_ssh("which inxi", result="/bin/inxi")
    self._expect_sh_ssh("'[' -e /bin/inxi ']'", result="")
    self._expect_sh_ssh("/bin/inxi", result="CPU")

    lsb_release = """
CHROMEOS_RELEASE_APPID={E0DD1258-E890-493E-ADA3-0C755240B89C}
CHROMEOS_BOARD_APPID={E0DD1258-E890-493E-ADA3-0C755240B89C}
CHROMEOS_CANARY_APPID={90F229CE-83E2-4FAF-8479-E368A34938B1}
DEVICETYPE=CHROMEBOOK
CHROMEOS_RELEASE_NAME=Chrome OS
CHROMEOS_AUSERVER=https://tools.google.com/service/update2
CHROMEOS_DEVSERVER=
CHROMEOS_ARC_VERSION=12899595
CHROMEOS_ARC_ANDROID_SDK_VERSION=33
CHROMEOS_RELEASE_BUILDER_PATH=dedede-release/R132-16093.83.0
CHROMEOS_RELEASE_KEYSET=devkeys
CHROMEOS_RELEASE_TRACK=testimage-channel
CHROMEOS_RELEASE_BUILD_TYPE=Official Build
CHROMEOS_RELEASE_DESCRIPTION=16093.83.0 (Official Build) dev-channel dedede test
CHROMEOS_RELEASE_BOARD=dedede
CHROMEOS_RELEASE_BRANCH_NUMBER=83
CHROMEOS_RELEASE_BUILD_NUMBER=16093
CHROMEOS_RELEASE_CHROME_MILESTONE=132
CHROMEOS_RELEASE_PATCH_NUMBER=0
CHROMEOS_RELEASE_VERSION=16093.83.0
GOOGLE_RELEASE=16093.83.0
CHROMEOS_RELEASE_UNIBUILD=1
"""
    self._expect_sh_ssh("cat /etc/lsb-release", result=lsb_release)

    details = self.platform.system_details()

    self.assertEqual(len(details["ChromeOS"]), 22)
    self.assertEqual(details["ChromeOS"]["CHROMEOS_RELEASE_BOARD"], "dedede")
    self.assertEqual(details["ChromeOS"]["CHROMEOS_RELEASE_BUILD_NUMBER"],
                     "16093")


del LinuxSshMockPlatformTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
