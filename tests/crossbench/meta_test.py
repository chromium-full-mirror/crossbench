# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import logging
import pathlib
import re
import tomllib
import unittest
from itertools import chain
from typing import TYPE_CHECKING, Final

import pytest
from tabulate import tabulate

import crossbench
from crossbench.cli.subcommand.describe import get_all_config_classes
from tests import test_helper

if TYPE_CHECKING:
  from crossbench.config import ConfigObject

MAIN_SNIPPET: Final[str] = 'if __name__ == "__main__":'
RUN_SNIPPET: Final[str] = f"{MAIN_SNIPPET}\n  test_helper.run_pytest(__file__)"
FUTURE_ANNOTATIONS_SNIPPET = "from __future__ import annotations"

COMMENTS_ONLY_RE = re.compile(r"^(?:#.*|\s*)*$", re.MULTILINE)

UNITTEST_DIR = pathlib.Path(__file__).parent
ROOT_DIR = UNITTEST_DIR.parents[1]
CROSSBENCH_DIR = ROOT_DIR / "crossbench"


class MetaTestCase(unittest.TestCase):

  def test_toplevel_py_main_snippet(self) -> None:
    for py_file in ROOT_DIR.glob("*.py"):
      if py_file.name == "PRESUBMIT.py":
        continue
      with self.subTest(py_file=str(py_file)):
        self.assertIn(MAIN_SNIPPET, py_file.read_text(),
                      f"{py_file} misses main snippet: {MAIN_SNIPPET}")

  def test_unittest_runner_snippet(self) -> None:
    # - All unittests files must end with the snippet for the CQ to pick it up.
    # - pytest files (in end2end) use a different approach that doesn't rely
    #   on a per-file runner
    for test_file in UNITTEST_DIR.glob("**/test_*.py"):
      with self.subTest(test_file=str(test_file)):
        self.assertTrue(
            test_file.read_text().rstrip().endswith(RUN_SNIPPET),
            f"{test_file} misses runner snippet: "
            "test_helper.run_pytest(__file__)")

  def test_future_annotation(self):
    for py_file in CROSSBENCH_DIR.glob("**/*.py"):
      with self.subTest(py_file=str(py_file)):
        text = py_file.read_text()
        if FUTURE_ANNOTATIONS_SNIPPET in text:
          continue
        if py_file.name == "__init__.py" and COMMENTS_ONLY_RE.fullmatch(text):
          continue
        self.fail(f"{py_file} is missing future annotation")

  def protobug_text_file_names(self):
    trace_config_dir = test_helper.config_dir()
    for config_file in trace_config_dir.glob("*.pbtxt"):
      self.fail(f"Invalid file extension, use .textpb: {config_file}")

  @pytest.mark.xfail
  def test_vpython_poetry_version_match(self):
    vpython_content = (ROOT_DIR / "vpython.toml.uv.lock").read_text()
    poetry_lock_content = (ROOT_DIR / "poetry.lock").read_text()

    vpython_re = re.compile(
        r"^(?P<name>[a-zA-Z0-9_.\-]+)==(?P<version>[^\s;]+)", re.MULTILINE)
    poetry_re = re.compile(
        r'name = "(?P<name>[^"]+)".*?'
        r'version = "(?P<version>[^"]+)"', re.DOTALL)

    vpython_packages = {}
    for match in vpython_re.finditer(vpython_content):
      name = match.group("name")
      version = (
          match.group("version").split("+chromium")[0].split(".chromium")[0])
      vpython_packages[name] = version

    poetry_packages = {}
    for package_block in poetry_lock_content.split("[[package]]"):
      if not package_block.strip():
        continue
      match = poetry_re.search(package_block)
      if match:
        name = match.group("name")
        version = match.group("version")
        poetry_packages[name] = version

    self.assertGreater(
        len(vpython_packages), 0, "No packages found in vpython.toml.uv.lock")
    self.assertGreater(
        len(poetry_packages), 0, "No packages found in poetry.lock")

    vpython_only = sorted(vpython_packages.keys() - poetry_packages.keys())
    if vpython_only:
      logging.warning("Packages only in vpython.toml.uv.lock: %s",
                      ", ".join(vpython_only))
    poetry_only = sorted(poetry_packages.keys() - vpython_packages.keys())
    if poetry_only:
      logging.warning("Packages only in poetry.lock: %s",
                      ", ".join(poetry_only))

    mismatches = []
    for name, vpython_version_str in vpython_packages.items():
      if name not in poetry_packages:
        continue
      poetry_version_str = poetry_packages[name]
      if vpython_version_str == poetry_version_str:
        continue
      mismatches.append((name, vpython_version_str, poetry_version_str))
    mismatches.sort(key=lambda row: row[0])
    if mismatches:
      headers = ["Package", "vpython.toml.uv.lock", "poetry.lock"]
      self.fail("Version mismatches found:\n" +
                tabulate(mismatches, headers=headers))

  def test_dependencies_are_sorted(self):
    pyproject_toml_path = ROOT_DIR / "pyproject.toml"
    pyproject_toml = tomllib.loads(pyproject_toml_path.read_text())
    poetry_options = pyproject_toml["tool"]["poetry"]
    dependencies = poetry_options["dependencies"]
    sorted_dependencies = sorted(dependencies.keys())
    self.assertEqual(
        list(dependencies.keys()),
        sorted_dependencies,
        "Dependencies in pyproject.toml are not sorted alphabetically.",
    )
    dev_dependencies = poetry_options["group"]["dev"]["dependencies"]
    sorted_dev_dependencies = sorted(dev_dependencies.keys())
    self.assertEqual(
        list(dev_dependencies.keys()),
        sorted_dev_dependencies,
        "Dev dependencies in pyproject.toml are not sorted alphabetically.",
    )

  def test_version_match(self):
    pyproject_toml_path = ROOT_DIR / "pyproject.toml"
    pyproject_toml = tomllib.loads(pyproject_toml_path.read_text())
    pyproject_version = pyproject_toml["project"]["version"]
    self.assertEqual(
        pyproject_version, crossbench.__version__,
        f"Version mismatch between {pyproject_toml_path} "
        "and crossbench.__version__")

  def test_no_raw_sh(self):
    # Matches .sh("cat", .shell("cat", .sh_stdout("cat", .shell_stdout("cat"
    # and also with adb: .adb.shell("cat", or .adb.shell_stdout("cat"
    # but avoids "logcat".
    # We check for common commands that have platform helpers.
    illegal_commands = ("cat", "rm", "mkdir", "mv", "cp", "touch", "chmod",
                        "which", "ps", "kill", "pkill", "killall", "uptime",
                        "uname")
    commands_re = "|".join(illegal_commands)
    # Match .sh(..., "command") or .sh(..., 'command')
    # Also handles escape sequences like \t or \n before the command.
    re_sh_raw = re.compile(
        rf"\.(sh|shell)(_stdout)?\(\s*(?:#[^\n]*\n\s*)?['\"]"
        rf"(?:(?:\\t|\\n|\\r)*)?\b({commands_re})\b", re.MULTILINE)
    for py_file in CROSSBENCH_DIR.glob("**/*.py"):
      if py_file.parent.name == "plt":
        continue
      content = py_file.read_text()
      for match in re_sh_raw.finditer(content):
        line_no = content.count("\n", 0, match.start()) + 1
        with self.subTest(py_file=str(py_file), line=line_no):
          command = match.group(3)
          self.fail(f"Use platform.{command}() helper instead of "
                    f"raw shell call at {py_file}:{line_no}")

  def test_no_module_shadowing(self):
    pyproject_toml_path = ROOT_DIR / "pyproject.toml"
    pyproject_toml = tomllib.loads(pyproject_toml_path.read_text())
    poetry_options = pyproject_toml["tool"]["poetry"]
    dependencies = set(poetry_options["dependencies"].keys())
    dependencies.update(poetry_options["group"]["dev"]["dependencies"].keys())

    # Some dependencies have different module names than their package names,
    # but for most it's the same.
    module_names = {
        "google",
    }
    pyproject_data = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())
    dependencies = pyproject_data["tool"]["poetry"]["dependencies"]
    module_names = set(dependencies.keys())

    found_shadows = []
    for init_file in chain(
        CROSSBENCH_DIR.glob("**/__init__.py"),
        UNITTEST_DIR.glob("**/__init__.py")):
      dir_name = init_file.parent.name
      if dir_name in module_names:
        found_shadows.append(str(init_file.parent.relative_to(ROOT_DIR)))

    if found_shadows:
      formatted_modules = "\n  - ".join(found_shadows)
      self.fail("Found crossbench modules with names that shadow toplevel "
                "dependencies from pyproject.toml.\n"
                "Either rename the crossbench module or remove its "
                "__init__.py file.\n"
                f"  - {formatted_modules}")


