# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import NotRequired, TypedDict


class OsDetails(TypedDict):
  system: str
  release: str
  version: str
  platform: str


class PythonDetails(TypedDict):
  version: str
  bits: int | str


class CpuDetails(TypedDict):
  info: str
  physical_cores: int
  logical_cores: int
  usage: NotRequired[list[float] | float | str]
  total_usage: NotRequired[float | str]
  system_load: NotRequired[tuple[float, float, float] | str]
  min_frequency: NotRequired[str]
  max_frequency: NotRequired[str]
  current_frequency: NotRequired[str]


class MacOsSystemDetails(TypedDict):
  system_profiler: str
  sysctl_machdep_cpu: str
  sysctl_hw: str
