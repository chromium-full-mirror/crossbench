# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, ClassVar, Final, Generic, Iterable, Self, \
    TypeVar

from typing_extensions import override

from crossbench.parse import ObjectParser
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeKeyT
from crossbench.probes.probe_context import ProbeContext
from crossbench.probes.probe_error import ProbeValidationError
from crossbench.probes.results import LocalProbeResult, ProbeResult

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench import plt
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.plt.types import CmdArg, TupleCmdArgs
  from crossbench.runner.run import Run


class ShellProbeBase(Probe):
  """
  Base class for probes executing shell commands at lifecycle hooks.
  """

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "setup_cmd",
        aliases=("setup",),
        type=ObjectParser.sh_cmd,
        help="CMD is run before the browser is started.")
    parser.add_argument(
        "start_cmd",
        type=ObjectParser.sh_cmd,
        aliases=("start",),
        help=("CMD is run right before each story is started "
              "and the browser is already running."))
    parser.add_argument(
        "start_story_run_cmd",
        aliases=("start-story",),
        type=ObjectParser.sh_cmd,
        help=("CMD is run right before the measurement phase "
              "of a story is started."))
    parser.add_argument(
        "stop_story_run_cmd",
        aliases=("stop-story",),
        type=ObjectParser.sh_cmd,
        help=("CMD is run right after the measurement phase "
              "of a story has ended."))
    parser.add_argument(
        "stop_cmd",
        aliases=("stop",),
        type=ObjectParser.sh_cmd,
        required=True,
        help=("CMD is run right after the workload ended and the browser "
              "is still running."))
    parser.add_argument(
        "teardown_cmd",
        aliases=("teardown",),
        type=ObjectParser.sh_cmd,
        help="CMD is run after the browser is stopped.")
    return parser

  def __init__(self,
               setup_cmd: Iterable[CmdArg] | None = None,
               start_cmd: Iterable[CmdArg] | None = None,
               start_story_run_cmd: Iterable[CmdArg] | None = None,
               stop_story_run_cmd: Iterable[CmdArg] | None = None,
               stop_cmd: Iterable[CmdArg] | None = None,
               teardown_cmd: Iterable[CmdArg] | None = None) -> None:
    super().__init__()
    self._setup_cmd: Final[TupleCmdArgs] = tuple(setup_cmd) if setup_cmd else ()
    self._start_cmd: Final[TupleCmdArgs] = tuple(start_cmd) if start_cmd else ()
    self._start_story_run_cmd: Final[TupleCmdArgs] = (
        tuple(start_story_run_cmd) if start_story_run_cmd else ())
    self._stop_story_run_cmd: Final[TupleCmdArgs] = (
        tuple(stop_story_run_cmd) if stop_story_run_cmd else ())
    self._stop_cmd: Final[TupleCmdArgs] = tuple(stop_cmd) if stop_cmd else ()
    self._teardown_cmd: Final[TupleCmdArgs] = (
        tuple(teardown_cmd) if teardown_cmd else ())

  @abc.abstractmethod
  @override
  def get_context_cls(self: Self) -> type[ProbeContext[Self]]:
    pass

  @property
  @override
  def key(self) -> ProbeKeyT:
    return (*super().key, ("setup_cmd", tuple(map(str, self.setup_cmd))),
            ("start_cmd", tuple(map(str, self.start_cmd))),
            ("start_story_run_cmd", tuple(map(str, self.start_story_run_cmd))),
            ("stop_story_run_cmd", tuple(map(str, self.stop_story_run_cmd))),
            ("stop_cmd", tuple(map(str, self.stop_cmd))),
            ("teardown_cmd", tuple(map(str, self.teardown_cmd))))

  @property
  def setup_cmd(self) -> TupleCmdArgs:
    return self._setup_cmd

  @property
  def start_cmd(self) -> TupleCmdArgs:
    return self._start_cmd

  @property
  def start_story_run_cmd(self) -> TupleCmdArgs:
    return self._start_story_run_cmd

  @property
  def stop_story_run_cmd(self) -> TupleCmdArgs:
    return self._stop_story_run_cmd

  @property
  def stop_cmd(self) -> TupleCmdArgs:
    return self._stop_cmd

  @property
  def teardown_cmd(self) -> TupleCmdArgs:
    return self._teardown_cmd

  @abc.abstractmethod
  def target_platform(self, browser: Browser) -> plt.Platform:
    pass

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    target_platform = self.target_platform(browser)
    for cmd_name in (
        "setup_cmd",
        "start_cmd",
        "start_story_run_cmd",
        "stop_story_run_cmd",
        "stop_cmd",
        "teardown_cmd",
    ):
      self._validate_cmd(target_platform, cmd_name)

  def _validate_cmd(self, platform: plt.Platform, cmd_name: str) -> None:
    cmd: TupleCmdArgs = getattr(self, cmd_name)
    if not cmd:
      return
    program = str(cmd[0])
    if platform.which(program):
      return
    raise ProbeValidationError(
        self, f"Command '{program}' in {cmd_name} is not executable or "
        f"does not exist on the target platform '{platform}'.")

  @override
  def validate_env(self, env: RunnerEnv) -> None:
    super().validate_env(env)
    if env.repetitions != 1:
      env.handle_warning(f"Probe={self.NAME} cannot merge data over multiple "
                         f"repetitions={env.repetitions}.")


