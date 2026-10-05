# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import io

from crossbench.pinpoint.output_format import OutputFormat, format_delimited, \
    write_delimited
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase


class OutputFormatTest(BaseCrossbenchTestCase):

  def test_output_format_all(self):
    self.assertEqual(
        OutputFormat.all(),
        (
            OutputFormat.TABLE,
            OutputFormat.JSON,
            OutputFormat.YAML,
            OutputFormat.CSV,
            OutputFormat.TSV,
        ),
    )

  def test_output_format_delimiter(self):
    self.assertEqual(OutputFormat.CSV.delimiter, ",")
    self.assertEqual(OutputFormat.TSV.delimiter, "\t")
    with self.assertRaises(ValueError):
      _ = OutputFormat.TABLE.delimiter
    with self.assertRaises(ValueError):
      _ = OutputFormat.JSON.delimiter
    with self.assertRaises(ValueError):
      _ = OutputFormat.YAML.delimiter

  def test_format_delimited(self):
    headers = ["Col1", "Col2"]
    rows = [["a", "b"], ["c", "d"]]
    formatted_csv = format_delimited(headers, rows, delimiter=",")
    self.assertEqual(
        formatted_csv.splitlines(),
        ["Col1,Col2", "a,b", "c,d"],
    )
    formatted_tsv = format_delimited(headers, rows, delimiter="\t")
    self.assertEqual(
        formatted_tsv.splitlines(),
        ["Col1\tCol2", "a\tb", "c\td"],
    )

  def test_write_delimited(self):
    buffer = io.StringIO()
    write_delimited(buffer, ["A", "B"], [["1", "2"]], delimiter=",")
    self.assertEqual(buffer.getvalue().splitlines(), ["A,B", "1,2"])


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
