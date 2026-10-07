# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import pathlib
import struct
import zipfile
from typing import TYPE_CHECKING, Any, Final
from unittest import mock

if TYPE_CHECKING:
  from collections.abc import Iterator

from pyfakefs.fake_filesystem import OSType
from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.enums import ButtonClick
from crossbench.action_runner.action.position import UiSelectorConfig
from crossbench.action_runner.display_rectangle import DisplayRectangle
from crossbench.action_runner.element_not_found_error import \
    ElementNotFoundError
from crossbench.action_runner.input_events import InputEvent, KeyEvent, \
    MouseButtonEvent, MouseMoveEvent, TouchEvent, WaitEvent
from crossbench.action_runner.virtual_device.keyboard import \
    KeyboardVirtualDeviceConfig
from crossbench.action_runner.virtual_device.mouse import \
    MouseVirtualDeviceConfig
from crossbench.action_runner.virtual_device.touchscreen import \
    TouchscreenVirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_config import \
    VirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.benchmarks.loading.point import Point
from crossbench.helper.version import VersionParseError
from crossbench.plt.android_adb import Adb, AndroidAdbPlatform, \
    AndroidDeviceInfo, AndroidVersion
from crossbench.plt.arch import MachineArch
from crossbench.plt.axml import RES_STRING_POOL_TYPE, \
    RES_XML_START_ELEMENT_TYPE, RES_XML_TYPE, \
    parse_binary_manifest_package_name
from crossbench.plt.evemu_platform_mixin import VirtualDeviceState
from crossbench.plt.port_manager import PortForwardException
from crossbench.plt.process_meminfo import ProcessMeminfo
from crossbench.plt.remote import RemotePopen
from tests import test_helper
from tests.crossbench.mock_helper import ShResult, ShResultType, \
    WinMockPlatform
from tests.crossbench.plt.helper import BasePosixMockPlatformTestCase

ADB_DEVICE_SAMPLE_OUTPUT = (
    "List of devices attached\n"
    "emulator-5556 device product:sdk_google_phone_x86_64 "
    "model:Android_SDK_built_for_x86_64 device:generic_x86_64\n")
ADB_DEVICES_SAMPLE_OUTPUT = (
    f"{ADB_DEVICE_SAMPLE_OUTPUT}"
    "emulator-5554 device product:sdk_google_phone_x86 "
    "model:Android_SDK_built_for_x86 device:generic_x86\n"
    "0a388e93      device usb:1-1 product:razor model:Nexus_7 device:flo\n")

DUMPSYS_DISPLAY_OUTPUT: Final[str] = """
  SensorObserver
    mIsProxActive=false
    mDozeStateByDisplay:
      0 -> false
BrightnessSynchronizer
  mLatestIntBrightness=43
  mLatestFloatBrightness=0.163
  mCurrentUpdate=null
"""


def load_pb(path: str):
  return (pth.LocalPath(__file__).parent / "pb" / path).read_bytes()


DUMPSYS_MEMINFO_OUTPUT = load_pb("dumpsys_meminfo.pb")
AC_POWERED_OUTPUT = load_pb("battery/ac_powered.pb")
BATTERY_POWERED_OUTPUT = load_pb("battery/battery_powered.pb")
DUMPSYS_WINDOW_DISPLAYS_OUTPUT = load_pb("display/1080p.pb")

DUMPSYS_MEMINFO_TIMEOUT_OUTPUT = b"""
*** SERVICE 'meminfo' DUMP TIMEOUT (1ms) EXPIRED ***
"""

DUMPSYS_MEMINFO_SYSTEM_OUTPUT = b"""
          0K: GL mtrack
          0K: Other mtrack

Total RAM: 7,698,860K (status normal)
 Free RAM: 1,234K (2,345K cached pss + 3,456K cached kernel + 4,567K free)
DMA-BUF:   817,715K (      152K mapped +   817,563K unmapped)
DMA-BUF Heaps:    24,844K
DMA-BUF Heaps pool:         0K
      GPU:   258,796K (  258,796K dmabuf +         0K private)
      Kernel CMA:         0K
 Used RAM: 3,528,301K (1,772,358K used pss + 1,755,943K kernel)
 Lost RAM:   362,207K
     ZRAM:   557,480K physical used for 1,723,064K in swap (11,284K total swap)
   Tuning: 192 (large 512), oom 322,560K, restore limit 107,520K (high-end-gfx)
"""

DUMPSYS_MEMINFO_SYSTEM_OUTPUT_NO_DMA_BUF = b"""
        800K: Ashmem
        324K: .ttf mmap
          0K: Cursor
          0K: Other mtrack

Total RAM: 3,486,196K (status moderate)
 Free RAM: 1,234K (2,345K cached pss + 3,456K cached kernel + 4,567K free)
      ION:   132,124K (  6,924K mapped +   125,200K unmapped +   0K pools)
      GPU:   194,788K
 Used RAM: 2,835,979K (2,170,795K used pss +   665,184K kernel)
 Lost RAM:   282,400K
     ZRAM:   203,732K physical used for 745,216K in swap (4,194,300K total swap)
   Tuning: 256 (large 512), oom 322,560K, restore limit 107,520K (high-end-gfx)
"""


