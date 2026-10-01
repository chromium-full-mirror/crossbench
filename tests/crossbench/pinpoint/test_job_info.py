# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import TYPE_CHECKING, Final

from crossbench.pinpoint.job_info import ComparisonMode, JobStatus, \
    PinpointJobInfo
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase

if TYPE_CHECKING:
  from crossbench.types import JsonDict

_SAMPLE_JOB_DATA: Final[JsonDict] = {
    "job_id": "1234567890",
    "status": "Running",
    "comparison_mode": "try",
    "user": "tester@example.com",
    "name": "test-run-1",
    "created": "2024-01-01T12:00:00Z",
    "started": "2024-01-01T12:01:00Z",
    "completed": "2024-01-01T12:30:00Z",
    "arguments": {
        "benchmark": "speedometer3",
        "configuration": "linux-perf",
        "story": "Speedometer3",
        "story_tags": "tag1,tag2",
        "bug_id": "9999",
        "initial_attempt_count": "10",
        "base_git_hash": "aaa111",
        "end_git_hash": "bbb222",
        "base_patch": "https://crrev.com/c/111",
        "experiment_patch": "https://crrev.com/c/222",
    },
    "state": [
        {
            "attempts": [
                {
                    "executions": [{}, {
                        "completed": True,
                    }],
                },
                {
                    "executions": [{}, {
                        "completed": True,
                    }],
                },
            ],
        },
        {
            "attempts": [{
                "executions": [{}, {
                    "completed": True,
                }],
            }],
        },
    ],
    "difference_count": 0,
    "results_url": "https://storage.cloud.google.com/results.html",
    "cancel_reason": "User cancelled",
}


