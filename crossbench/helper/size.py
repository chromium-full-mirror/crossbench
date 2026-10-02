# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
from typing import Final


class Size(enum.IntEnum):
  B = 1
  KiB = 1024
  MiB = 1024 * 1024
  GiB = 1024 * 1024 * 1024
  TiB = 1024 * 1024 * 1024 * 1024

  @classmethod
  def format(cls, size_bytes: float, digits: int = 2) -> str:
    sign = ""
    if size_bytes < 0:
      sign = "-"
    size = abs(size_bytes)
    unit_index = 0
    divisor = float(cls.KiB)
    max_unit_index = len(SIZE_UNITS) - 1
    while unit_index < max_unit_index and size >= divisor:
      unit_index += 1
      size /= divisor
    formatted = f"{size:.{digits}f}"
    if float(formatted) == 0.0:
      sign = ""
    return f"{sign}{formatted} {SIZE_UNITS[unit_index]}"


SIZE_UNITS: Final[tuple[str, ...]] = tuple(member.name for member in Size)