class BaseAndroidAdbMockPlatformTestCase(BasePosixMockPlatformTestCase):
  DEVICE_ID = "emulator-5554"
  platform: AndroidAdbPlatform
  adb: Adb

  @override
  def setUp(self) -> None:
    self.adb_setup()
    super().setUp()

  @override
  def setup_platform(self):
    self.expect_startup_devices()
    self.adb = Adb(self.host_platform, self.DEVICE_ID)
    platform = AndroidAdbPlatform(
        self.host_platform, self.DEVICE_ID, adb=self.adb)
    self.mock_platform_str(platform, "adb.mock_platform.arm64")
    return platform

  def test_str(self):
    self.assertEqual(str(self.platform), "adb.mock_platform.arm64")

  def adb_setup(self):
    adb_patcher = mock.patch(
        "crossbench.plt.android_adb._find_adb_bin",
        return_value=pathlib.Path("adb"))
    adb_patcher.start()
    self.addCleanup(adb_patcher.stop)

  def expect_startup_devices(self, devices: str = ADB_DEVICES_SAMPLE_OUTPUT):
    if self.host_platform.is_macos:
      self.host_platform.expect_sh(
          "brew", "--prefix", result=ShResult(returncode=1))
    self.host_platform.expect_sh(pathlib.Path("adb"), "start-server")
    self.host_platform.expect_sh(
        pathlib.Path("adb"), "devices", "-l", result=devices)

  def expect_sh(self, *args, result: ShResultType = "", returncode: int = 0):
    self.expect_adb("shell", *args, result=result, returncode=returncode)

  def expect_path_check(
      self,
      flag: str,
      path: pth.AnyPathLike,
      exists: bool = True,
  ) -> None:
    self.expect_sh(
        f"'[' {flag} {self.platform.path(path)} ']'",
        returncode=0 if exists else 1,
    )

  def expect_adb(self, *args, result: ShResultType = "", returncode: int = 0):
    self.host_platform.expect_sh(
        pathlib.Path("adb"),
        "-s",
        self.DEVICE_ID,
        *args,
        result=result,
        returncode=returncode)

  def test_is_android(self):
    self.assertTrue(self.platform.is_android)

  def test_clear_memory_page_cache(self):
    self.expect_sh("getprop ro.build.version.sdk", result="37")
    self.expect_sh("sync")
    self.expect_sh("setprop perf.drop_caches 3")
    self.expect_sh("getprop perf.drop_caches", result="3")
    self.expect_sh("getprop perf.drop_caches", result="0")
    with mock.patch.object(
        self.platform, "sh", wraps=self.platform.sh) as mock_sh:
      self.platform.clear_memory_page_cache()
    mock_sh.assert_has_calls([
        mock.call("sync"),
        mock.call("setprop", "perf.drop_caches", "3"),
    ])

  def test_clear_memory_page_cache_unsupported_sdk(self):
    with mock.patch.object(
        self.adb,
        "getprop",
        return_value=str(AndroidAdbPlatform.MIN_DROP_CACHES_SDK_VERSION - 1)):
      with self.assertLogs(level="ERROR") as cm:
        with mock.patch.object(self.platform, "sh") as mock_sh:
          self.platform.clear_memory_page_cache()
          mock_sh.assert_not_called()
          self.assertIn("Cannot clear memory page cache on Android SDK",
                        cm.output[0])

  def test_name(self):
    self.assertEqual(self.platform.name, "android")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "android")

  def test_popen_kill_all_sends_remote_adb_kill(self):
    self.expect_sh(
        "mktemp /data/local/tmp/XXXXXXXXXXX", result="/data/local/tmp/pid1")
    self.expect_sh("mv /data/local/tmp/pid1 /data/local/tmp/pid1popen_pid_")
    self.expect_sh("cat /data/local/tmp/pid1popen_pid_", result="4242\n")
    self.expect_sh("'[' -e /data/local/tmp/pid1popen_pid_ ']'")
    self.expect_sh("rm /data/local/tmp/pid1popen_pid_")
    self.expect_sh("kill -9 4242")
    with (mock.patch("subprocess.Popen.__init__", return_value=None)
          as mock_popen_init,
          mock.patch("subprocess.Popen.poll", return_value=None),
          mock.patch("subprocess.Popen.send_signal") as mock_local_send_signal):
      proc = self.platform.popen("sleep", "5")
      self.assertIsInstance(proc, RemotePopen)
      self.assertEqual(proc.remote_pid, 4242)
      mock_popen_init.assert_called_once_with([
          self.adb._adb_bin,
          "-s",
          self.DEVICE_ID,
          "shell",
          "set -m; sleep 5 & PID=$!"
          " && echo $PID >/data/local/tmp/pid1popen_pid_ && wait $PID",
      ],
                                              bufsize=-1,
                                              stdout=None,
                                              stderr=None,
                                              stdin=None)
      self.assertEqual(self.platform.active_popens, (proc,))
      self.assertEqual(self.host_platform.active_popens, ())

      self.platform.kill_all_popens()
      mock_local_send_signal.assert_not_called()
      self.assertEqual(
          self.host_platform.sh_cmds[-1],
          (self.adb._adb_bin, "-s", self.DEVICE_ID, "shell", "kill -9 4242"))

  def test_is_battery_powered(self):
    self.expect_sh("dumpsys battery --proto", result=AC_POWERED_OUTPUT)
    self.assertFalse(self.platform.is_battery_powered)

    self.expect_sh("dumpsys battery --proto", result=BATTERY_POWERED_OUTPUT)
    self.assertTrue(self.platform.is_battery_powered)

  def test_display_details(self):
    self.expect_sh(
        "dumpsys window displays --proto",
        result=DUMPSYS_WINDOW_DISPLAYS_OUTPUT)
    result = self.platform.display_details()
    self.assertEqual(len(result), 1)
    self.assertDictEqual(result[0], {
        "resolution": (1920, 1080),
        "refresh_rate": -1,
    })

  def test_unique_name(self):
    platform_2 = AndroidAdbPlatform(
        self.host_platform, "SomeDeviceId", adb=self.adb)
    self.assertNotEqual(self.platform.unique_name, platform_2.unique_name)


class AndroidAdbOnWinMockPlatformTestCase(BaseAndroidAdbMockPlatformTestCase):
  __test__ = True

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.os = OSType.WINDOWS

  @override
  def setup_host_platform(self):
    return WinMockPlatform()

  def test_host_platform(self):
    self.assertTrue(self.platform.host_platform.is_win)
    self.assertIsInstance(
        self.platform.host_path("foo/bar"), pathlib.PureWindowsPath)
    self.assertNotEqual(
        str(self.platform.host_path("foo/bar")),
        str(self.platform.path("foo/bar")))

  def test_mktemp(self):
    self.assertTrue(self.platform.default_tmp_dir.is_absolute())
    self.assertIsInstance(self.platform.default_tmp_dir, pathlib.PurePosixPath)
    self.expect_sh("mktemp -d /data/local/tmp/custom_prefix.XXXXXXXXXXX")
    self.platform.mkdtemp(prefix="custom_prefix.")

  def test_mktemp_prefix_and_suffix(self):
    # suffix need special handling on android.
    self.assertTrue(self.platform.default_tmp_dir.is_absolute())
    self.assertIsInstance(self.platform.default_tmp_dir, pathlib.PurePosixPath)
    self.expect_sh(
        "mktemp -d /data/local/tmp/custom_prefix.XXXXXXXXXXX",
        result="/data/local/tmp/custom_prefix.RANDOM")
    self.expect_sh("mv /data/local/tmp/custom_prefix.RANDOM "
                   "/data/local/tmp/custom_prefix.RANDOM.custom_suffix")
    self.platform.mkdtemp(".custom_suffix", "custom_prefix.")

  def test_mktemp_suffix(self):
    # suffix need special handling on android.
    self.assertTrue(self.platform.default_tmp_dir.is_absolute())
    self.assertIsInstance(self.platform.default_tmp_dir, pathlib.PurePosixPath)
    self.expect_sh(
        "mktemp -d /data/local/tmp/XXXXXXXXXXX",
        result="/data/local/tmp/RANDOM")
    self.expect_sh(
        "mv /data/local/tmp/RANDOM /data/local/tmp/RANDOM.custom_suffix")
    self.platform.mkdtemp(".custom_suffix")

  def test_push(self):
    local_path = self.host_platform.path("C:/foo/push.local.data")
    remote_path = self.platform.default_tmp_dir / "push.remote.data"
    self.assertIsInstance(local_path, pathlib.PureWindowsPath)
    self.fs.create_file(local_path, contents="some data")
    self.expect_adb("push", "C:\\foo\\push.local.data",
                    "/data/local/tmp/push.remote.data")
    self.platform.push(local_path, remote_path)

  def test_push_remote_win_path(self):
    local_path = self.host_platform.path("C:/foo/push.local.data")
    remote_path = self.platform.path("custom/push.remote.data")
    self.assertIsInstance(local_path, pathlib.PureWindowsPath)
    self.fs.create_file(local_path, contents="some data")
    self.expect_adb("push", "C:\\foo\\push.local.data",
                    "custom/push.remote.data")
    self.platform.push(local_path, remote_path)


