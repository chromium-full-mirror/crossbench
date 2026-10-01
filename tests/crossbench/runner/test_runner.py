# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import pathlib
import unittest
from typing import TYPE_CHECKING, Any, Iterator
from unittest import mock

from typing_extensions import override

from crossbench.browsers.settings import Settings
from crossbench.browsers.webdriver import RemoteWebDriver
from crossbench.device_config import DeviceConfig, DeviceConfigValueError, \
    RequiredDeviceConfigMode
from crossbench.exception import MultiException
from crossbench.flags.base import Flags
from crossbench.helper import input_helper
from crossbench.helper.state import UnexpectedStateError
from crossbench.network.live import LiveNetwork
from crossbench.probes import all as all_probes
from crossbench.probes.js import JSProbe
from crossbench.probes.probe import ProbeIncompatibleBrowser, ProbePriority
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe
from crossbench.runner.groups.session import BrowserSessionRunGroup
from crossbench.runner.groups.thread import RunThreadGroup
from crossbench.runner.pause_controller import ResumeMode
from crossbench.runner.runner import CacheTemperature, Runner, ThreadMode
from tests import test_helper
from tests.crossbench.mock_browser import MockChromeDev
from tests.crossbench.mock_helper import MockBenchmark
from tests.crossbench.mock_helper import MockPlatform as FullMockPlatform
from tests.crossbench.runner.helper import BaseRunnerTestCase, MockBrowser, \
    MockPlatform, MockProbe, MockProbeContext, MockRun, MockRunner

if TYPE_CHECKING:
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.probe import Probe
  from crossbench.stories.story import Story


# Skip strict type checks for better mocking
class TestThreadModeTestCase(unittest.TestCase):

  def create_session(self, browser, index) -> BrowserSessionRunGroup:
    return BrowserSessionRunGroup(
        self.env,
        self.probes,
        browser,
        Flags(),
        index,
        self.root_dir,
        create_symlinks=True,
        throw=True)

  @override
  def setUp(self) -> None:
    self.platform_a = MockPlatform("platform a")
    self.platform_b = MockPlatform("platform b")
    self.browser_a_1 = MockBrowser("mock browser a 1", self.platform_a)
    self.browser_a_2 = MockBrowser("mock browser b 1", self.platform_a)
    self.browser_b_1 = MockBrowser("mock browser b 1", self.platform_b)
    self.browser_b_2 = MockBrowser("mock browser b 2", self.platform_b)
    self.runner = MockRunner()
    self.root_dir = pathlib.Path()
    self.env = self.runner.env
    self.probes: list[Probe] = []
    self.runs = (
        MockRun(self.runner, self.create_session(self.browser_a_1, 1), "run 1"),
        MockRun(self.runner, self.create_session(self.browser_a_2, 2), "run 2"),
        MockRun(self.runner, self.create_session(self.browser_a_1, 3), "run 3"),
        MockRun(self.runner, self.create_session(self.browser_a_2, 4), "run 4"),
        MockRun(self.runner, self.create_session(self.browser_b_1, 5), "run 5"),
        MockRun(self.runner, self.create_session(self.browser_b_2, 6), "run 6"),
        MockRun(self.runner, self.create_session(self.browser_b_1, 7), "run 7"),
        MockRun(self.runner, self.create_session(self.browser_b_2, 8), "run 8"),
    )
    self.runner.runs = self.runs

  def test_default_runs(self):
    session_ids = {run.browser_session.index for run in self.runs}
    self.assertEqual(len(session_ids), len(self.runs))

  def test_group_none(self):
    groups = ThreadMode.NONE.group(self.runs)
    self.assertEqual(len(groups), 1)
    self.assertSequenceEqual(groups[0].runs, self.runs)
    self.assertEqual(groups[0].index, 0)

  def test_group_platform(self):
    groups = ThreadMode.PLATFORM.group(self.runs)
    self.assertEqual(len(groups), 2)
    group_a, group_b = groups
    self.assertSequenceEqual(group_a.runs, self.runs[:4])
    self.assertSequenceEqual(group_b.runs, self.runs[4:])
    self.assertEqual(group_a.index, 0)
    self.assertEqual(group_b.index, 1)

  def test_group_browser(self):
    groups = ThreadMode.BROWSER.group(self.runs)
    self.assertEqual(len(groups), 4)
    self.assertSequenceEqual(groups[0].runs, (self.runs[0], self.runs[2]))
    self.assertSequenceEqual(groups[1].runs, (self.runs[1], self.runs[3]))
    self.assertSequenceEqual(groups[2].runs, (self.runs[4], self.runs[6]))
    self.assertSequenceEqual(groups[3].runs, (self.runs[5], self.runs[7]))
    for index, group in enumerate(groups):
      self.assertEqual(group.index, index)

  def test_group_session(self):
    groups = ThreadMode.SESSION.group(self.runs)
    self.assertEqual(len(groups), len(self.runs))
    for group, run in zip(groups, self.runs, strict=True):
      self.assertSequenceEqual(group.runs, (run,))
    for index, group in enumerate(groups):
      self.assertEqual(group.index, index)

  def test_group_session_2(self):
    session_1 = self.create_session(self.browser_a_1, 1)
    session_2 = self.create_session(self.browser_a_2, 2)
    runs = (
        MockRun(self.runner, session_1, "story 1"),
        MockRun(self.runner, session_2, "story 2"),
        MockRun(self.runner, session_1, "story 3"),
        MockRun(self.runner, session_2, "story 4"),
    )
    groups = ThreadMode.SESSION.group(runs)
    group_a, group_b = groups
    self.assertSequenceEqual(group_a.runs, (runs[0], runs[2]))
    self.assertSequenceEqual(group_b.runs, (runs[1], runs[3]))
    for index, group in enumerate(groups):
      self.assertEqual(group.index, index)


