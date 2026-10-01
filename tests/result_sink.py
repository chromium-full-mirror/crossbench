# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import base64
import enum
import functools
import html
import json
import os
import sys
import traceback
import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
import requests
from immutabledict import immutabledict

from crossbench import path as pth

if TYPE_CHECKING:
  from collections.abc import Generator, Mapping, Sequence

REPO_URL: Final[str] = "https://chromium.googlesource.com/crossbench"
NODE_ID_SEPARATOR: Final[str] = "::"


class LuciContext:
  """Handles reading, caching, and accessing LUCI_CONTEXT data."""

  @classmethod
  @functools.lru_cache(maxsize=32)
  def _load_dict_from_file(cls, path: str) -> Mapping[str, Any]:
    luci_ctx_file = pth.LocalPath(path)
    with luci_ctx_file.open(encoding="utf-8") as f:
      data = json.load(f)
    assert isinstance(data,
                      dict), f"LUCI_CONTEXT must be a dict, got {type(data)}"
    return data

  @classmethod
  def clear_cache(cls) -> None:
    cls._load_dict_from_file.cache_clear()

  @classmethod
  def from_file(cls, path: str) -> LuciContext:
    return cls(cls._load_dict_from_file(path))

  @classmethod
  def from_env(cls) -> LuciContext | None:
    if luci_ctx_path := os.environ.get("LUCI_CONTEXT"):
      return cls.from_file(luci_ctx_path)
    return None

  def __init__(self, data: Mapping[str, Any]) -> None:
    assert isinstance(data,
                      dict), f"LUCI_CONTEXT must be a dict, got {type(data)}"
    self._data: Final[Mapping[str, Any]] = data

  @property
  def data(self) -> Mapping[str, Any]:
    return self._data

  def section(self, key: str) -> Mapping[str, Any] | None:
    section = self._data.get(key)
    if not isinstance(section, dict):
      return None
    return section

  @property
  def result_sink(self) -> _ResultSinkContext | None:
    sink_ctx = self.section("result_sink")
    if not sink_ctx:
      return None
    address = sink_ctx.get("address")
    auth_token = sink_ctx.get("auth_token")
    if not (address and auth_token):
      return None
    return _ResultSinkContext(str(address), str(auth_token))


class _ResultSinkContext(NamedTuple):
  address: str
  auth_token: str


class ResultStatus(enum.StrEnum):
  """LUCI ResultDB test result status values."""
  PASS = "PASS"
  FAIL = "FAIL"
  SKIP = "SKIP"
  CRASH = "CRASH"
  ABORT = "ABORT"


class PytestReportWhen(enum.StrEnum):
  """Execution phase ('when') matching pytest.TestReport.when Literals."""
  SETUP = "setup"
  CALL = "call"
  TEARDOWN = "teardown"


class PytestReportOutcome(enum.StrEnum):
  """Outcome matching pytest.TestReport.outcome Literals."""
  PASSED = "passed"
  FAILED = "failed"
  SKIPPED = "skipped"


class ArtifactId(enum.StrEnum):
  """Artifact IDs uploaded alongside test results to LUCI ResultSink."""
  TRACEBACK = "traceback"
  STDERR = "stderr"
  STDOUT = "stdout"
  LOG = "log"


OUTCOME_TO_STATUS: Final[immutabledict[str, ResultStatus]] = immutabledict({
    PytestReportOutcome.PASSED: ResultStatus.PASS,
    PytestReportOutcome.FAILED: ResultStatus.FAIL,
    PytestReportOutcome.SKIPPED: ResultStatus.SKIP,
})

TRUNCATED_SUFFIX: Final[str] = "\n...\n[Truncated]"
MAX_FAILURE_REASON_BYTES: Final[int] = 1024
RESULTS_BATCH_SIZE: Final[int] = 200
HTTP_TIMEOUT_SECONDS: Final[int] = 10

NAV_HTML_TEMPLATE: Final[str] = (
    '<p><a href="?q=">View all test results in build</a> | '
    '<a href="?q={encoded_file}">View all tests in {escaped_file}</a></p>')
