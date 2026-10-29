# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
  from presubmit_support import AffectedFile, InputApi, OutputApi

PLACEHOLDER_BYPASS_REASONS: Final[frozenset[str]] = frozenset(
    {"todo", "tbd", "none", "n/a", "fixme", "xxx"})

SKIPPED_PATHS: Final[tuple[str, ...]] = (
    "third_party/*",
    "*crossbench/third_party/*",
)


class PresubmitCheck:

  def __init__(self, input_api: InputApi, output_api: OutputApi) -> None:
    self._input_api: Final[InputApi] = input_api
    self._output_api: Final[OutputApi] = output_api

  @property
  def input_api(self) -> InputApi:
    return self._input_api

  @property
  def output_api(self) -> OutputApi:
    return self._output_api

  @property
  def root_path(self) -> pathlib.Path:
    return pathlib.Path(self._input_api.PresubmitLocalPath())

  @property
  def description(self) -> str:
    return self._input_api.change.FullDescriptionText()

  @classmethod
  def is_skipped_path(cls, input_api: InputApi, file_path: str) -> bool:
    return any(
        input_api.fnmatch.fnmatch(file_path, pattern)
        for pattern in SKIPPED_PATHS)

  def affected_python_files(self, path_prefix: str = "") -> list[AffectedFile]:

    def file_filter(f: AffectedFile) -> bool:
      path: str = f.LocalPath()
      return (path.startswith(path_prefix) and path.endswith(".py") and
              not self.is_skipped_path(self._input_api, path))

    return list(
        self._input_api.AffectedFiles(
            file_filter=file_filter, include_deletes=False))

  @classmethod
  def changed_lines(cls, affected_file: AffectedFile) -> set[int]:
    return {lineno for lineno, _ in affected_file.ChangedContents()}

  @classmethod
  def parse_bypass_reason(cls, description: str, key: str) -> str | None:
    pattern: str = rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(\S.*)$"
    for match in re.finditer(pattern, description,
                             re.MULTILINE | re.IGNORECASE):
      reason: str = match.group(1).strip()
      if reason.lower() not in PLACEHOLDER_BYPASS_REASONS:
        return reason
    return None

  def bypass_reason(self, key: str) -> str | None:
    return self.parse_bypass_reason(self.description, key)