class FailingMockProbeContext(MockProbeContext):

  @override
  def setup(self):
    raise CustomException("failing setup")


class MockNonLiveNetwork(LiveNetwork):

  @property
  @override
  def is_live(self) -> bool:
    return False


class RunnerTestCase(BaseRunnerTestCase):

  def test_default_instance(self):
    runner = self.default_runner()
    self.assertSequenceEqual(self.stories, runner.stories)
    self.assertSequenceEqual(self.browsers, runner.browsers)
    self.assertEqual(runner.repetitions, 1)
    self.assertEqual(len(runner.platforms), 1)
    self.assertTrue(runner.exceptions.is_success)
    default_probes = list(runner.default_probes)
    self.assertSequenceEqual(list(runner.probes), default_probes)
    self.assertEqual(
        len(default_probes), len(all_probes.DEFAULT_INTERNAL_PROBES))
    self.assertEqual(len(runner.runs), 0)
    # no runs => is_success == false
    self.assertFalse(runner.is_success)

  def test_cache_temperatures_arg_parsing(self):
    parser = argparse.ArgumentParser()
    Runner._add_run_arguments(MockBenchmark, parser)
    Runner._add_output_arguments(MockBenchmark, parser)

    # Test default (no flag)
    args = parser.parse_args(["--out-dir", "out"])
    self.assertSequenceEqual(args.cache_temperatures,
                             [CacheTemperature.DEFAULT])

    # Test flag present (no args)
    args = parser.parse_args(["--cache-temperatures", "--out-dir", "out"])
    self.assertEqual(args.cache_temperatures, list(CacheTemperature.all()))

  def test_upload_results_arg_parsing(self) -> None:
    parser = argparse.ArgumentParser()
    Runner._add_output_arguments(MockBenchmark, parser)

    # Test default (no flag).
    args = parser.parse_args([])
    self.assertIsNone(args.upload_results)

    # Test flag with explicit URL (`--flag value`).
    args = parser.parse_args(["--upload-results", "gs://my-bucket/path"])
    self.assertEqual(args.upload_results, "gs://my-bucket/path")

    # Test flag with explicit URL (`--flag=value`).
    args = parser.parse_args(["--upload-results=gs://my-bucket/path"])
    self.assertEqual(args.upload_results, "gs://my-bucket/path")

    # Test flag without value when CROSSBENCH_RESULT_UPLOAD_TARGET is set.
    with mock.patch.dict(
        "os.environ", {"CROSSBENCH_RESULT_UPLOAD_TARGET": "gs://env-bucket"}):
      args = parser.parse_args(["--upload-results"])
      self.assertEqual(args.upload_results, "gs://env-bucket")

    # Test explicit URL takes precedence over CROSSBENCH_RESULT_UPLOAD_TARGET.
    with mock.patch.dict(
        "os.environ", {"CROSSBENCH_RESULT_UPLOAD_TARGET": "gs://env-bucket"}):
      args = parser.parse_args(["--upload-results", "gs://explicit-bucket"])
      self.assertEqual(args.upload_results, "gs://explicit-bucket")
      args = parser.parse_args(["--upload-results=gs://explicit-bucket"])
      self.assertEqual(args.upload_results, "gs://explicit-bucket")

    # Test flag without value when CROSSBENCH_RESULT_UPLOAD_TARGET is not set.
    with mock.patch.dict("os.environ", {}, clear=True):
      with self.assertRaises(SystemExit):
        parser.parse_args(["--upload-results"])

  def test_dry_run(self):
    self.test_run(is_dry_run=True)

  def test_run(self, is_dry_run=False):
    runner = self.default_runner()

    runner.run(is_dry_run)
    # Don't reuse the Runner:
    with self.assertRaises(UnexpectedStateError):
      runner.run(is_dry_run)

    self.assertEqual(len(runner.runs), 4)
    self.assertTrue(runner.is_success)
    for run in runner.runs:
      self.assertTrue(run.is_success)

      if not is_dry_run:
        self.assertEqual(
            len(run.results), len(all_probes.DEFAULT_INTERNAL_PROBES))
        for probe in runner.probes:
          self.assertIn(probe, run.results)

  def test_run_mock_probe(self):
    runner = self.default_runner()
    probe = MockProbe("custom_probe_data")
    runner.attach_probe(probe)
    self.assertIn(probe, runner.probes)
    for browser in runner.browsers:
      self.assertIn(probe, browser.probes)

    runner.run()
    self.assertTrue(runner.is_success)
    self.assertEqual(len(runner.runs), 4)
    for run in runner.runs:
      self._validate_successful_run(run, runner, probe, "custom_probe_data")
    for browser in runner.browsers:
      runs_symlinks = list(
          (runner.out_dir / browser.unique_name / "runs").iterdir())
      self.assertEqual(len(runs_symlinks), 2)

  def test_story_specific_extra_flags(self) -> None:

    class StoryCustomFlagsBenchmark(MockBenchmark):

      @classmethod
      @override
      def extra_flags(cls, browser_attributes: BrowserAttributes,
                      story: Story) -> Flags:
        if story.name == "story_1":
          return Flags({"--story-one-flag": None})
        if story.name == "story_2":
          return Flags({"--story-two-flag": "some-string-value"})
        return Flags()

    benchmark = StoryCustomFlagsBenchmark(self.stories)
    runner = self.default_runner(benchmark=benchmark)
    runner.run()

    self.assertTrue(runner.is_success)
    self.assertEqual(len(runner.runs), 4)

    for run in runner.runs:
      details = run.get_browser_details_json()
      flags = details["flags"]
      assert isinstance(flags, tuple)
      self.assertEqual(
          "--story-one-flag" in flags,
          run.story.name == "story_1",
      )
      self.assertEqual(
          "--story-two-flag=some-string-value" in flags,
          run.story.name == "story_2",
      )

  def test_run_remote_web_driver(self):
    driver = mock.Mock()
    driver.capabilities = {
        "browserVersion": "123.0.4567.89",
        "setWindowRect": False,
    }
    browser = RemoteWebDriver("test-driver", driver)
    runner = self.default_runner(browsers=[browser])
    runner.run()

  def _validate_successful_run(self, run, runner, probe, probe_data):
    results = run.results[probe]
    with results.json.open() as f:
      probe_data = json.load(f)
      self.assertEqual(probe_data, probe_data)
    browser_dir = runner.out_dir / run.browser.unique_name
    # Pyfakefs is having some issues with relative symlinks, thus we're
    # manually combining the paths.
    runs_dir = browser_dir / "runs"
    run_symlink = runs_dir / (runs_dir / str(run.index)).readlink()
    self.assertEqual(run_symlink.resolve(), run.out_dir)
    self._validate_probes(run, runner)

  def _validate_probes(self, run, runner):
    for probe in runner.probes:
      probe.validate_result(run)

  def test_single_story_run_mock_probe_partial_setup_fail(self):
    runner = self.single_story_runner(throw=False)

    probe = MockProbe("custom_probe_data", FailingMockProbeContext)
    runner.attach_probe(probe)
    self.assertIn(probe, runner.probes)
    for browser in runner.browsers:
      self.assertIn(probe, browser.probes)

    with self.assertRaises(MultiException) as cm:
      runner.run()
    self.assertEqual(len(cm.exception), 1)
    exception = cm.exception.exceptions[0].exception
    self.assertIsInstance(exception, CustomException)

    self.assertFalse(runner.is_success)
    self.assertEqual(len(runner.runs), 1)
    failed_run = next(iter(runner.runs))
    self.assertFalse(failed_run.is_success)
    self.assertTrue(failed_run.results[probe].is_empty)
    self._validate_probes(failed_run, runner)

  def test_single_story_run_mock_probe_calls(self):
    # Make sure start / stop are called.
    runner = self.single_story_runner(throw=True)
    with mock.patch.object(FailingMockProbeContext,
                           "setup") as setup_mock, mock.patch.object(
                               FailingMockProbeContext,
                               "start") as start_mock, mock.patch.object(
                                   FailingMockProbeContext,
                                   "stop") as stop_mock:
      probe = MockProbe("custom_probe_data", FailingMockProbeContext)
      runner.attach_probe(probe)
      runner.run()
    self.assertTrue(runner.is_success)
    setup_mock.assert_called_once()
    start_mock.assert_called_once()
    stop_mock.assert_called_once()

  def test_single_story_run_mock_probe_partial_setup_fail_mock(self):
    # Make sure start / stop / teardown are not called after a setup failure
    runner = self.single_story_runner(throw=False)
    with mock.patch.object(FailingMockProbeContext,
                           "start") as start_mock, mock.patch.object(
                               FailingMockProbeContext,
                               "stop") as stop_mock, mock.patch.object(
                                   FailingMockProbeContext,
                                   "teardown") as teardown_mock:
      probe = MockProbe("custom_probe_data", FailingMockProbeContext)
      runner.attach_probe(probe)
      with self.assertRaises(MultiException) as cm:
        runner.run()
      exception = cm.exception.exceptions[0].exception
      self.assertIsInstance(exception, CustomException)
    self.assertFalse(runner.is_success)
    start_mock.assert_not_called()
    stop_mock.assert_not_called()
    teardown_mock.assert_not_called()

  def test_run_mock_probe_partial_setup_fail(self):
    runner = self.default_runner(throw=False)
    setup_count = 0

    class PartialFailingMockProbeContext(MockProbeContext):

      @override
      def setup(self):
        nonlocal setup_count
        setup_count += 1
        if setup_count == 3:
          raise CustomException(f"failing setup number {setup_count}")

    probe = MockProbe("custom_probe_data", PartialFailingMockProbeContext)
    runner.attach_probe(probe)
    self.assertIn(probe, runner.probes)
    for browser in runner.browsers:
      self.assertIn(probe, browser.probes)

    with self.assertRaises(MultiException) as cm:
      runner.run()
    self.assertEqual(len(cm.exception), 1)
    exception = cm.exception.exceptions[0].exception
    self.assertIsInstance(exception, CustomException)

    self.assertFalse(runner.is_success)
    self.assertEqual(setup_count, 4)
    self.assertEqual(len(runner.runs), 4)
    failed_runs = [run for run in runner.runs if not run.is_success]
    self.assertEqual(len(failed_runs), 1)
    failed_run = failed_runs[0]

    for run in runner.runs:
      if run is failed_run:
        continue
      self.assertTrue(run.is_success)
      self._validate_successful_run(run, runner, probe, "custom_probe_data")

    self.assertEqual(failed_run.index, 2)
    self.assertFalse(failed_run.is_success)
    self.assertTrue(failed_run.results[probe].is_empty)
    self._validate_probes(failed_run, runner)

  def test_attach_probe_twice(self):
    runner = self.default_runner()
    probe = MockProbe("custom_probe_data")
    runner.attach_probe(probe)
    # Cannot attach same probe twice.
    with self.assertRaises(ValueError) as cm:
      runner.attach_probe(probe)
    self.assertIn("twice", str(cm.exception))
    self.assertIn(probe, runner.probes)
    self.assertNotIn(probe, runner.default_probes)

  def test_attach_probe_sorts_probes(self):
    """Verify that probes are sorted by priority when attached."""

    class UserProbe(MockProbe):
      NAME = "probe_user"
      PRIORITY = ProbePriority.USER

    class InternalProbe(MockProbe):
      NAME = "probe_internal"
      PRIORITY = ProbePriority.INTERNAL

    runner = self.default_runner()
    probe_1 = UserProbe("probe_user_data")
    probe_internal = InternalProbe("probe_internal_data")

    runner.attach_probe(probe_1)
    runner.attach_probe(probe_internal)

    probe_list = list(runner.probes)
    self.assertLess(
        probe_list.index(probe_internal), probe_list.index(probe_1),
        "Probes were not sorted correctly upon attach_probe().")

  def test_attach_incompatible_probe(self):
    runner = self.default_runner()
    probe = MockProbe("custom_probe_data")

    def mock_validate_browser(env: RunnerEnv, browser: Browser):
      del env
      nonlocal probe
      raise ProbeIncompatibleBrowser(probe, browser, "mock invalid")

    probe.validate_browser = mock_validate_browser
    with self.assertRaises(MultiException) as cm:
      runner.attach_probe(probe)
    self.assertIn("mock invalid", str(cm.exception))
    # matching_browser_only = True silence the error
    runner.attach_probe(probe, matching_browser_only=True)
    # No browser matches => probe is not available
    self.assertNotIn(probe, runner.probes)
    self.assertNotIn(probe, runner.default_probes)
    for browser in self.browsers:
      self.assertNotIn(probe, browser.probes)

  def test_attach_partially_incompatible_probe(self):
    runner = self.default_runner()
    probe = MockProbe("custom_probe_data")
    compatible_browser = self.browsers[1]

    def mock_validate_browser(env: RunnerEnv, browser: Browser):
      del env
      nonlocal probe
      nonlocal compatible_browser
      if browser != compatible_browser:
        raise ProbeIncompatibleBrowser(probe, browser, "mock invalid")

    # Attaching incompatible probes raises errors by default.
    probe.validate_browser = mock_validate_browser
    with self.assertRaises(MultiException) as cm:
      runner.attach_probe(probe)
    self.assertIn("mock invalid", str(cm.exception))
    # matching_browser_only = True silences the error
    runner.attach_probe(probe, matching_browser_only=True)
    self.assertIn(probe, runner.probes)
    self.assertNotIn(probe, runner.default_probes)
    for browser in self.browsers:
      if browser == compatible_browser:
        self.assertIn(probe, browser.probes)
      else:
        self.assertNotIn(probe, browser.probes)

  def test_has_any_live_network(self):
    runner = self.default_runner()
    self.assertTrue(runner.has_any_live_network())

  def test_has_any_live_network_false(self):
    mock_chrome = MockChromeDev(
        "chrome-dev_non_live",
        settings=Settings(platform=self.platform, network=MockNonLiveNetwork()))
    runner = self.default_runner(browsers=(mock_chrome,))
    self.assertFalse(runner.has_any_live_network())

  def test_has_any_live_network_multi_browser(self):
    mock_chrome = MockChromeDev(
        "chrome-dev_non_live",
        settings=Settings(platform=self.platform, network=MockNonLiveNetwork()))
    runner = self.default_runner(browsers=(
        *self.browsers,
        mock_chrome,
    ))
    self.assertTrue(runner.has_any_live_network())

  def test_has_all_live_network(self):
    runner = self.default_runner()
    self.assertTrue(runner.has_all_live_network())

  def test_has_all_live_network_false(self):
    mock_chrome = MockChromeDev(
        "chrome-dev_non_live",
        settings=Settings(platform=self.platform, network=MockNonLiveNetwork()))
    runner = self.default_runner(browsers=(mock_chrome,))
    self.assertFalse(runner.has_all_live_network())

  def test_has_all_live_network_false_multi_browser(self):
    mock_chrome = MockChromeDev(
        "chrome-dev_non_live",
        settings=Settings(platform=self.platform, network=MockNonLiveNetwork()))
    runner = self.default_runner(browsers=(
        *self.browsers,
        mock_chrome,
    ))
    self.assertFalse(runner.has_all_live_network())

  def test_has_only_single_run_platforms_multi_runs(self):
    runner = self.default_runner()
    with self.assertRaises(RuntimeError):
      runner.has_only_single_run_platforms()
    runner.run()
    self.assertTrue(runner.runs)
    self.assertFalse(runner.has_only_single_run_platforms())

  def test_has_only_single_run_platforms_single_runs(self):
    benchmark = MockBenchmark((self.stories[0],))
    browsers = (self.browsers[0],)
    runner = self.default_runner(browsers=browsers, benchmark=benchmark)
    runner.run()
    self.assertEqual(len(runner.runs), 1)
    self.assertTrue(runner.has_only_single_run_platforms())

  def test_has_only_single_run_platforms_multi_platform(self):
    benchmark = MockBenchmark((self.stories[0],))

    class RemoteMockPlatform(FullMockPlatform):

      @property
      def key(self) -> tuple[str, ...]:
        return ("remote", "remote-mock-platform")

    mock_remote_chrome = MockChromeDev(
        "chrome-dev_remote", settings=Settings(platform=RemoteMockPlatform()))
    browsers = (self.browsers[0], mock_remote_chrome)
    runner = self.default_runner(browsers=browsers, benchmark=benchmark)
    runner.run()
    self.assertEqual(len(runner.runs), 2)
    self.assertTrue(runner.has_only_single_run_platforms())

  def test_has_only_single_run_platforms_multi_platform_stories(self):

    class RemoteMockPlatform(FullMockPlatform):

      @property
      def key(self) -> tuple[str, ...]:
        return ("remote", "remote-mock-platform")

    mock_remote_chrome = MockChromeDev(
        "chrome-dev_remote", settings=Settings(platform=RemoteMockPlatform()))
    browsers = (self.browsers[0], mock_remote_chrome)
    runner = self.default_runner(browsers=browsers)
    runner.run()
    self.assertEqual(len(runner.runs), 4)
    self.assertFalse(runner.has_only_single_run_platforms())

  def test_trace_processor_probe_single(self):
    probe = TraceProcessorProbe.parse_dict({})
    runner = self.default_runner(probes=(probe,))
    self.assertTrue(list(runner.probes))

  def test_trace_processor_probe_first(self):
    trace_processor_probe = TraceProcessorProbe.parse_dict({})
    js_probe = JSProbe(js="return []")
    runner = self.default_runner(probes=(trace_processor_probe, js_probe))
    probes = list(runner.probes)
    self.assertTrue(probes)
    self.assertEqual(probes[-1], js_probe)
    self.assertEqual(probes[-2], trace_processor_probe)

  def test_trace_processor_probe_last(self):
    trace_processor_probe = TraceProcessorProbe.parse_dict({})
    js_probe = JSProbe(js="return []")
    runner = self.default_runner(probes=(
        js_probe,
        trace_processor_probe,
    ))
    probes = list(runner.probes)
    self.assertTrue(probes)
    self.assertEqual(probes[-1], js_probe)
    self.assertEqual(probes[-2], trace_processor_probe)


