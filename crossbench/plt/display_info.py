# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import NamedTuple, TypedDict


class DisplayResolution(NamedTuple):
  width: int
  height: int


class DisplayInfo(TypedDict):
  resolution: DisplayResolution
  refresh_rate: float
