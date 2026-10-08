# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import datetime
import logging
from typing import TYPE_CHECKING, Any

import requests
from tabulate import tabulate

from crossbench.helper.collection_helper import close_matches_message
from crossbench.pinpoint import http_requests
from crossbench.pinpoint.api import PINPOINT_BUILDS_API_URL_TEMPLATE
from crossbench.pinpoint.format_time import DATETIME_FORMAT, format_time
from crossbench.pinpoint.helper import annotate
from crossbench.pinpoint.list_bots import fetch_bots

if TYPE_CHECKING:
  from crossbench.types import TableData


@dataclasses.dataclass(frozen=True)
class Build:
  """Represents a Pinpoint build.

  Attributes:
    commit: The hash of the commit associated with the build.
    date: The date and time when the build was created in format
      "%Y-%m-%d %H:%M:%S".
  """
  commit: str
  number: int
  date: str


def list_builds(bot: str, limit: int) -> None:
  """Fetches and displays recent successful builds for a given bot."""
  builds = fetch_builds(bot)
  _display_builds(builds[:limit])


def fetch_builds(bot: str) -> list[Build]:
  if not bot:
    raise ValueError(
        "Bot is required. Run 'cb pp bots' to list all available bots.")
  url = PINPOINT_BUILDS_API_URL_TEMPLATE.format(bot=bot)

  with annotate(f"Fetching recent builds for '{bot}'"):
    try:
      response = http_requests.get(url)
      response.raise_for_status()
      return _convert_json_to_builds(response.json())
    except requests.exceptions.HTTPError as e:
      if e.response is not None and e.response.status_code == 400:
        available_bots = fetch_bots()
        msg, _ = close_matches_message(bot, available_bots, "bot")
        raise ValueError(
            f"{msg}\nRun 'cb pp bots' to list all available bots.") from e
      raise


def _convert_json_to_builds(builds_json: dict[str, Any]) -> list[Build]:
  builds = []
  for build in builds_json["builds"]:
    if build.get("status") != "SUCCESS":
      continue

    number = build.get("number", 0)
    commit = build.get("input", {}).get("gitilesCommit", {}).get("id")
    if not commit:
      continue

    end_time = build.get("endTime")
    if not end_time:
      continue
    try:
      datetime_obj = datetime.datetime.fromisoformat(
          end_time.replace("Z", "+00:00"))
      date = datetime_obj.strftime(DATETIME_FORMAT)
    except ValueError:
      logging.warning("Invalid date format: %s", end_time)
      continue

    builds.append(Build(commit=commit, number=number, date=date))

  builds.sort(key=lambda build: build.number, reverse=True)
  return builds


def _display_builds(builds: list[Build]) -> None:
  headers = ["Commit", "Number", "Date"]
  table_data: TableData = [[
      build.commit,
      str(build.number),
      format_time(build.date),
  ] for build in builds]
  print(tabulate(table_data, headers=headers, numalign="left"))