class CustomException(Exception):
  pass


class RunThreadGroupTestCase(BaseRunnerTestCase):

  @override
  def tearDown(self) -> None:
    for browser in self.browsers:
      self.assertFalse(browser.is_running)
    return super().tearDown()

  def test_create_no_runs(self):
    with self.assertRaises(AssertionError):
      RunThreadGroup([])

  def test_different_runners(self):
    runs_a = list(self.default_runner()._get_runs())
    self.out_dir = self.out_dir.parent / "second_out_dir"
    runner_b = Runner(
        self.out_dir, [MockChromeDev("chrome-dev-2")],
        self.benchmark,
        platform=self.platform,
        throw=True,
        in_memory_result_db=True)
    runs_b = list(runner_b._get_runs())
    self.assertNotEqual(runs_a[0].runner, runs_b[0].runner)
    with self.assertRaises(AssertionError) as cm:
      RunThreadGroup(runs_a + runs_b)
    self.assertIn("same Runner", str(cm.exception))

  @contextlib.contextmanager
  def patch_teardown_run(self, runner) -> Iterator[mock.MagicMock]:
    with mock.patch.object(
        runner.results_db, "teardown_run",
        side_effect=None) as teardown_run_mock:
      yield teardown_run_mock

  def test_simple_runs(self):
    runner = self.default_runner()
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    self.assertEqual(thread.index, 0)
    self.assertEqual(thread.runner, runner)
    self.assertSequenceEqual(thread.runs, runs)
    self.assertTrue(thread.is_success)

    run_count = 0

    def test_run(run_method):
      nonlocal run_count
      run_count += 1
      run_method(is_dry_run=False)

    for run in runs:
      run.run = (  # noqa: PLC3002
          lambda run_method: lambda is_dry_run: test_run(run_method))(
              run.run)
    with self.patch_teardown_run(runner) as teardown_run_mock:
      thread.run()
      self.assertEqual(teardown_run_mock.call_count, len(runs))

    self.assertTrue(thread.is_success)
    self.assertSequenceEqual(thread.runs, runs)
    self.assertEqual(run_count, 4)

  def test_run_fail_run_probe_create_context(self):
    # 2 runs, same browser different stories
    runner = self.default_runner(browsers=[self.browsers[1]], throw=False)
    probe = MockProbe("custom_probe_data")
    runner.attach_probe(probe)
    self.assertTrue(probe.is_attached)
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    failing_session, successful_session = thread.browser_sessions
    failing_run, successful_run = runs

    setup_fail_count = 0

    def mock_get_context_fail(run):
      if run == successful_run:
        return MockProbeContext(probe, run)
      nonlocal setup_fail_count
      setup_fail_count += 1
      raise CustomException

    probe.create_context = mock_get_context_fail

    self.assertEqual(setup_fail_count, 0)
    with self.patch_teardown_run(runner) as teardown_run_mock:
      thread.run()
      self.assertEqual(teardown_run_mock.call_count, len(runs))
    self.assertEqual(setup_fail_count, 1)

    self.assertTrue(successful_session.is_success)
    self.assertTrue(successful_run.is_success)

    # Errors are propagated up:
    for exceptions_holder in (runner, thread, failing_session, failing_run):
      self.assertFalse(exceptions_holder.is_success)
      exceptions = exceptions_holder.exceptions
      self.assertEqual(len(exceptions), 1)
      exception_entry = exceptions[0]
      self.assertIsInstance(exception_entry.exception, CustomException)

  def test_run_fail_run_probe_setup(self):
    # 2 runs, same browser different stories
    runner = self.default_runner(browsers=[self.browsers[1]], throw=False)
    probe = MockProbe("custom_probe_data")
    runner.attach_probe(probe)
    self.assertTrue(probe.is_attached)
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    failing_session, successful_session = thread.browser_sessions
    failing_run, successful_run = runs

    setup_fail_count = 0

    def mock_setup_fail() -> None:
      nonlocal setup_fail_count
      setup_fail_count += 1
      raise CustomException

    def mock_get_context_fail(run):
      context = MockProbeContext(probe, run)
      if run == failing_run:
        context.setup = mock_setup_fail
      return context

    probe.create_context = mock_get_context_fail

    self.assertEqual(setup_fail_count, 0)
    with self.patch_teardown_run(runner) as teardown_run_mock:
      thread.run()
      self.assertEqual(teardown_run_mock.call_count, len(runs))
    self.assertEqual(setup_fail_count, 1)

    self.assertTrue(successful_session.is_success)
    self.assertTrue(successful_run.is_success)

    # Errors are propagated up:
    for exceptions_holder in (runner, thread, failing_session, failing_run):
      self.assertFalse(exceptions_holder.is_success)
      exceptions = exceptions_holder.exceptions
      self.assertEqual(len(exceptions), 1)
      exception_entry = exceptions[0]
      self.assertIsInstance(exception_entry.exception, CustomException)

  def test_run_fail_one_browser_setup(self):
    # 2 runs, same story, different browsers
    benchmark = MockBenchmark(stories=[self.stories[0]])
    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        platform=self.platform,
        in_memory_result_db=True)
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    failing_session, successful_session = thread.browser_sessions
    failing_run, successful_run = runs
    self.assertNotEqual(failing_run.browser, successful_run.browser)

    setup_fail_count = 0

    def mock_start_fail(session: BrowserSessionRunGroup) -> None:
      del session
      nonlocal setup_fail_count
      setup_fail_count += 1
      raise CustomException

    failing_run.browser.start = mock_start_fail

    self.assertEqual(setup_fail_count, 0)
    with self.patch_teardown_run(runner) as teardown_run_mock:
      thread.run()
      self.assertEqual(teardown_run_mock.call_count, len(runs))
    self.assertEqual(setup_fail_count, 1)

    self.assertTrue(successful_session.is_success)
    self.assertTrue(successful_run.is_success)

    # browser startup failures should also propagate down to all runs.
    for exceptions_holder in (runner, thread, failing_session, failing_run):
      self.assertFalse(exceptions_holder.is_success)
      exceptions = exceptions_holder.exceptions
      self.assertEqual(len(exceptions), 1)
      exception_entry = exceptions[0]
      self.assertIsInstance(exception_entry.exception, CustomException)

  def test_run_fail_run(self):
    # 4 runs = (2 browser) x (2 stories)
    runner = self.default_runner(throw=False)
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    failing_run = runs[0]
    failing_session = failing_run.browser_session

    run_fail_count = 0

    def mock_run_story_fail():
      nonlocal run_fail_count
      run_fail_count += 1
      raise CustomException

    with mock.patch.object(failing_run, "_run_story", mock_run_story_fail):
      self.assertEqual(run_fail_count, 0)
      with self.patch_teardown_run(runner) as teardown_run_mock:
        thread.run()
        self.assertEqual(teardown_run_mock.call_count, len(runs))
      self.assertEqual(run_fail_count, 1)

    for session in thread.browser_sessions:
      if session != failing_run.browser_session:
        self.assertTrue(session.is_success)
    for run in runs:
      if run != failing_run:
        self.assertTrue(run.is_success)

    # Errors are propagate up:
    for exceptions_holder in (runner, thread, failing_session, failing_run):
      self.assertFalse(exceptions_holder.is_success)
      exceptions = exceptions_holder.exceptions
      self.assertEqual(len(exceptions), 1)
      exception_entry = exceptions[0]
      self.assertIsInstance(exception_entry.exception, CustomException)

  def test_run_ignore_partial_failures(self):
    # 4 runs = (2 browser) x (2 stories)
    runner = self.default_runner(throw=False)
    runner._setup_runs()
    runs = tuple(runner.all_runs)
    thread = RunThreadGroup(runs)
    failing_run = runs[0]
    failing_session = failing_run.browser_session

    run_fail_count = 0

    def mock_run_story_fail():
      nonlocal run_fail_count
      run_fail_count += 1
      raise CustomException

    with mock.patch.object(failing_run, "_run_story", mock_run_story_fail):
      self.assertEqual(run_fail_count, 0)
      with self.patch_teardown_run(runner) as teardown_run_mock:
        thread.run()
        self.assertEqual(teardown_run_mock.call_count, len(runs))
      self.assertEqual(run_fail_count, 1)

    for session in thread.browser_sessions:
      if session != failing_run.browser_session:
        self.assertTrue(session.is_success)
    for run in runs:
      if run != failing_run:
        self.assertTrue(run.is_success)

    # Errors are propagate up:
    for exceptions_holder in (runner, thread, failing_session, failing_run):
      self.assertFalse(exceptions_holder.is_success)
      exceptions = exceptions_holder.exceptions
      self.assertEqual(len(exceptions), 1)
      exception_entry = exceptions[0]
      self.assertIsInstance(exception_entry.exception, CustomException)

    with (mock.patch.object(runner, "_ignore_partial_failures", True),
          mock.patch.object(runner, "_measured_runs", runs)):
      runner.assert_successful_sessions_and_runs()

  def test_setup_creates_patch_diff(self):
    """Verifies patch.diff is created when git diff returns non-empty output."""
    runner = self.default_runner()
    diff_content = "diff --git a/file.py b/file.py\n+new line"

    def mock_sh(*args, stdout=None, **kwargs):
      del args, kwargs
      if stdout and hasattr(stdout, "write"):
        stdout.write(diff_content)
      return mock.MagicMock()

    with mock.patch.object(
        runner.platform,
        "crossbench_details",
        return_value={"canonical_parent_hash": "abcdef123"}), mock.patch.object(
            runner.platform, "sh", side_effect=mock_sh):
      runner._setup()
    patch_file = runner.out_dir / "patch.diff"
    self.assertTrue(patch_file.exists())
    self.assertEqual(patch_file.read_text(encoding="utf-8"), diff_content)

  def test_setup_creates_patch_diff_no_changes(self):
    """Verifies an empty patch.diff is created when there are no git changes."""
    runner = self.default_runner()
    with mock.patch.object(
        runner.platform,
        "crossbench_details",
        return_value={"canonical_parent_hash": "abcdef123"}), mock.patch.object(
            runner.platform, "sh", return_value=mock.MagicMock()):
      runner._setup()
    patch_file = runner.out_dir / "patch.diff"
    self.assertTrue(patch_file.exists())
    self.assertEqual(patch_file.read_text(encoding="utf-8"), "")

  def test_setup_skips_patch_diff_no_parent_hash(self):
    """Verifies patch.diff is skipped when parent git hash is unavailable."""
    runner = self.default_runner()
    with mock.patch.object(
        runner.platform, "crossbench_details", return_value={}):
      runner._setup()
    patch_file = runner.out_dir / "patch.diff"
    self.assertFalse(patch_file.exists())

  def test_setup_handles_git_patch_exception(self):
    """Verifies setup handles exceptions during git patch generation."""
    runner = self.default_runner()
    with mock.patch.object(
        runner.platform,
        "crossbench_details",
        return_value={"canonical_parent_hash": "abcdef123"}), mock.patch.object(
            runner.platform, "sh", side_effect=OSError("Git failed")):
      runner._setup()

  def test_pause_on_error_flag_disabled_by_default(self):
    runner = self.default_runner(pause_on_error=False)
    mock_run = mock.MagicMock(is_success=False)
    self.assertEqual(runner.check_pause(mock_run), ResumeMode.CONTINUE)

  def test_pause_on_error_flag_enabled(self):
    runner = self.default_runner(pause_on_error=True)
    mock_run = mock.MagicMock(is_success=True)
    self.assertEqual(runner.check_pause(mock_run), ResumeMode.CONTINUE)
    mock_run.is_success = False
    with mock.patch.object(input_helper, "prompt", return_value="s"):
      self.assertEqual(runner.check_pause(mock_run), ResumeMode.STOP)

  def test_stop_early_filters_skipped_runs(self):
    runner = self.default_runner()
    with mock.patch.object(
        runner._pause_controller, "check_pause", return_value=ResumeMode.STOP):
      runner.run()
    self.assertEqual(len(runner.runs), 1)
    self.assertFalse(runner.all_runs[0].is_skipped)
    for skipped_run in runner.all_runs[1:]:
      self.assertTrue(skipped_run.is_skipped)


