#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import platform
import re
import shutil
import sys
from typing import Any, Final

USE_PYTHON3 = True

SOURCE_SKIP_RE: Final[tuple[str, ...]] = (r"^third_party/.*",)


def CheckChange(input_api: Any, output_api: Any, on_commit: bool) -> Any:
  local_path = input_api.PresubmitLocalPath()
  if local_path not in sys.path:
    sys.path.insert(0, local_path)

  tests = []
  results = []
  testing_env = dict(input_api.environ)
  root_path = pathlib.Path(local_path)
  crossbench_test_path = root_path / "tests" / "crossbench"
  testing_env["PYTHONPATH"] = input_api.os_path.pathsep.join(
      map(str, [root_path, crossbench_test_path]))

  modified_py_files: list[str] = ModifiedFiles(input_api, on_commit)
  modified_hjson_files: list[str] = ModifiedFiles(
      input_api, False, filename_pattern="*.hjson")

  # ---------------------------------------------------------------------------
  # VPython Spec:
  # ---------------------------------------------------------------------------
  if platform.system() in ("Linux", "Darwin"):
    tests += input_api.canned_checks.CheckVPythonSpec(input_api, output_api)

  # ---------------------------------------------------------------------------
  # PanProject Checks:
  # ---------------------------------------------------------------------------
  results += input_api.canned_checks.PanProjectChecks(
      input_api,
      output_api,
      excluded_paths=SOURCE_SKIP_RE,
      owners_check=False,
  )

  # ---------------------------------------------------------------------------
  # Poetry Lock Validation:
  # ---------------------------------------------------------------------------
  if shutil.which("poetry", path=input_api.environ.get("PATH")):
    tests.append(
        input_api.Command(
            name="poetry check --lock",
            cmd=[
                "poetry",
                "check",
                "--no-interaction",
                "--lock",
                "-C",
                str(root_path),
            ],
            message=output_api.PresubmitError,
            kwargs={},
            python3=True,
        ))
  else:
    results.append(
        output_api.PresubmitPromptWarning(
            "poetry not found in PATH, skipping lock file validation."))

  # ---------------------------------------------------------------------------
  # Ruff:
  # ---------------------------------------------------------------------------
  # Ruff is fast, let's run it on all sources, excludes are configured
  # separately in pyproject.toml. We explicitly exclude untracked files.
  ruff_cmd = [
      input_api.python3_executable,
      "-m",
      "ruff",
      "check",
      str(root_path),
  ]
  for untracked_file in GetUntrackedFiles(input_api):
    if untracked_file.endswith(".py"):
      ruff_cmd.extend(["--extend-exclude", untracked_file])

  tests.append(
      input_api.Command(
          name="ruff",
          cmd=ruff_cmd,
          message=output_api.PresubmitError,
          kwargs={},
          python3=True,
      ))

  # ---------------------------------------------------------------------------
  # MyPy:
  # ---------------------------------------------------------------------------
  mypy_files_to_check: list[str] = TyperPaths(input_api, on_commit,
                                              modified_py_files)
  if mypy_files_to_check:
    tests.append(
        input_api.Command(
            name="mypy",
            cmd=[
                input_api.python3_executable,
                "-m",
                "mypy",
                "--check-untyped-defs",
                "--pretty",
            ] + mypy_files_to_check,
            message=output_api.PresubmitError,
            kwargs={},
            python3=True,
        ))

  # ---------------------------------------------------------------------------
  # isort:
  # ---------------------------------------------------------------------------
  from tools.presubmit.import_sorter import SortImports
  results += SortImports(input_api, output_api, modified_py_files)

  # ---------------------------------------------------------------------------
  # js:
  # ---------------------------------------------------------------------------
  results += input_api.canned_checks.CheckPatchFormatted(
      input_api, output_api, check_js=True)

  # ---------------------------------------------------------------------------
  # hjson:
  # ---------------------------------------------------------------------------
  from tools.presubmit.hjson_formatter import FormatHjsonFiles
  results += FormatHjsonFiles(input_api, output_api, modified_hjson_files)

  # ---------------------------------------------------------------------------
  # AST Checks (Banned builtins, Constants marked Final):
  # ---------------------------------------------------------------------------
  from tools.presubmit.ast_checks import CheckAst
  results += CheckAst(input_api, output_api)

  # ---------------------------------------------------------------------------
  # Skills:
  # ---------------------------------------------------------------------------
  results += input_api.canned_checks.CheckSkillFiles(input_api, output_api)

  # ---------------------------------------------------------------------------
  # Unittest:
  # ---------------------------------------------------------------------------
  test_dir, file_pattern = TestFilePatternsToCheck(on_commit,
                                                   crossbench_test_path)
  unit_tests = [str(path) for path in test_dir.glob(f"**/{file_pattern}")]
  tests += input_api.canned_checks.GetUnitTests(
      input_api, output_api, unit_tests, env=testing_env)

  # ---------------------------------------------------------------------------
  # Run all tests:
  # ---------------------------------------------------------------------------
  results += input_api.RunTests(tests)
  return results


