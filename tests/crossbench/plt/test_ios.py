# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import subprocess
import unittest.mock as mock
import urllib.error
import urllib.parse
import urllib.request

from pyfakefs.fake_filesystem import OSType
from typing_extensions import override

from crossbench import path as pth
from crossbench.plt.bin import Binaries
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.ios import IOSDeviceInfo, IOSPlatform, IOSPortManager, \
    IOSSimulatorPortManager, ios_devices
from crossbench.plt.version import PlatformVersion
from crossbench.plt.wda import WDAClient, WDAError
from tests import test_helper
from tests.crossbench.mock_helper import MacOsMockPlatform
from tests.crossbench.plt.helper import BaseMockPlatformTestCase

DEVICES_SINGLE = {
    "result": {
        "devices": [{
            "hardwareProperties": {
                "udid": "00001111-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone",
                "osVersionNumber": "17.1.2",
            },
            "connectionProperties": {
                "tunnelState": "connected",
            },
        }, {
            "hardwareProperties": {
                "udid": "00002222-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone Pro",
                "osVersionNumber": "17.1.1",
            },
            "connectionProperties": {
                "tunnelState": "unavailable",
            },
        }],
    },
}

DEVICES_MULTIPLE = {
    "result": {
        "devices": [{
            "hardwareProperties": {
                "udid": "00001111-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone",
                "osVersionNumber": "17.1.2",
            },
            "connectionProperties": {
                "tunnelState": "connected",
            },
        }, {
            "hardwareProperties": {
                "udid": "00002222-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone Pro",
                "osVersionNumber": "17.1.1",
            },
            "connectionProperties": {
                "tunnelState": "connected",
            },
        }, {
            "hardwareProperties": {
                "udid": "00003333-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone Pro Max",
                "osVersionNumber": "17.1.0",
            },
            "connectionProperties": {
                "tunnelState": "unavailable",
            },
        }],
    },
}

DEVICES_NONE = {
    "result": {
        "devices": [{
            "hardwareProperties": {
                "udid": "00002222-11AA22BB33DD",
            },
            "deviceProperties": {
                "name": "An iPhone Pro",
                "osVersionNumber": "17.1.1",
            },
            "connectionProperties": {
                "tunnelState": "unavailable",
            },
        }],
    },
}

IPHONE_SIMULATOR = {
    "udid": "SIM-UDID-1111",
    "name": "iPhone 15 Simulator",
    "state": "Booted",
}

WATCH_SIMULATOR = {
    "udid": "SIM-UDID-2222",
    "name": "Apple Watch Simulator",
    "state": "Booted",
}

SIMULATORS_SAMPLE = {
    "devices": {
        "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [IPHONE_SIMULATOR],
        "com.apple.CoreSimulator.SimRuntime.watchOS-10-0": [WATCH_SIMULATOR],
    },
}


class BaseIOsMockPlatformTestCase(BaseMockPlatformTestCase):
  SAFARI_PATH = "/Applications/Safari.app"

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.os = OSType.MACOS

  @override
  def setup_host_platform(self) -> MacOsMockPlatform:
    platform = MacOsMockPlatform()

    @contextlib.contextmanager
    def mock_named_temporary_file(suffix=None, prefix=None, dir=None):
      yield pth.LocalPath("/devicectl_output.json")

    platform.NamedTemporaryFile = mock_named_temporary_file
    return platform

  @override
  def setup_platform(self) -> IOSPlatform:
    self.expect_startup_devices()
    return IOSPlatform(self.host_platform)

  def expect_startup_devices(self, devices=None, simulators=None):
    if devices is None:
      devices = DEVICES_SINGLE
    if simulators is None:
      simulators = {"devices": {}}
    # Use the fs directly to avoid issues with /tmp symlinks on MacOS fakefs
    if self.fs.exists("/devicectl_output.json"):
      self.fs.remove_object("/devicectl_output.json")
    self.fs.create_file("/devicectl_output.json", contents=json.dumps(devices))
    self.host_platform.expect_sh(
        "xcrun",
        "devicectl",
        "list",
        "devices",
        "--json-output=/devicectl_output.json",
        result="")
    self.host_platform.expect_sh(
        "xcrun",
        "simctl",
        "list",
        "devices",
        "booted",
        "--json",
        result=json.dumps(simulators))

  def test_name(self):
    self.assertEqual(self.platform.name, "ios")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "ios")

  def test_is_ios(self):
    self.assertTrue(self.platform.is_ios)

  def test_is_apple(self):
    self.assertTrue(self.platform.is_apple)


