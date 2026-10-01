# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import TYPE_CHECKING, Any, NamedTuple

from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.base import ActionRunner
from crossbench.cli.config.secrets import Secrets
from crossbench.env.runner_env import RunnerEnv
from crossbench.exception import Annotator
from crossbench.helper.durations import Durations
from crossbench.helper.wait import WaitRange
from crossbench.probes.probe import Probe
from crossbench.probes.probe_context import ProbeContext
from crossbench.probes.results import LocalProbeResult, ProbeResult
from crossbench.runner.actions import Actions
from crossbench.runner.pause_controller import ResumeMode
from crossbench.runner.result_origin import ResultOrigin
from crossbench.runner.timing import Timing
from tests.crossbench.mock_helper import MockBenchmark, MockStory

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import ProbeT
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner
  from crossbench.runner.timing import AnyTimeUnit


class MockBrowser:

  def __init__(self, unique_name: str, platform) -> None:
    self.unique_name = unique_name
    self.platform = platform
    self.network = MockNetwork()

  def __str__(self):
    return self.unique_name


class MockRun(ResultOrigin):

  def __init__(self,
               runner,
               browser_session,
               story="story",
               action_runner: ActionRunner | None = None,
               repetition=0,
               is_warmup=False,
               temperature="default",
               index=0,
               name="run 0",
               probe=None,
               probe_context=None) -> None:
    self._runner = runner
    self.browser_session = browser_session
    self._browser = browser_session.browser
    self._exceptions = Annotator(False)
    self._durations = Durations()
    self._browser_tmp_dir = pth.AnyPath("/browser_tmp")
    self.repetition = repetition
    self.is_warmup = is_warmup
    self.temperature = temperature
    self.name = name
    self._probes: list[Probe] = [probe]
    self.probe_context: ProbeContext | None = probe_context
    self.timing = Timing()
    self.is_success = True
    self.index = index
    self.story = story
    self.action_runner: ActionRunner = action_runner or ActionRunner(self)
    self.action_runner.run = self

    self.story_secrets = Secrets()
    self._out_dir = (
        browser_session.root_dir /
        pth.safe_filename(self._browser.unique_name) / "stories" / name /
        f"repetition={self.repetition}" / self.temperature)
    self.group_dir = self._out_dir.parent
    self.did_setup = False
    self.did_run = False
    self.did_teardown = False
    self.did_teardown_browser = False
    self.is_skipped = False
    self.is_dry_run: bool | None = None

  @property
  def benchmark(self) -> Any:
    return self._runner.benchmark

  def validate_env(self, env: RunnerEnv):
    pass

  def setup(self, is_dry_run: bool) -> None:
    assert self.is_dry_run is None
    self.is_dry_run = is_dry_run
    assert not self.did_setup
    self.did_setup = True

  def actions(self,
              name: str,
              verbose: bool = False,
              measure: bool = True,
              performance_mark: str = "") -> Actions:
    return Actions(
        name,
        self,
        verbose=verbose,
        measure=measure,
        performance_mark=performance_mark)

  def set_probe_context(self, probe_context: ProbeContext) -> None:
    self.probe_context = probe_context

  @property
  def runner(self) -> Runner:
    return self._runner

  @runner.setter
  def runner(self, value: Runner) -> None:
    self._runner = value

  @property
  def probes(self) -> list[Probe]:
    return self._probes

  @probes.setter
  def probes(self, value: list[Probe]) -> None:
    self._probes = value

  @property
  def browser(self) -> Browser:
    return self._browser

  @browser.setter
  def browser(self, value: Browser) -> None:
    self._browser = value

  @property
  def out_dir(self) -> pth.LocalPath:
    return self._out_dir

  @out_dir.setter
  def out_dir(self, value: pth.LocalPath) -> None:
    self._out_dir = value

  @property
  def exceptions(self) -> Annotator:
    return self._exceptions

  @property
  def durations(self) -> Durations:
    return self._durations

  @property
  def browser_tmp_dir(self) -> pth.AnyPath:
    return self._browser_tmp_dir

  @property
  def secrets(self) -> Secrets:
    return self.story_secrets.merge(fallback=self.browser.secrets)

  @property
  def is_remote(self) -> bool:
    return self.browser_platform.is_remote

  def max_end_datetime(self) -> dt.datetime:
    return dt.datetime.max

  def mark_skipped(self) -> None:
    self.is_skipped = True

  def run(self, is_dry_run: bool) -> None:
    assert self.is_dry_run is is_dry_run
    assert not self.did_run
    self.did_run = True

  def teardown(self, is_dry_run: bool) -> None:
    assert self.is_dry_run is is_dry_run
    assert not self.did_teardown
    self.did_teardown = True

  def wait_range(self,
                 min_interval: AnyTimeUnit,
                 timeout: AnyTimeUnit,
                 delay: AnyTimeUnit = 0) -> WaitRange:
    timing = self.timing
    return WaitRange(
        min=timing.timedelta(min_interval),
        timeout=timing.timeout_timedelta(timeout),
        delay=timing.timedelta(delay))

  def get_probe_context(self,
                        probe_cls: type[ProbeT]) -> ProbeContext[ProbeT] | None:
    del probe_cls
    return self.probe_context

  def get_default_probe_result_path(self, probe: Probe) -> pth.AnyPath:
    del probe
    return pth.AnyPath("/")

  def get_local_probe_result_path(self, probe: Probe) -> pth.LocalPath:
    del probe
    return pth.LocalPath("/")

  def _teardown_browser(self, is_dry_run: bool) -> None:
    assert self.is_dry_run is is_dry_run
    assert not self.did_teardown_browser
    self.did_teardown_browser = True
    self.browser.quit()

  def __repr__(self):
    return f"MockRun({self.name}, id={hex(id(self))})"

  def __str__(self):
    return self.name