SECTION_HTML_TEMPLATE: Final[str] = (
    "<h3>{escaped_title}</h3>"
    '<pre><text-artifact artifact-id="{artifact_id}"></text-artifact></pre>')


class _PytestTupleLongrepr(NamedTuple):
  """Representation of pytest's 3-tuple longrepr (e.g. from skips/subtests)."""
  path: str
  lineno: int
  message: str


class _ArtifactSection(NamedTuple):
  artifact_id: str
  title: str
  content: str


class _ArtifactsAndSummary(NamedTuple):
  artifacts: dict[str, dict[str, str]]
  summary_html: str


class ResultSinkTracebackPlugin:
  """Worker/controller plugin that attaches full Python tracebacks on failure.

  Registered only when ResultDB/ResultSink is enabled in LUCI_CONTEXT.
  See: https://docs.pytest.org/en/stable/how-to/writing_plugins.html
  """
  SECTION_NAME: Final[str] = "Python traceback"

  @pytest.hookimpl(hookwrapper=True)
  def pytest_runtest_makereport(
      self,
      item: pytest.Item,
      call: pytest.CallInfo[Any],
  ) -> Generator[None, Any, None]:
    del item
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if call.excinfo is None or report.outcome != PytestReportOutcome.FAILED:
      return
    raw_tb = "".join(
        traceback.format_exception(
            call.excinfo.type,
            call.excinfo.value,
            call.excinfo.tb,
        ))
    if raw_tb:
      report.sections.append((self.SECTION_NAME, raw_tb))

  @classmethod
  def extract_full_traceback(cls, report: pytest.TestReport) -> str:
    parts: list[str] = []
    if report.longreprtext:
      parts.append(report.longreprtext.strip())
    for _, section_content in report.get_sections(cls.SECTION_NAME):
      if stripped := section_content.strip():
        parts.append(f"--- Full Python Stack Trace ---\n{stripped}")
    return "\n\n".join(parts)