class IOsMockPlatformTestCase(BaseIOsMockPlatformTestCase):
  __test__ = True

  def test_create_device_udid(self):
    self.expect_startup_devices()
    platform_a = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.assertEqual(platform_a.udid, "00001111-11AA22BB33DD")
    self.expect_startup_devices()
    platform_b = IOSPlatform(self.host_platform)
    self.assertEqual(platform_b.udid, "00001111-11AA22BB33DD")

  def test_create_device_udid_multiple(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.assertEqual(platform_a.udid, "00001111-11AA22BB33DD")
    with self.assertRaises(ValueError):
      self.expect_startup_devices(DEVICES_MULTIPLE)
      IOSPlatform(self.host_platform)
    with self.assertRaises(ValueError):
      self.expect_startup_devices(DEVICES_MULTIPLE)
      IOSPlatform(self.host_platform, "invalid device id")

  def test_create_device_name(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(platform_a.udid, "00002222-11AA22BB33DD")

  def test_create_device_name_non_unique(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    with self.assertRaisesRegex(ValueError, "2 devices"):
      IOSPlatform(self.host_platform, "iPhone")

  def test_create_no_devices(self):
    self.expect_startup_devices(DEVICES_NONE)
    with self.assertRaisesRegex(ValueError, "No devices"):
      IOSPlatform(self.host_platform, "iPhone")

  def test_uptime(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(platform_a.uptime(), dt.timedelta())

  def test_which_empty_path(self):
    with self.assertRaises(ValueError):
      self.platform.which("")
    with self.assertRaises(ValueError):
      self.platform.which(pathlib.Path())

  def test_search_binary_empty_path(self):
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary(pathlib.Path())
    self.assertIn("empty", str(cm.exception))
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary("")
    self.assertIn("empty", str(cm.exception))

  def test_search_binary_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(
        str(platform.search_binary(self.SAFARI_PATH)),
        str(pth.AnyPath(self.SAFARI_PATH)))

  def test_search_binary_not_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    with self.assertRaisesRegex(ValueError, "Safari is the only supported app"):
      platform_a.search_binary("/usr/bin/safaridriver")

  def test_is_file_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertTrue(platform_a.is_file(self.SAFARI_PATH))

  def test_is_file_not_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    with self.assertRaisesRegex(ValueError, "Safari is the only supported app"):
      platform_a.is_file("/usr/bin/safaridriver")

  def test_app_version_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(platform_a.app_version(self.SAFARI_PATH), "17.1.1")

  def test_app_version_not_safari(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    with self.assertRaisesRegex(ValueError, "Safari is the only supported app"):
      platform_a.app_version("/usr/bin/safaridriver")

  def test_process_children(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertSequenceEqual(platform_a.process_children(123), [])

  def test_os_details(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(
        platform_a.os_details(), {
            "system": "ios",
            "platform": "ios 17.1.1",
            "version": "17.1.1",
            "release": "17.1.1",
        })

  def test_version(self):
    self.expect_startup_devices(DEVICES_MULTIPLE)
    platform_a = IOSPlatform(self.host_platform, "iPhone Pro")
    self.assertEqual(platform_a.version, PlatformVersion([17, 1, 1]))

  def test_simulator_device_discovery(self):
    self.expect_startup_devices(
        devices=DEVICES_NONE, simulators=SIMULATORS_SAMPLE)
    expected_device = IOSDeviceInfo(
        device_id=IPHONE_SIMULATOR["udid"],
        name=IPHONE_SIMULATOR["name"],
        version="17.5",
        is_simulator=True)
    devices = ios_devices(self.host_platform)
    self.assertEqual(devices, {IPHONE_SIMULATOR["udid"]: expected_device})
    # Implied, but for clarity's sake.
    self.assertNotIn(WATCH_SIMULATOR["udid"], devices)

  def test_simulator_and_physical_devices_combined(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    expected_physical = IOSDeviceInfo(
        device_id="00001111-11AA22BB33DD",
        name="An iPhone",
        version="17.1.2",
        is_simulator=False)
    expected_sim = IOSDeviceInfo(
        device_id=IPHONE_SIMULATOR["udid"],
        name=IPHONE_SIMULATOR["name"],
        version="17.5",
        is_simulator=True)
    devices = ios_devices(self.host_platform)
    self.assertEqual(
        devices, {
            "00001111-11AA22BB33DD": expected_physical,
            IPHONE_SIMULATOR["udid"]: expected_sim,
        })
    # Implied, but for clarity's sake.
    self.assertNotIn(WATCH_SIMULATOR["udid"], devices)

  def test_is_simulator(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.assertFalse(platform_physical.is_simulator)

    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_sim = IOSPlatform(self.host_platform, IPHONE_SIMULATOR["udid"])
    self.assertTrue(platform_sim.is_simulator)

  def test_devicectl_skips_simulated_devices(self):
    devicectl_with_simulators = {
        "result": {
            "devices": [{
                "hardwareProperties": {
                    "udid": "00001111-11AA22BB33DD",
                },
                "deviceProperties": {
                    "name": "An iPhone",
                    "osVersionNumber": "17.1.2",
                },
                "connectionProperties": {
                    "tunnelState": "connected",
                },
            }, {
                "hardwareProperties": {
                    "udid": "7600EAC9-72DA-4538-86F6-DA1DC29419E8",
                    "reality": "simulated",
                },
                "deviceProperties": {
                    "bootState": "shutdown",
                    "name": "iPhone 17",
                    "osVersionNumber": "26.5",
                },
                "connectionProperties": {
                    "tunnelState": "disconnected",
                },
                "visibilityClass": "simulators",
            }],
        },
    }
    self.expect_startup_devices(devices=devicectl_with_simulators)
    devices = ios_devices(self.host_platform)
    self.assertEqual(list(devices.keys()), ["00001111-11AA22BB33DD"])

  def test_simulator_port_forward(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_sim = IOSPlatform(self.host_platform, IPHONE_SIMULATOR["udid"])
    self.assertIsInstance(platform_sim._default_port_manager,
                          IOSSimulatorPortManager)
    port = platform_sim.ports.forward(8100, 8100)
    self.assertEqual(port, 8100)
    platform_sim.ports.stop_forward(8100)

  def test_simulator_port_forward_mismatch(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_sim = IOSPlatform(self.host_platform, IPHONE_SIMULATOR["udid"])
    with self.assertRaises(ValueError):
      platform_sim.ports.forward(8200, 8100)

  def test_physical_port_forward(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.assertIsInstance(platform_physical._default_port_manager,
                          IOSPortManager)
    self.fs.create_file("/usr/local/bin/iproxy")
    self.host_platform.which = mock.MagicMock(
        return_value=pth.LocalPath("/usr/local/bin/iproxy"))
    self.host_platform.is_port_used = mock.MagicMock(return_value=True)
    mock_proc = mock.MagicMock()
    self.host_platform.popen = mock.MagicMock(return_value=mock_proc)

    port = platform_physical.ports.forward(8100, 8100)
    self.assertEqual(port, 8100)
    self.host_platform.popen.assert_called_once_with(
        pth.LocalPath("/usr/local/bin/iproxy"),
        "8100",
        "8100",
        "-u",
        "00001111-11AA22BB33DD",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    platform_physical.ports.stop_forward(8100)
    mock_proc.terminate.assert_called_once()

  def test_physical_port_forward_wait_failure_cleanup(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.fs.create_file("/usr/local/bin/iproxy")
    self.host_platform.which = mock.MagicMock(
        return_value=pth.LocalPath("/usr/local/bin/iproxy"))
    self.host_platform.wait_for_port = mock.MagicMock(
        side_effect=TimeoutError("Port not bound"))
    mock_proc = mock.MagicMock()
    self.host_platform.popen = mock.MagicMock(return_value=mock_proc)

    with self.assertRaises(TimeoutError):
      platform_physical.ports.forward(8100, 8100)
    mock_proc.terminate.assert_called_once()
    self.assertNotIn(8100,
                     platform_physical._default_port_manager._forward_popens)

  def test_physical_port_forward_reverse_not_supported(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    with self.assertRaises(NotImplementedError):
      platform_physical.ports.reverse_forward(8100, 8100)
    self.assertFalse(
        platform_physical.ports.is_reverse_forwarded_port_used(8100))

  def test_display_details(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    self.assertEqual(platform_physical.display_details(), ())

  def test_display_resolution(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform_physical = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    mock_wda = mock.MagicMock()
    mock_wda.window_size.return_value = DisplayResolution(440, 956)
    platform_physical._wda = mock_wda

    res = platform_physical.display_resolution()
    self.assertEqual(res, DisplayResolution(440, 956))
    mock_wda.window_size.assert_called_once()


class IOsWdaTestCase(BaseIOsMockPlatformTestCase):
  __test__ = True

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.create_file("/usr/bin/iproxy", st_mode=0o755)
    self.host_platform.is_port_used = mock.MagicMock(return_value=True)
    self.host_platform.get_free_port = mock.MagicMock(
        side_effect=range(54321, 54400))
    self.host_platform.popen = mock.MagicMock(
        side_effect=lambda *args, **kwargs: mock.MagicMock())

  @contextlib.contextmanager
  def mock_wda_server(self, platform: IOSPlatform | None = None):
    target_platform = platform or self.platform

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0):
      del timeout
      parsed = urllib.parse.urlparse(req.full_url)
      self.assertTrue(
          target_platform.ports.is_forwarded_port_used(parsed.port or 0))
      payload = {"value": {"ready": True, "sessionId": "session-1"}}
      return io.BytesIO(json.dumps(payload).encode("utf-8"))

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
      yield

  def test_wda_window_size(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    wda._session_id = "test-session-123"

    with mock.patch.object(wda, "_request") as mock_request:
      mock_request.return_value = {
          "value": {
              "width": 440,
              "height": 956,
          },
      }
      res = wda.window_size()
      self.assertEqual(res, DisplayResolution(440, 956))
      mock_request.assert_called_once_with(
          "GET",
          "/session/test-session-123/window/size",
          timeout=mock.ANY,
      )

    with mock.patch.object(wda, "_request") as mock_request:
      mock_request.return_value = {"value": {"width": 0, "height": 0}}
      with self.assertRaises(WDAError):
        wda.window_size()

  def test_wda_gestures(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    wda._session_id = "test-session-123"

    with mock.patch.object(wda, "_request") as mock_request:
      wda.swipe(
          100,
          200,
          300,
          400,
          dt.timedelta(milliseconds=500),
          settle_duration=dt.timedelta(milliseconds=150),
      )
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/actions",
          mock.ANY,
          timeout=mock.ANY,
      )
      payload = mock_request.call_args[0][2]
      actions = payload["actions"][0]["actions"]
      self.assertEqual(len(actions), 7)
      self.assertEqual(
          actions[-3],
          {
              "type": "pointerMove",
              "duration": 140,
              "x": 0,
              "y": 4,
              "origin": "pointer",
          },
      )
      self.assertEqual(actions[-2], {"type": "pause", "duration": 10})
      self.assertEqual(actions[-1], {"type": "pointerUp", "button": 0})

    with mock.patch.object(wda, "_request") as mock_request:
      wda.swipe_sequence(
          [(100, 400, 100, 200), (100, 200, 100, 400)],
          duration=dt.timedelta(milliseconds=750),
          settle_duration=dt.timedelta(milliseconds=150),
          lift_duration=dt.timedelta(milliseconds=100),
      )
      mock_request.assert_called_once()
      batch = mock_request.call_args[0][2]["actions"]
      self.assertEqual(len(batch), 2)
      self.assertEqual(
          batch[1]["actions"][0],
          {
              "type": "pause",
              "duration": 1000,
          },
      )

    with mock.patch.object(wda, "_request") as mock_request:
      wda.scroll("down")
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/wda/scroll",
          {"direction": "down"},
          timeout=mock.ANY,
      )

    with mock.patch.object(wda, "_request") as mock_request:
      wda.drag(100, 200, 300, 400, dt.timedelta(milliseconds=500))
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/wda/dragfromtoforduration",
          {
              "fromX": 100,
              "fromY": 200,
              "toX": 300,
              "toY": 400,
              "duration": 0.5,
          },
          timeout=mock.ANY,
      )

  def test_wda_app_management_and_navigation(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    wda._session_id = "test-session-123"

    with mock.patch.object(wda, "_request") as mock_request:
      wda.launch_app(
          "com.apple.mobilesafari",
          arguments=["-u", "https://example.com"],
      )
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/wda/apps/launch",
          {
              "bundleId": "com.apple.mobilesafari",
              "arguments": ["-u", "https://example.com"],
          },
          timeout=mock.ANY,
      )

    with mock.patch.object(wda, "_request") as mock_request:
      wda.terminate_app("com.apple.mobilesafari")
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/wda/apps/terminate",
          {"bundleId": "com.apple.mobilesafari"},
          timeout=mock.ANY,
      )

    with mock.patch.object(wda, "_request") as mock_request:
      wda.open_url("https://example.com")
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/url",
          {"url": "https://example.com"},
          timeout=mock.ANY,
      )

  def test_wda_settings_and_session_configuration(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    wda._session_id = "test-session-123"

    with mock.patch.object(wda, "_request") as mock_request:
      wda.set_settings({"animationCoolOffTimeout": 0})
      mock_request.assert_called_once_with(
          "POST",
          "/session/test-session-123/appium/settings",
          {
              "settings": {
                  "animationCoolOffTimeout": 0,
              },
          },
          timeout=mock.ANY,
      )

    wda._session_id = None
    with mock.patch.object(wda, "start"), \
         mock.patch.object(wda, "_request") as mock_request:
      mock_request.side_effect = [
          {
              "value": {
                  "sessionId": "new-session-456",
              },
          },
          {},
      ]
      session_id = wda.ensure_session()
      self.assertEqual(session_id, "new-session-456")
      self.assertEqual(mock_request.call_count, 2)
      mock_request.assert_has_calls([
          mock.call("GET", "/status", timeout=mock.ANY),
          mock.call(
              "POST",
              "/session/new-session-456/appium/settings",
              {
                  "settings": {
                      "animationCoolOffTimeout": 0,
                      "snapshotMaxChildren": 1,
                      "snapshotMaxDepth": 1,
                      "waitForIdleTimeout": 0,
                  },
              },
              timeout=mock.ANY,
          ),
      ])

  def test_wda_find_xctestrun_bin_override(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    custom_path = pth.LocalPath("/custom/test.xctestrun")
    self.fs.create_file(str(custom_path))
    with self.host_platform.override_binary(Binaries.WDA_XCTESTRUN,
                                            custom_path):
      self.assertEqual(wda._find_xctestrun(), custom_path)

  def test_wda_find_xctestrun_derived_data(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    home = self.host_platform.home()
    older = (
        home / "Library/Developer/Xcode/DerivedData/WebDriverAgent-old"
        "/Build/Products/WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun")
    newer = (
        home / "Library/Developer/Xcode/DerivedData/WebDriverAgent-new"
        "/Build/Products/WebDriverAgentRunner_iphoneos27.0-arm64.xctestrun")
    self.fs.create_file(str(older))
    self.fs.create_file(str(newer))
    os.utime(str(older), (100, 100))
    os.utime(str(newer), (200, 200))
    self.assertEqual(wda._find_xctestrun(), newer)

  def test_wda_find_xctestrun_bin_override_missing_file_raises(self):
    missing = pth.LocalPath("/custom/missing.xctestrun")
    with self.assertRaisesRegex(ValueError, "does not exist"):
      self.host_platform.set_binary_lookup_override(Binaries.WDA_XCTESTRUN.name,
                                                    missing)

  def test_wda_find_xctestrun_prefers_matching_sdk(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    products = (
        self.host_platform.home() /
        "Library/Developer/Xcode/DerivedData/WebDriverAgent-x/Build/Products")
    device_build = (
        products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun")
    sim_build = (
        products / "WebDriverAgentRunner_iphonesimulator26.5-arm64.xctestrun")
    self.fs.create_file(str(device_build))
    self.fs.create_file(str(sim_build))
    # The simulator build is newer, but must not be picked for a real device.
    os.utime(str(device_build), (100, 100))
    os.utime(str(sim_build), (200, 200))

    wda_device = WDAClient(
        IOSPlatform(self.host_platform, "00001111-11AA22BB33DD"))
    self.assertEqual(wda_device._find_xctestrun(), device_build)

    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    wda_sim = WDAClient(
        IOSPlatform(self.host_platform, IPHONE_SIMULATOR["udid"]))
    self.assertEqual(wda_sim._find_xctestrun(), sim_build)

  def test_wda_request_http_error_includes_body(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    body = io.BytesIO(
        b'{"value": {"error": "invalid argument", "message": "bad actions"}}')
    http_error = urllib.error.HTTPError(
        wda.base_url + "/session/x/actions",
        500,
        "Internal Server Error",
        hdrs=None,
        fp=body)  # type: ignore[arg-type]
    with mock.patch("urllib.request.urlopen", side_effect=http_error):
      with self.assertRaisesRegex(WDAError, "HTTP 500.*bad actions") as cm:
        wda._request("POST", "/session/x/actions", {"actions": []})
    self.assertIs(cm.exception.__cause__, http_error)

  def test_wda_start_runner_missing_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    self.host_platform.expect_sh(
        "DevToolsSecurity",
        "-status",
        result="Developer mode is currently enabled.")
    with self.assertRaises(WDAError) as cm:
      wda._start_runner()
    self.assertIn("WebDriverAgent is not running", str(cm.exception))
    self.assertIn("https://github.com/appium/WebDriverAgent", str(cm.exception))
    self.assertIn("--bin-override wda-xctestrun=", str(cm.exception))

  def test_wda_devtools_security_disabled_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    self.host_platform.expect_sh(
        "DevToolsSecurity",
        "-status",
        result="Developer mode is currently disabled.")
    with self.assertRaises(WDAError) as cm:
      wda._start_runner()
    self.assertIn("sudo DevToolsSecurity -enable", str(cm.exception))

  def test_wda_provisioning_profile_device_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    self.host_platform.expect_sh(
        "mdfind",
        "kMDItemFSName == 'WebDriverAgent.xcodeproj'",
        result="/Users/test/WebDriverAgent/WebDriverAgent.xcodeproj\n")
    output = ("Failed to install embedded profile for "
              "com.facebook.WebDriverAgentRunner.xctrunner : 0xe8008012 "
              "(This provisioning profile cannot be installed on this device.)")
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("open /Users/test/WebDriverAgent/WebDriverAgent.xcodeproj",
                  str(cm.exception))
    self.assertIn("00001111-11AA22BB33DD", str(cm.exception))

  def test_wda_untrusted_developer_certificate_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = (
        "The application could not be launched because the Developer App "
        "Certificate is not trusted.\n"
        "Domain: IDELaunchCoreDevice\nCode: 0\n"
        "Recovery Suggestion: Verify that the Developer App certificate for "
        "your account is trusted on your device.")
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("Developer App Certificate is not trusted", str(cm.exception))
    self.assertIn("VPN & Device Management", str(cm.exception))

  def test_wda_guided_access_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = ('Error Domain=FBSOpenApplicationErrorDomain Code=1 '
              '"Guided Access active"')
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("Guided Access is active", str(cm.exception))
    self.assertIn("Settings -> Accessibility -> Guided Access",
                  str(cm.exception))

  def test_wda_license_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = "You have not agreed to the Xcode license agreements."
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("sudo xcodebuild -license accept", str(cm.exception))

  def test_wda_developer_mode_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = "Developer Mode is disabled on device."
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("Developer Mode", str(cm.exception))

  def test_wda_device_locked_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = "Device is locked. Please unlock the device."
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(65, output)
    self.assertIn("Device 00001111-11AA22BB33DD is locked", str(cm.exception))

  def test_wda_password_auth_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    for output in (
        "Password: ",
        "sudo: a terminal is required to read the password",
    ):
      with self.assertRaises(WDAError) as cm:
        wda._handle_runner_error(65, output)
      self.assertIn("sudo DevToolsSecurity -enable", str(cm.exception))

  def test_wda_generic_error(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    output = "Unknown failure occurred during test run."
    with self.assertRaises(WDAError) as cm:
      wda._handle_runner_error(1, output)
    self.assertIn("code 1", str(cm.exception))
    self.assertIn("Unknown failure occurred", str(cm.exception))

  def test_wda_swipe_sequence_interrupt_stops_runner(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, "00001111-11AA22BB33DD")
    wda = WDAClient(platform)
    wda._session_id = "test-session-123"
    mock_proc = mock.MagicMock()
    wda._xcodebuild_proc = mock_proc

    self.fs.remove_object("/devicectl_output.json")
    self.fs.create_file(
        "/devicectl_output.json",
        contents=json.dumps({
            "result": {
                "runningProcesses": [
                    {
                        "executable": "file:///System/Developer/usr/libexec"
                                      "/testmanagerd",
                        "processIdentifier": 823,
                    },
                    {
                        "executable": "file:///private/var/containers/Bundle"
                                      "/WebDriverAgentRunner-Runner.app"
                                      "/WebDriverAgentRunner-Runner",
                        "processIdentifier": 827,
                    },
                ],
            },
        }),
    )
    self.host_platform.expect_sh(
        "xcrun",
        "devicectl",
        "device",
        "info",
        "processes",
        "--device",
        "00001111-11AA22BB33DD",
        "--json-output=/devicectl_output.json",
        result="",
    )
    self.host_platform.expect_sh(
        "xcrun",
        "devicectl",
        "device",
        "process",
        "terminate",
        "--device",
        "00001111-11AA22BB33DD",
        "--pid",
        "827",
        "--kill",
        result="",
    )
    self.host_platform.expect_sh(
        "xcrun",
        "devicectl",
        "device",
        "process",
        "terminate",
        "--device",
        "00001111-11AA22BB33DD",
        "--pid",
        "823",
        "--kill",
        result="",
    )

    with mock.patch.object(
        wda, "_request", side_effect=KeyboardInterrupt) as mock_request:
      with self.assertRaises(KeyboardInterrupt):
        wda.swipe_sequence([(100, 500, 100, 200)])
      mock_proc.terminate.assert_called_once_with()
      self.assertIsNone(wda._session_id)

      # Subsequent terminate_app should be a no-op since session was stopped.
      mock_request.reset_mock()
      wda.terminate_app("com.apple.mobilesafari")
      mock_request.assert_not_called()

  def test_wda_ensure_session_reuses_port_forward(self):
    wda = WDAClient(self.platform)
    with self.mock_wda_server(), self.platform.ports.nested():
      self.assertEqual(wda.ensure_session(), "session-1")
      self.assertEqual(wda.base_url, "http://localhost:54321")
      self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
      self.assertEqual(self.host_platform.popen.call_count, 1)

      self.assertEqual(wda.ensure_session(), "session-1")
      self.assertEqual(self.host_platform.popen.call_count, 1)
      wda.stop()

  def test_wda_port_forward_on_nested_scope_exit(self):
    wda = WDAClient(self.platform)
    with self.mock_wda_server():
      with self.platform.ports.nested():
        self.assertEqual(wda.ensure_session(), "session-1")
        self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))

      self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
      wda.stop()

  def test_wda_port_forward_across_nested_scopes(self):
    wda = WDAClient(self.platform)
    with self.mock_wda_server():
      with self.platform.ports.nested():
        self.assertEqual(wda.ensure_session(), "session-1")
        self.assertEqual(wda.base_url, "http://localhost:54321")
        self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
        self.assertEqual(self.host_platform.popen.call_count, 1)

      with self.platform.ports.nested():
        self.assertEqual(wda.ensure_session(), "session-1")
        self.assertEqual(wda.base_url, "http://localhost:54321")
        self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
        self.assertEqual(self.host_platform.popen.call_count, 1)
        wda.stop()

  def test_wda_terminate_app_after_nested_scope_reuses_port_forward(self):
    wda = WDAClient(self.platform)
    with self.mock_wda_server():
      with self.platform.ports.nested():
        self.assertEqual(wda.ensure_session(), "session-1")
        self.assertEqual(self.host_platform.popen.call_count, 1)

      wda.terminate_app("com.apple.mobilesafari")
      self.assertEqual(wda.base_url, "http://localhost:54321")
      self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
      self.assertEqual(self.host_platform.popen.call_count, 1)
      wda.stop()

  def test_wda_stop_stops_port_forward_in_nested_scope(self):
    wda = WDAClient(self.platform)
    with self.mock_wda_server(), self.platform.ports.nested():
      wda.start()
      self.assertTrue(self.platform.ports.is_forwarded_port_used(54321))
      wda.stop()
      self.assertFalse(self.platform.ports.is_forwarded_port_used(54321))

  def test_wda_simulator_start_forwards_without_iproxy(self):
    self.expect_startup_devices(
        devices=DEVICES_SINGLE, simulators=SIMULATORS_SAMPLE)
    platform = IOSPlatform(self.host_platform, IPHONE_SIMULATOR["udid"])
    wda = WDAClient(platform)
    with self.mock_wda_server(platform):
      wda.start()
    self.assertEqual(wda.base_url, "http://localhost:8100")
    self.assertTrue(platform.ports.is_forwarded_port_used(8100))
    self.host_platform.popen.assert_not_called()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
