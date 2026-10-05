# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from immutabledict import immutabledict

from crossbench.cli.ui import ui
from crossbench.helper import txt_helper
from crossbench.parse import NumberParser, ObjectParser
from crossbench.pinpoint.api import JOB_SHORTEN_URL_TEMPLATE, \
    LESZEK_PERF_DEV_JOB_URL_TEMPLATE, LESZEK_PERF_JOB_SHORT_URL_TEMPLATE, \
    PINPOINT_JOB_URL_TEMPLATE
from crossbench.pinpoint.format_time import format_datetime

if TYPE_CHECKING:
  import datetime as dt

  from typing_extensions import Self

  from crossbench.types import JsonDict


class JobStatus(enum.StrEnum):
  QUEUED = "queued"
  RUNNING = "running"
  COMPLETED = "completed"
  CANCELLED = "cancelled"
  FAILED = "failed"

  @classmethod
  def parse(cls, value: Any) -> JobStatus | None:
    if isinstance(value, cls):
      return value
    if not isinstance(value, str):
      return None
    try:
      return cls(value.lower().strip())
    except ValueError:
      return None

  @property
  def status_emoji(self) -> str:
    return _STATUS_EMOJI_LOOKUP.get(self, "")

  @property
  def is_terminal(self) -> bool:
    return self in (
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    )

  @property
  def is_failed(self) -> bool:
    return self is JobStatus.FAILED

  @property
  def is_cancelled(self) -> bool:
    return self is JobStatus.CANCELLED

  @property
  def is_completed(self) -> bool:
    return self is JobStatus.COMPLETED


_STATUS_EMOJI_LOOKUP: Final[immutabledict[str, str]] = immutabledict({
    JobStatus.QUEUED: "⌛",
    JobStatus.RUNNING: "🏃",
    JobStatus.COMPLETED: "✅",
    JobStatus.CANCELLED: "🛑",
    JobStatus.FAILED: "❌",
})


class ComparisonMode(enum.StrEnum):
  PERFORMANCE = "performance"
  FUNCTIONAL = "functional"
  BISECT = "bisect"
  TRY = "try"

  @classmethod
  def parse(cls, value: Any) -> ComparisonMode | None:
    if isinstance(value, cls):
      return value
    if not isinstance(value, str):
      return None
    try:
      return cls(value.lower().strip())
    except ValueError:
      return None

  @property
  def is_bisect(self) -> bool:
    return self in (
        ComparisonMode.PERFORMANCE,
        ComparisonMode.FUNCTIONAL,
        ComparisonMode.BISECT,
    )

  @property
  def job_type(self) -> str:
    if self.is_bisect:
      return "bisect"
    return self.value


class UrlSource(enum.StrEnum):
  LESZEK_PERF = "leszek-perf"
  PINPOINT_CLASSIC = "pinpoint-classic"
  LESZEK_PERF_DEV = "leszek-perf-dev"

  @classmethod
  def all(cls) -> tuple[UrlSource, ...]:
    return tuple(cls)

  def format_short_job_url(self, job_id: str) -> str:
    if self == UrlSource.PINPOINT_CLASSIC:
      return JOB_SHORTEN_URL_TEMPLATE.format(job_id=job_id)
    if self == UrlSource.LESZEK_PERF_DEV:
      return LESZEK_PERF_DEV_JOB_URL_TEMPLATE.format(job_id=job_id)
    return LESZEK_PERF_JOB_SHORT_URL_TEMPLATE.format(job_id=job_id)


_DefaultT = TypeVar("_DefaultT")