class ShellProbe(ShellProbeBase):
  """
  Run an arbitrary shell command on the browser platform and store the
  stdout and stderr of the command as a result file.
  """
  NAME: ClassVar = "shell"

  @override
  def target_platform(self, browser: Browser) -> plt.Platform:
    return browser.platform

  @override
  def get_context_cls(self) -> type[ShellProbeContext]:
    return ShellProbeContext


ProbeT = TypeVar("ProbeT", bound="ShellProbeBase")


class ShellProbeContextBase(ProbeContext[ProbeT], Generic[ProbeT]):
  """
  Base ProbeContext for executing shell commands at lifecycle hooks.
  """

  def __init__(self, probe: ProbeT, run: Run) -> None:
    super().__init__(probe, run)
    self._result_files: Final[list[pth.LocalPath]] = []

  @property
  @abc.abstractmethod
  def target_platform(self) -> plt.Platform:
    pass

  def _maybe_run_cmd(self, name: str, cmd: TupleCmdArgs) -> None:
    if not cmd:
      return
    stdout_path = self.local_result_path / f"{name}.stdout.txt"
    self.host_platform.touch(stdout_path)
    self._result_files.append(stdout_path)
    stderr_path = self.local_result_path / f"{name}.stderr.txt"
    self.host_platform.touch(stderr_path)
    self._result_files.append(stderr_path)
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
      self.target_platform.sh(*cmd, stdout=stdout, stderr=stderr)

  @override
  def setup(self) -> None:
    self.host_platform.mkdir(self.local_result_path)
    self._maybe_run_cmd("setup", self.probe.setup_cmd)

  def start(self) -> None:
    self._maybe_run_cmd("start", self.probe.start_cmd)

  @override
  def start_story_run(self) -> None:
    self._maybe_run_cmd("start_story_run", self.probe.start_story_run_cmd)

  @override
  def stop_story_run(self) -> None:
    self._maybe_run_cmd("stop_story_run", self.probe.stop_story_run_cmd)

  def stop(self) -> None:
    self._maybe_run_cmd("stop", self.probe.stop_cmd)

  def teardown(self) -> ProbeResult:
    self._maybe_run_cmd("teardown", self.probe.teardown_cmd)
    return LocalProbeResult(file=tuple(self._result_files))


class ShellProbeContext(ShellProbeContextBase[ShellProbe]):
  """
  ProbeContext for running shell commands on the browser platform.
  """

  @property
  @override
  def target_platform(self) -> plt.Platform:
    return self.browser_platform


class LocalShellProbe(ShellProbeBase):
  """
  Run an arbitrary shell command on the host platform and store the
  stdout and stderr of the command as a result file.
  """
  NAME: ClassVar[str] = "local_shell"

  @override
  def target_platform(self, browser: Browser) -> plt.Platform:
    return browser.host_platform

  @override
  def get_context_cls(self) -> type[LocalShellProbeContext]:
    return LocalShellProbeContext


class LocalShellProbeContext(ShellProbeContextBase[LocalShellProbe]):
  """
  ProbeContext for running shell commands on the host platform.
  """

  @property
  @override
  def target_platform(self) -> plt.Platform:
    return self.host_platform
