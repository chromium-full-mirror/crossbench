# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import io
import json
from unittest import mock

from crossbench.pinpoint import http_requests
from crossbench.pinpoint.api import USERINFO_API_URL
from crossbench.pinpoint.job_info import UrlSource
from crossbench.pinpoint.list_format import ListFormatEnum
from crossbench.pinpoint.list_jobs import list_jobs, truncate
from crossbench.pinpoint.user import UserEnum
from tests import test_helper
from tests.crossbench.pinpoint.http_requests_mixin import MockHttpRequestsMixin


class ListJobsTest(MockHttpRequestsMixin):

  def setUp(self):
    super().setUp()
    self.stdout_mock = io.StringIO()
    self.sys_stdout_patch = self.enterContext(
        mock.patch("sys.stdout", self.stdout_mock))
    self.mock_annotate = self.enterContext(
        mock.patch("crossbench.pinpoint.list_jobs.annotate"))
    self.mock_annotate.return_value.__enter__.return_value = None

  def test_list_jobs_no_jobs(self):
    self.mock_get.return_value.json.return_value = {"jobs": []}

    list_jobs(UserEnum.ALL, 10, None, ListFormatEnum.TABLE)

    output = self.stdout_mock.getvalue()
    self.assertIn("No jobs found.", output)

  def test_list_jobs_me_fetching_email(self):
    # Mock user info response
    self.mock_get.side_effect = [
        mock.Mock(json=lambda: {"email": "user@example.com"}),
        mock.Mock(json=lambda: {"jobs": []}),
        mock.Mock(json=lambda: {"jobs": []}),
        mock.Mock(json=lambda: {"jobs": []}),
    ]

    list_jobs(
        user=UserEnum.ME,
        number=10,
        truncate=None,
        output_format=ListFormatEnum.JSON)

    # Verify calls: 1 for email, 3 for jobs (email, @google, @chromium)
    self.assertEqual(self.mock_get.call_count, 4)
    self.mock_get.assert_any_call(USERINFO_API_URL)

  def test_list_jobs_json_format(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs("user@example.com", 1, None, ListFormatEnum.JSON)

    output = self.stdout_mock.getvalue()
    parsed_output = json.loads(output)
    self.assertEqual(len(parsed_output), 1)
    self.assertEqual(parsed_output[0], job_data)

  def test_list_jobs_csv_format(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs("user@example.com", 1, None, ListFormatEnum.CSV)

    output = self.stdout_mock.getvalue()
    self.assertIn("Benchmark,Config,Type,Start Time,Job URL,Status", output)
    self.assertIn(
        "speedometer,config,performance,2024-01-01 00:00:00,"
        "http://go/l_/r/123,completed", output)

  def test_list_jobs_table_format(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs("user@example.com", 1, None, ListFormatEnum.TABLE)

    output = self.stdout_mock.getvalue()
    # Check for table headers and content
    self.assertIn("Benchmark", output)
    self.assertIn("speedometer", output)
    self.assertIn("✅", output)  # Completed status emoji
    self.assertIn("http://go/l_/r/123", output)
    self.assertIn("2024-Jan-01 00:00", output)

  def test_list_jobs_url_source_pinpoint_classic(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs(
        "user@example.com",
        1,
        None,
        ListFormatEnum.TABLE,
        url_source=UrlSource.PINPOINT_CLASSIC)

    output = self.stdout_mock.getvalue()
    self.assertIn("http://go/j_/123", output)
    self.assertNotIn("http://go/l_/r/123", output)

  def test_list_jobs_url_source_leszek_perf(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs(
        "user@example.com",
        1,
        None,
        ListFormatEnum.TABLE,
        url_source=UrlSource.LESZEK_PERF)

    output = self.stdout_mock.getvalue()
    self.assertIn("http://go/l_/r/123", output)
    self.assertNotIn("http://go/j_/123", output)

  def test_list_jobs_url_source_leszek_perf_dev(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
        },
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs(
        "user@example.com",
        1,
        None,
        ListFormatEnum.TABLE,
        url_source=UrlSource.LESZEK_PERF_DEV)

    output = self.stdout_mock.getvalue()
    self.assertIn("https://leszek-perf-dev.corp.goog/r/123", output)
    self.assertNotIn("http://go/j_/123", output)

  def test_list_jobs_pagination(self):
    # First page
    page1 = {
        "jobs": [{
            "job_id": "1",
            "created": "2024-01-01T00:00:00Z",
        }],
        "next_cursor": "cursor1",
        "next": True,
    }
    # Second page
    page2 = {
        "jobs": [{
            "job_id": "2",
            "created": "2024-01-02T00:00:00Z",
        }],
        "next_cursor": None,
        "next": False,
    }

    self.mock_get.side_effect = [
        mock.Mock(json=lambda: page1),
        mock.Mock(json=lambda: page2),
    ]

    list_jobs("user@example.com", 10, None, ListFormatEnum.JSON)

    output = self.stdout_mock.getvalue()
    parsed_output = json.loads(output)
    self.assertEqual(len(parsed_output), 2)
    job_ids = [job["job_id"] for job in parsed_output]
    # Reversed order because job "1" has earlier creation date.
    self.assertSequenceEqual(job_ids, ["2", "1"])

  def test_list_jobs_all_users(self):
    job_data = {
        "job_id": "123",
        "user": "other@example.com",
        "created": "2024-01-01T00:00:00Z",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs(UserEnum.ALL, 1, None, ListFormatEnum.CSV)

    output = self.stdout_mock.getvalue()
    self.assertIn("User",
                  output)  # "User" column should be present for ALL users
    self.assertIn("other@example.com", output)
    self.assertIn("http://go/l_/r/123", output)
    self.assertIn("2024-01-01 00:00:00", output)

  def test_list_jobs_truncate(self):
    job_data = {
        "job_id": "1",
        "configuration": "very_long_configuration_string_that_needs_truncating",
        "user": "u",
        "created": "2024-01-01",
        "status": "queued",
        "arguments": {
            "benchmark": "b",
        },
        "comparison_mode": "try",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs("u", 1, 10, ListFormatEnum.TABLE)

    output = self.stdout_mock.getvalue()
    self.assertIn("very_lo...", output)
    self.assertNotIn("very_long_configuration_string_that_needs_truncating",
                     output)
    self.assertIn("try", output)
    self.assertIn("⌛", output)  # Queued status emoji

  def test_truncate_small_max_length(self):
    self.assertEqual(truncate("hello", 1), "h")
    self.assertEqual(truncate("hello", 2), "he")
    self.assertEqual(truncate("hello", 3), "hel")
    self.assertEqual(truncate("hello", 4), "h...")
    self.assertEqual(truncate("hello", 5), "hello")
    self.assertEqual(truncate("hello", 10), "hello")

  def test_list_jobs_server_error(self):
    self.mock_get.return_value.raise_for_status.side_effect = (
        http_requests.requests.exceptions.HTTPError("404 Client Error"))

    with self.assertRaises(http_requests.requests.exceptions.HTTPError):
      list_jobs(UserEnum.ALL, 10, None, ListFormatEnum.TABLE)

  def test_list_jobs_extra_columns(self):
    job_data = {
        "job_id": "123",
        "configuration": "config",
        "user": "user@example.com",
        "created": "2024-01-01T00:00:00Z",
        "status": "completed",
        "arguments": {
            "benchmark": "speedometer",
            "story": "story_name",
            "initial_attempt_count": "10",
        },
        "bug_id": "123456",
        "comparison_mode": "performance",
    }
    self.mock_get.return_value.json.return_value = {"jobs": [job_data]}

    list_jobs(
        "user@example.com",
        1,
        None,
        ListFormatEnum.TABLE,
        extra_columns=["bug", "story", "attempts"])

    output = self.stdout_mock.getvalue()
    self.assertIn("Bug", output)
    self.assertIn("123456", output)
    self.assertIn("Story", output)
    self.assertIn("story_name", output)
    self.assertIn("Attempts", output)
    self.assertIn("10", output)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