# ---------------------------------------------------------------------------


def ModifiedFiles(
    input_api: Any,
    on_commit: bool,
    filename_pattern: str = "*.py",
) -> list[str]:
  if on_commit:
    return []
  from tools.presubmit.common import GlobalSkipChecks
  files = [file.AbsoluteLocalPath() for file in input_api.AffectedFiles()]
  files_to_check = []
  for file_path in files:
    if not input_api.fnmatch.fnmatch(file_path, filename_pattern):
      continue
    if GlobalSkipChecks(input_api, file_path):
      continue
    if not input_api.os_path.exists(file_path):
      continue
    file_path = input_api.os_path.relpath(file_path,
                                          input_api.PresubmitLocalPath())
    files_to_check.append(file_path)
  return files_to_check


def GetUntrackedFiles(input_api: Any) -> list[str]:
  try:
    return input_api.subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"],
        encoding="utf-8").splitlines()
  except input_api.subprocess.CalledProcessError:
    return []


def LinterFilePatterns(
    on_commit: bool,
    modified_py_files: list[str],
) -> list[str]:
  if on_commit:
    # Test all files on commit
    return [r"^[^\.]+\.py$"]
  # By default, the pylint canned check lints all Python files together to
  # check for potential problems between dependencies. This is slow to run
  # across all of crossbench (>2 min), so only lint affected files.
  return [re.escape(file) for file in modified_py_files]


def TyperPaths(
    input_api: Any,
    on_commit: bool,
    modified_py_files: list[str],
) -> list[str]:
  from tools.presubmit.common import GlobalSkipChecks
  root_path = pathlib.Path(input_api.PresubmitLocalPath())
  mypy_files_to_check = {"PRESUBMIT.py"}
  crossbench_path = root_path / "crossbench"
  if on_commit:
    mypy_files_to_check.add(str(crossbench_path))
    mypy_files_to_check.add(str(root_path / "tools"))
  else:
    mypy_files_to_check.update(modified_py_files)
  # TODO: enable mypy on all tests
  result = []
  for file in mypy_files_to_check:
    if file.startswith("tests/"):
      continue
    if GlobalSkipChecks(input_api, file):
      continue
    result.append(file)
  return result


def TestFilePatternsToCheck(
    on_commit: bool,
    crossbench_test_path: pathlib.Path,
) -> tuple[pathlib.Path, str]:
  # Only run test_cli to speed up the presubmit checks
  if on_commit:
    test_dir: pathlib.Path = crossbench_test_path
    file_pattern = "*test_*.py"
  else:
    # Only check a small subset on upload
    test_dir = crossbench_test_path / "cli"
    file_pattern = "*test_cli_fast_*.py"
  return test_dir, file_pattern


def CheckChangeOnUpload(input_api: Any, output_api: Any) -> Any:
  return CheckChange(input_api, output_api, on_commit=False)


def CheckChangeOnCommit(input_api: Any, output_api: Any) -> Any:
  return CheckChange(input_api, output_api, on_commit=True)
