# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
  from presubmit_support import OutputApi


class PyreflyErrorDict(TypedDict):
  line: int
  column: int
  stop_line: int
  stop_column: int
  path: str
  name: str
  concise_description: str


class PyreflyOutputDict(TypedDict):
  errors: list[PyreflyErrorDict]


def ParsePyreflyOutput(
    output_api: OutputApi,
    root_path: pathlib.Path,
    returncode: int,
    stdout: str,
    stderr: str,
) -> list[OutputApi.PresubmitError] | None:
  del stderr
  if returncode == 0:
    return None
  payload: PyreflyOutputDict = json.loads(stdout)
  results: list[OutputApi.PresubmitError] = []
  for err in payload["errors"]:
    file_path = pathlib.Path(err["path"])
    if file_path.is_absolute():
      file_path = file_path.relative_to(root_path)
    rel_path = file_path.as_posix()
    line = err["line"]
    col = err["column"]
    stop_line = max(line, err["stop_line"])
    results.append(
        output_api.PresubmitError(
            f"pyrefly [{err['name']}] {rel_path}:{line}:{col}: "
            f"{err['concise_description']}",
            locations=[
                output_api.PresubmitResultLocation(
                    file_path=rel_path,
                    start_line=line,
                    end_line=stop_line,
                ),
            ],
        ))
  return results
