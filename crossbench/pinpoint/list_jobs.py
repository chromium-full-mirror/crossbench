# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import itertools
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final, Mapping

import yaml
from immutabledict import immutabledict
from ordered_set import OrderedSet
from tabulate import tabulate

from crossbench.pinpoint import http_requests
from crossbench.pinpoint.api import PINPOINT_JOBS_API_URL, USERINFO_API_URL
from crossbench.pinpoint.format_time import DATETIME_FORMAT, format_time
from crossbench.pinpoint.helper import annotate
from crossbench.pinpoint.job_info import UrlSource
from crossbench.pinpoint.output_format import OutputFormat, write_delimited
from crossbench.pinpoint.user import UserEnum


class Column:

  def __init__(self, name: str, description: str, json_field: str = "") -> None:
    self.name = name
    self.json_field = json_field or name
    self.description = description


EXTRA_COLUMNS: Final[list[Column]] = [
    Column(
        name="user",
        description="The email address of the user created the job.",
    ),
    Column(
        name="name",
        description="The name of the job.",
    ),
    Column(
        name="base_commit",
        json_field="base_git_hash",
        description="The Git commit hash of the base revision.",
    ),
    Column(
        name="exp_commit",
        json_field="end_git_hash",
        description="The Git commit hash of the experiment revision.",
    ),
    Column(
        name="base_patch",
        description="The Gerrit patch URL applied to the base variant.",
    ),
    Column(
        name="exp_patch",
        json_field="experiment_patch",
        description="The Gerrit patch URL applied to the experiment.",
    ),
    Column(
        name="story",
        description="The tested story within the benchmark.",
    ),
    Column(
        name="attempts",
        json_field="initial_attempt_count",
        description="The number of times the job ran the test.",
    ),
    Column(
        name="bug",
        json_field="bug_id",
        description="The buganier ID associated with the job.",
    ),
    Column(
        name="differences",
        json_field="difference_count",
        description="The number of regressions found for bisection jobs.",
    ),
]

EXTRA_COLUMNS_DICT: Final[immutabledict[str, Column]] = immutabledict(
    {c.name: c for c in EXTRA_COLUMNS})