class ConfigObjectMetaTest(unittest.TestCase):

  exempt_classes: Final[frozenset[str]] = frozenset({
      "crossbench.benchmarks.loading.config.login.base.BaseLoginBlock",
      "crossbench.cli.config.flags.FlagsConfig",
  })

  def validate_is_dataclass(self, cls: type[ConfigObject],
                            class_name: str) -> list[str]:
    if not dataclasses.is_dataclass(cls):
      return [
          f"{class_name}: Missing @dataclasses.dataclass(frozen=True) "
          "decorator. All concrete ConfigObject implementations in "
          "Crossbench MUST be declared as frozen dataclasses.",
      ]
    return []

  def validate_dataclass_frozen(self, cls: type[ConfigObject],
                                class_name: str) -> list[str]:
    if not cls.__dataclass_params__.frozen:
      return [
          f"{class_name}: Declared with frozen=False. Concrete ConfigObject "
          "schemas MUST enforce strict, post-instantiation immutability ("
          "@dataclasses.dataclass(frozen=True)).",
      ]
    return []

  def validate_no_ghost_annotations(self, cls: type[ConfigObject],
                                    class_name: str) -> list[str]:
    violations: list[str] = []
    registered_fields = {field.name for field in dataclasses.fields(cls)}
    for attr_name, attr_type in cls.__annotations__.items():
      if "ClassVar" in str(attr_type):
        continue
      if attr_name not in registered_fields:
        violations.append(
            f"{class_name}: Detected Ghost-Dataclass attribute drop! The field "
            f"'{attr_name}' was annotated inside the class body, but dropped "
            "from the compiled Dataclass metadata and `.asdict()` "
            "serialization schema. Verify the subclass is directly decorated "
            "with @dataclasses.dataclass(frozen=True).")
    return violations

  def validate_config_object_cls(self, cls: type[ConfigObject]) -> list[str]:
    class_name = f"{cls.__module__}.{cls.__name__}"

    dataclass_errors = self.validate_is_dataclass(cls, class_name)
    if dataclass_errors:
      return dataclass_errors

    violations: list[str] = []
    violations.extend(self.validate_dataclass_frozen(cls, class_name))
    violations.extend(self.validate_no_ghost_annotations(cls, class_name))
    return violations

  def test_all_config_objects_are_frozen_dataclasses(self):
    violations: list[str] = []
    for cls in get_all_config_classes():
      if not cls.__module__.startswith("crossbench."):
        continue
      class_name = f"{cls.__module__}.{cls.__name__}"
      if class_name in self.exempt_classes:
        continue

      violations.extend(self.validate_config_object_cls(cls))

    if violations:
      error_report = "\n  - ".join(violations)
      self.fail(
          "Discovered concrete `ConfigObject` schemas violating Crossbench's "
          "Immutable PEP-557 Dataclass design invariants:\n\n"
          f"  - {error_report}")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
