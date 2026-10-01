# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import pathlib
from typing import TYPE_CHECKING, Iterable
from unittest import mock

from typing_extensions import override

from crossbench import path as pth
from crossbench.browsers.settings import Settings
from crossbench.runner.runner import Runner
from tests.crossbench.base import BaseCrossbenchTestCase
from tests.crossbench.mock_browser import MockChromeDev, MockFirefox
from tests.crossbench.mock_helper import MockBenchmark, MockStory

if TYPE_CHECKING:
  from crossbench import plt
  from crossbench.benchmarks.base import Benchmark
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import Probe

from tests.crossbench.runner.mocks import MockBrowser, MockNetwork, \
    MockPlatform, MockProbe, MockProbeContext, MockRun, MockRunner, MockWait

__all__ = [
    "BaseRunnerTestCase",
    "MockBrowser",
    "MockRun",
    "MockPlatform",
    "MockWait",
    "MockRunner",
    "MockNetwork",
    "MockProbe",
    "MockProbeContext",
]


class CrossbenchMagicMockMixin:
  if TYPE_CHECKING:
    platform: plt.Platform
    magic_mock_session: mock.MagicMock

  @property
  def magic_mock_platform(self) -> mock.MagicMock:
    return mock.MagicMock(name="magic_mock_platform")

  @property
  def magic_mock_browser(self) -> mock.MagicMock:
    browser = mock.MagicMock(name="magic_mock_browser")
    browser.unique_name = "mock_browser"
    browser.platform = self.magic_mock_platform
    browser.host_platform = self.platform
    return browser

  @property
  def magic_mock_session(self) -> mock.MagicMock:
    session = mock.MagicMock(name="magic_mock_session")
    session.browser = self.magic_mock_browser
    session.root_dir = pth.LocalPath("/path/to/root")
    return session

  def mock_run(
      self,
      result_path: str | pth.AnyPath = "/results/logcat.txt",
  ) -> MockRun:
    local_path = pth.LocalPath(result_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run = MockRun(mock.MagicMock(), self.magic_mock_session)
    run.get_default_probe_result_path = mock.MagicMock(return_value=local_path)
    return run


class BaseRunnerTestCase(
    CrossbenchMagicMockMixin, BaseCrossbenchTestCase, metaclass=abc.ABCMeta):

  @override
  def setUp(self):
    super().setUp()
    self.out_dir = pathlib.Path("/testing/out_dir")
    self.out_dir.parent.mkdir(exist_ok=False, parents=True)
    self.stories = [MockStory("story_1"), MockStory("story_2")]
    self.benchmark = MockBenchmark(self.stories)
    self.mock_chrome_dev = MockChromeDev(
        "chrome-dev", settings=Settings(platform=self.platform))
    self.mock_firefox = MockFirefox(
        "firefox-stable", settings=Settings(platform=self.platform))
    self.browsers: list[Browser] = [self.mock_chrome_dev, self.mock_firefox]

  def default_runner(
      self,
      browsers: Iterable[Browser] | None = None,
      benchmark: Benchmark | None = None,
      probes: Iterable[Probe] | None = None,
      throw: bool = True,
      create_symlinks: bool = True,
      disabled_probes: Iterable[str] = (),
      pause_on_error: bool = False,
  ) -> Runner:
    return Runner(
        self.out_dir,
        browsers=browsers or self.browsers,
        benchmark=benchmark or self.benchmark,
        probes=probes or (),
        platform=self.platform,
        create_symlinks=create_symlinks,
        throw=throw,
        in_memory_result_db=True,
        disabled_probes=disabled_probes,
        pause_on_error=pause_on_error)

  def single_story_runner(self,
                          browser: Browser | None = None,
                          throw: bool = True) -> Runner:
    browsers = [browser or self.mock_chrome_dev]
    benchmark = MockBenchmark([self.stories[0]])
    return Runner(
        self.out_dir,
        browsers,
        benchmark,
        platform=self.platform,
        throw=throw,
        in_memory_result_db=True)
