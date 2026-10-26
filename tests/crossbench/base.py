# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import contextlib
import dataclasses
import datetime as dt
import io
import logging
import pathlib
from typing import TYPE_CHECKING, Any, Callable, Final, Iterator, Sequence
from unittest import mock

from pyfakefs import fake_filesystem_unittest
from typing_extensions import override

import crossbench
from crossbench import path as pth
from crossbench import plt
from crossbench.action_runner.action.wait_for_ready_state import \
    WaitForReadyStateAction
from crossbench.benchmarks.loading.browser_startup import \
    BrowserStartupBenchmark
from crossbench.benchmarks.loading.playback_controller import \
    PlaybackController
from crossbench.benchmarks.loading.tab_controller import TabController
from crossbench.benchmarks.loadline import LoadLine1TabletBenchmark, \
    LoadLine2TabletBenchmark
from crossbench.browsers.settings import Settings
from crossbench.cli.config.browser_variants import BaseBrowserVariantsConfig
from crossbench.cli.config.env import EnvConfig
from crossbench.cli.config.network import NetworkConfig
from crossbench.cli.config.secrets import Secrets
from crossbench.cli.parser import CBNamespace
from crossbench.cli.subcommand.benchmark import BenchmarkSubcommand
from crossbench.config import config_dir
from crossbench.flags.base import Flags
from crossbench.probes.cb_perfetto.perfetto import TraceConfig
from crossbench.runner.groups.session import BrowserSessionRunGroup
from crossbench.runner.runner import Runner
from tests.crossbench import mock_browser
from tests.crossbench.mock_helper import MockCLI, MockPlatform
from tests.crossbench.runner.mocks import MockRun, MockRunner

if TYPE_CHECKING:
  from pyfakefs import fake_filesystem

  from crossbench.browsers.browser import Browser


class CrossbenchFakeFsTestCase(
    fake_filesystem_unittest.TestCase, metaclass=abc.ABCMeta):

  def setUp(self) -> None:
    super().setUp()
    self.setUpPyfakefs(modules_to_reload=[crossbench, mock_browser, pth, plt])
    # gettext is used extensively in argparse
    gettext_patcher = mock.patch(
        "gettext.dgettext", side_effect=lambda domain, message: message)
    gettext_patcher.start()
    self.addCleanup(gettext_patcher.stop)

    sleep_patcher = mock.patch("time.sleep", return_value=None)
    self.sleep_mock = sleep_patcher.start()
    self.addCleanup(sleep_patcher.stop)

    atexit_patcher = mock.patch("atexit.register")
    self.mock_atexit_register = atexit_patcher.start()
    self.addCleanup(atexit_patcher.stop)

    # This is platform specific and causes issues pending sh commands
    self.wakelock_patcher = mock.patch("crossbench.plt.PLATFORM.wakelock")
    self.addCleanup(self.wakelock_patcher.stop)
    self.wakelock_patcher.start()

  def create_file(self, path_str: str, contents: str = "") -> pathlib.Path:
    path = pathlib.Path(path_str)
    self.fs.create_file(path, contents=contents)
    return path

  def setup_chromium_checkout(self, chrome_src: pth.AnyPath) -> None:
    self.fs.create_file(chrome_src.parent / ".gclient")
    self.fs.create_file(chrome_src / "tools/perf/cb")
    self.fs.create_dir(chrome_src / "third_party/crossbench")

  def mock_platform_default_tmp_dir(self, platform_cls: type) -> None:
    patcher = mock.patch.object(
        platform_cls,
        "_create_default_tmp_dir",
        return_value=pth.AnyPosixPath("/var/tmp"))
    self.addCleanup(patcher.stop)
    patcher.start()


TEST_WARNING = "Test Warning"


