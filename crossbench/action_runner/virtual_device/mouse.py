# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import ClassVar, Final

from crossbench.action_runner.virtual_device.pointing import \
    PointingVirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType

# Standard USB mouse reporting rate (8ms interval).
DEFAULT_MOUSE_POLLING_RATE_HZ: Final[int] = 125


@dataclasses.dataclass(frozen=True)
class MouseVirtualDeviceConfig(PointingVirtualDeviceConfig):
  TYPE: ClassVar[VirtualDeviceType] = VirtualDeviceType.MOUSE
  DEFAULT_POLLING_RATE_HZ: ClassVar[int] = DEFAULT_MOUSE_POLLING_RATE_HZ
  polling_rate_hz: int = DEFAULT_MOUSE_POLLING_RATE_HZ
