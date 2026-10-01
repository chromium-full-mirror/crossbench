# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.plt.base import Platform


def get_chromedriver_target(is_android: bool) -> str:
  if is_android:
    return "clang_x64/chromedriver"
  return "chromedriver"


def get_chromedriver_build_instructions(build_dir: pth.LocalPath,
                                        is_android: bool = False) -> str:
  return ("Please build 'chromedriver' manually for local builds:\n"
          f"    autoninja -C {build_dir} {get_chromedriver_target(is_android)}")


def find_build_dir(path: pth.AnyPath,
                   platform: Platform,
                   limit: int = 5) -> pth.AnyPath | None:
  if is_build_dir(path, platform):
    return path
  for parent in path.parents[:limit]:
    if is_build_dir(parent, platform):
      return parent
  return None


def is_build_dir(path: pth.AnyPath, platform: Platform) -> bool:
  return (platform.is_file(path / "args.gn") or
          platform.is_file(path / "build.ninja") or
          platform.is_dir(path / "lib.unstripped"))


def is_in_build_dir(path: pth.AnyPath, platform: Platform) -> bool:
  # bypass potentially expensive checks
  if "src" not in path.parts:
    return False
  return bool(find_build_dir(path, platform))
