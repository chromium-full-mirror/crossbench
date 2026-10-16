# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import unittest
from typing import Any
from unittest import mock

from crossbench.action_runner.config import DEFAULT_VIRTUAL_DEVICES, \
    ActionRunnerConfig
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

  def test_parse_str_deprecated_noop(self) -> None:
    with self.assertLogs(level=logging.WARNING) as cm:
      action_runner_config = ActionRunnerConfig.parse("android")
    self.assertTrue(any("deprecated" in msg for msg in cm.output))
    self.assertEqual(action_runner_config, ActionRunnerConfig())

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
    config.instantiate(self.mock_run)
    setup_devices.assert_called_once_with(())

  def test_instantiate_explicit_virtual_devices(self) -> None:
    setup_devices = self.mock_run.browser_platform.setup_virtual_devices
    ts1 = TouchscreenVirtualDeviceConfig(name="ts1")
    mouse1 = MouseVirtualDeviceConfig(name="mouse1")
    config = ActionRunnerConfig(virtual_devices=(ts1, mouse1))
    config.instantiate(self.mock_run)
    setup_devices.assert_called_once_with((ts1, mouse1))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