class MockPlatform:

  def __init__(self, name) -> None:
    self.name = name

  def __str__(self):
    return self.name

  @property
  def key(self) -> str:
    return self.name

  def setup_virtual_devices(self, virtual_devices: tuple) -> None:
    del virtual_devices


class MockWait(NamedTuple):
  time: AnyTimeUnit
  absolute_time: bool


class MockRunner:

  def __init__(self, probes: list[Probe] | None = None) -> None:
    self.benchmark = MockBenchmark(stories=[MockStory("mock_story")])
    self.runs: tuple[Run, ...] = ()
    self.platform = MockPlatform("test-platform")
    self.repetitions = 1
    self.create_symlinks = True
    self.probes: list[Probe] = probes if probes else []
    self.browsers: list[Browser] = []
    self.out_dir = pathlib.Path("results/out")
    self.timing = Timing()
    self.env = RunnerEnv(self.platform, self.out_dir, self.browsers,
                         self.probes, self.repetitions)
    self.mock_waits: list[MockWait] = []

  def check_pause(self, run: Run) -> ResumeMode:
    del run
    return ResumeMode.CONTINUE

  def wait(self, time: AnyTimeUnit, absolute_time: bool = False) -> None:
    self.mock_waits.append(MockWait(time, absolute_time))


class MockNetwork:
  pass


class MockProbe(Probe):
  NAME = "test-probe"

  def __init__(self,
               test_data: Any = (),
               context_cls: type[MockProbeContext] | None = None) -> None:
    super().__init__()
    self.test_data = test_data
    self.context_cls = context_cls or MockProbeContext

  @property
  @override
  def result_path_name(self) -> str:
    return f"{self.name}.json"

  @override
  def get_context_cls(self):
    return self.context_cls


class MockProbeContext(ProbeContext):

  def start(self) -> None:
    pass

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    with pathlib.Path(self.result_path).open("w", encoding="utf-8") as f:
      json.dump(self.probe.test_data, f)
    return LocalProbeResult(json=(self.result_path,))