class AndroidAdbMockPlatformTest(BaseAndroidAdbMockPlatformTestCase):
  __test__ = True

  def test_create_no_devices(self):
    self.expect_startup_devices("List of devices attached")
    with self.assertRaises(ValueError):
      Adb(self.host_platform, self.DEVICE_ID)

  def test_create_default_too_many_devices(self):
    self.expect_startup_devices()
    with self.assertRaisesRegex(ValueError, r"(?i)too many"):
      Adb(self.host_platform)

  def test_create_default_one_device(self):
    self.expect_startup_devices(ADB_DEVICE_SAMPLE_OUTPUT)
    adb = Adb(self.host_platform)
    self.assertEqual(adb.serial_id, "emulator-5556")

  def test_create_default_one_device_invalid(self):
    self.expect_startup_devices(ADB_DEVICE_SAMPLE_OUTPUT)
    with self.assertRaisesRegex(ValueError, r"(?i)invalid device identifier"):
      Adb(self.host_platform, "")

  def test_create_by_name(self):
    self.expect_startup_devices(ADB_DEVICES_SAMPLE_OUTPUT)
    adb = Adb(self.host_platform, "Nexus_7")
    self.assertEqual(adb.serial_id, "0a388e93")
    self.expect_startup_devices(ADB_DEVICES_SAMPLE_OUTPUT)
    adb = Adb(self.host_platform, "Nexus 7")
    self.assertEqual(adb.serial_id, "0a388e93")

  def test_create_by_name_duplicate(self):
    self.expect_startup_devices(ADB_DEVICES_SAMPLE_OUTPUT)
    with self.assertRaisesRegex(ValueError, "devices"):
      Adb(self.host_platform, "Android_SDK_built_for_x86")

  def test_basic_properties(self):
    self.assertTrue(self.platform.is_remote)
    self.assertEqual(self.platform.name, "android")
    self.assertIs(self.platform.host_platform, self.host_platform)
    self.assertEqual(self.platform.default_tmp_dir,
                     pathlib.PurePosixPath("/data/local/tmp/"))

  def test_adb_basic_properties(self):
    self.assertEqual(self.adb.serial_id, self.DEVICE_ID)
    self.assertEqual(
        self.adb.device_info,
        AndroidDeviceInfo(
            device_id=self.DEVICE_ID,
            name="generic_x86",
            model="Android_SDK_built_for_x86",
            product="sdk_google_phone_x86"))
    self.assertIn(self.DEVICE_ID, str(self.adb))

  def test_get_evemu_device_cmd(self):
    self.assertEqual(
        self.platform._get_evemu_device_cmd(VirtualDeviceType.KEYBOARD),
        ("uinput", "-"))

  @contextlib.contextmanager
  def patch_getprop(
      self,
      return_value: Any = AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION - 1,
  ) -> Iterator[mock.MagicMock]:
    with mock.patch.object(
        self.adb, "getprop", return_value=str(return_value)) as mock_getprop:
      yield mock_getprop

  def test_sdk_version(self) -> None:
    with self.patch_getprop(37):
      self.assertEqual(self.adb.sdk_version, 37)

  @contextlib.contextmanager
  def _patch_uinput_setup(
      self,
      sdk_version: int = AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION,
  ) -> Iterator[tuple[mock.MagicMock, mock.MagicMock]]:
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = mock.MagicMock()
    with self.patch_getprop(sdk_version):
      with mock.patch.object(
          self.platform, "popen", return_value=mock_proc) as mock_popen:
        yield mock_popen, mock_proc

  def test_setup_virtual_devices(self) -> None:
    with self._patch_uinput_setup() as (mock_popen, mock_proc):
      self.platform.setup_virtual_devices(
          (KeyboardVirtualDeviceConfig(name="kb1"),))
      mock_popen.assert_called_once_with("uinput", "-", stdin=mock.ANY)
      self.assertIn("kb1", self.platform._virtual_devices)
      self.assertIs(self.platform._virtual_devices["kb1"].proc, mock_proc)
      mock_proc.stdin.write.assert_called_once()
      mock_proc.stdin.flush.assert_called_once()

  def test_setup_virtual_devices_unsupported_sdk(self) -> None:
    sdk_version = AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION - 1
    with self._patch_uinput_setup(sdk_version=sdk_version) as (mock_popen, _):
      with self.assertLogs(level="WARNING") as cm:
        self.platform.setup_virtual_devices(
            (KeyboardVirtualDeviceConfig(name="kb1"),))
        mock_popen.assert_not_called()
        self.assertNotIn("kb1", self.platform._virtual_devices)
        self.assertIn("uinput injection is only supported on Android SDK",
                      cm.output[0])

  def test_setup_virtual_devices_touchscreen(self) -> None:
    with self._patch_uinput_setup() as (mock_popen, mock_proc):
      self.platform.setup_virtual_devices((TouchscreenVirtualDeviceConfig(
          name="touch1", width=1080, height=2400),))
      mock_popen.assert_called_once_with("uinput", "-", stdin=mock.ANY)
      self.assertIn("touch1", self.platform._virtual_devices)
      self.assertIs(self.platform._virtual_devices["touch1"].proc, mock_proc)
      mock_proc.stdin.write.assert_called_once()
      written_header = mock_proc.stdin.write.call_args[0][0].decode("utf-8")
      self.assertIn("N: touch1", written_header)
      self.assertIn("A: 35 0 1080 0 0 12", written_header)
      self.assertIn("A: 36 0 2400 0 0 12", written_header)
      mock_proc.stdin.flush.assert_called_once()

  def test_setup_virtual_devices_touchscreen_fallback_resolution(self) -> None:
    with self._patch_uinput_setup() as (mock_popen, mock_proc):
      with mock.patch.object(
          self.platform, "display_resolution",
          return_value=(1440, 3120)) as mock_res:
        self.platform.setup_virtual_devices(
            (TouchscreenVirtualDeviceConfig(name="touch1"),))
        mock_res.assert_called_once()
        mock_popen.assert_called_once_with("uinput", "-", stdin=mock.ANY)
        self.assertIn("touch1", self.platform._virtual_devices)
        written_header = mock_proc.stdin.write.call_args[0][0].decode("utf-8")
        self.assertIn("N: touch1", written_header)
        self.assertIn("A: 35 0 1440 0 0 12", written_header)
        self.assertIn("A: 36 0 3120 0 0 12", written_header)

  def test_setup_virtual_devices_mouse(self) -> None:
    with self._patch_uinput_setup() as (mock_popen, mock_proc):
      self.platform.setup_virtual_devices(
          (MouseVirtualDeviceConfig(name="mouse1", width=1920, height=1080),))
      mock_popen.assert_called_once_with("uinput", "-", stdin=mock.ANY)
      self.assertIn("mouse1", self.platform._virtual_devices)
      self.assertIs(self.platform._virtual_devices["mouse1"].proc, mock_proc)
      mock_proc.stdin.write.assert_called_once()
      written_header = mock_proc.stdin.write.call_args[0][0].decode("utf-8")
      self.assertIn("N: mouse1", written_header)
      self.assertIn("A: 35 0 1920 0 0 0", written_header)
      self.assertIn("A: 36 0 1080 0 0 0", written_header)
      mock_proc.stdin.flush.assert_called_once()

  def test_setup_virtual_devices_mouse_fallback_resolution(self) -> None:
    with self._patch_uinput_setup() as (mock_popen, mock_proc):
      with mock.patch.object(
          self.platform, "display_resolution",
          return_value=(1440, 3120)) as mock_res:
        self.platform.setup_virtual_devices(
            (MouseVirtualDeviceConfig(name="mouse1"),))
        mock_res.assert_called_once()
        mock_popen.assert_called_once_with("uinput", "-", stdin=mock.ANY)
        self.assertIn("mouse1", self.platform._virtual_devices)
        written_header = mock_proc.stdin.write.call_args[0][0].decode("utf-8")
        self.assertIn("N: mouse1", written_header)
        self.assertIn("A: 35 0 1440 0 0 0", written_header)
        self.assertIn("A: 36 0 3120 0 0 0", written_header)

  def test_setup_virtual_devices_unsupported(self) -> None:
    unsupported_config = mock.MagicMock(spec=VirtualDeviceConfig)
    unsupported_config.device_type = "unsupported_device_type"
    unsupported_config.name = "touch1"

    with self.patch_getprop(AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION):
      with self.assertRaisesRegex(ValueError,
                                  "Unsupported virtual device type"):
        self.platform.setup_virtual_devices((unsupported_config,))

  def test_execute_evemu_script(self) -> None:
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = mock.MagicMock()
    self.platform._virtual_devices["kb1"] = VirtualDeviceState(mock_proc)

    with self.patch_getprop(AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION):
      self.platform._execute_evemu_script("kb1", "E: 0.000000 0001 001e 0001\n")
      mock_proc.stdin.write.assert_called_once_with(
          b"E: 0.000000 0001 001e 0001\n")
      mock_proc.stdin.flush.assert_called_once()

  def test_execute_evemu_script_uninitialized(self) -> None:
    with self.patch_getprop(AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION):
      with self.assertRaisesRegex(
          RuntimeError, "Virtual device 'unknown' was not initialized"):
        self.platform._execute_evemu_script("unknown", "E: ...")

  def test_execute_evemu_script_unsupported_sdk(self) -> None:
    with self.patch_getprop():
      with self.assertRaisesRegex(
          NotImplementedError,
          f"Virtual device uinput injection is only supported on Android SDK "
          f"{AndroidAdbPlatform.MIN_UINPUT_SDK_VERSION}+"):
        self.platform._execute_evemu_script("kb1", "E: ...")

  def test_inject_input_events_legacy_sdk_touch_tap(self) -> None:
    self.expect_sh("input tap 100 200")
    events = (
        TouchEvent(Point(100, 200), is_down=True),
        WaitEvent(dt.timedelta(milliseconds=50)),
        TouchEvent(Point(100, 200), is_down=False),
    )
    with self.patch_getprop():
      self.platform.inject_input_events("default_touchscreen", events)

  def test_inject_input_events_legacy_sdk_touch_long_press_raises(self) -> None:
    events = (
        TouchEvent(Point(100, 200), is_down=True),
        WaitEvent(dt.timedelta(milliseconds=500)),
        TouchEvent(Point(100, 200), is_down=False),
    )
    with self.patch_getprop():
      with self.assertRaisesRegex(
          NotImplementedError,
          "Non-zero click duration \\(long-press\\) is not supported"):
        self.platform.inject_input_events("default_touchscreen", events)

  def test_inject_input_events_legacy_sdk_touch_swipe(self) -> None:
    self.expect_sh("input swipe 100 200 300 400 500")
    events = (
        TouchEvent(Point(100, 200), is_down=True),
        WaitEvent(dt.timedelta(milliseconds=250)),
        TouchEvent(Point(200, 300), is_down=True),
        WaitEvent(dt.timedelta(milliseconds=250)),
        TouchEvent(Point(300, 400), is_down=True),
        TouchEvent(Point(300, 400), is_down=False),
    )
    with self.patch_getprop():
      self.platform.inject_input_events("default_touchscreen", events)

  def test_inject_input_events_legacy_sdk_mouse_raises(self) -> None:
    with self.patch_getprop():
      with self.assertRaisesRegex(NotImplementedError,
                                  "Mouse input injection is not supported"):
        self.platform.inject_input_events("default_mouse",
                                          (MouseMoveEvent(Point(10, 20)),))
      with self.assertRaisesRegex(NotImplementedError,
                                  "Mouse input injection is not supported"):
        self.platform.inject_input_events(
            "default_mouse",
            (MouseButtonEvent(ButtonClick.LEFT, is_down=True),))

  def test_inject_input_events_legacy_sdk_keyboard_text(self) -> None:
    self.expect_sh("input keyboard text Hi%s1")
    events = (
        KeyEvent("ShiftLeft", is_down=True),
        KeyEvent("KeyH", is_down=True),
        KeyEvent("KeyH", is_down=False),
        KeyEvent("ShiftLeft", is_down=False),
        KeyEvent("KeyI", is_down=True),
        KeyEvent("KeyI", is_down=False),
        KeyEvent("Space", is_down=True),
        KeyEvent("Space", is_down=False),
        KeyEvent("Digit1", is_down=True),
        KeyEvent("Digit1", is_down=False),
    )
    with self.patch_getprop():
      self.platform.inject_input_events("default_keyboard", events)

  def test_inject_input_events_legacy_sdk_keyboard_text_flushes_on_keyevent(
      self) -> None:
    self.expect_sh("input keyboard text hi")
    self.expect_sh("input keyevent KEYCODE_ENTER")
    self.expect_sh("input keyboard text ok")
    events = (
        KeyEvent("KeyH", is_down=True),
        KeyEvent("KeyH", is_down=False),
        KeyEvent("KeyI", is_down=True),
        KeyEvent("KeyI", is_down=False),
        KeyEvent("Enter", is_down=True),
        KeyEvent("Enter", is_down=False),
        KeyEvent("KeyO", is_down=True),
        KeyEvent("KeyO", is_down=False),
        KeyEvent("KeyK", is_down=True),
        KeyEvent("KeyK", is_down=False),
    )
    with self.patch_getprop():
      self.platform.inject_input_events("default_keyboard", events)

  def test_inject_input_events_legacy_sdk_keyboard_text_timed(self) -> None:
    self.expect_sh("input keyboard text a")
    self.expect_sh("input keyboard text %s")
    events = (
        KeyEvent("KeyA", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=200)),
        KeyEvent("KeyA", is_down=False),
        WaitEvent(dt.timedelta(milliseconds=300)),
        KeyEvent("Space", is_down=True),
        WaitEvent(dt.timedelta(milliseconds=200)),
        KeyEvent("Space", is_down=False),
        WaitEvent(dt.timedelta(milliseconds=300)),
    )
    with self.patch_getprop():
      with mock.patch.object(self.platform, "sleep") as mock_sleep:
        self.platform.inject_input_events("default_keyboard", events)
        self.assertEqual(mock_sleep.call_count, 2)

  def test_inject_input_events_legacy_sdk_keyevent(self) -> None:
    self.expect_sh("input keyevent KEYCODE_ENTER")
    self.expect_sh("input keyevent KEYCODE_BACK")
    events = (
        KeyEvent("Enter", is_down=True),
        KeyEvent("Enter", is_down=False),
        KeyEvent("KEYCODE_BACK", is_down=True),
        KeyEvent("KEYCODE_BACK", is_down=False),
    )
    with self.patch_getprop():
      self.platform.inject_input_events("default_keyboard", events)

  def test_inject_input_events_legacy_sdk_unsupported_event(self) -> None:
    with self.patch_getprop():
      with self.assertRaisesRegex(ValueError, "Unsupported InputEvent type"):
        self.platform.inject_input_events("default_keyboard", (InputEvent(),))

  def test_has_root(self):
    self.expect_sh("id", result="uid=2000(shell) gid=2000(shell)")
    self.assertFalse(self.adb.has_root())
    self.expect_sh("id", result="uid=0(root)n gid=0(root)")
    self.assertTrue(self.adb.has_root())

  def test_version(self):
    version_str = "13 (Tiramisu)"
    self.expect_sh("getprop ro.build.description", result=version_str)
    version = self.platform.version
    self.assertSequenceEqual(version.parts, (13,))
    self.assertEqual(version.version_str, version_str)
    self.assertIs(version, self.platform.version)

  def test_version_long(self):
    version_str = "oriole-user 13 TQ3A.230805.001 10452339 release-keys"
    self.expect_sh("getprop ro.build.description", result=version_str)
    version = self.platform.version
    self.assertSequenceEqual(version.parts, (13,))
    self.assertEqual(version.version_str, version_str)
    self.assertIs(version, self.platform.version)

  def test_device(self):
    self.expect_sh("getprop ro.product.model", result="Pixel 999")
    self.assertEqual(self.platform.model, "Pixel 999")
    # Subsequent calls are cached.
    self.assertEqual(self.platform.model, "Pixel 999")

  def test_cpu(self):
    self.expect_sh("getprop dalvik.vm.isa.arm.variant", result="cortex-a999")
    self.expect_sh("getprop ro.board.platform", result="msmnile")
    cpu_info = "processor       : 0\nprocessor       : 1"
    self.expect_sh(
        "grep -E 'processor|core id|physical id' /proc/cpuinfo",
        result=cpu_info)
    self.assertEqual(self.platform.cpu, "cortex-a999 msmnile 2 cores")
    # Subsequent calls are cached.
    self.assertEqual(self.platform.cpu, "cortex-a999 msmnile 2 cores")

  def test_cpu_detailed(self):
    self.expect_sh("getprop dalvik.vm.isa.arm.variant", result="cortex-a999")
    self.expect_sh("getprop ro.board.platform", result="msmnile")
    cpu_info = "processor       : 0\nprocessor       : 1"
    self.expect_sh(
        "grep -E 'processor|core id|physical id' /proc/cpuinfo",
        result=cpu_info)
    self.assertEqual(self.platform.cpu, "cortex-a999 msmnile 2 cores")
    # Subsequent calls are cached.
    self.assertEqual(self.platform.cpu, "cortex-a999 msmnile 2 cores")

  def test_adb(self):
    self.assertIs(self.platform.adb, self.adb)

  def test_device_config(self):
    self.expect_sh(
        "cmd device_config list",
        result="accessibility/font_scale=1.0\ntop_level=true")
    self.expect_sh(
        "getprop",
        result="[ro.product.model]: [Pixel 10]\n[ro.build.version.sdk]: [34]")
    self.expect_sh(
        "settings list global",
        result="stay_on_while_plugged_in=3\nanimator_duration_scale=0.0")
    self.expect_sh(
        "settings list secure",
        result="immersive_mode_confirmations=confirmed\nlong_press_timeout=400")
    self.expect_sh(
        "settings list system",
        result="screen_brightness=100\nscreen_off_timeout=60000")
    self.assertEqual(
        self.platform.device_config(), {
            "android": {
                "device_config": {
                    "accessibility/font_scale": "1.0",
                    "top_level": "true",
                },
                "getprop": {
                    "ro.product.model": "Pixel 10",
                    "ro.build.version.sdk": "34",
                },
                "settings": {
                    "global": {
                        "stay_on_while_plugged_in": "3",
                        "animator_duration_scale": "0.0",
                    },
                    "secure": {
                        "immersive_mode_confirmations": "confirmed",
                        "long_press_timeout": "400",
                    },
                    "system": {
                        "screen_brightness": "100",
                        "screen_off_timeout": "60000",
                    },
                },
            },
        })

  def test_is_installed(self):
    package_name = "com.example.app"
    self.expect_sh(
        f"pm path {package_name}",
        result=f"package:/data/app/{package_name}-1/base.apk\n")
    self.assertTrue(self.adb.is_installed(package_name))

  def test_is_installed_false(self):
    package_name = "com.example.non_existent"
    # pm path returns returncode 1 if not found.
    self.expect_sh(
        f"pm path {package_name}", result=ShResult(returncode=1, result=""))
    self.assertFalse(self.adb.is_installed(package_name))

  def test_machine_unknown(self):
    self.expect_sh("getprop ro.product.cpu.abi", result="arm37-XXX")
    with self.assertRaises(ValueError) as cm:
      self.assertEqual(self.platform.machine, MachineArch.ARM_64)
    self.assertIn("arm37-XXX", str(cm.exception))

  def test_home_and_tilde_lookups_raise_runtime_error(self):
    test_binary_home = "~/crossbench-non-existing-test-binary"

    with self.assertRaisesRegex(RuntimeError, "home dir"):
      self.platform.home()

    with self.assertRaisesRegex(RuntimeError, "home dir"):
      self.platform.expanduser(test_binary_home)

    with self.assertRaisesRegex(RuntimeError, "home dir"):
      self.platform.which(test_binary_home)

    self.assertIsNone(self.platform.lookup_binary_override(test_binary_home))

  def test_machine_arm64(self):
    self.expect_sh("getprop ro.product.cpu.abi", result="arm64-v8a")
    self.assertEqual(self.platform.machine, MachineArch.ARM_64)
    # Subsequent calls are cached.
    self.assertEqual(self.platform.machine, MachineArch.ARM_64)

  def test_machine_arm32(self):
    self.expect_sh("getprop ro.product.cpu.abi", result="armeabi-v7a")
    self.assertEqual(self.platform.machine, MachineArch.ARM_32)
    # Subsequent calls are cached.
    self.assertEqual(self.platform.machine, MachineArch.ARM_32)

  def test_app_path_to_package_invalid_path(self):
    path = pathlib.Path("path/to/app.bin")
    with self.assertRaises(ValueError) as cm:
      self.platform.app_path_to_package(path)
    self.assertIn(str(self.platform.path(path)), str(cm.exception))

  def test_app_path_to_package_not_installed(self):
    with self.assertRaises(ValueError) as cm:
      self.expect_sh(
          "cmd package list packages",
          result=("package:com.google.android.wifi.resources\n"
                  "package:com.google.android.GoogleCamera"))
      self.platform.app_path_to_package(pathlib.Path("com.custom.app"))
    self.assertIn("com.custom.app", str(cm.exception))
    self.assertIn("not installed", str(cm.exception))

  def test_app_path_to_package(self):
    path = pathlib.Path("com.custom.app")
    self.expect_sh(
        "cmd package list packages",
        result=("package:com.google.android.wifi.resources\n"
                "package:com.custom.app"))
    self.assertEqual(self.platform.app_path_to_package(path), "com.custom.app")

  def test_app_path_to_package_apk(self):
    path = self.create_file("test.apk")
    aapt_bin = pathlib.Path("/usr/bin/aapt")
    self.create_file(aapt_bin)
    self.host_platform.expect_sh(
        aapt_bin,
        "dump",
        "badging",
        path,
        result=("package: name='com.example.app' "
                "versionCode='1' versionName='1.0'"))
    with mock.patch(
        "crossbench.plt.android_adb.Binaries.AAPT.search",
        return_value=aapt_bin):
      self.assertEqual(
          self.platform.app_path_to_package(path), "com.example.app")

  def test_app_path_to_package_apk_fallback(self):
    # No aapt binary
    path = self.host_platform.path("test.apk")
    apk_data = io.BytesIO()
    with zipfile.ZipFile(apk_data, "w") as apk_zip:
      apk_zip.writestr("AndroidManifest.xml",
                       self._create_axml("com.example.app"))
    self.create_file(path, contents=apk_data.getvalue())

    self.assertEqual(self.platform.app_path_to_package(path), "com.example.app")

  def test_app_path_to_package_apks_fallback(self):
    # No aapt binary
    path = self.host_platform.path("test.apks")

    # Create a base.apk
    base_apk_buffer = io.BytesIO()
    with zipfile.ZipFile(base_apk_buffer, "w") as base_apk_zip:
      base_apk_zip.writestr("AndroidManifest.xml",
                            self._create_axml("com.example.apks"))
    base_apk_data = base_apk_buffer.getvalue()

    # Create the .apks bundle
    apks_buffer = io.BytesIO()
    with zipfile.ZipFile(apks_buffer, "w") as apks_zip:
      apks_zip.writestr("base.apk", base_apk_data)
    apks_data = apks_buffer.getvalue()

    self.create_file(path, contents=apks_data)

    self.assertEqual(
        self.platform.app_path_to_package(path), "com.example.apks")

  def test_app_path_to_package_apk_aapt_error(self):
    path = self.create_file("test.apk")
    aapt_bin = pathlib.Path("/usr/bin/aapt")
    self.create_file(aapt_bin)
    self.host_platform.expect_sh(
        aapt_bin, "dump", "badging", path, result="some other output")
    with mock.patch(
        "crossbench.plt.android_adb.Binaries.AAPT.search",
        return_value=aapt_bin):
      with self.assertRaisesRegex(ValueError,
                                  "Could not find package name in aapt output"):
        self.platform.app_path_to_package(path)

  def test_app_path_to_package_apk_all_fail(self):
    # No aapt binary
    path = self.host_platform.path("test.apk")
    apk_buffer = io.BytesIO()
    with zipfile.ZipFile(apk_buffer, "w") as apk_zip:
      apk_zip.writestr("AndroidManifest.xml", b"no package name here")
    self.create_file(path, contents=apk_buffer.getvalue())

    with self.assertRaisesRegex(ValueError,
                                "Invalid Android Binary XML header"):
      self.platform.app_path_to_package(path)

  def test_app_path_to_package_apk_all_fail_invalid_pool(self):
    # Valid header, but wrong chunk type for String Pool
    path = self.host_platform.path("test.apk")
    # AXML header (8 bytes) + chunk header (8 bytes)
    # chunk: type=0xFFFF (invalid), header_size=8, chunk_size=8
    invalid_axml = struct.pack("<HHL HH L", RES_XML_TYPE, 0x0008, 16, 0xFFFF, 8,
                               8)
    apk_buffer = io.BytesIO()
    with zipfile.ZipFile(apk_buffer, "w") as apk_zip:
      apk_zip.writestr("AndroidManifest.xml", invalid_axml)
    self.create_file(path, contents=apk_buffer.getvalue())

    with self.assertRaisesRegex(ValueError, "Expected String Pool chunk"):
      self.platform.app_path_to_package(path)

  def test_app_version(self):
    path = pathlib.Path("com.custom.app")
    self.expect_sh("cmd package list packages", result="package:com.custom.app")
    self.expect_sh("dumpsys package com.custom.app", result="versionName=9.999")
    self.assertEqual(self.platform.app_version(path), "9.999")

  def test_app_version_unknown(self):
    path = pathlib.Path("com.custom.app")
    self.expect_sh("cmd package list packages", result="package:com.custom.app")
    self.expect_sh("dumpsys package com.custom.app", result="something")
    with self.assertRaises(ValueError) as cm:
      self.platform.app_version(path)
    self.assertIn("something", str(cm.exception))
    self.assertIn("com.custom.app", str(cm.exception))

  def test_get_relative_cpu_speed(self):
    self.assertGreater(self.platform.get_relative_cpu_speed(), 0)

  def test_check_autobrightness(self):
    self.assertTrue(self.platform.check_autobrightness())

  def get_main_display_brightness(self):
    display_info = ("BrightnessSynchronizer\n"
                    "mLatestFloatBrightness=0.5\n"
                    "mLatestIntBrightness=128\n"
                    "mPendingUpdate=null")
    self.expect_sh("dumpsys", "display", result=display_info)
    self.assertEqual(self.platform.get_main_display_brightness(), 50)
    # Values are not cached
    display_info = ("BrightnessSynchronizer\n"
                    "mLatestFloatBrightness=1.0\n"
                    "mLatestIntBrightness=255\n"
                    "mPendingUpdate=null")
    self.expect_sh("dumpsys", "display", result=display_info)
    self.assertEqual(self.platform.get_main_display_brightness(), 100)

  def test_which_empty_path(self):
    with self.assertRaises(ValueError):
      self.platform.which("")
    with self.assertRaises(ValueError):
      self.platform.which(pathlib.Path())

  def test_search_binary_empty_path(self):
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary(pathlib.Path())
    self.assertIn("empty path", str(cm.exception))
    with self.assertRaises(ValueError) as cm:
      self.platform.search_binary("")
    self.assertIn("empty path", str(cm.exception))

  def test_search_binary(self):
    ls_path = self.platform.path("/system/bin/ls")
    self.expect_sh("which ls", result=str(ls_path))
    self.expect_path_check("-e", ls_path)
    path = self.platform.search_binary("ls")
    self.assertEqual(str(path), str(ls_path))

  def test_binary_lookup_override(self):
    # Overriding the default test for android.
    ls_path = self.platform.path("ls")
    override_path = self.platform.path("/root/sbin/ls")
    # override_binary checks if the result binary exists.
    self.expect_sh(f"which {override_path}", result=str(override_path))
    self.expect_path_check("-e", override_path)
    with self.platform.override_binary(ls_path, override_path):
      path = self.platform.search_binary("ls")
      self.assertEqual(path, override_path)

  def test_search_binary_app_package_non(self):
    self.expect_sh("which com.google.chrome", result="")
    self.expect_sh("cmd package list packages", result="")
    path = self.platform.search_binary("com.google.chrome")
    self.assertIsNone(path)

    self.expect_sh("which com.google.chrome", result="")
    self.expect_sh(
        "cmd package list packages", result="package:com.google.chrome")
    path = self.platform.search_binary("com.google.chrome")
    self.assertEqual(path, pathlib.PurePosixPath("com.google.chrome"))

  def test_search_binary_app_package_lookup_override(self):
    chrome_package = self.platform.path("com.google.chrome")
    chrome_dev_package = self.platform.path("com.chrome.dev")
    self.expect_sh(f"which {chrome_dev_package}", result="")
    self.expect_sh("cmd package list packages", result="package:com.chrome.dev")
    with self.platform.override_binary(chrome_package, chrome_dev_package):
      path = self.platform.search_binary(chrome_package)
      self.assertEqual(chrome_dev_package, path)

  def test_override_binary_non_existing_package(self):
    chrome_package = self.platform.path("com.google.chrome")
    chrome_dev_package = self.platform.path("com.chrome.dev")
    self.expect_sh(f"which {chrome_dev_package}", result="")
    self.expect_sh("cmd package list packages", result="")
    with self.assertRaises(ValueError) as cm:
      with self.platform.override_binary(chrome_package, chrome_dev_package):
        pass
    self.assertIn(str(chrome_package), str(cm.exception))
    self.assertIn(str(chrome_dev_package), str(cm.exception))

  def test_home(self):
    # not implemented yet
    with self.assertRaises(RuntimeError):
      self.platform.home()

  def test_get_main_display_brightness(self):
    self.expect_sh("dumpsys display", result=DUMPSYS_DISPLAY_OUTPUT)
    brightness = self.platform.get_main_display_brightness()
    self.assertEqual(brightness, 16)

  def test_iterdir(self):
    self.expect_path_check("-d", "parent_dir/child_dir")
    self.expect_sh("ls -1 parent_dir/child_dir", result="file1\nfile2\n")

    self.assertSetEqual(
        set(self.platform.iterdir(pth.AnyWindowsPath("parent_dir\\child_dir"))),
        {
            pth.AnyPosixPath("parent_dir/child_dir/file1"),
            pth.AnyPosixPath("parent_dir/child_dir/file2"),
        })

  def test_cat_file(self):
    self.expect_sh("cat path/to/a/file")
    self.platform.cat(self.platform.path("path/to/a/file"))
    self.expect_sh("cat 'path/with a space/to/a/file'")
    self.platform.cat(self.platform.path("path/with a space/to/a/file"))

  def test_sh_input(self):
    self.expect_sh("cat", result="hello world")
    hello_world = self.platform.sh_stdout("cat", input=b"hello world")
    self.assertEqual(hello_world, "hello world")

    self.expect_sh("cat", result=b"hello world bytes")
    hello_world_bytes = self.platform.sh_stdout_bytes(
        "cat", input=b"hello world bytes")
    self.assertEqual(hello_world_bytes, b"hello world bytes")

  def test_sh_shell_invalid(self):
    with self.assertRaisesRegex(ValueError, "shell=True"):
      self.platform.sh_stdout("ls", "folder with space", shell=True)

  def test_sh_shell(self):
    self.expect_sh("ls sdcard", result="FILE1\nFILE2\n")
    self.assertEqual(self.platform.sh_stdout("ls", "sdcard"), "FILE1\nFILE2\n")

    self.expect_sh("ls 'folder with space'", result="FOLDER\n")
    self.assertEqual(
        self.platform.sh_stdout("ls", "folder with space"), "FOLDER\n")

    self.expect_sh("'ls foo && ls bar'", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls foo && ls bar"), "FILE1\nFILE2\n")

    self.expect_sh("ls foo && ls bar", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls foo && ls bar", shell=True),
        "FILE1\nFILE2\n")

    self.expect_sh("ls foo '&&' ls bar", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls", "foo", "&&", "ls", "bar"),
        "FILE1\nFILE2\n")

  def test_port_forward_default(self):
    # Closing the default port-manager happens in the atexit handler.
    self.expect_adb("forward", "tcp:0", "tcp:33221", result="666")
    self.platform.ports.forward(0, 33221)
    self.expect_adb("forward", "--remove", "tcp:666")
    self.platform.ports.stop_forward(666)

  def test_port_forward(self):
    self.expect_adb("forward", "tcp:0", "tcp:33221", result="666")
    self.expect_adb("forward", "--remove", "tcp:666")
    with self.platform.ports.nested() as ports:
      port = ports.forward(0, 33221)
      self.assertEqual(port, 666)
      # Cannot forward the same ports in a nested scope.
      with self.platform.ports.nested() as ports_2:
        with self.assertRaises(PortForwardException):
          ports_2.forward(666, 33221)
      ports.stop_forward(port)
      with self.assertRaises(PortForwardException):
        ports.stop_forward(port)

  def test_port_forward_auto_close(self):
    self.expect_adb("forward", "tcp:0", "tcp:33221", result="666")
    self.expect_adb("forward", "--remove", "tcp:666")
    with self.platform.ports.nested() as ports:
      port = ports.forward(0, 33221)
      self.assertEqual(port, 666)

  def test_reverse_port_forward_default(self):
    self.expect_adb("reverse", "tcp:0", "tcp:33221", result="666")
    self.platform.ports.reverse_forward(0, 33221)
    self.expect_adb("reverse", "--remove", "tcp:666")
    self.platform.ports.stop_reverse_forward(666)

  def test_reverse_port_forward(self):
    with self.platform.ports.nested() as ports:
      self.expect_adb("reverse", "tcp:0", "tcp:33221", result="666")
      self.expect_adb("reverse", "--remove", "tcp:666")
      port = ports.reverse_forward(0, 33221)
      self.assertEqual(port, 666)
      # Cannot forward the same ports in a nested scope.
      with self.platform.ports.nested() as ports_2:
        with self.assertRaises(PortForwardException):
          ports_2.reverse_forward(666, 33221)
      ports.stop_reverse_forward(port)
      with self.assertRaises(PortForwardException):
        ports.stop_reverse_forward(port)

  def test_reverse_port_forward_nested_auto_close(self):
    self.expect_adb("reverse", "tcp:0", "tcp:33300", result="333")
    self.expect_adb("reverse", "tcp:0", "tcp:33221", result="666")
    self.expect_adb("reverse", "--remove", "tcp:666")
    self.expect_adb("reverse", "--remove", "tcp:333")
    with self.platform.ports.nested() as ports_1:
      port = ports_1.reverse_forward(0, 33300)
      self.assertEqual(port, 333)
      with self.platform.ports.nested() as ports_2:
        port = ports_2.reverse_forward(0, 33221)
        self.assertEqual(port, 666)

  def test_reverse_port_forward_auto_close(self):
    self.expect_adb("reverse", "tcp:0", "tcp:33221", result="666")
    self.expect_adb("reverse", "--remove", "tcp:666")
    with self.platform.ports.nested() as ports:
      port = ports.reverse_forward(0, 33221)
      self.assertEqual(port, 666)

  def test_port_forward_invalid_adb(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(argparse.ArgumentTypeError, "remote_port"):
        ports.forward(1111, 0)

  def test_reverse_port_forward_invalid_adb(self):
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(argparse.ArgumentTypeError, "local_port"):
        ports.reverse_forward(1111, 0)

  def test_display_resolution(self):
    self.expect_sh(
        "dumpsys window displays --proto",
        result=DUMPSYS_WINDOW_DISPLAYS_OUTPUT)
    [horizontal, vertical] = self.platform.display_resolution()
    self.assertEqual(horizontal, 1920)
    self.assertEqual(vertical, 1080)

  def test_get_window_rect(self):
    dumpsys_output = ("Window #0 Window{1a2b3c4 u0 com.android.chrome/Main}:\n"
                      "  mAppBounds=Rect(0, 0 - 1080, 2400)\n")
    self.expect_sh("dumpsys window windows", result=dumpsys_output)
    rect = self.platform.get_window_rect("com.android.chrome")
    self.assertEqual(rect, DisplayRectangle(Point(0, 0), 1080, 2400))

  def test_get_window_rect_with_insets(self):
    dumpsys_output = (
        "Window #0 Window{1a2b3c4 u0 com.android.chrome/Main}:\n"
        "  mAppBounds=Rect(0, 0 - 1080, 1920)\n"
        "  InsetsFrameProvider: {type=statusBars,"
        " insetsSize=Insets{left=0, top=72, right=0, bottom=0}}\n"
        "  InsetsFrameProvider: {type=navigationBars,"
        " insetsSize=Insets{left=0, top=0, right=0, bottom=72}}\n")
    self.expect_sh("dumpsys window windows", result=dumpsys_output)
    rect = self.platform.get_window_rect("com.android.chrome")
    self.assertEqual(rect, DisplayRectangle(Point(0, 72), 1080, 1776))

  def test_get_window_rect_multi_window(self):
    dumpsys_output = ("Window #0 Window{1a2b3c4 u0 com.android.chrome/Main}:\n"
                      "  mAppBounds=Rect(191, 83 - 1174, 635)\n")
    self.expect_sh("dumpsys window windows", result=dumpsys_output)
    rect = self.platform.get_window_rect("com.android.chrome")
    self.assertEqual(rect, DisplayRectangle(Point(191, 83), 983, 552))

  def test_get_window_rect_empty_window_name_raises(self):
    with self.assertRaises(AssertionError):
      self.platform.get_window_rect("")

  def test_get_window_rect_not_found_raises(self):
    self.expect_sh(
        "dumpsys window windows",
        result="Window #0 Window{1a2b3c4 u0 com.other.app}:")
    with self.assertRaisesRegex(
        RuntimeError, "Could not find window bounds for com.android.chrome"):
      self.platform.get_window_rect("com.android.chrome")

  def test_user_id(self):
    self.expect_sh("am get-current-user", result="10")
    self.assertEqual(self.platform.user_id(), 10)

  def test_process_meminfo_no_process(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo --proto --package com.android.chrome",
        result=b"")
    meminfo = self.platform.process_meminfo("com.android.chrome")
    self.assertEqual(len(meminfo), 0)

  def test_process_meminfo(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo --proto --package com.android.chrome",
        result=DUMPSYS_MEMINFO_OUTPUT)
    meminfo = self.platform.process_meminfo("com.android.chrome")
    self.assertEqual(len(meminfo), 4)

    privileged_process = "com.android.chrome:privileged_process0"
    sandbox_prefix = ("com.android.chrome:sandboxed_process0:org.chromium."
                      "content.app.SandboxedProcessService0:")
    self.assertSequenceEqual(meminfo, [
        ProcessMeminfo(20533, privileged_process, 37794, 186356, 203),
        ProcessMeminfo(20527, f"{sandbox_prefix}0", 49907, 184636, 245),
        ProcessMeminfo(20596, f"{sandbox_prefix}1", 30679, 156928, 244),
        ProcessMeminfo(20438, "com.android.chrome", 200986, 412436, 148),
    ])

  def test_process_meminfo_timeout(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo --proto --package com.android.chrome",
        result=DUMPSYS_MEMINFO_TIMEOUT_OUTPUT)

    with self.assertRaises(TimeoutError):
      self.platform.process_meminfo("com.android.chrome")

  def test_system_meminfo(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo", result=DUMPSYS_MEMINFO_SYSTEM_OUTPUT)
    meminfo = self.platform.system_meminfo()
    self.assertDictEqual(
        meminfo, {
            "total_ram_kb": 7698860.0,
            "cached_pss_kb": 2345.0,
            "cached_kernel_kb": 3456.0,
            "free_kb": 4567.0,
            "dma_buf_kb": 817715.0,
            "dma_buf_mapped_kb": 152.0,
            "dma_buf_unmapped_kb": 817563.0,
        })

  def test_system_meminfo_no_dma_buf(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo",
        result=DUMPSYS_MEMINFO_SYSTEM_OUTPUT_NO_DMA_BUF)
    meminfo = self.platform.system_meminfo()
    self.assertDictEqual(
        meminfo, {
            "total_ram_kb": 3486196.0,
            "cached_pss_kb": 2345.0,
            "cached_kernel_kb": 3456.0,
            "free_kb": 4567.0,
        })

  def test_system_meminfo_timeout(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo", result=DUMPSYS_MEMINFO_TIMEOUT_OUTPUT)

    with self.assertRaises(TimeoutError):
      self.platform.system_meminfo()

  def test_system_memory_bytes(self):
    self.expect_sh(
        "dumpsys -T 10000 meminfo", result=DUMPSYS_MEMINFO_SYSTEM_OUTPUT)
    self.assertEqual(self.platform.system_memory_bytes, 7698860 * 1024)

  def test_system_memory_bytes_missing(self):
    self.expect_sh("dumpsys -T 10000 meminfo", result=b"")
    with self.assertRaisesRegex(RuntimeError, "No 'Total RAM' line found"):
      self.platform.system_memory_bytes

  def test_doze(self):
    self.expect_sh("dumpsys deviceidle force-idle")
    self.platform.doze()

  def test_exit_doze(self):
    self.expect_sh("dumpsys deviceidle unforce")
    self.expect_sh("dumpsys battery reset")
    self.platform.exit_doze()

  def test_lock_screen(self):
    self.expect_sh("input keyevent KEYCODE_POWER")
    self.platform.lock_screen()

  def test_unlock_screen(self):
    self.expect_sh("input keyevent KEYCODE_WAKEUP")
    self.expect_sh("input keyevent KEYCODE_MENU")
    self.platform.unlock_screen()

  def test_users(self):
    self.expect_sh(
        "pm list users",
        result=("Users:\n\tUserInfo{0:Owner:13} running\n\t"
                "UserInfo{10:Guest:10} running"))
    self.assertSequenceEqual(self.platform.adb.users(), ["0", "10"])

  def test_users_fallback(self):
    self.expect_sh("pm list users", result=ShResult(returncode=1))
    self.expect_sh("am get-current-user", result="10")
    self.assertSequenceEqual(self.platform.adb.users(), ["10"])

  def test_force_stop(self):
    self.expect_sh("pm list users", result="UserInfo{0:Owner:13}")
    self.expect_sh("am force-stop --user 0 com.example.app")
    self.platform.adb.force_stop("com.example.app")

  def test_force_stop_error(self):
    self.expect_sh("pm list users", result="UserInfo{0:Owner:13}")
    self.expect_sh(
        "am force-stop --user 0 com.example.app", result=ShResult(returncode=1))
    self.platform.adb.force_stop("com.example.app")

  def test_force_clear(self):
    self.expect_sh("pm list users", result="UserInfo{10:Owner:13}")
    self.expect_sh("pm clear --user 10 com.example.app")
    self.platform.adb.force_clear("com.example.app")

  def test_force_clear_error(self):
    self.expect_sh("pm list users", result="UserInfo{10:Owner:13}")
    self.expect_sh(
        "pm clear --user 10 com.example.app", result=ShResult(returncode=1))
    self.platform.adb.force_clear("com.example.app")

  def test_killall(self):
    self.expect_sh("pkill com.example.app")
    self.platform.killall("com.example.app")

  def test_exists(self):
    self.expect_path_check("-e", "/data/local/tmp/file", exists=True)
    self.assertTrue(self.platform.exists("/data/local/tmp/file"))
    self.expect_path_check("-e", "/data/local/tmp/missing", exists=False)
    self.assertFalse(self.platform.exists("/data/local/tmp/missing"))

  def test_is_file(self):
    self.expect_path_check("-f", "/data/local/tmp/file", exists=True)
    self.assertTrue(self.platform.is_file("/data/local/tmp/file"))
    self.expect_path_check("-f", "/data/local/tmp/missing", exists=False)
    self.assertFalse(self.platform.is_file("/data/local/tmp/missing"))

  def test_is_dir(self):
    self.expect_path_check("-d", "/data/local/tmp/dir", exists=True)
    self.assertTrue(self.platform.is_dir("/data/local/tmp/dir"))
    self.expect_path_check("-d", "/data/local/tmp/missing", exists=False)
    self.assertFalse(self.platform.is_dir("/data/local/tmp/missing"))

  def test_gpu_vram_used_adreno(self):
    self.expect_path_check("-e", "/sys/class/kgsl/kgsl-3d0/page_alloc")
    self.expect_sh(
        "cat /sys/class/kgsl/kgsl-3d0/page_alloc",
        result=str(1024 * 1024 * 512),
    )
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {"adreno_gpu": 512.0})

  def test_gpu_vram_used_none(self):
    self.expect_path_check(
        "-e", "/sys/class/kgsl/kgsl-3d0/page_alloc", exists=False)
    vram = self.platform.gpu_vram_used()
    self.assertEqual(vram, {})

  def test_platform_version_cls(self):
    version = AndroidVersion.parse("13 (Tiramisu)")
    self.assertSequenceEqual(version.parts, (13,))
    self.assertEqual(version.version_str, "13 (Tiramisu)")
    with self.assertRaises(VersionParseError):
      AndroidVersion.parse("foo")

  def test_parse_binary_manifest_package_name_utf8(self):
    package_name = "org.chromium.chrome"
    axml_data = self._create_axml(package_name)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
      z.writestr("AndroidManifest.xml", axml_data)
    with zipfile.ZipFile(b, "r") as z:
      with z.open("AndroidManifest.xml") as manifest_file:
        self.assertEqual(
            parse_binary_manifest_package_name(manifest_file.read()),
            package_name)

  def test_get_ui_element_rect(self) -> None:
    mock_ad = mock.MagicMock()
    mock_ui_obj = mock.MagicMock()
    mock_ui_obj.wait.exists.return_value = True
    bounds_mock = mock.MagicMock()
    bounds_mock.left = 10
    bounds_mock.top = 20
    bounds_mock.right = 110
    bounds_mock.bottom = 220
    mock_ui_obj.visible_bounds = bounds_mock
    mock_ad.ui.return_value = mock_ui_obj

    mock_context = mock.MagicMock()
    mock_context.__enter__.return_value = mock_ad
    mock_context.__exit__.return_value = None

    with mock.patch.object(
        self.platform, "uiautomator_device",
        return_value=mock_context) as mock_uiautomator:
      ui_selector = UiSelectorConfig(text="Click me")
      rect = self.platform.get_ui_element_rect(ui_selector)
      self.assertEqual(rect.origin, Point(10, 20))
      self.assertEqual(rect.width, 100)
      self.assertEqual(rect.height, 200)
      self.assertEqual(rect.middle, Point(60, 120))
      mock_uiautomator.assert_called_once_with(root_device=False)
      mock_ad.ui.assert_called_once_with(text="Click me")
      mock_ui_obj.wait.exists.assert_called_once()

  def test_get_ui_element_rect_not_found_raises(self) -> None:
    mock_ad = mock.MagicMock()
    mock_ui_obj = mock.MagicMock()
    mock_ui_obj.wait.exists.return_value = False
    mock_ad.ui.return_value = mock_ui_obj

    mock_context = mock.MagicMock()
    mock_context.__enter__.return_value = mock_ad
    mock_context.__exit__.return_value = None

    with mock.patch.object(
        self.platform, "uiautomator_device", return_value=mock_context):
      ui_selector = UiSelectorConfig(text="Click me")
      with self.assertRaises(ElementNotFoundError) as cm:
        self.platform.get_ui_element_rect(ui_selector)
      self.assertIn("Click me", str(cm.exception))

  def _create_axml(self, package_name: str) -> bytes:
    # A very minimal Android Binary XML generator for testing.
    # 1. String Pool
    strings = ["manifest", "package", package_name]
    str_offsets = []
    pool_data = b""
    for s in strings:
      str_offsets.append(len(pool_data))
      encoded = s.encode("utf-16le")
      pool_data += struct.pack("<H", len(s)) + encoded + b"\x00\x00"

    # Pad pool_data to 4 bytes
    if len(pool_data) % 4:
      pool_data += b"\x00" * (4 - len(pool_data) % 4)

    header_size = 28
    chunk_size = header_size + len(strings) * 4 + len(pool_data)
    style_count = 0
    flags = 0
    string_offset = header_size + len(strings) * 4
    style_offset = 0

    string_pool_chunk = struct.pack("<HHL LLLLL", RES_STRING_POOL_TYPE,
                                    header_size, chunk_size, len(strings),
                                    style_count, flags, string_offset,
                                    style_offset)
    for offset in str_offsets:
      string_pool_chunk += struct.pack("<L", offset)
    string_pool_chunk += pool_data

    # 2. Manifest Start Element
    # RES_XML_START_ELEMENT_TYPE, Header=16, Ext=20
    attr_ns = 0xFFFFFFFF
    attr_name = 1  # "package" index in string pool
    attr_raw = 2  # package_name index in string pool
    attr_type = 0
    attr_data = 2  # package_name index in string pool
    attr_data_bytes = struct.pack("<LLLLL", attr_ns, attr_name, attr_raw,
                                  attr_type, attr_data)

    element_header_size = 16
    element_ext_size = 20
    element_chunk_size = element_header_size + element_ext_size + len(
        attr_data_bytes)

    line_number = 0
    comment_idx = 0xFFFFFFFF
    ns_idx = 0xFFFFFFFF
    name_idx = 0  # "manifest" index in string pool
    attr_start = element_ext_size
    attr_size = 20
    attr_count = 1
    id_idx = 0
    class_idx = 0
    style_idx = 0

    start_element_chunk = struct.pack("<HHL LLLL HH HHHH",
                                      RES_XML_START_ELEMENT_TYPE,
                                      element_header_size, element_chunk_size,
                                      line_number, comment_idx, ns_idx,
                                      name_idx, attr_start, attr_size,
                                      attr_count, id_idx, class_idx, style_idx)
    start_element_chunk += attr_data_bytes

    axml_header = struct.pack(
        "<HHL", RES_XML_TYPE, 0x0008,
        8 + len(string_pool_chunk) + len(start_element_chunk))
    return axml_header + string_pool_chunk + start_element_chunk


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