class DeviceConfigRunnerTestCase(BaseRunnerTestCase):

  def _valid_device_config(self,
                           platform: str = "",
                           value: str = "test_val") -> dict[str, Any]:
    return {
        platform or self.platform.name: {
            "settings": {
                "secure": {
                    "test_key": value,
                },
            },
        },
    }

  def _setup_runner(
      self,
      required: DeviceConfig,
      actual: dict[str, Any],
      mode: RequiredDeviceConfigMode,
  ) -> Runner:
    runner = self.default_runner()
    runner._required_device_config_mode = mode
    with mock.patch.object(
        runner.benchmark, "required_device_config",
        return_value=required), mock.patch.object(
            runner.platform, "device_config", return_value=actual):
      runner._setup()
    return runner

  def test_setup_validates_required_device_config_success(self):
    """Verifies setup succeeds when required device config matches."""
    config = self._valid_device_config()
    self._setup_runner(
        required=config, actual=config, mode=RequiredDeviceConfigMode.THROW)

  def test_setup_skips_unmatched_platform_device_config(self):
    """Verifies setup skips required device config for unmatched platforms."""
    self._setup_runner(
        required=self._valid_device_config("unmatched_platform"),
        actual=self._valid_device_config(value="wrong_val"),
        mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_error(self):
    """Verifies setup raises DeviceConfigValueError on a device discrepancy."""
    with self.assertRaises(DeviceConfigValueError):
      self._setup_runner(
          required=self._valid_device_config(),
          actual=self._valid_device_config(value="wrong_val"),
          mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_warn(self):
    """Verifies setup logs critical and succeeds when mode is warn."""
    with self.assertLogs(level=logging.CRITICAL) as cm:
      self._setup_runner(
          required=self._valid_device_config(),
          actual=self._valid_device_config(value="wrong_val"),
          mode=RequiredDeviceConfigMode.WARN)
    self.assertTrue(any("test_key" in log for log in cm.output))

  def test_setup_validates_required_device_config_from_json_file(self):
    """Verifies setup loads and validates required config from a JSON file."""
    config = self._valid_device_config()
    json_path = self.out_dir.parent / "required_device_config.json"
    json_path.write_text(json.dumps(config), encoding="utf-8")
    self._setup_runner(
        required=json_path, actual=config, mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_case_insensitive_platform(
      self):
    """Verifies setup validates config when platform key has uppercase."""
    config = {self.platform.name.upper(): {"test_prop": "expected_val"}}
    actual = {self.platform.name: {"test_prop": "expected_val"}}
    self._setup_runner(
        required=config, actual=actual, mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_from_json_file_error(self):
    """Verifies setup raises DeviceConfigValueError on a file discrepancy."""
    config = self._valid_device_config()
    json_path = self.out_dir.parent / "required_device_config.json"
    json_path.write_text(json.dumps(config), encoding="utf-8")
    with self.assertRaises(DeviceConfigValueError):
      self._setup_runner(
          required=json_path,
          actual=self._valid_device_config(value="wrong_val"),
          mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_file_not_found(self):
    """Verifies setup raises an argument error when config file is missing."""
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "Path does not exist"):
      self._setup_runner(
          required=self.out_dir.parent / "non_existent.json",
          actual=self._valid_device_config(),
          mode=RequiredDeviceConfigMode.THROW)

  def test_setup_validates_required_device_config_invalid_json(self):
    """Verifies setup raises ValueError on invalid configuration syntax."""
    invalid_json_path = self.out_dir.parent / "invalid.json"
    invalid_json_path.write_text("{not-json", encoding="utf-8")
    with self.assertRaises(ValueError):
      self._setup_runner(
          required=invalid_json_path,
          actual=self._valid_device_config(),
          mode=RequiredDeviceConfigMode.THROW)


class SetDeviceConfigRunnerTestCase(BaseRunnerTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    # Writing any of these values raises.
    self.failing_values: set[str] = set()
    real_set = self.platform.set_device_config_value

    def set_or_raise(key_path: tuple[str, ...], val: str | None) -> None:
      if val in self.failing_values:
        raise RuntimeError(f"Cannot write {val!r}.")
      real_set(key_path, val)

    patcher = mock.patch.object(
        self.platform, "set_device_config_value", side_effect=set_or_raise)
    patcher.start()
    self.addCleanup(patcher.stop)

  def _runner(self,
              value: str | None,
              mode: RequiredDeviceConfigMode = RequiredDeviceConfigMode.SET,
              throw: bool = True) -> Runner:
    """Returns a runner requiring test_key to be test_val.

    The platform's test_key starts as value, or absent if None.
    """
    runner = self.default_runner(throw=throw)
    runner._required_device_config_mode = mode
    required = {
        self.platform.name: {
            "settings": {
                "secure": {
                    "test_key": "test_val",
                },
            },
        },
    }
    patcher = mock.patch.object(
        runner.benchmark, "required_device_config", return_value=required)
    patcher.start()
    self.addCleanup(patcher.stop)
    secure = {} if value is None else {"test_key": value}
    self.platform.device_config_data = {"settings": {"secure": secure}}
    return runner

  def _run_failing(self, runner: Runner, target: Any, attribute: str) -> None:
    """Runs, with target.attribute raising a ValueError."""
    with mock.patch.object(
        target, attribute, side_effect=ValueError("Failed.")):
      with self.assertRaisesRegex(ValueError, "Failed."):
        runner.run()

  @property
  def value(self) -> str | None:
    return self.platform.device_config_data["settings"]["secure"].get(
        "test_key")

  @property
  def writes(self) -> list[str | None]:
    """The values successfully written, in order."""
    return [value for _, value in self.platform.device_config_writes]

  def test_run_sets_and_restores_device_config(self):
    runner = self._runner("wrong_val")
    values_during_run: list[str | None] = []
    run = runner._run

    def recording_run(is_dry_run: bool) -> None:
      values_during_run.append(self.value)
      run(is_dry_run)

    with mock.patch.object(runner, "_run", side_effect=recording_run):
      runner.run()
    self.assertEqual(values_during_run, ["test_val"])
    self.assertEqual(self.value, "wrong_val")

  def test_setup_skips_matching_device_config(self):
    runner = self._runner("test_val")
    runner._setup()
    self.assertEqual(self.writes, [])

  def test_run_restores_device_config_on_later_setup_failure(self):
    runner = self._runner("wrong_val")
    self._run_failing(runner, runner, "_setup_probes")
    self.assertEqual(self.writes, ["test_val", "wrong_val"])

  def test_run_restores_device_config_on_run_failure(self):
    runner = self._runner(None)
    self._run_failing(runner, runner, "_run")
    self.assertEqual(self.writes, ["test_val", None])

  def test_run_restores_device_config_on_teardown_failure(self):
    runner = self._runner("wrong_val")
    self._run_failing(runner, runner.benchmark, "teardown")
    self.assertEqual(self.writes, ["test_val", "wrong_val"])

  def test_setup_raises_when_set_fails(self):
    runner = self._runner("wrong_val")
    self.failing_values.add("test_val")
    with self.assertRaisesRegex(RuntimeError, "Cannot write 'test_val'."):
      runner._setup()
    self.assertEqual(self.writes, [])
    self.assertEqual(self.value, "wrong_val")

  def test_dry_run_warns_instead_of_setting(self):
    runner = self._runner("wrong_val")
    with self.assertLogs(level="CRITICAL") as logs:
      runner.run(is_dry_run=True)
    self.assertIn("Device config discrepancies", "\n".join(logs.output))
    self.assertEqual(self.writes, [])

  def test_dry_run_keeps_throw_mode(self):
    runner = self._runner("wrong_val", mode=RequiredDeviceConfigMode.THROW)
    with self.assertRaises(DeviceConfigValueError):
      runner.run(is_dry_run=True)
    self.assertEqual(self.writes, [])

  def test_failed_restore_does_not_mask_run_failure(self):
    """Verify a failed run's error is raised, not a restore failure."""
    runner = self._runner("wrong_val")
    self.failing_values.add("wrong_val")
    with self.assertLogs(level=logging.ERROR) as logs:
      self._run_failing(runner, runner, "_run")
    self.assertIn("Failed to restore device config", "\n".join(logs.output))
    self.assertEqual(runner._exceptions.matching(DeviceConfigValueError), [])
    self.assertEqual(self.value, "test_val")

  def test_run_reports_failed_device_config_restore(self):
    """Verify a restore failure after a successful run fails the run.

    Restoring is broken only once the run is done, so that only the restore
    fails. throw=False collects the error, rather than raising it.
    """
    runner = self._runner("wrong_val", throw=False)
    run = runner._run

    def run_then_break_restore(is_dry_run: bool) -> None:
      run(is_dry_run)
      self.failing_values.add("wrong_val")

    with mock.patch.object(runner, "_run", side_effect=run_then_break_restore):
      with self.assertRaises(MultiException):
        runner.run()
    errors = runner._exceptions.matching(DeviceConfigValueError)
    self.assertEqual(len(errors), 1)
    self.assertIn("Failed to restore device config", str(errors[0]))
    self.assertEqual(self.value, "test_val")


del BaseRunnerTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
