# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from unittest import mock

from typing_extensions import override

from crossbench.probes.screenshot import ScreenshotProbe
from crossbench.probes.video import VideoProbe
from crossbench.runner.run import Run
from crossbench.runner.run_annotation import RunAnnotation
from tests import test_helper
from tests.crossbench.mock_helper import MockStory
from tests.crossbench.runner.groups.base import BaseRunGroupTestCase
from tests.crossbench.runner.helper import MockProbe

if TYPE_CHECKING:
  from crossbench.runner.runner import Runner


class RunTestCase(BaseRunGroupTestCase):

  @override
  def default_runner(self) -> Runner:
    return super().default_runner(create_symlinks=False)

  def _create_run(self) -> Run:
    session = self.default_session()
    return Run(self.runner, session, MockStory("mock story"), 1, False,
               "1_default", 1, "test run", dt.timedelta(minutes=1), True)

  def _run_actions_and_get_new_marks(self, **kwargs) -> list[str]:
    run = self._create_run()
    initial_marks = list(run.browser.performance_marks)
    initial_trace_marks = list(self.platform.trace_marks)
    with run.actions("Some_Custom_Action", **kwargs):
      pass
    new_marks = run.browser.performance_marks
    new_trace_marks = self.platform.trace_marks
    self.assertSequenceEqual(new_marks[:len(initial_marks)], initial_marks)
    self.assertSequenceEqual(new_trace_marks[:len(initial_trace_marks)],
                             initial_trace_marks)
    self.assertSequenceEqual(new_marks[len(initial_marks):],
                             new_trace_marks[len(initial_trace_marks):])
    return new_marks[len(initial_marks):]

  def test_find_probe_context(self):
    self.runner.attach_probe(MockProbe())
    run = self._create_run()
    session = run.browser_session
    session.set_ready()
    with session.open():
      self.assertIsNotNone(run.get_probe_context(MockProbe))
      self.assertIsNone(run.get_probe_context(ScreenshotProbe))

  def _assert_has_probe_context(self, attached_probe, unattached_probe_cls,
                                invalid_name: str):
    self.runner.attach_probe(attached_probe)
    run = self._create_run()
    session = run.browser_session
    session.set_ready()
    with session.open():
      self.assertTrue(run.has_probe_context_by_name(attached_probe.NAME))
      self.assertFalse(run.has_probe_context_by_name(unattached_probe_cls.NAME))
      with self.assertRaisesRegex(ValueError,
                                  f"Unknown probe name: '{invalid_name}'"):
        run.has_probe_context_by_name(invalid_name)

  def test_has_probe_context_by_name(self):
    """Check that real probes return True/False if attached/unattached,
       and typos yield exceptions."""

    class MockProbe1(MockProbe):
      NAME = "probe_attached"

    class MockProbe2(MockProbe):
      NAME = "probe_unattached"

    # We inject our mock probes into the PROBE_LOOKUP so validation passes.
    with mock.patch.dict("crossbench.runner.probe_context_manager.PROBE_LOOKUP",
                         {
                             "probe_attached": MockProbe1,
                             "probe_unattached": MockProbe2,
                         }):
      self._assert_has_probe_context(
          attached_probe=MockProbe1(),
          unattached_probe_cls=MockProbe2,
          invalid_name="probe_invalid")

  def test_has_probe_context_by_name_real_probes(self):
    """Repeat `test_has_probe_context_by_name` with real probes.
       The choice of probes is arbitrary; should breaking changes ever
       be made, choose other probes to fix this test."""
    self._assert_has_probe_context(
        attached_probe=VideoProbe(),
        unattached_probe_cls=ScreenshotProbe,
        invalid_name="video_probee")

  def test_annotate(self):
    run = self._create_run()
    self.assertFalse(list(run.annotations))
    annotation = RunAnnotation.warning("Some warning")

    with self.assertNoLogs(level="INFO"):
      run.log_annotations()

    run.annotate(annotation)
    self.assertIn(annotation, run.annotations)
    with self.assertLogs(level="INFO") as cm:
      run.log_annotations()
    self.assertIn("Some warning", " ".join(cm.output))

  def test_actions_no_performance_mark(self):
    self.assertSequenceEqual(self._run_actions_and_get_new_marks(), [])

  def test_actions_explicit_empty_performance_mark(self):
    self.assertSequenceEqual(
        self._run_actions_and_get_new_marks(performance_mark=""), [])

  def test_actions_with_performance_mark(self):
    self.assertSequenceEqual(
        self._run_actions_and_get_new_marks(performance_mark="custom-marker"),
        ["crossbench-custom-marker-start", "crossbench-custom-marker-stop"])

  def test_mark_skipped(self) -> None:
    run = self._create_run()
    self.assertFalse(run.is_skipped)
    run.mark_skipped()
    self.assertTrue(run.is_skipped)

  def test_run_without_starting_browser(self) -> None:

    class NoBrowserStory(MockStory):

      @override
      def run(self, run: Run) -> None:
        run.performance_mark("no-browser-mark")

    session = self.default_session()
    session.browser.settings._start_browser = False
    run = Run(self.runner, session, NoBrowserStory("no_browser"), 1, False,
              "1_default", 1, "test run", dt.timedelta(minutes=1), True)
    session.set_ready()
    with mock.patch.object(run, "teardown_write_results_db"), session.open():
      run.run(is_dry_run=False)
      self.assertTrue(run.is_success)
      self.assertFalse(run.browser.is_running)
      self.assertFalse(run.browser.did_run)
      self.assertEqual(run.browser.url_list, [])
      self.assertEqual(run.browser.performance_marks,
                       ["crossbench-no-browser-mark"])
      self.assertIn("crossbench-no-browser-mark", self.platform.trace_marks)

  def test_run_starts_and_stops_browser_explicitly(self) -> None:

    class ExplicitBrowserStory(MockStory):

      @override
      def run(self, run: Run) -> None:
        assert not run.browser.is_running
        run.browser_session.start_browser()
        assert run.browser.is_running
        with run.actions("Navigate") as actions:
          actions.show_url("https://example.com")
        run.browser_session.stop_browser()
        assert not run.browser.is_running
        run.browser_session.start_browser()
        assert run.browser.is_running
        with run.actions("Reopen") as actions:
          actions.show_url("https://example.org")

    session = self.default_session()
    session.browser.settings._start_browser = False
    run = Run(self.runner, session, ExplicitBrowserStory("explicit_browser"), 1,
              False, "1_default", 1, "test run", dt.timedelta(minutes=1), True)
    session.set_ready()
    with (
        mock.patch.object(run, "teardown_write_results_db"),
        mock.patch.object(
            run, "_run_splashscreen", wraps=run._run_splashscreen) as
        mock_splashscreen,
    ):
      with session.open():
        run.run(is_dry_run=False)
      self.assertTrue(run.is_success)
      mock_splashscreen.assert_not_called()
      self.assertIn("https://example.com", run.browser.url_list)
      self.assertIn("https://example.org", run.browser.url_list)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
