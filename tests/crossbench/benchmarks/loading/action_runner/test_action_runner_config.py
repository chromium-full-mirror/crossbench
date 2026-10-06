# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import unittest
from typing import Any
from unittest import mock

from crossbench import plt
from crossbench.action_runner.android_input_action_runner import \
    AndroidInputActionRunner
from crossbench.action_runner.base import ActionRunner
from crossbench.action_runner.chromeos_input_action_runner import \
    ChromeOSInputActionRunner
from crossbench.action_runner.config import DEFAULT_VIRTUAL_DEVICES, \
    ActionRunnerConfig, ActionRunnerType
from crossbench.action_runner.virtual_device.keyboard import \
    KeyboardVirtualDeviceConfig
from crossbench.action_runner.virtual_device.mouse import \
    MouseVirtualDeviceConfig
from crossbench.action_runner.virtual_device.touchscreen import \
    TouchscreenVirtualDeviceConfig
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.runner.run import Run
from tests import test_helper


class ActionRunnerConfigTest(unittest.TestCase):

  def setUp(self) -> None:
    self.mock_run = mock.MagicMock(spec=Run)

  def test_parse_invalid(self):
    for invalid in ["bas", "adnroid", "chroms"]:
      with self.subTest(pattern=invalid):
        with self.assertRaises((argparse.ArgumentTypeError, ValueError)):
          ActionRunnerConfig.parse(invalid)

  def test_parse_basic(self):
    action_runner = ActionRunnerConfig.parse("basic")
    self.assertIsInstance(action_runner, ActionRunnerConfig)
    self.assertEqual(action_runner.type, ActionRunnerType.BASIC)
    self.assertIsInstance(
        action_runner.instantiate(plt.PLATFORM, self.mock_run), ActionRunner)

  def test_parse_auto(self):
    action_runner = ActionRunnerConfig.parse("auto")
    self.assertIsInstance(action_runner, ActionRunnerConfig)
    self.assertEqual(action_runner.type, ActionRunnerType.AUTO)
    self.assertIsInstance(
        action_runner.instantiate(plt.PLATFORM, self.mock_run), ActionRunner)

  def test_parse_auto_android(self):
    action_runner = ActionRunnerConfig.parse("auto")
    mock_platform = mock.MagicMock()
    mock_platform.is_android = True
    self.assertIsInstance(
        action_runner.instantiate(mock_platform, self.mock_run),
        AndroidInputActionRunner)

  def test_parse_auto_chromeos(self):
    action_runner = ActionRunnerConfig.parse("auto")
    mock_platform = mock.MagicMock()
    mock_platform.is_android = False
    mock_platform.is_chromeos = True
    self.assertIsInstance(
        action_runner.instantiate(mock_platform, self.mock_run),
        ChromeOSInputActionRunner)

  def test_parse_android(self):
    action_runner = ActionRunnerConfig.parse("android")
    self.assertIsInstance(action_runner, ActionRunnerConfig)
    self.assertEqual(action_runner.type, ActionRunnerType.ANDROID)
    self.assertIsInstance(
        action_runner.instantiate(plt.PLATFORM, self.mock_run),
        AndroidInputActionRunner)

  def test_parse_chromeos(self):
    action_runner = ActionRunnerConfig.parse("chromeos")
    self.assertIsInstance(action_runner, ActionRunnerConfig)
    self.assertEqual(action_runner.type, ActionRunnerType.CHROMEOS)
    self.assertIsInstance(
        action_runner.instantiate(plt.PLATFORM, self.mock_run),
        ChromeOSInputActionRunner)

  def test_default_virtual_devices(self) -> None:
    action_runner_config = ActionRunnerConfig()
    self.assertEqual(action_runner_config.virtual_devices, ())
    self.assertEqual(len(DEFAULT_VIRTUAL_DEVICES), 3)
    self.assertEqual(
        DEFAULT_VIRTUAL_DEVICES[InputSource.KEYBOARD],
        KeyboardVirtualDeviceConfig(name="default_keyboard"),
    )
    self.assertEqual(
        DEFAULT_VIRTUAL_DEVICES[InputSource.TOUCH],
        TouchscreenVirtualDeviceConfig(name="default_touchscreen"),
    )
    self.assertEqual(
        DEFAULT_VIRTUAL_DEVICES[InputSource.MOUSE],
        MouseVirtualDeviceConfig(name="default_mouse"),
    )

  def test_default_virtual_devices_unique_names(self) -> None:
    names = [device.name for device in DEFAULT_VIRTUAL_DEVICES.values()]
    self.assertEqual(len(names), len(set(names)))

  def test_parse_virtual_devices(self) -> None:
    config_dict: dict[str, Any] = {
        "type":
            "android",
        "virtual_devices": [
            {
                "type": "keyboard",
                "name": "kb1",
            },
            {
                "type": "touchscreen",
                "name": "ts1",
                "width": 1080,
                "height": 2400,
            },
            {
                "type": "mouse",
                "name": "mouse1",
                "width": 1920,
                "height": 1080,
            },
        ],
    }
    action_runner_config = ActionRunnerConfig.parse_dict(config_dict)
    self.assertEqual(action_runner_config.type, ActionRunnerType.ANDROID)
    self.assertEqual(len(action_runner_config.virtual_devices), 3)
    self.assertEqual(
        action_runner_config.virtual_devices[0],
        KeyboardVirtualDeviceConfig(name="kb1"),
    )
    self.assertEqual(
        action_runner_config.virtual_devices[1],
        TouchscreenVirtualDeviceConfig(name="ts1", width=1080, height=2400),
    )
    self.assertEqual(
        action_runner_config.virtual_devices[2],
        MouseVirtualDeviceConfig(name="mouse1", width=1920, height=1080),
    )

  def test_instantiate_default_no_virtual_devices(self) -> None:
    setup_devices = self.mock_run.browser_platform.setup_virtual_devices
    config = ActionRunnerConfig()
    config.instantiate(plt.PLATFORM, self.mock_run)
    setup_devices.assert_called_once_with(())

  def test_instantiate_explicit_virtual_devices(self) -> None:
    setup_devices = self.mock_run.browser_platform.setup_virtual_devices
    ts1 = TouchscreenVirtualDeviceConfig(name="ts1")
    mouse1 = MouseVirtualDeviceConfig(name="mouse1")
    config = ActionRunnerConfig(virtual_devices=(ts1, mouse1))
    config.instantiate(plt.PLATFORM, self.mock_run)
    setup_devices.assert_called_once_with((ts1, mouse1))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
