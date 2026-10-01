# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum

from crossbench.config import ConfigEnum


@enum.unique
class VirtualDeviceType(ConfigEnum):
  KEYBOARD = ("keyboard", "Virtual keyboard device")
  TOUCHSCREEN = ("touchscreen", "Virtual touchscreen device")
  MOUSE = ("mouse", "Virtual mouse device")