def list_jobs(
    user: UserEnum | str,
    number: int,
    truncate: int | None,
    output_format: OutputFormat,
    extra_columns: list[str] | None = None,
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> None:
  extra_columns = extra_columns or []
  emails_to_query = _fetch_user_emails(user)

  jobs = []
  with annotate("Fetching jobs"), ThreadPoolExecutor() as executor:
    results = executor.map(lambda email: _fetch_jobs(number, email),
                           emails_to_query)
    jobs = list(itertools.chain.from_iterable(results))

  jobs.sort(key=lambda job: job.get("created", ""), reverse=True)

  if not jobs:
    print("No jobs found.")
    return

  _display_jobs(jobs[:number], output_format, user == UserEnum.ALL, truncate,
                OrderedSet(extra_columns), url_source)


def _fetch_user_emails(user: UserEnum | str) -> set[str | None]:
  if user == UserEnum.ME:
    email = _get_user_email()
    username = email.split("@")[0]
    return {email, f"{username}@google.com", f"{username}@chromium.org"}
  if user == UserEnum.ALL:
    return {None}
  return {user}


def _get_user_email() -> str:
  with annotate("Fetching user-email"):
    response = http_requests.get(USERINFO_API_URL)
    response.raise_for_status()
    return response.json()["email"]


def _fetch_jobs(number: int, email: str | None = None) -> list[dict[str, Any]]:
  jobs = []
  next_cursor = None
  params = {}
  if email:
    params["filter"] = f"user={email}"

  while True:
    if next_cursor:
      params["next_cursor"] = next_cursor

    response = http_requests.get(PINPOINT_JOBS_API_URL, params=params)
    response.raise_for_status()
    data = response.json()
    jobs.extend(data.get("jobs", []))

    if len(jobs) >= number:
      return jobs[:number]

    next_cursor = data.get("next_cursor")
    if not data.get("next") or not next_cursor:
      break
  return jobs


def _prepare_job_list_data(
    jobs: list[dict[str, Any]],
    all_users: bool,
    extra_columns: OrderedSet[str],
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> tuple[list[str], list[list[Any]]]:
  if all_users and "user" not in extra_columns:
    extra_columns = OrderedSet(["user", *extra_columns])
  headers = [
      "Benchmark",
      "Config",
      "Type",
      *[c.replace("_", " ").title() for c in extra_columns],
      "Start Time",
      "Job URL",
      "Status",
  ]
  table_data = []

  for job in jobs:
    created_time = _extract_field(job, "created")
    if created_time:
      dt_object = dt.datetime.fromisoformat(created_time.replace("Z", "+00:00"))
      created_time = dt_object.strftime(DATETIME_FORMAT)

    row = [
        _extract_field(job, "benchmark"),
        _extract_field(job, "configuration"),
        _extract_field(job, "comparison_mode"),
        *[_extract_field(job, _to_json_field(col)) for col in extra_columns],
        created_time,
        url_source.format_short_job_url(_extract_field(job, "job_id")),
        _extract_field(job, "status"),
    ]
    table_data.append(row)
  return headers, table_data


def _to_json_field(column_name: str) -> str:
  column = EXTRA_COLUMNS_DICT.get(column_name)
  if not column:
    raise ValueError(f"Unknown column name: {column_name}")
  return column.json_field


def _extract_field(job: dict[str, Any], field_name: str) -> str:
  if value := job.get(field_name, ""):
    return str(value)
  return str(job.get("arguments", {}).get(field_name, ""))


def _display_jobs(
    jobs: list[dict[str, Any]],
    output_format: OutputFormat,
    all_users: bool,
    truncate: int | None,
    extra_columns: OrderedSet[str],
    url_source: UrlSource = UrlSource.LESZEK_PERF,
) -> None:
  match output_format:
    case OutputFormat.JSON:
      print(json.dumps(jobs, indent=2))
    case OutputFormat.YAML:
      print(yaml.dump(jobs))
    case OutputFormat.CSV | OutputFormat.TSV:
      headers, rows = _prepare_job_list_data(jobs, all_users, extra_columns,
                                             url_source)
      write_delimited(
          sys.stdout, headers, rows, delimiter=output_format.delimiter)
    case OutputFormat.TABLE:
      headers, rows = _prepare_job_list_data(jobs, all_users, extra_columns,
                                             url_source)
      _display_jobs_as_table(headers, rows, truncate)


def _display_jobs_as_table(headers: list[str], rows: list,
                           max_length: int | None) -> None:
  table_data = [[truncate(cell, max_length) for cell in row] for row in rows]
  url_index = headers.index("Job URL")
  type_index = headers.index("Type")
  time_index = headers.index("Start Time")
  status_index = headers.index("Status")
  for row in table_data:
    row[url_index] = _format_link(row[url_index])
    row[type_index] = _format_type(row[type_index])
    row[time_index] = format_time(row[time_index])
    row[status_index] = _format_status(row[status_index])
  headers[status_index] = "🚦"
  print(tabulate(table_data, headers=headers))


def _format_link(url: str) -> str:
  text = url
  osc8_start = "\x1b]8;;"
  osc8_end = "\x1b\\"
  return f"{osc8_start}{url}{osc8_end}{text}{osc8_start}{osc8_end}"


JOB_TYPE_LOOKUP: Final[Mapping[str, str]] = {
    "performance": "bisect",
    "try": "try",
}


def _format_type(job_type: str) -> str:
  lookup_str = job_type.lower().strip()
  return JOB_TYPE_LOOKUP.get(lookup_str, job_type)


STATUS_EMOJI_LOOKUP: Final[Mapping[str, str]] = {
    "queued": "⌛",
    "running": "🏃",
    "completed": "✅",
    # An extra space is added because this emoji eats a space from the right.
    "cancelled": "⏹️ ",
    "failed": "❌",
}


def _format_status(status: str) -> str:
  lookup_str = status.lower().strip()
  return STATUS_EMOJI_LOOKUP.get(lookup_str, status)


def truncate(text: str, max_length: int | None = None) -> str:
  text = str(text)
  if max_length and len(text) > max_length:
    if max_length <= 3:
      return text[:max_length]
    return text[:max_length - 3] + "..."
  return text
