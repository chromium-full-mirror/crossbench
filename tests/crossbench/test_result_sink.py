# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
import tempfile
import unittest
from typing import TYPE_CHECKING, Any, Final, cast
from unittest import mock

import pytest
import requests

from tests import result_sink, test_helper

if TYPE_CHECKING:
  from collections.abc import Iterator, Mapping, Sequence
  from typing import Literal

  _OutcomeType = (
      result_sink.PytestReportOutcome | Literal["passed", "failed", "skipped"])
  _WhenType = (
      result_sink.PytestReportWhen | Literal["setup", "call", "teardown"])

DEFAULT_SUBTEST_LOCATION: Final[tuple[str, int | None, str]] = (
    "tests/test_foo.py",
    10,
    "test_sub",
)


class DummySubtestReport(pytest.SubtestReport):

  def __init__(
      self,
      nodeid: str,
      outcome: _OutcomeType,
      longrepr: Any = None,
      location: tuple[str, int | None, str] = DEFAULT_SUBTEST_LOCATION,
  ) -> None:
    super().__init__(
        nodeid=nodeid,
        location=location,
        keywords={},
        outcome=cast(Any, outcome),
        longrepr=longrepr,
        when=cast(Any, result_sink.PytestReportWhen.CALL),
    )


class ResultSinkPluginTestCase(unittest.TestCase):

  def _decode_artifact(
      self,
      artifacts: Mapping[str, Mapping[str, str]],
      artifact_id: str,
  ) -> str:
    return base64.b64decode(artifacts[artifact_id]["contents"]).decode("utf-8")

  def _make_sink_plugin(
      self,
      url: str = "http://127.0.0.1:12345/report",
      token: str = "secret-token",
  ) -> result_sink.ResultSinkPlugin:
    return result_sink.ResultSinkPlugin(
        sink_url=url,
        auth_header={"Authorization": f"ResultSink {token}"},
    )

  def _mock_session_post(
      self,
      plugin: result_sink.ResultSinkPlugin,
      status_code: int = 200,
  ) -> mock.MagicMock:
    assert plugin._session is not None
    mock_post = mock.MagicMock()
    mock_post.return_value.status_code = status_code
    plugin._session.post = mock_post
    return mock_post

  def _make_report(
      self,
      nodeid: str,
      outcome: _OutcomeType = result_sink.PytestReportOutcome.PASSED,
      when: _WhenType = result_sink.PytestReportWhen.CALL,
      line: int = 1,
      longrepr: Any = None,
      duration: float = 0.1,
      sections: Sequence[tuple[str, str]] = (),
  ) -> pytest.TestReport:
    fspath = nodeid.partition(result_sink.NODE_ID_SEPARATOR)[0]
    return pytest.TestReport(
        nodeid=nodeid,
        location=(fspath, line, "test_fn"),
        keywords={},
        outcome=cast(Any, outcome),
        longrepr=longrepr,
        when=cast(Any, when),
        duration=duration,
        sections=list(sections),
    )

  @contextlib.contextmanager
  def _mock_no_luci_context(self) -> Iterator[None]:
    result_sink.LuciContext.clear_cache()
    try:
      with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LUCI_CONTEXT", None)
        os.environ.pop("PYTEST_XDIST_WORKER", None)
        yield
    finally:
      result_sink.LuciContext.clear_cache()

  @contextlib.contextmanager
  def _mock_luci_context(self, ctx: Mapping[str, Any]) -> Iterator[None]:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
    ) as f:
      json.dump(ctx, f)
      f.flush()
      result_sink.LuciContext.clear_cache()
      try:
        with mock.patch.dict(os.environ, {}, clear=False):
          os.environ["LUCI_CONTEXT"] = f.name
          os.environ.pop("PYTEST_XDIST_WORKER", None)
          yield
      finally:
        result_sink.LuciContext.clear_cache()

  def test_create_session(self) -> None:
    self.assertIsNone(result_sink.ResultSinkPlugin._create_session(None, None))
    self.assertIsNone(
        result_sink.ResultSinkPlugin._create_session("http://127.0.0.1:1234",
                                                     None))
    self.assertIsNone(
        result_sink.ResultSinkPlugin._create_session(
            None, {"Authorization": "token"}))

    session = result_sink.ResultSinkPlugin._create_session(
        "http://127.0.0.1:1234",
        {"Authorization": "ResultSink token"},
    )
    self.assertIsNotNone(session)
    assert session is not None
    self.assertEqual(session.headers["Content-Type"], "application/json")
    self.assertEqual(session.headers["Accept"], "application/json")
    self.assertEqual(session.headers["Authorization"], "ResultSink token")

  def test_luci_context_instance(self) -> None:
    empty_ctx = result_sink.LuciContext({})
    self.assertEqual(empty_ctx.data, {})
    self.assertIsNone(empty_ctx.section("result_sink"))
    self.assertIsNone(empty_ctx.result_sink)

    invalid_ctx = result_sink.LuciContext({"result_sink": "not-a-dict"})
    self.assertIsNone(invalid_ctx.section("result_sink"))
    self.assertIsNone(invalid_ctx.result_sink)

    incomplete_ctx = result_sink.LuciContext({
        "result_sink": {
            "address": "127.0.0.1:1234",
        },
    })
    self.assertEqual(
        incomplete_ctx.section("result_sink"),
        {"address": "127.0.0.1:1234"},
    )
    self.assertIsNone(incomplete_ctx.result_sink)

    valid_ctx = result_sink.LuciContext({
        "result_sink": {
            "address": "127.0.0.1:1234",
            "auth_token": "token123",
        },
    })
    self.assertEqual(
        valid_ctx.section("result_sink"),
        {
            "address": "127.0.0.1:1234",
            "auth_token": "token123",
        },
    )
    sink_ctx = valid_ctx.result_sink
    self.assertIsNotNone(sink_ctx)
    assert sink_ctx is not None
    self.assertEqual(sink_ctx.address, "127.0.0.1:1234")
    self.assertEqual(sink_ctx.auth_token, "token123")

  def test_disabled_locally_without_resultdb(self) -> None:
    with self._mock_no_luci_context():
      self.assertFalse(result_sink.ResultSinkPlugin.is_result_sink_enabled())
      self.assertIsNone(result_sink.ResultSinkPlugin.from_env())

    with self._mock_luci_context({"local_auth": {"rpc_port": 1234}}):
      self.assertFalse(result_sink.ResultSinkPlugin.is_result_sink_enabled())
      self.assertIsNone(result_sink.ResultSinkPlugin.from_env())

  def test_from_env_result_sink(self) -> None:
    ctx = {
        "result_sink": {
            "address": "127.0.0.1:12345",
            "auth_token": "secret-sink-token",
        },
    }
    with self._mock_luci_context(ctx):
      self.assertTrue(result_sink.ResultSinkPlugin.is_result_sink_enabled())
      plugin = result_sink.ResultSinkPlugin.from_env()
      self.assertIsNotNone(plugin)
      assert isinstance(plugin, result_sink.ResultSinkPlugin)
      self.assertTrue(plugin.enabled)
      self.assertEqual(
          plugin._endpoint_url,
          ("http://127.0.0.1:12345/prpc/luci.resultsink.v1.Sink/"
           "ReportTestResults"),
      )

  def test_luci_context_parameter(self) -> None:
    luci_ctx = result_sink.LuciContext({
        "result_sink": {
            "address": "127.0.0.1:12345",
            "auth_token": "secret-sink-token",
        },
    })
    self.assertTrue(
        result_sink.ResultSinkPlugin.is_result_sink_enabled(luci_ctx))
    with mock.patch.dict(os.environ, {}, clear=False):
      os.environ.pop("PYTEST_XDIST_WORKER", None)
      plugin = result_sink.ResultSinkPlugin.from_env(luci_ctx)
      self.assertIsNotNone(plugin)
      assert isinstance(plugin, result_sink.ResultSinkPlugin)
      self.assertTrue(plugin.enabled)

      empty_ctx = result_sink.LuciContext({})
      self.assertFalse(
          result_sink.ResultSinkPlugin.is_result_sink_enabled(empty_ctx))
      self.assertIsNone(result_sink.ResultSinkPlugin.from_env(empty_ctx))

  def test_xdist_worker_disabled(self) -> None:
    luci_ctx = result_sink.LuciContext({
        "result_sink": {
            "address": "127.0.0.1:12345",
            "auth_token": "secret-sink-token",
        },
    })
    with mock.patch.dict(
        os.environ, {"PYTEST_XDIST_WORKER": "gw0"}, clear=False):
      self.assertIsNone(result_sink.ResultSinkPlugin.from_env(luci_ctx))

  def test_build_test_result_pass_and_fail(self) -> None:
    plugin = self._make_sink_plugin(
        url=("http://127.0.0.1:9999/prpc/luci.resultsink.v1.Sink/"
             "ReportTestResults"))
    pass_report = self._make_report(
        "tests/crossbench/test_result_sink.py::test_ok",
        line=41,
        duration=0.125,
    )
    pass_tr = plugin.build_test_result(pass_report)
    self.assertEqual(pass_tr["status"], result_sink.ResultStatus.PASS)
    self.assertTrue(pass_tr["expected"])
    self.assertEqual(
        pass_tr["testMetadata"]["location"]["fileName"],
        "//tests/crossbench/test_result_sink.py",
    )
    self.assertEqual(pass_tr["testMetadata"]["location"]["line"], 42)
    self.assertIn("View all test results in build", pass_tr["summaryHtml"])

    fail_report = self._make_report(
        "tests/crossbench/test_result_sink.py::test_fail",
        line=99,
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr=(
            "tests/crossbench/test_result_sink.py",
            100,
            "AssertionError: expected <foo> & <bar>",
        ),
        duration=0.5,
        sections=[
            ("Captured stdout call", "hello <stdout>"),
            ("Captured stderr call", "hello <stderr>"),
            ("Captured log call", "hello <log>"),
            ("Python traceback", "Traceback (most recent call last):\n  ..."),
        ],
    )
    fail_tr = plugin.build_test_result(fail_report)
    self.assertEqual(fail_tr["status"], result_sink.ResultStatus.FAIL)
    self.assertFalse(fail_tr["expected"])
    self.assertIn(
        "AssertionError: expected <foo> & <bar>",
        fail_tr["failureReason"]["primaryErrorMessage"],
    )

    long_fail_report = self._make_report(
        "tests/crossbench/test_result_sink.py::test_long_fail",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr="E " + ("x" * 2000),
    )
    long_fail_tr = plugin.build_test_result(long_fail_report)
    self.assertLessEqual(
        len(long_fail_tr["failureReason"]["primaryErrorMessage"].encode(
            "utf-8")),
        result_sink.MAX_FAILURE_REASON_BYTES,
    )
    self.assertTrue(
        long_fail_tr["failureReason"]["primaryErrorMessage"].endswith(
            result_sink.TRUNCATED_SUFFIX))
    for artifact_id in (result_sink.ArtifactId.TRACEBACK,
                        result_sink.ArtifactId.STDOUT,
                        result_sink.ArtifactId.STDERR,
                        result_sink.ArtifactId.LOG):
      self.assertIn(
          f'<text-artifact artifact-id="{artifact_id}">',
          fail_tr["summaryHtml"],
      )
    artifacts = fail_tr["artifacts"]
    decoded_tb = self._decode_artifact(artifacts,
                                       result_sink.ArtifactId.TRACEBACK)
    self.assertIn("AssertionError: expected <foo> & <bar>", decoded_tb)
    self.assertIn("Full Python Stack Trace", decoded_tb)
    self.assertEqual(
        self._decode_artifact(artifacts, result_sink.ArtifactId.STDOUT),
        "hello <stdout>")
    self.assertEqual(
        self._decode_artifact(artifacts, result_sink.ArtifactId.STDERR),
        "hello <stderr>")
    self.assertEqual(
        self._decode_artifact(artifacts, result_sink.ArtifactId.LOG),
        "hello <log>")

  def test_extract_primary_error(self) -> None:
    # 1. Tuple longrepr
    report_tuple = self._make_report(
        "tests/foo.py::test_tuple",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr=("tests/foo.py", 12, "Tuple error message"),
    )
    self.assertEqual(
        result_sink.ResultSinkPlugin.extract_primary_error(report_tuple),
        "Tuple error message",
    )

    # 2. Lines starting with 'E '
    report_e = self._make_report(
        "tests/foo.py::test_e",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr=("def test_foo():\n"
                  ">       assert 1 == 2\n"
                  "E       AssertionError: assert 1 == 2\n"
                  "E       Extra line\n"),
    )
    self.assertEqual(
        result_sink.ResultSinkPlugin.extract_primary_error(report_e),
        "AssertionError: assert 1 == 2\nExtra line",
    )

    # 3. Raw text fallback when no lines start with 'E '
    report_raw = self._make_report(
        "tests/foo.py::test_raw",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr="Custom error header\nSecond error line\n",
    )
    self.assertEqual(
        result_sink.ResultSinkPlugin.extract_primary_error(report_raw),
        "Custom error header\nSecond error line",
    )

    # 4. Empty text fallback
    report_empty = self._make_report(
        "tests/foo.py::test_empty",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr="",
    )
    self.assertEqual(
        result_sink.ResultSinkPlugin.extract_primary_error(report_empty),
        "Test failed",
    )

  def test_truncate_summary(self) -> None:
    text = "Hello World! This is a short error message."
    self.assertEqual(result_sink.ResultSinkPlugin.truncate_summary(text), text)

    long_text = "a" * 2000
    truncated = result_sink.ResultSinkPlugin.truncate_summary(long_text)
    self.assertLessEqual(
        len(truncated.encode("utf-8")), result_sink.MAX_FAILURE_REASON_BYTES)
    self.assertTrue(truncated.endswith("\n...\n[Truncated]"))

    # Multi-byte UTF-8 fallback cropping.
    unicode_text = "🔥" * 1500
    truncated_unicode = result_sink.ResultSinkPlugin.truncate_summary(
        unicode_text)
    self.assertLessEqual(
        len(truncated_unicode.encode("utf-8")),
        result_sink.MAX_FAILURE_REASON_BYTES)

  def test_flush_pending_results(self) -> None:
    plugin = self._make_sink_plugin()
    mock_post = self._mock_session_post(plugin)

    plugin._pending_results.append({
        "testId": "test_1",
        "status": result_sink.ResultStatus.PASS,
    })
    plugin._pending_results.append({
        "testId": "test_2",
        "status": result_sink.ResultStatus.FAIL,
    })
    plugin._flush_pending_results()

    self.assertEqual(len(plugin._pending_results), 0)
    self.assertEqual(plugin._reported_count, 2)
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    self.assertIn("testResults", kwargs["json"])
    self.assertEqual(len(kwargs["json"]["testResults"]), 2)

  def test_flush_pending_results_request_exception(self) -> None:
    plugin = self._make_sink_plugin()
    assert plugin._session is not None
    plugin._session.post = mock.MagicMock(
        side_effect=requests.RequestException("boom"))

    plugin._pending_results.append({
        "testId": "test_1",
        "status": result_sink.ResultStatus.PASS,
    })
    with mock.patch.object(sys.stderr, "write") as mock_stderr:
      plugin._flush_pending_results()

    self.assertEqual(len(plugin._pending_results), 0)
    self.assertEqual(plugin._reported_count, 0)
    mock_stderr.assert_called()

  def test_result_sink_traceback_plugin(self) -> None:
    plugin = result_sink.ResultSinkTracebackPlugin()
    report = self._make_report(
        "tests/test_sample.py::test_err",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr="Error occurred",
    )
    try:
      raise ValueError("deliberate sample exception")
    except ValueError:
      exc_info = sys.exc_info()
    mock_call = mock.MagicMock()
    mock_call.excinfo = mock.MagicMock()
    mock_call.excinfo.type = exc_info[0]
    mock_call.excinfo.value = exc_info[1]
    mock_call.excinfo.tb = exc_info[2]

    generator = plugin.pytest_runtest_makereport(
        mock.MagicMock(),  # type: ignore[arg-type]
        mock_call,
    )
    next(generator)
    mock_outcome = mock.MagicMock()
    mock_outcome.get_result.return_value = report
    with contextlib.suppress(StopIteration):
      generator.send(mock_outcome)

    tb_sections = [
        content for _, content in report.get_sections(
            result_sink.ResultSinkTracebackPlugin.SECTION_NAME)
    ]
    self.assertEqual(len(tb_sections), 1)
    self.assertIn("ValueError: deliberate sample exception", tb_sections[0])

  def test_subtest_report_filtering(self) -> None:
    plugin = self._make_sink_plugin()
    subtest_pass = DummySubtestReport(
        nodeid="tests/test_foo.py::test_sub[case_pass]",
        outcome=result_sink.PytestReportOutcome.PASSED,
    )
    plugin.pytest_runtest_logreport(subtest_pass)
    self.assertEqual(len(plugin._pending_results), 0)

    subtest_fail = DummySubtestReport(
        nodeid="tests/test_foo.py::test_sub[case1]",
        outcome=result_sink.PytestReportOutcome.FAILED,
        longrepr="Subtest failed",
    )
    plugin.pytest_runtest_logreport(subtest_fail)
    self.assertEqual(len(plugin._pending_results), 1)
    self.assertEqual(plugin._pending_results[0]["status"],
                     result_sink.ResultStatus.FAIL)
    self.assertEqual(
        plugin._pending_results[0]["testId"],
        "tests/test_foo.py::test_sub[case1]",
    )

  def test_teardown_failure_handling(self) -> None:
    plugin = self._make_sink_plugin()

    def _feed_test_cycle(
        nodeid: str,
        call_outcome: _OutcomeType = result_sink.PytestReportOutcome.PASSED,
        call_error: Any = None,
        teardown_outcome: _OutcomeType = (
            result_sink.PytestReportOutcome.PASSED),
        teardown_error: Any = None,
    ) -> None:
      plugin.pytest_runtest_logreport(
          self._make_report(nodeid, when=result_sink.PytestReportWhen.SETUP))
      plugin.pytest_runtest_logreport(
          self._make_report(
              nodeid,
              when=result_sink.PytestReportWhen.CALL,
              outcome=call_outcome,
              longrepr=call_error,
          ))
      plugin.pytest_runtest_logreport(
          self._make_report(
              nodeid,
              when=result_sink.PytestReportWhen.TEARDOWN,
              outcome=teardown_outcome,
              longrepr=teardown_error,
          ))

    # Case 1: Setup, call, and teardown all pass -> enqueued as PASS.
    _feed_test_cycle("tests/test_foo.py::test_ok")
    self.assertEqual(len(plugin._pending_results), 1)
    self.assertEqual(plugin._pending_results[0]["status"],
                     result_sink.ResultStatus.PASS)

    # Case 2: Call passes, but teardown fails -> marked FAIL.
    _feed_test_cycle(
        "tests/test_foo.py::test_td_fail",
        teardown_outcome=result_sink.PytestReportOutcome.FAILED,
        teardown_error=("tests/test_foo.py", 5, "Teardown error"),
    )
    self.assertEqual(len(plugin._pending_results), 2)
    self.assertEqual(plugin._pending_results[1]["status"],
                     result_sink.ResultStatus.FAIL)

    # Case 3: Call fails and teardown fails -> marked FAIL with call error.
    _feed_test_cycle(
        "tests/test_foo.py::test_both_fail",
        call_outcome=result_sink.PytestReportOutcome.FAILED,
        call_error=("tests/test_foo.py", 5, "Call error"),
        teardown_outcome=result_sink.PytestReportOutcome.FAILED,
        teardown_error=("tests/test_foo.py", 5, "Teardown error"),
    )
    self.assertEqual(len(plugin._pending_results), 3)
    self.assertEqual(plugin._pending_results[2]["status"],
                     result_sink.ResultStatus.FAIL)
    self.assertIn(
        "Call error",
        plugin._pending_results[2]["failureReason"]["primaryErrorMessage"],
    )

  def test_sessionfinish_flushes_leftover_reports(self) -> None:
    plugin = self._make_sink_plugin()
    self._mock_session_post(plugin)

    nodeid_interrupted = "tests/test_foo.py::test_interrupted"
    plugin.pytest_runtest_logreport(
        self._make_report(
            nodeid_interrupted, when=result_sink.PytestReportWhen.CALL))
    self.assertEqual(len(plugin._pending_results), 0)
    self.assertIn(nodeid_interrupted, plugin._test_reports)

    plugin.pytest_sessionfinish(mock.MagicMock(), 0)
    self.assertEqual(len(plugin._test_reports), 0)
    self.assertEqual(len(plugin._pending_results), 0)
    self.assertEqual(plugin._reported_count, 1)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
