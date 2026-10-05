# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from unittest import mock

import requests

from crossbench.exception import MultiException
from crossbench.pinpoint.api import PINPOINT_START_JOB_API_URL
from crossbench.pinpoint.config import PinpointBisectJobConfig, \
    PinpointTryJobConfig
from crossbench.pinpoint.job_info import UrlSource
from crossbench.pinpoint.start_job import bisect_job, start_job
from tests import test_helper
from tests.crossbench.pinpoint.http_requests_mixin import MockHttpRequestsMixin


class StartJobTest(MockHttpRequestsMixin):

  def setUp(self):
    super().setUp()
    self.mock_print = self.enterContext(mock.patch("builtins.print"))

    def mock_post_side_effect(url, *args, **kwargs):
      self.assertEqual(url, PINPOINT_START_JOB_API_URL,
                       f"Unexpected URL called: {url}")
      mock_response = mock.Mock()
      mock_response.json.return_value = {
          "jobId": "123",
          "jobUrl": "https://example.com/123",
      }
      mock_response.raise_for_status.return_value = None
      return mock_response

    self.mock_post.side_effect = mock_post_side_effect

  def test_start_job_correct_parameters(self):
    start_job(
        config=PinpointTryJobConfig.parse(
            json.dumps({
                "benchmark": "test_benchmark",
                "bot": "test_bot",
                "story": "test_story",
                "story_tags": "test_tag",
                "repeat": 42,
                "bug": 123456789,
                "base": {
                    "commit": "HEAD",
                    "patch": "https://chromium-review.googlesource.com/12345",
                    "flags": "--test-flag --js-flags=--base-js-flag",
                },
                "experiment": {
                    "commit": "abcd1234",
                    "patch": "https://chromium-review.googlesource.com/67890",
                    "flags": "--js-flags=--exp-js-flag",
                },
            })))
    expected_payload = {
        "comparison_mode":
            "try",
        "benchmark":
            "test_benchmark",
        "configuration":
            "test_bot",
        "story":
            "test_story",
        "story_tags":
            "test_tag",
        "initial_attempt_count":
            42,
        "bug_id":
            123456789,
        "base_git_hash":
            "HEAD",
        "end_git_hash":
            "abcd1234",
        "base_patch":
            "https://chromium-review.googlesource.com/12345",
        "experiment_patch":
            "https://chromium-review.googlesource.com/67890",
        "base_extra_args":
            '--extra-browser-args="--test-flag --js-flags=--base-js-flag"',
        "experiment_extra_args":
            '--extra-browser-args="--js-flags=--exp-js-flag"',
        "tags":
            '{"origin": "pinpoint_cli"}',
    }
    self.mock_post.assert_called_with(
        PINPOINT_START_JOB_API_URL, data=expected_payload)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/l_/r/123",
        })

  def test_start_job_url_source_pinpoint_classic(self):
    start_job(
        config=PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
        ),
        url_source=UrlSource.PINPOINT_CLASSIC)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/j_/123",
        })

  def test_start_job_url_source_leszek_perf(self):
    start_job(
        config=PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
        ),
        url_source=UrlSource.LESZEK_PERF)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/l_/r/123",
        })

  def test_start_job_url_source_leszek_perf_dev(self):
    start_job(
        config=PinpointTryJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
        ),
        url_source=UrlSource.LESZEK_PERF_DEV)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "https://leszek-perf-dev.corp.goog/r/123",
        })

  def test_bisect_job_includes_short_url(self):
    bisect_job(
        config=PinpointBisectJobConfig.parse(
            json.dumps({
                "benchmark": "test_benchmark",
                "bot": "test_bot",
                "chart": "test_chart",
                "start": {
                    "commit": "HEAD",
                },
                "end": {
                    "commit": "abcd1234",
                },
            })))
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/l_/r/123",
        })

  def test_bisect_job_url_source_pinpoint_classic(self):
    bisect_job(
        config=PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            chart="test_chart",
        ),
        url_source=UrlSource.PINPOINT_CLASSIC)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/j_/123",
        })

  def test_bisect_job_url_source_leszek_perf(self):
    bisect_job(
        config=PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            chart="test_chart",
        ),
        url_source=UrlSource.LESZEK_PERF)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "http://go/l_/r/123",
        })

  def test_bisect_job_url_source_leszek_perf_dev(self):
    bisect_job(
        config=PinpointBisectJobConfig(
            benchmark="test_benchmark",
            bot="test_bot",
            chart="test_chart",
        ),
        url_source=UrlSource.LESZEK_PERF_DEV)
    self.assertEqual(self.mock_print.call_count, 2)
    output_data = json.loads(self.mock_print.call_args[0][0])
    self.assertEqual(
        output_data, {
            "jobId": "123",
            "jobUrl": "https://example.com/123",
            "shortJobUrl": "https://leszek-perf-dev.corp.goog/r/123",
        })

  def test_start_job_api_error(self):
    self.mock_post.side_effect = requests.exceptions.HTTPError("API Error")
    with self.assertRaises(MultiException):
      start_job(
          PinpointTryJobConfig(
              benchmark="test_benchmark",
              bot="test_bot",
          ))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
