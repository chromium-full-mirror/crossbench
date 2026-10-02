# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, TypeVar

from crossbench import plt
from crossbench.helper.size import Size

if TYPE_CHECKING:
  from crossbench import path as pth
  PathT = TypeVar("PathT", bound=pth.AnyPath)


def sort_by_file_size(files: Iterable[PathT],
                      platform: plt.Platform | None = None) -> list[PathT]:
  real_platform = platform or plt.PLATFORM
  return sorted(files, key=lambda f: (real_platform.file_size(f), f.name))


def get_file_size(file: pth.AnyPath,
                  digits: int = 2,
                  platform: plt.Platform | None = None) -> str:
  real_platform = platform or plt.PLATFORM
  return Size.format(real_platform.file_size(file), digits=digits)