@dataclasses.dataclass(frozen=True)
class PinpointJobInfo:
  """Normalized, parsed representation of a Pinpoint job from API response."""
  job_id: str
  status: JobStatus | None = None
  comparison_mode: ComparisonMode | None = None
  user: str | None = None
  name: str | None = None
  benchmark: str | None = None
  bot: str | None = None
  story: str | None = None
  story_tags: str | None = None
  bug: str | None = None
  created: dt.datetime | None = None
  started: dt.datetime | None = None
  completed: dt.datetime | None = None
  base_commit: str | None = None
  exp_commit: str | None = None
  base_patch: str | None = None
  exp_patch: str | None = None
  attempts: int | None = None
  progress: str | None = None
  differences: int | None = None
  results_url: str | None = None
  cancel_reason: str | None = None
  raw_data: dict[str, Any] = dataclasses.field(
      default_factory=dict, repr=False, compare=False)

  @classmethod
  def _parse_arguments(cls, data: JsonDict) -> JsonDict:
    raw_arguments = data.get("arguments")
    if isinstance(raw_arguments, dict):
      return raw_arguments
    return {}

  @classmethod
  def _parse_property(
      cls,
      data: JsonDict,
      *keys: str,
      default: _DefaultT = cast(Any, None),
  ) -> str | _DefaultT:
    arguments = cls._parse_arguments(data)
    for key in keys:
      val = arguments.get(key)
      if not val:
        val = data.get(key)
      if val:
        val_str = str(val).strip()
        if val_str and val_str != "None":
          return val_str
    return default

  @classmethod
  def _is_execution_completed(cls, execution: Any) -> bool:
    if not isinstance(execution, dict):
      return False
    return bool(execution.get("completed") or execution.get("result"))

  @classmethod
  def _is_attempt_completed(cls, attempt: JsonDict) -> bool:
    executions = attempt.get("executions")
    if not isinstance(executions, list):
      return False
    if len(executions) >= 2:
      return True
    return any(cls._is_execution_completed(e) for e in executions)

  @classmethod
  def _parse_completed_attempts_counts(cls, state: list[Any]) -> int:
    completed_attempts = 0
    for variant in state:
      if not isinstance(variant, dict):
        continue
      attempts = variant.get("attempts")
      if not isinstance(attempts, list):
        continue
      for attempt in attempts:
        if isinstance(attempt, dict) and cls._is_attempt_completed(attempt):
          completed_attempts += 1
    return completed_attempts

  @classmethod
  def _format_bisect_progress(cls, total_variants: int,
                              completed_attempts: int) -> str:
    commits_unit = txt_helper.plural_str(total_variants, "commit")
    if completed_attempts > 0:
      attempts_unit = txt_helper.plural_str(completed_attempts, "attempt")
      return (f"{total_variants} {commits_unit}, "
              f"{completed_attempts} {attempts_unit}")
    return f"{total_variants} {commits_unit}"

  @classmethod
  def _format_expected_progress(cls, expected_per_variant: int,
                                total_variants: int, completed_attempts: int,
                                is_completed: bool) -> str:
    total_expected = expected_per_variant * total_variants
    if is_completed:
      return f"{total_expected}/{total_expected} (100%)"
    percent = ""
    if total_expected > 0:
      percent = f" ({round(100 * completed_attempts / total_expected)}%)"
    return f"{completed_attempts}/{total_expected}{percent}"

  @classmethod
  def _is_bisect_job(cls, data: JsonDict, arguments: JsonDict) -> bool:
    comparison_mode = ComparisonMode.parse(
        cls._parse_property(data, "comparison_mode"))
    if comparison_mode and comparison_mode.is_bisect:
      return True
    return "start_git_hash" in arguments

  @classmethod
  def _parse_try_progress(cls, data: JsonDict, arguments: JsonDict,
                          total_variants: int,
                          completed_attempts: int) -> str | None:
    expected_per_variant = NumberParser.optional_int(
        arguments.get("initial_attempt_count"))
    if expected_per_variant is not None:
      status = str(data.get("status", "")).lower().strip()
      return cls._format_expected_progress(
          expected_per_variant,
          total_variants,
          completed_attempts,
          is_completed=(status == "completed"),
      )
    if completed_attempts > 0:
      return f"{completed_attempts} completed"
    return None

  @classmethod
  def _parse_progress(cls, data: JsonDict) -> str | None:
    state = data.get("state")
    if not isinstance(state, list):
      return None

    total_variants = len(state)
    completed_attempts = cls._parse_completed_attempts_counts(state)
    arguments = cls._parse_arguments(data)

    if cls._is_bisect_job(data, arguments):
      return cls._format_bisect_progress(total_variants, completed_attempts)

    return cls._parse_try_progress(data, arguments, total_variants,
                                   completed_attempts)

  @classmethod
  def _parse_datetime(cls, value: Any) -> dt.datetime | None:
    with contextlib.suppress(argparse.ArgumentTypeError):
      return ObjectParser.optional_datetime(value)
    return None

  @classmethod
  def from_json(cls, data: JsonDict) -> Self:
    arguments = cls._parse_arguments(data)
    status = JobStatus.parse(data.get("status"))
    comparison_mode = ComparisonMode.parse(
        cls._parse_property(data, "comparison_mode"))
    return cls(
        job_id=str(data.get("job_id", "")),
        status=status,
        comparison_mode=comparison_mode,
        user=cls._parse_property(data, "user"),
        name=cls._parse_property(data, "name"),
        benchmark=cls._parse_property(data, "benchmark"),
        bot=cls._parse_property(data, "configuration", "bot"),
        story=cls._parse_property(data, "story"),
        story_tags=cls._parse_property(data, "story_tags"),
        bug=cls._parse_property(data, "bug_id", "bug"),
        created=cls._parse_datetime(data.get("created")),
        started=cls._parse_datetime(data.get("started")),
        completed=cls._parse_datetime(data.get("completed")),
        base_commit=cls._parse_property(data, "base_git_hash"),
        exp_commit=cls._parse_property(data, "end_git_hash"),
        base_patch=cls._parse_property(data, "base_patch"),
        exp_patch=cls._parse_property(data, "experiment_patch"),
        attempts=NumberParser.optional_int(
            arguments.get("initial_attempt_count", arguments.get("attempts"))),
        progress=cls._parse_progress(data),
        differences=NumberParser.optional_int(
            data.get("difference_count", data.get("differences"))),
        results_url=cls._parse_property(data, "results_url"),
        cancel_reason=cls._parse_property(data, "cancel_reason"),
        raw_data=data,
    )

  @property
  def url(self) -> str:
    return PINPOINT_JOB_URL_TEMPLATE.format(job_id=self.job_id)

  @property
  def short_url(self) -> str:
    return UrlSource.LESZEK_PERF.format_short_job_url(self.job_id)

  @property
  def short_url_link(self) -> str:
    return ui.link(self.short_url)

  @property
  def job_type(self) -> str:
    if self.comparison_mode:
      return self.comparison_mode.job_type
    return ""

  @property
  def status_emoji(self) -> str:
    if self.status:
      return self.status.status_emoji
    return ""

  @property
  def is_terminal(self) -> bool:
    if self.status:
      return self.status.is_terminal
    return False

  @property
  def is_failed(self) -> bool:
    if self.status:
      return self.status.is_failed
    return False

  @property
  def is_cancelled(self) -> bool:
    if self.status:
      return self.status.is_cancelled
    return False

  @property
  def is_completed(self) -> bool:
    if self.status:
      return self.status.is_completed
    return False

  @property
  def status_display(self) -> str:
    if self.status:
      if emoji := self.status.status_emoji:
        return f"{emoji} {self.status}"
      return str(self.status)
    if raw := self.raw_data.get("status"):
      return str(raw)
    return "Unknown"

  def _format_time(self, time_val: dt.datetime | None, raw_key: str) -> str:
    if time_val:
      return format_datetime(time_val)
    if raw := self.raw_data.get(raw_key):
      return str(raw)
    return ""

  @property
  def formatted_created(self) -> str:
    return self._format_time(self.created, "created")

  @property
  def formatted_started(self) -> str:
    return self._format_time(self.started, "started")

  @property
  def formatted_completed(self) -> str:
    return self._format_time(self.completed, "completed")

  @property
  def differences_str(self) -> str:
    if self.differences is not None:
      return str(self.differences)
    return ""

  @property
  def formatted_results_url(self) -> str:
    if self.results_url:
      return ui.link(self.results_url)
    return ""

  def to_status_entries(self) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str | None]] = [
        ("Job ID", self.job_id),
        ("Status", self.status_display),
        ("URL", self.short_url_link),
        ("Type", self.job_type or None),
        ("Benchmark", self.benchmark),
        ("Bot", self.bot),
        ("Story", self.story),
        ("Bug", self.bug),
        ("User", self.user),
        ("Created", self.formatted_created or None),
        ("Started", self.formatted_started or None),
        ("Completed", self.formatted_completed or None),
        ("Progress", self.progress),
        ("Differences", self.differences_str or None),
        ("Results URL", self.formatted_results_url or None),
        ("Cancel Reason", self.cancel_reason),
    ]
    return tuple((k, v) for k, v in entries if v is not None)

  def to_dict(self) -> JsonDict:
    return dataclasses.asdict(self)
