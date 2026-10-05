# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from crossbench.pinpoint import http_requests
from crossbench.pinpoint.api import PINPOINT_START_JOB_API_URL
from crossbench.pinpoint.helper import annotate
from crossbench.pinpoint.job_info import UrlSource

if TYPE_CHECKING:
  from crossbench.pinpoint.config import PinpointBisectJobConfig, \
      PinpointTryJobConfig


def _print_started_job(
    data: dict[str, Any],
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> None:
  if job_id := data.get("jobId"):
    data = dict(data)
    data.setdefault("shortJobUrl", url_source.format_short_job_url(job_id))
  print(json.dumps(data, indent=2))


def start_job(
    config: PinpointTryJobConfig,
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> None:
  """Starts a new Pinpoint job."""
  with annotate("Starting Pinpoint job"):
    response = http_requests.post(
        PINPOINT_START_JOB_API_URL, data=config.to_request_dict())
    response.raise_for_status()
  _print_started_job(response.json(), url_source=url_source)


def bisect_job(
    config: PinpointBisectJobConfig,
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> None:
  """Starts a new Pinpoint bisect job."""
  with annotate("Starting Pinpoint bisect job"):
    response = http_requests.post(
        PINPOINT_START_JOB_API_URL, data=config.to_request_dict())
    response.raise_for_status()
  _print_started_job(response.json(), url_source=url_source)
