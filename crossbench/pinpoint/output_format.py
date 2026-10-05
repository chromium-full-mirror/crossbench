# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import csv
import io
from enum import StrEnum
from typing import Any, Iterable, Sequence, TextIO


class OutputFormat(StrEnum):
  TABLE = "table"
  JSON = "json"
  YAML = "yaml"
  CSV = "csv"
  TSV = "tsv"

  @classmethod
  def all(cls) -> tuple[OutputFormat, ...]:
    return tuple(cls)

  @property
  def delimiter(self) -> str:
    if self == OutputFormat.TSV:
      return "\t"
    if self == OutputFormat.CSV:
      return ","
    raise ValueError(f"OutputFormat {self} is not a delimited format")


def write_delimited(stream: TextIO,
                    headers: Sequence[str],
                    rows: Iterable[Sequence[Any]],
                    delimiter: str = ",") -> None:
  """Writes rows with headers to stream as delimited CSV/TSV data."""
  writer = csv.writer(stream, delimiter=delimiter)
  writer.writerow(headers)
  writer.writerows(rows)


def format_delimited(headers: Sequence[str],
                     rows: Iterable[Sequence[Any]],
                     delimiter: str = ",") -> str:
  """Formats rows with headers as a delimited CSV/TSV string."""
  buffer = io.StringIO()
  write_delimited(buffer, headers, rows, delimiter=delimiter)
  return buffer.getvalue().rstrip()
