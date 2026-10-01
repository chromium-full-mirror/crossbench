# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from unittest import mock

from crossbench.pinpoint.format_time import format_datetime, format_time
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase


class FormatTimeTest(BaseCrossbenchTestCase):

  def test_format_time_today(self):
    now = dt.datetime(2024, 3, 10, 15, 0, 0)
    input_str = "2024-03-10 09:30:00"

    with mock.patch("crossbench.pinpoint.format_time.dt") as mock_dt_module:
      mock_dt_module.datetime.now.return_value = now
      mock_dt_module.datetime.strptime.side_effect = dt.datetime.strptime

      result = format_time(input_str)
      self.assertEqual(result, "Today 09:30")

  def test_format_time_this_year(self):
    now = dt.datetime(2024, 3, 10, 15, 0, 0)
    input_str = "2024-01-15 14:45:00"

    with mock.patch("crossbench.pinpoint.format_time.dt") as mock_dt_module:
      mock_dt_module.datetime.now.return_value = now
      mock_dt_module.datetime.strptime.side_effect = dt.datetime.strptime

      result = format_time(input_str)
      # %b is locale dependent
      self.assertRegex(result, r"^.+-15 14:45$")

  def test_format_time_different_year(self):
    now = dt.datetime(2024, 3, 10, 15, 0, 0)
    input_str = "2023-12-25 08:00:00"

    with mock.patch("crossbench.pinpoint.format_time.dt") as mock_dt_module:
      mock_dt_module.datetime.now.return_value = now
      mock_dt_module.datetime.strptime.side_effect = dt.datetime.strptime

      result = format_time(input_str)
      # %b is locale dependent
      self.assertRegex(result, r"^2023-.+-25 08:00$")

  def test_format_time_invalid_format(self):
    input_str = "invalid-date-string"

    with mock.patch("logging.warning") as mock_logging:
      result = format_time(input_str)
      self.assertEqual(result, input_str)
      mock_logging.assert_called_once()

  def test_format_datetime(self):
    self.assertEqual(format_datetime(None), "")
    dt_obj = dt.datetime(2024, 1, 1, 12, 0, 0)
    self.assertEqual(format_datetime(dt_obj), "2024-01-01 12:00:00")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
