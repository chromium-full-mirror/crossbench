# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from collections.abc import Sequence

  from presubmit_support import InputApi, OutputApi


def SortImports(
    input_api: InputApi,
    output_api: OutputApi,
    modified_py_files: Sequence[str],
) -> list[object]:
  results: list[object] = []
  files_to_sort = [
      str(pathlib.Path(input_api.change.RepositoryRoot()) / f)
      for f in modified_py_files
  ]
  if not files_to_sort:
    return results

  process = subprocess.run(
      [input_api.python_executable, "-m", "isort", "-j", "0", *files_to_sort],
      check=True,
      capture_output=True,
      text=True)
  output = process.stdout + process.stderr
  offending_files = [f for f in files_to_sort if f in output]

  if offending_files:
    results.append(
        output_api.PresubmitPromptWarning(
            "Unsorted python imports:",
            items=offending_files,
            long_text=(
                "Please update your commit with the formatted files.\n\n" +
                output)))
  return results
