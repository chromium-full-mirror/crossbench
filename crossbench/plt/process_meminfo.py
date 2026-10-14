# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True)
class ProcessMeminfo:
  pid: int
  name: str
  pss_total: int
  rss_total: int
  swap_total: int

  def to_json(self) -> JsonDict:
    return dataclasses.asdict(self)
