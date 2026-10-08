# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import pathlib
from typing import Any, Final

from tools.presubmit.common import GetBypassReason

BYPASS_KEY: Final[str] = "ALLOW_TOPLEVEL_FILE"

_ERROR_MESSAGE: Final[str] = (
    "Found newly added file(s) in a top-level directory:")

_ERROR_LONG_TEXT: Final[str] = f"""\
Adding new files directly to top-level directories is discouraged in
Crossbench. Please place new source files, scripts, configs, or tests
in an appropriate subdirectory.

If adding a new top-level file is strictly necessary, provide a
non-empty reason in your commit message footer/tags to bypass this
check:
  {BYPASS_KEY}=<REASON>
"""

PROTECTED_TOPLEVEL_DIRS: Final[frozenset[pathlib.Path]] = frozenset({
    pathlib.Path(),
    pathlib.Path("crossbench"),
    pathlib.Path("tests"),
    pathlib.Path("tests/crossbench"),
})


class FileAction(enum.StrEnum):
  ADD = "A"
  COPY = "C"
  DELETE = "D"
  MODIFY = "M"
  RENAME = "R"
  TYPE_CHANGE = "T"


def _is_toplevel_path(file_path: str) -> bool:
  return pathlib.Path(file_path).parent in PROTECTED_TOPLEVEL_DIRS


def _find_new_toplevel_files(input_api: Any) -> list[str]:
  new_files: list[str] = []
  for affected_file in input_api.AffectedFiles(include_deletes=False):
    if affected_file.Action() != FileAction.ADD:
      continue
    file_path = affected_file.LocalPath()
    if _is_toplevel_path(file_path):
      new_files.append(file_path)
  return sorted(new_files)


def check_no_new_toplevel_files(input_api: Any, output_api: Any) -> list[Any]:
  new_toplevel_files = _find_new_toplevel_files(input_api)
  if not new_toplevel_files:
    return []

  description: str = input_api.change.FullDescriptionText()
  if reason := GetBypassReason(description, BYPASS_KEY):
    return [
        output_api.PresubmitNotifyResult(
            f"Bypassing top-level file check ({', '.join(new_toplevel_files)}) "
            f"via commit message tag: {BYPASS_KEY}={reason}"),
    ]

  return [
      output_api.PresubmitError(
          _ERROR_MESSAGE, items=new_toplevel_files, long_text=_ERROR_LONG_TEXT),
  ]
