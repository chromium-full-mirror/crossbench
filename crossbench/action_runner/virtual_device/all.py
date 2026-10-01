# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench.action_runner.virtual_device.keyboard import \
    KeyboardVirtualDeviceConfig
from crossbench.action_runner.virtual_device.mouse import \
    MouseVirtualDeviceConfig
from crossbench.action_runner.virtual_device.touchscreen import \
    TouchscreenVirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_config import \
    VIRTUAL_DEVICES, VirtualDeviceConfig

VIRTUAL_DEVICES_TUPLE: tuple[type[VirtualDeviceConfig], ...] = (
    KeyboardVirtualDeviceConfig,
    TouchscreenVirtualDeviceConfig,
    MouseVirtualDeviceConfig,
)
for device_cls in VIRTUAL_DEVICES_TUPLE:
  VIRTUAL_DEVICES[device_cls.TYPE] = device_cls

assert len(VIRTUAL_DEVICES_TUPLE) == len(VIRTUAL_DEVICES), (
    "Non unique VirtualDeviceConfig.TYPE present")