class PinpointJobInfoTest(BaseCrossbenchTestCase):

  def test_from_json_empty(self):
    job_info = PinpointJobInfo.from_json({})
    self.assertEqual(job_info.job_id, "")
    self.assertIsNone(job_info.status)
    self.assertIsNone(job_info.comparison_mode)
    self.assertEqual(job_info.job_type, "")
    self.assertIsNone(job_info.user)
    self.assertIsNone(job_info.name)
    self.assertIsNone(job_info.benchmark)
    self.assertIsNone(job_info.bot)
    self.assertIsNone(job_info.story)
    self.assertIsNone(job_info.story_tags)
    self.assertIsNone(job_info.bug)
    self.assertIsNone(job_info.created)
    self.assertIsNone(job_info.started)
    self.assertIsNone(job_info.completed)
    self.assertIsNone(job_info.base_commit)
    self.assertIsNone(job_info.exp_commit)
    self.assertIsNone(job_info.base_patch)
    self.assertIsNone(job_info.exp_patch)
    self.assertIsNone(job_info.attempts)
    self.assertIsNone(job_info.progress)
    self.assertIsNone(job_info.differences)
    self.assertIsNone(job_info.results_url)
    self.assertIsNone(job_info.cancel_reason)
    self.assertEqual(job_info.differences_str, "")
    self.assertEqual(job_info.formatted_results_url, "")
    self.assertEqual(job_info.status_display, "Unknown")
    self.assertEqual(job_info.url,
                     "https://pinpoint-dot-chromeperf.appspot.com/job/")
    self.assertEqual(job_info.short_url, "http://go/j_/")

  def test_from_json_full(self):
    job_info = PinpointJobInfo.from_json(_SAMPLE_JOB_DATA)
    self.assertEqual(job_info.job_id, "1234567890")
    self.assertIs(job_info.status, JobStatus.RUNNING)
    self.assertIs(job_info.comparison_mode, ComparisonMode.TRY)
    self.assertEqual(job_info.user, "tester@example.com")
    self.assertEqual(job_info.name, "test-run-1")
    self.assertEqual(job_info.benchmark, "speedometer3")
    self.assertEqual(job_info.bot, "linux-perf")
    self.assertEqual(job_info.story, "Speedometer3")
    self.assertEqual(job_info.story_tags, "tag1,tag2")
    self.assertEqual(job_info.bug, "9999")
    self.assertEqual(job_info.created,
                     dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.UTC))
    self.assertEqual(job_info.started,
                     dt.datetime(2024, 1, 1, 12, 1, 0, tzinfo=dt.UTC))
    self.assertEqual(job_info.completed,
                     dt.datetime(2024, 1, 1, 12, 30, 0, tzinfo=dt.UTC))
    self.assertEqual(job_info.base_commit, "aaa111")
    self.assertEqual(job_info.exp_commit, "bbb222")
    self.assertEqual(job_info.base_patch, "https://crrev.com/c/111")
    self.assertEqual(job_info.exp_patch, "https://crrev.com/c/222")
    self.assertEqual(job_info.attempts, 10)
    self.assertEqual(job_info.progress, "3/20 (15%)")
    self.assertEqual(job_info.differences, 0)
    self.assertEqual(job_info.differences_str, "0")
    self.assertEqual(job_info.results_url,
                     "https://storage.cloud.google.com/results.html")
    self.assertIn("https://storage.cloud.google.com/results.html",
                  job_info.formatted_results_url)
    self.assertEqual(job_info.cancel_reason, "User cancelled")

  def test_urls(self):
    job_info = PinpointJobInfo(job_id="test-id", status=JobStatus.COMPLETED)
    self.assertEqual(
        job_info.url,
        "https://pinpoint-dot-chromeperf.appspot.com/job/test-id",
    )
    self.assertEqual(job_info.short_url, "http://go/j_/test-id")
    self.assertIn("https://pinpoint-dot-chromeperf.appspot.com/job/test-id",
                  job_info.url_link)
    self.assertEqual(job_info.formatted_results_url, "")

    job_with_results = PinpointJobInfo(
        job_id="test-id",
        status=JobStatus.COMPLETED,
        results_url="https://example.com/results.html",
    )
    self.assertIn("https://example.com/results.html",
                  job_with_results.formatted_results_url)

  def test_differences_str(self):
    job_info = PinpointJobInfo(
        job_id="1", status=JobStatus.COMPLETED, differences=None)
    self.assertEqual(job_info.differences_str, "")

    job_info = PinpointJobInfo(
        job_id="1", status=JobStatus.COMPLETED, differences=0)
    self.assertEqual(job_info.differences_str, "0")

    job_info = PinpointJobInfo(
        job_id="1", status=JobStatus.COMPLETED, differences=42)
    self.assertEqual(job_info.differences_str, "42")

  def test_status_display(self):
    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "Running",
    })
    self.assertEqual(job_info.status_display, "🏃 running")

    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "completed",
    })
    self.assertEqual(job_info.status_display, "✅ completed")

    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "queued",
    })
    self.assertEqual(job_info.status_display, "⌛ queued")

    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "cancelled",
    })
    self.assertEqual(job_info.status_display, "🛑 cancelled")

    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "failed",
    })
    self.assertEqual(job_info.status_display, "❌ failed")

    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "unknown_custom_state",
    })
    self.assertEqual(job_info.status_display, "unknown_custom_state")

    job_info = PinpointJobInfo(job_id="1", status=JobStatus.RUNNING)
    self.assertEqual(job_info.status_display, "🏃 running")
    self.assertEqual(job_info.status_emoji, "🏃")

    job_info = PinpointJobInfo(job_id="1", status=JobStatus.COMPLETED)
    self.assertEqual(job_info.status_display, "✅ completed")
    self.assertEqual(job_info.status_emoji, "✅")

    job_info = PinpointJobInfo(job_id="1", status=None)
    self.assertEqual(job_info.status_display, "Unknown")
    self.assertEqual(job_info.status_emoji, "")

  def test_job_type(self):
    job_info = PinpointJobInfo(
        job_id="1",
        status="completed",
        comparison_mode=ComparisonMode.PERFORMANCE)
    self.assertEqual(job_info.job_type, "bisect")

    job_info = PinpointJobInfo(
        job_id="1", status="completed", comparison_mode=ComparisonMode.TRY)
    self.assertEqual(job_info.job_type, "try")

    job_info = PinpointJobInfo(job_id="1", status="completed")
    self.assertEqual(job_info.job_type, "")

    job_info = PinpointJobInfo(
        job_id="1", status="completed", comparison_mode=None)
    self.assertEqual(job_info.job_type, "")

  def test_time_formatting(self):
    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "created": "2024-01-01T12:00:00Z",
        "started": "2024-01-01T12:05:00+00:00",
        "completed": "invalid-time",
    })
    self.assertEqual(job_info.formatted_created, "2024-01-01 12:00:00")
    self.assertEqual(job_info.formatted_started, "2024-01-01 12:05:00")
    self.assertEqual(job_info.formatted_completed, "invalid-time")

  def test_to_status_entries(self):
    job_info = PinpointJobInfo.from_json(_SAMPLE_JOB_DATA)
    entries = job_info.to_status_entries()
    labels = [k for k, _ in entries]
    expected_labels = [
        "Job ID",
        "Status",
        "URL",
        "Type",
        "Benchmark",
        "Bot",
        "Story",
        "Bug",
        "User",
        "Created",
        "Started",
        "Completed",
        "Progress",
        "Differences",
        "Results URL",
        "Cancel Reason",
    ]
    self.assertEqual(labels, expected_labels)
    entry_dict = dict(entries)
    self.assertEqual(entry_dict["Job ID"], "1234567890")
    self.assertEqual(entry_dict["Status"], "🏃 running")
    self.assertEqual(entry_dict["Type"], "try")
    self.assertEqual(entry_dict["Benchmark"], "speedometer3")
    self.assertEqual(entry_dict["Bot"], "linux-perf")
    self.assertEqual(entry_dict["Story"], "Speedometer3")
    self.assertEqual(entry_dict["Bug"], "9999")
    self.assertEqual(entry_dict["User"], "tester@example.com")
    self.assertEqual(entry_dict["Created"], "2024-01-01 12:00:00")
    self.assertEqual(entry_dict["Started"], "2024-01-01 12:01:00")
    self.assertEqual(entry_dict["Completed"], "2024-01-01 12:30:00")
    self.assertEqual(entry_dict["Progress"], "3/20 (15%)")
    self.assertEqual(entry_dict["Differences"], "0")
    self.assertIn("https://storage.cloud.google.com/results.html",
                  entry_dict["Results URL"])
    self.assertEqual(entry_dict["Cancel Reason"], "User cancelled")

  def test_to_status_entries_sparse(self):
    job_info = PinpointJobInfo.from_json({
        "job_id": "simple-123",
        "status": "Queued",
    })
    entries = job_info.to_status_entries()
    labels = [k for k, _ in entries]
    self.assertEqual(labels, ["Job ID", "Status", "URL"])
    entry_dict = dict(entries)
    self.assertEqual(entry_dict["Job ID"], "simple-123")
    self.assertEqual(entry_dict["Status"], "⌛ queued")

  def test_status_helpers(self):
    running_job = PinpointJobInfo.from_json({
        "job_id": "1",
        "status": "Running",
    })
    self.assertFalse(running_job.is_terminal)
    self.assertFalse(running_job.is_failed)
    self.assertFalse(running_job.is_cancelled)
    self.assertFalse(running_job.is_completed)

    completed_job = PinpointJobInfo.from_json({
        "job_id": "2",
        "status": "Completed",
    })
    self.assertTrue(completed_job.is_terminal)
    self.assertFalse(completed_job.is_failed)
    self.assertFalse(completed_job.is_cancelled)
    self.assertTrue(completed_job.is_completed)

    failed_job = PinpointJobInfo.from_json({"job_id": "3", "status": "Failed"})
    self.assertTrue(failed_job.is_terminal)
    self.assertTrue(failed_job.is_failed)
    self.assertFalse(failed_job.is_cancelled)
    self.assertFalse(failed_job.is_completed)

    cancelled_job = PinpointJobInfo.from_json({
        "job_id": "4",
        "status": "Cancelled",
    })
    self.assertTrue(cancelled_job.is_terminal)
    self.assertFalse(cancelled_job.is_failed)
    self.assertTrue(cancelled_job.is_cancelled)
    self.assertFalse(cancelled_job.is_completed)

  def test_to_dict(self):
    job_info = PinpointJobInfo.from_json(_SAMPLE_JOB_DATA)
    job_dict = job_info.to_dict()
    self.assertEqual(job_dict, dataclasses.asdict(job_info))
    self.assertEqual(job_dict["job_id"], "1234567890")
    self.assertIs(job_dict["status"], JobStatus.RUNNING)
    self.assertIs(job_dict["comparison_mode"], ComparisonMode.TRY)
    self.assertEqual(job_dict["benchmark"], "speedometer3")
    self.assertEqual(job_dict["bot"], "linux-perf")
    self.assertEqual(job_dict["story"], "Speedometer3")
    self.assertEqual(job_dict["story_tags"], "tag1,tag2")
    self.assertEqual(job_dict["bug"], "9999")
    self.assertEqual(job_dict["user"], "tester@example.com")
    self.assertEqual(job_dict["name"], "test-run-1")
    self.assertEqual(job_dict["created"],
                     dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.UTC))
    self.assertEqual(job_dict["started"],
                     dt.datetime(2024, 1, 1, 12, 1, 0, tzinfo=dt.UTC))
    self.assertEqual(job_dict["completed"],
                     dt.datetime(2024, 1, 1, 12, 30, 0, tzinfo=dt.UTC))
    self.assertEqual(job_dict["base_commit"], "aaa111")
    self.assertEqual(job_dict["exp_commit"], "bbb222")
    self.assertEqual(job_dict["base_patch"], "https://crrev.com/c/111")
    self.assertEqual(job_dict["exp_patch"], "https://crrev.com/c/222")
    self.assertEqual(job_dict["attempts"], 10)
    self.assertEqual(job_dict["differences"], 0)
    self.assertEqual(job_dict["progress"], "3/20 (15%)")
    self.assertEqual(job_dict["results_url"],
                     "https://storage.cloud.google.com/results.html")
    self.assertEqual(job_dict["cancel_reason"], "User cancelled")

  def test_from_json_property_fallbacks(self):
    data = {
        "job_id": "1",
        "story": "top_story",
        "benchmark": "top_benchmark",
        "arguments": {
            "story": "arg_story",
            "user": "None",
            "name": "  spaced_name  ",
        },
    }
    job_info = PinpointJobInfo.from_json(data)
    self.assertEqual(job_info.story, "arg_story")
    self.assertEqual(job_info.benchmark, "top_benchmark")
    self.assertEqual(job_info.name, "spaced_name")
    self.assertIsNone(job_info.user)
    self.assertIsNone(job_info.bot)

  def test_from_json_invalid_arguments(self):
    job_info = PinpointJobInfo.from_json({
        "job_id": "1",
        "arguments": "invalid",
    })
    self.assertEqual(job_info.job_id, "1")
    self.assertIsNone(job_info.story)

  def test_from_json_progress_bisect(self):
    bisect_data = {
        "job_id":
            "1",
        "status":
            "Running",
        "comparison_mode":
            "performance",
        "state": [
            {
                "attempts": [{
                    "executions": [{}, {
                        "completed": True,
                    }],
                }],
            },
            {
                "attempts": [],
            },
        ],
    }
    job_info = PinpointJobInfo.from_json(bisect_data)
    self.assertEqual(job_info.progress, "2 commits, 1 attempt")

  def test_from_json_progress_bisect_with_start_git_hash(self):
    data = {
        "job_id": "1",
        "status": "Running",
        "arguments": {
            "start_git_hash": "abc",
        },
        "state": [{
            "attempts": [],
        }],
    }
    job_info = PinpointJobInfo.from_json(data)
    self.assertEqual(job_info.progress, "1 commit")

  def test_from_json_progress_try(self):
    data = {
        "job_id":
            "1",
        "status":
            "Running",
        "arguments": {
            "initial_attempt_count": "10",
        },
        "state": [
            {
                "attempts": [{
                    "executions": [{}, {
                        "completed": True,
                    }],
                }],
            },
            {
                "attempts": [],
            },
        ],
    }
    job_info = PinpointJobInfo.from_json(data)
    self.assertEqual(job_info.progress, "1/20 (5%)")

    # Completed status gives 100%
    data["status"] = "Completed"
    job_info = PinpointJobInfo.from_json(data)
    self.assertEqual(job_info.progress, "20/20 (100%)")

    # Fallback to completed count when initial_attempt_count is missing
    del data["arguments"]["initial_attempt_count"]
    data["status"] = "Running"
    job_info = PinpointJobInfo.from_json(data)
    self.assertEqual(job_info.progress, "1 completed")

    # No completed attempts and no initial_attempt_count returns None
    data["state"] = []
    job_info = PinpointJobInfo.from_json(data)
    self.assertIsNone(job_info.progress)

  def test_job_status(self):
    self.assertEqual(JobStatus.parse("completed"), JobStatus.COMPLETED)
    self.assertEqual(JobStatus.parse("COMPLETED"), JobStatus.COMPLETED)
    self.assertEqual(JobStatus.parse(" running "), JobStatus.RUNNING)
    self.assertIsNone(JobStatus.parse("unknown"))
    self.assertIsNone(JobStatus.parse(""))

    self.assertTrue(JobStatus.COMPLETED.is_terminal)
    self.assertTrue(JobStatus.FAILED.is_terminal)
    self.assertTrue(JobStatus.CANCELLED.is_terminal)
    self.assertFalse(JobStatus.RUNNING.is_terminal)
    self.assertFalse(JobStatus.QUEUED.is_terminal)

    self.assertTrue(JobStatus.FAILED.is_failed)
    self.assertFalse(JobStatus.COMPLETED.is_failed)

    self.assertTrue(JobStatus.CANCELLED.is_cancelled)
    self.assertFalse(JobStatus.COMPLETED.is_cancelled)

    self.assertTrue(JobStatus.COMPLETED.is_completed)
    self.assertFalse(JobStatus.FAILED.is_completed)

    self.assertEqual(JobStatus.QUEUED.status_emoji, "⌛")
    self.assertEqual(JobStatus.RUNNING.status_emoji, "🏃")
    self.assertEqual(JobStatus.COMPLETED.status_emoji, "✅")
    self.assertEqual(JobStatus.CANCELLED.status_emoji, "🛑")
    self.assertEqual(JobStatus.FAILED.status_emoji, "❌")

  def test_comparison_mode(self):
    self.assertEqual(
        ComparisonMode.parse("performance"), ComparisonMode.PERFORMANCE)
    self.assertEqual(
        ComparisonMode.parse("PERFORMANCE"), ComparisonMode.PERFORMANCE)
    self.assertEqual(ComparisonMode.parse(" try "), ComparisonMode.TRY)
    self.assertIsNone(ComparisonMode.parse("unknown"))
    self.assertIsNone(ComparisonMode.parse(""))

    self.assertTrue(ComparisonMode.PERFORMANCE.is_bisect)
    self.assertTrue(ComparisonMode.FUNCTIONAL.is_bisect)
    self.assertTrue(ComparisonMode.BISECT.is_bisect)
    self.assertFalse(ComparisonMode.TRY.is_bisect)

    self.assertEqual(ComparisonMode.PERFORMANCE.job_type, "bisect")
    self.assertEqual(ComparisonMode.FUNCTIONAL.job_type, "bisect")
    self.assertEqual(ComparisonMode.BISECT.job_type, "bisect")
    self.assertEqual(ComparisonMode.TRY.job_type, "try")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