class CrossbenchMockArgsMixin:

  def mock_args(self, **kwargs) -> CBNamespace:
    args = CBNamespace(
        wraps=kwargs.pop("wraps", False),
        throw=kwargs.pop("throw", False),
        browser=kwargs.pop("browser", []),
        driver_path=kwargs.pop("driver_path", None),
        remote_driver_path=kwargs.pop("remote_driver_path", None),
        network_config=kwargs.pop("network_config", NetworkConfig.default()),
        browser_config=kwargs.pop("browser_config", None),
        probe_config=kwargs.pop("probe_config", None),
        viewport=kwargs.pop("viewport", None),
        splash_screen=kwargs.pop("splash_screen", None),
        secrets=kwargs.pop("secrets", Secrets()),
        driver_logging=kwargs.pop("driver_logging", False),
        wipe_system_user_data=kwargs.pop("wipe_system_user_data", False),
        http_request_timeout=kwargs.pop("", dt.timedelta()),
        cache_dir=pathlib.Path("test_cache_dir"),
        browser_cache_dir=kwargs.pop("browser_cache_dir", None),
        clear_browser_cache_dir=kwargs.pop("clear_browser_cache_dir", None),
        enable_features=kwargs.pop("enable_features", None),
        disable_features=kwargs.pop("disable_features", None),
        js_flags=kwargs.pop("js_flags", None),
        sandbox=kwargs.pop("sandbox", None),
        enable_field_trial_config=kwargs.pop("enable_field_trial_config", None),
        network=kwargs.pop("network", NetworkConfig.default()),
        probe=kwargs.pop("probe", []),
        no_probe=kwargs.pop("no_probe", []),
        extra_browser_args=kwargs.pop("extra_browser_args", []),
        other_browser_args=kwargs.pop("other_browser_args", []),
        playback=kwargs.pop("playback", PlaybackController.default()),
        tabs=kwargs.pop("tabs", TabController.default()),
        about_blank_duration=kwargs.pop("about_blank_duration", dt.timedelta()),
        run_login=kwargs.pop("run_login", True),
        run_setup=kwargs.pop("run_setup", True),
        env_config=kwargs.pop("env_config", EnvConfig.default()),
        binary_overrides=kwargs.pop("binary_overrides", []),
        action_runner_config=kwargs.pop("action_runner_config", None))
    assert not kwargs, f"got unused kwargs: {kwargs}"
    return args


class CrossbenchConfigTestMixin:
  fs: fake_filesystem.FakeFilesystem

  def setup_loadline_configs(self):
    self.setup_config_dir(
        LoadLine1TabletBenchmark.default_network_config_path().parent)
    self.setup_config_dir(
        LoadLine2TabletBenchmark.default_network_config_path().parent)

  def setup_browser_startup_configs(self) -> None:
    self.setup_config_dir(
        BrowserStartupBenchmark.default_probe_config_path().parent)

  def setup_perfetto_config_presets(self):
    self.setup_config_dir(TraceConfig.preset_dir())
    self.setup_config_dir(config_dir() / "doc/probe")

  def setup_config_dir(self, config_dir):
    self.fs.add_real_directory(config_dir, lazy_read=True)


class CrossbenchPlatformMockMixin:
  if TYPE_CHECKING:
    platform: plt.Platform
    addCleanup: Callable[..., None]  # noqa: N815

  def setup_platform_mock(self) -> None:
    platform_id_patcher = mock.patch("crossbench.plt.base._NEXT_PLATFORM_ID",
                                     777)
    platform_id_patcher.start()
    self.addCleanup(platform_id_patcher.stop)

    mock_platform_patcher = mock.patch("crossbench.plt.PLATFORM", self.platform)
    mock_platform_patcher.start()
    self.addCleanup(mock_platform_patcher.stop)


class BaseCrossbenchTestCase(
    CrossbenchConfigTestMixin,
    CrossbenchMockArgsMixin,
    CrossbenchPlatformMockMixin,
    CrossbenchFakeFsTestCase,
    metaclass=abc.ABCMeta):

  def filter_splashscreen_urls(self, urls: Sequence[str]) -> list[str]:
    return [url for url in urls if not url.startswith("data:")]

  @override
  def setUp(self) -> None:
    # Instantiate MockPlatform before setting up fake_filesystem so we can
    # still interact with the original, real plt.Platform object for extracting
    # basic system information.
    self.platform = self.setup_platform()
    self.platform.use_fs = True
    super().setUp()
    # Reset the platform ID counter for each test
    # The PLATFORM singleton is created at import time, so we need to patch
    # the counter in the base module.
    self.setup_platform_mock()

    self._default_log_level = logging.getLogger().getEffectiveLevel()
    logging.getLogger().setLevel(logging.CRITICAL)

    for mock_browser_cls in mock_browser.ALL:
      mock_browser_cls.setup_fs(self.fs, self.platform)
      self.assertTrue(
          self.platform.exists(mock_browser_cls.mock_app_path(self.platform)))
    self.out_dir = pathlib.Path("/crossbench-test/results/test")
    self.out_dir.parent.mkdir(parents=True)
    self.browsers: list[mock_browser.MockBrowser] = [
        mock_browser.MockChromeDev(
            "dev", settings=Settings(platform=self.platform)),
        mock_browser.MockChromeStable(
            "stable", settings=Settings(platform=self.platform)),
    ]
    for browser in self.browsers:
      self.assertSequenceEqual(browser.expected_js, [])

  def setup_platform(self) -> MockPlatform:
    return MockPlatform()

  def tearDown(self) -> None:
    logging.getLogger().setLevel(self._default_log_level)
    self.assertSequenceEqual(self.platform.sh_results, [])
    super().tearDown()

  def mock_run(
      self,
      runner: Any | None = None,
      browser: Any | None = None,
      story: str = "story",
  ) -> MockRun:
    runner = runner or MockRunner()
    browser = browser or self.browsers[0]
    session = BrowserSessionRunGroup(
        runner.env,
        runner.probes,
        browser,
        Flags(),
        1,
        pathlib.Path(),
        True,
        True,
    )
    return MockRun(runner, session, story)


