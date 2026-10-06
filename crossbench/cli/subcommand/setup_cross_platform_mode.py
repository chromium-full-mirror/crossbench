# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import atexit
import datetime
import logging
import subprocess
import sys
from typing import TYPE_CHECKING

from typing_extensions import override

from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.cli.ui import ui
from crossbench.helper import wait
from crossbench.parse import ObjectParser
from crossbench.plt import PLATFORM
from crossbench.plt.android_adb import adb_devices
from crossbench.plt.ios import ios_devices

if TYPE_CHECKING:
  import argparse

  from crossbench.cli.parser import CBArgumentParser
  from crossbench.cli.types import Subparsers
  from crossbench.plt.types import CmdArg

WARNING_MESSAGE = """
WARNING: In order to establish an Ethernet connection to the tested device,
crossbench will attempt to reconfigure the '{interface}' network interface on
your workstation. This will require running commands with root privileges.

USE AT YOUR OWN RISK.

Before you continue, please stop any system services that attempt to configure
network interfaces, e.g. on Ubuntu:
$ sudo systemctl stop NetworkManager
"""

CONNECT_DEVICE_MESSAGE = """
Please disable WiFi on your device and connect it via an Ethernet cable.
Press Enter when ready.
"""

KEEP_RUNNING_MESSAGE = """
Network setup complete. You can now run the loadline2-webapi-phone benchmark.
Keep this script running until the bencmark finishes executing. Then you can
terminate it via Ctrl+C.
"""

DEVICE_IP = "192.168.1.100"
ADB_PORT = "5555"
SETUP_TIMEOUT = datetime.timedelta(seconds=20)


class SetupCrossPlatformModeSubcommand(CrossbenchSubcommand):

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    self._parser = subparsers.add_parser(
        "setup_cross_platform_mode",
        help=("Sets up Ethernet connection to your device in a way "
              "required by the loadline2-webapi benchmark."))
    self._parser.set_defaults(crossbench_subcommand=self)
    return self.parser

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    parser.add_argument(
        "--interface",
        type=ObjectParser.non_empty_str,
        required=True,
        help="Network interface to use.")
    self.cli.add_debugging_arguments(parser)

    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    setup = SetupNetwork(args.interface)
    setup.run()


class SetupNetwork:

  def __init__(self, interface: str) -> None:
    self._interface: str = interface
    self._dnsmasq_process: subprocess.Popen | None = None
    self._is_android: bool = False
    assert self._interface, "Missing network interface"

  def run(self) -> None:
    self._setup()
    assert self._dnsmasq_process, "Missing dnsmasq process"
    print(KEEP_RUNNING_MESSAGE)
    _, stderr = self._dnsmasq_process.communicate()
    logging.error("dnsmasq process failed: %s", stderr.decode("utf-8"))

  def _sh(self, *args: CmdArg) -> subprocess.CompletedProcess:
    return PLATFORM.sh(
        *args,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)

  def _fail(self, msg: str, *args) -> None:
    logging.error(msg, *args)
    sys.exit(1)

  def _list_adb_devices(self) -> list[str]:
    if adb_bin := PLATFORM.which("adb"):
      return list(adb_devices(PLATFORM, adb_bin).keys())
    return []

  def _list_ios_devices(self) -> list[str]:
    if PLATFORM.which("xcrun"):
      return list(ios_devices(PLATFORM).keys())
    return []

  def _check_device(self) -> None:
    adb_devices = self._list_adb_devices()
    ios_devices = self._list_ios_devices()
    devices = adb_devices + ios_devices
    if len(devices) > 1:
      self._fail(
          "LoadLine 2 WebAPI only supports running on 1 device at a "
          "time. The following devices are connected:\n%s", "\n".join(devices))
    elif len(devices) == 0:
      self._fail("No devices found")
    if adb_devices:
      self._is_android = True
    else:
      self._is_android = False

  def _check_ports(self) -> None:
    self._check_port_available(53)
    self._check_port_available(80)
    self._check_port_available(443)

  def _check_port_available(self, port: int) -> None:
    result = self._sh("sudo", "lsof", "+c0", f"-i:{port}")
    lsof = result.stdout.decode("utf-8")
    listeners = [line for line in lsof.splitlines() if "(LISTEN)" in line]
    if len(listeners) > 0:
      self._fail("Port %s is used by the following processes:\n%s", port,
                 "\n".join(listeners))

  def _configure_networking(self) -> None:
    atexit.register(self._disconnect)

    dnsmasq_bin = PLATFORM.which("dnsmasq")
    assert dnsmasq_bin, "dnsmasq binary not found in $PATH"
    assert self._interface, "Missing network interface"

    PLATFORM.sh(
        "sudo",
        "ifconfig",
        self._interface,
        "192.168.1.1",
        "netmask",
        "255.255.255.0",
    )
    self._dnsmasq_process = PLATFORM.popen(
        "sudo",
        dnsmasq_bin,
        "--no-daemon",
        "--no-resolv",
        "--interface",
        self._interface,
        "--address",
        "/#/192.168.1.1",
        "--dhcp-range",
        f"{DEVICE_IP},{DEVICE_IP}",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    for _ in wait.wait_with_backoff(SETUP_TIMEOUT):
      ping_result = self._sh("ping", "-c1", "-W1", DEVICE_IP)
      if ping_result.returncode == 0:
        break

  def _setup_device(self) -> None:
    if self._is_android:
      result = self._sh("adb", "connect", f"{DEVICE_IP}:{ADB_PORT}")
      # adb connect always returns code 0, check stderr instead
      if result.stderr:
        self._fail("adb connect failed:\n%s", result.stderr.decode("utf-8"))
    else:
      result = self._sh("idevice_id", "-n")
      devices = result.stdout.decode("utf-8").strip().splitlines()
      if len(devices) == 0:
        self._fail("Failed to connect to iOS device")
      elif len(devices) > 1:
        self._fail("More than one iOS device connected to network")
      else:
        print("iOS device found. You can use the following cmdline flag to "
              "specify the device in crossbench:\n\n"
              "    --browser='{browser:\"safari\",driver:{type:\"ios\","
              f"device_id:\"{devices[0]}\"}}'")

  def _disconnect(self) -> None:
    atexit.unregister(self._disconnect)
    if self._is_android:
      self._sh("adb", "disconnect")
    if self._dnsmasq_process:
      self._dnsmasq_process.terminate()
      self._dnsmasq_process = None

  def _setup(self) -> None:
    self._check_device()
    print(WARNING_MESSAGE.format(interface=self._interface))
    result = ui.prompt("When ready, please type 'yes' to continue:")
    if result.lower() != "yes":
      return

    if self._is_android:
      PLATFORM.sh("adb", "tcpip", ADB_PORT, stdout=subprocess.DEVNULL)

    ui.prompt(CONNECT_DEVICE_MESSAGE)
    logging.info("Setting up Ethernet connection...")
    self._check_ports()
    self._configure_networking()
    self._setup_device()
