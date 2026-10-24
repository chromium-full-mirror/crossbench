# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import os
import pathlib
import shutil
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Sequence

import pytest

from crossbench import config
from crossbench.cli import exception_formatter
from crossbench.flags.base import Flags

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.plt.types import CmdArg, ListCmdArgs, SequenceCmdArgs, \
      TupleCmdArgs

root_dir = config.root_dir
config_dir = config.config_dir


def crossbench_dir() -> pathlib.Path:
  return root_dir() / "crossbench"


def is_on_swarming():
  return "SWARMING_SERVER" in os.environ


@dataclass(frozen=True)
class TestEnv:
  # Avoid getting PytestCollectionWarning as the class name starts with Test.
  __test__ = False

  output_dir: pathlib.Path
  test_name: str
  is_cq: bool = field(init=False)
  cq_flags: TupleCmdArgs = field(init=False)
  archive_dir: pathlib.Path = field(init=False)
  results_dir: pathlib.Path = field(init=False)
  root_dir: pathlib.Path = field(init=False)

  def __post_init__(self):
    output_path = pathlib.Path(self.output_dir)
    self._set("is_cq", output_path.parts[-1].startswith("cq_archive_"))
    self._set("cq_flags", ("--no-symlinks",) if self.is_cq else ())
    run_seq = 0
    while True:
      self._set("output_dir", output_path / self.test_name / str(run_seq))
      if not self.output_dir.exists():
        break
      run_seq += 1
    self.output_dir.mkdir(parents=True)
    self._set("archive_dir", self.output_dir / "browser_archive")
    assert not self.archive_dir.exists()
    self._set("results_dir", self.output_dir / "results")
    assert not self.results_dir.exists()
    self._set("root_dir", root_dir())

  def _set(self, attr: str, value: Any):
    object.__setattr__(self, attr, value)

  def remove_non_result(self):
    for output_path in self.output_dir.iterdir():
      if output_path.is_dir() and output_path != self.results_dir:
        shutil.rmtree(output_path)

  def assert_empty_output_dir(self):
    assert not tuple(self.output_dir.glob("**/*"))


DEFAULT_PYTEST_FLAGS: Final[Flags] = Flags({
    "-vv": None,
    "--log-file-level": "DEBUG",
    "--durations": "5",
    "--no-fold-skipped": None,
    "-r": "s",
}).freeze()


class DurationPlugin:

  @pytest.hookimpl(hookwrapper=True)
  def pytest_runtest_makereport(self, item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
      sys.stdout.write(f" [DURATION] {item.nodeid}: {report.duration:.2f}s\n")
      sys.stdout.flush()


def build_retry_args(extra_args: SequenceCmdArgs) -> ListCmdArgs:
  retry_args: ListCmdArgs = list(extra_args)
  if "--last-failed" not in retry_args:
    retry_args.extend(["--last-failed", "--last-failed-no-failures=none"])
  has_cov = any(
      arg == "--cov" or str(arg).startswith("--cov=") for arg in retry_args)
  if has_cov and "--cov-append" not in retry_args:
    retry_args.append("--cov-append")
  return retry_args


def _make_plugins(plugins: Sequence[object] | None) -> Sequence[object]:
  if plugins is not None:
    return list(plugins)
  return [DurationPlugin()]


def run_pytest(
    path: pth.LocalPathLike,
    *args: CmdArg,
    plugins: Sequence[object] | None = None,
    use_default_flags: bool = True,
    check: bool = True,
    retries: int = 0,
) -> int | pytest.ExitCode:
  assert retries >= 0, f"Expected non-negative retries, got {retries}"
  sys.excepthook = exception_formatter.excepthook
  extra_args: ListCmdArgs = list(args)
  if use_default_flags:
    extra_args = [*DEFAULT_PYTEST_FLAGS, *extra_args]
  pass_through_args: list[str] = sys.argv[1:]
  extra_args.extend(pass_through_args)
  # Run tests single-threaded by default when running the test file directly.
  if not any(arg == "-n" or arg.startswith(("-n=", "--numprocesses="))
             for arg in extra_args):
    extra_args.append("-n=0")
  if not any(arg == "-r" or arg.startswith("-r") for arg in extra_args):
    extra_args.append("-rs")

  pytest_args: list[str] = [str(path), *map(str, extra_args)]
  return_code: int | pytest.ExitCode = pytest.main(
      pytest_args, plugins=_make_plugins(plugins))
  retry_args: ListCmdArgs = build_retry_args(extra_args)
  for attempt in range(retries):
    if return_code != pytest.ExitCode.TESTS_FAILED:
      break
    sys.stdout.write(f"\n[run_pytest] Retrying failed tests "
                     f"(attempt {attempt + 1}/{retries})...\n")
    sys.stdout.flush()
    retry_pytest_args: list[str] = [str(path), *map(str, retry_args)]
    return_code = pytest.main(retry_pytest_args, plugins=_make_plugins(plugins))

  if return_code == pytest.ExitCode.NO_TESTS_COLLECTED:
    return_code = pytest.ExitCode.OK
  if check:
    sys.exit(return_code)
  return return_code