class SysExitTestException(Exception):

  def __init__(self, exit_code=0):
    super().__init__("sys.exit")
    self.exit_code = exit_code


@dataclasses.dataclass
class IoCapture:
  stdout: str = ""
  stderr: str = ""


class BaseCliTestCase(BaseCrossbenchTestCase):

  SPLASH_URLS_LEN: Final[int] = 2

  @override
  def setUp(self) -> None:
    super().setUp()
    # tabulate and textwrap can be slow for tests, let's mock them out.
    self.setup_tabulate_patcher()
    self.setup_wrap_patcher()
    self.setup_wait_for_ready_state_patcher()
    self.setup_loadline_configs()
    self.setup_browser_startup_configs()
    self.setup_perfetto_config_presets()

  def setup_tabulate_patcher(self) -> None:

    def mock_tabulate(table, *args, **kwargs):
      del args, kwargs
      return str(table)

    patcher = mock.patch("tabulate.tabulate", side_effect=mock_tabulate)
    self.addCleanup(patcher.stop)
    patcher.start()

  def setup_wrap_patcher(self) -> None:

    def mock_wrap(text, *args, **kwargs):
      del args, kwargs
      return [text]

    patcher = mock.patch("textwrap.wrap", side_effect=mock_wrap)
    self.addCleanup(patcher.stop)
    patcher.start()

  def setup_wait_for_ready_state_patcher(self):
    patcher = mock.patch.object(
        WaitForReadyStateAction, "run_with", return_value=True)
    self.addCleanup(patcher.stop)
    patcher.start()

  @contextlib.contextmanager
  def capture_io(self) -> Iterator[IoCapture]:
    io_capture = IoCapture()
    with mock.patch(
        "sys.stdout", new_callable=io.StringIO) as mock_stdout, mock.patch(
            "sys.stderr", new_callable=io.StringIO) as mock_stderr:
      try:
        yield io_capture
      finally:
        # Ensure we don't accidentally reuse the buffers across run_cli calls.
        io_capture.stdout = mock_stdout.getvalue()
        io_capture.stderr = mock_stderr.getvalue()
        mock_stdout.close()
        mock_stderr.close()

  def run_cli_output(self,
                     *args,
                     raises=None,
                     enable_logging: bool = True) -> tuple[MockCLI, str, str]:
    with self.capture_io() as io_capture:
      cli = self.run_cli(*args, raises=raises, enable_logging=enable_logging)
    return cli, io_capture.stdout, io_capture.stderr

  @contextlib.contextmanager
  def _patch_get_runner(self) -> Iterator[None]:
    with mock.patch.object(
        BenchmarkSubcommand, "_get_runner", side_effect=self._mock_get_runner):
      yield

  def _mock_get_runner(self, args, benchmark, probes, env_config,
                       env_validation_mode, timing):
    if not args.out_dir:
      # Use stable mock out dir
      args.out_dir = pathlib.Path("/results")
      assert not args.out_dir.exists()
    runner_kwargs = Runner.kwargs_from_cli(args)
    runner = Runner(
        benchmark=benchmark,
        probes=probes,
        env_config=env_config,
        env_validation_mode=env_validation_mode,
        timing=timing,
        **runner_kwargs,
        # Use custom platform
        platform=self.platform,
        in_memory_result_db=True)
    return runner

  @contextlib.contextmanager
  def _patch_sys_exit(self) -> Iterator[None]:
    with mock.patch(
        "sys.exit", side_effect=SysExitTestException), mock.patch.object(
            plt, "PLATFORM", self.platform):
      yield

  @contextlib.contextmanager
  def _patch_get_browser_cls(self,
                             return_value: type[Browser] | None = None,
                             **kwargs) -> Iterator[mock.MagicMock]:
    if not kwargs:
      kwargs["return_value"] = return_value or mock_browser.MockChromeStable
    with mock.patch.object(BaseBrowserVariantsConfig, "get_browser_cls",
                           **kwargs) as patcher:
      yield patcher

  @contextlib.contextmanager
  def cli(self, enable_logging: bool = False) -> Iterator[MockCLI]:
    cli = MockCLI(platform=self.platform, enable_logging=enable_logging)
    with self._patch_sys_exit(), self._patch_get_runner():
      yield cli

  def run_cli(self,
              *args,
              raises=None,
              enable_logging: bool = False) -> MockCLI:
    with self.cli(enable_logging=enable_logging) as cli:
      if raises:
        with self.assertRaises(raises):
          cli.run(args)
      else:
        cli.run(args)
    return cli

  @contextlib.contextmanager
  def _patch_get_browser(
      self,
      return_value: Sequence[Browser] | None = None,
  ) -> Iterator[None]:
    if not return_value:
      return_value = self.browsers
    with mock.patch.object(
        BenchmarkSubcommand, "_get_browsers", return_value=return_value):
      yield