class ResultSinkPlugin:
  """Pytest plugin for uploading test results to local LUCI ResultSink."""

  def __init__(
      self,
      sink_url: str | None = None,
      auth_header: Mapping[str, str] | None = None,
      auth_token: str | None = None,
  ) -> None:
    if auth_token and not auth_header:
      auth_header = {"Authorization": f"ResultSink {auth_token}"}
    self._endpoint_url: Final[str | None] = sink_url
    # Queued ResultDB test results waiting to be uploaded in batches.
    self._pending_results: Final[list[dict[str, Any]]] = []
    # Buffered setup/call reports per test node ID awaiting teardown.
    self._test_reports: Final[dict[str, pytest.TestReport]] = {}
    self._reported_count: int = 0
    self._session: Final[requests.Session | None] = self._create_session(
        sink_url, auth_header)

  @classmethod
  def is_result_sink_enabled(
      cls,
      luci_context: LuciContext | None = None,
  ) -> bool:
    if luci_context is None:
      luci_context = LuciContext.from_env()
    return bool(luci_context and luci_context.result_sink)

  @classmethod
  def _is_xdist_worker(cls) -> bool:
    return "PYTEST_XDIST_WORKER" in os.environ

  @classmethod
  def from_env(
      cls,
      luci_context: LuciContext | None = None,
  ) -> ResultSinkPlugin | None:
    if cls._is_xdist_worker():
      return None
    if luci_context is None:
      luci_context = LuciContext.from_env()
    if not (luci_context and luci_context.result_sink):
      return None
    sink_context = luci_context.result_sink
    return cls(
        sink_url=(f"http://{sink_context.address}/prpc/luci.resultsink.v1.Sink/"
                  "ReportTestResults"),
        auth_token=sink_context.auth_token,
    )

  @classmethod
  def _create_session(
      cls,
      endpoint_url: str | None,
      auth_header: Mapping[str, str] | None,
  ) -> requests.Session | None:
    if not (endpoint_url and auth_header):
      return None
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        **auth_header,
    })
    return session

  @classmethod
  def truncate_summary(cls, text: str) -> str:
    # ResultDB's FailureReason.primary_error_message proto field is capped at
    # 1024 bytes.
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_FAILURE_REASON_BYTES:
      return text
    max_bytes = MAX_FAILURE_REASON_BYTES - len(TRUNCATED_SUFFIX)
    return (encoded[:max_bytes].decode("utf-8", errors="ignore") +
            TRUNCATED_SUFFIX)

  @classmethod
  def encode_text_artifact(cls, content: str) -> dict[str, str]:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return {
        "contents": encoded,
        "contentType": "text/plain; charset=utf-8",
    }

  @classmethod
  def extract_primary_error(cls, report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
      tuple_repr = _PytestTupleLongrepr(*longrepr)
      return str(tuple_repr.message)
    text = report.longreprtext.strip()
    if not text:
      return "Test failed"
    lines: list[str] = []
    for raw_line in text.splitlines():
      stripped_line = raw_line.strip()
      if stripped_line.startswith("E "):
        lines.append(stripped_line[2:].strip())
    if lines:
      return "\n".join(lines)
    return text

  @classmethod
  def resolve_repo_rel_path(cls, path_str: str) -> str:
    file_path = pth.LocalPath(path_str)
    if not file_path.is_absolute():
      candidate = pth.ROOT_DIR / file_path
      file_tests_path = pth.ROOT_DIR / "tests" / file_path
      if not candidate.exists() and file_tests_path.exists():
        file_path = file_tests_path
      else:
        file_path = candidate
    try:
      rel_path = file_path.relative_to(pth.ROOT_DIR).as_posix()
    except ValueError:
      rel_path = pth.LocalPath(path_str).as_posix()
    return rel_path.lstrip("/")

  @classmethod
  def format_test_id(cls, nodeid: str) -> str:
    clean = nodeid.lstrip("/")
    file_part, sep, rest = clean.partition(NODE_ID_SEPARATOR)
    resolved_file = cls.resolve_repo_rel_path(file_part)
    if sep:
      return f"{resolved_file}{sep}{rest}"
    return resolved_file

  def _collect_artifact_sections(
      self,
      report: pytest.TestReport,
  ) -> list[_ArtifactSection]:
    candidates = (
        (ArtifactId.TRACEBACK, "Stack Trace",
         ResultSinkTracebackPlugin.extract_full_traceback(report)),
        (ArtifactId.STDERR, "Captured stderr", report.capstderr),
        (ArtifactId.STDOUT, "Captured stdout", report.capstdout),
        (ArtifactId.LOG, "Captured log", report.caplog),
    )
    return [
        _ArtifactSection(artifact_id, title, content)
        for artifact_id, title, content in candidates
        if content
    ]

  @property
  def enabled(self) -> bool:
    return self._session is not None

  def _build_nav_html(self, rel_path: str) -> str:
    encoded_file = urllib.parse.quote(rel_path, safe="")
    return NAV_HTML_TEMPLATE.format(
        encoded_file=encoded_file,
        escaped_file=html.escape(rel_path),
    )

  def _build_artifact_sections(
      self,
      sections: Sequence[_ArtifactSection],
      nav_html: str,
  ) -> _ArtifactsAndSummary:
    artifacts: dict[str, dict[str, str]] = {}
    html_parts: list[str] = [nav_html]
    for section in sections:
      artifacts[section.artifact_id] = self.encode_text_artifact(
          section.content)
      html_parts.append(
          SECTION_HTML_TEMPLATE.format(
              escaped_title=html.escape(section.title),
              artifact_id=section.artifact_id,
          ))
    return _ArtifactsAndSummary(artifacts, "".join(html_parts))

  def _build_artifacts_and_summary(
      self,
      report: pytest.TestReport,
      rel_path: str,
  ) -> _ArtifactsAndSummary:
    nav_html = self._build_nav_html(rel_path)
    if report.outcome == PytestReportOutcome.PASSED:
      return _ArtifactsAndSummary({}, nav_html)

    sections = self._collect_artifact_sections(report)
    if not sections:
      return _ArtifactsAndSummary({}, nav_html)

    return self._build_artifact_sections(sections, nav_html)

  def build_test_result(self, report: pytest.TestReport) -> dict[str, Any]:
    status = OUTCOME_TO_STATUS.get(report.outcome, ResultStatus.FAIL)
    expected = report.outcome in (PytestReportOutcome.PASSED,
                                  PytestReportOutcome.SKIPPED)
    fspath, lineno, _ = report.location
    rel_path = self.resolve_repo_rel_path(fspath)
    location: dict[str, Any] = {
        "repo": REPO_URL,
        "fileName": f"//{rel_path}",
    }
    if lineno is not None and lineno >= 0:
      location["line"] = lineno + 1

    result_id = uuid.uuid4().hex[:16]
    test_id = self.format_test_id(report.nodeid)
    test_result: dict[str, Any] = {
        "testId": test_id,
        "resultId": result_id,
        "status": status.value,
        "expected": expected,
        "duration": f"{max(0.0, float(report.duration)):.6f}s",
        "testMetadata": {
            "name": test_id,
            "location": location,
        },
    }

    if report.outcome == PytestReportOutcome.FAILED:
      primary_error = self.extract_primary_error(report)
      test_result["failureReason"] = {
          "primaryErrorMessage": self.truncate_summary(primary_error),
      }
    artifacts_and_summary = self._build_artifacts_and_summary(report, rel_path)
    if artifacts := artifacts_and_summary.artifacts:
      test_result["artifacts"] = artifacts
    if summary_html := artifacts_and_summary.summary_html:
      test_result["summaryHtml"] = summary_html
    return test_result

  def _enqueue_result(self, test_result: dict[str, Any]) -> None:
    self._pending_results.append(test_result)
    if len(self._pending_results) >= RESULTS_BATCH_SIZE:
      self._flush_pending_results()

  def _log_error(self, message: str) -> None:
    sys.stderr.write(f"[{type(self).__name__}] {message}\n")

  def _flush_pending_results(self) -> None:
    if not self.enabled or not self._pending_results:
      self._pending_results.clear()
      return
    assert self._session is not None and self._endpoint_url is not None
    batch = list(self._pending_results)
    self._pending_results.clear()
    payload = {"testResults": batch}
    try:
      response = self._session.post(
          self._endpoint_url,
          json=payload,
          timeout=HTTP_TIMEOUT_SECONDS,
      )
      if response.status_code >= 400:
        self._log_error(
            f"HTTP {response.status_code} from {self._endpoint_url}: "
            f"{response.text[:200]}")
      else:
        self._reported_count += len(batch)
    except requests.RequestException as exc:
      self._log_error(f"Failed to upload results: {exc}")

  def _handle_teardown_report(self, report: pytest.TestReport) -> None:
    existing_report = self._test_reports.pop(report.nodeid, None)
    final_report: pytest.TestReport | None
    if report.outcome == PytestReportOutcome.FAILED and (
        existing_report is None or
        existing_report.outcome == PytestReportOutcome.PASSED):
      final_report = report
    else:
      final_report = existing_report

    if final_report is not None:
      self._enqueue_result(self.build_test_result(final_report))

  def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
    if not self.enabled:
      return
    if isinstance(report, pytest.SubtestReport):
      if report.outcome != PytestReportOutcome.PASSED:
        self._enqueue_result(self.build_test_result(report))
      return

    if report.when == PytestReportWhen.SETUP:
      if report.outcome != PytestReportOutcome.PASSED:
        self._test_reports[report.nodeid] = report
      return

    if report.when == PytestReportWhen.CALL:
      self._test_reports[report.nodeid] = report
      return

    if report.when == PytestReportWhen.TEARDOWN:
      self._handle_teardown_report(report)

  def pytest_sessionfinish(
      self,
      session: pytest.Session,
      exitstatus: int,
  ) -> None:
    del session, exitstatus
    if not self.enabled:
      return
    for leftover in self._test_reports.values():
      self._enqueue_result(self.build_test_result(leftover))
    self._test_reports.clear()
    self._flush_pending_results()
    if self._session:
      self._session.close()
    sys.stdout.write(
        f"\n[ResultSinkPlugin] Uploaded {self._reported_count} test "
        "results to ResultSink.\n")
    sys.stdout.flush()
