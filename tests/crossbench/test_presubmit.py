# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import ast
import enum
import unittest
from typing import Any, Callable, ClassVar, Iterable, TypeAlias
from unittest import mock

from typing_extensions import override

from tests import test_helper
from tools.presubmit import (ast_checks, banned_builtins, constant_final,
                             toplevel_files)
from tools.presubmit.toplevel_files import FileAction

ChangedLines: TypeAlias = set[int] | None
ChangedLinesMap: TypeAlias = dict[str, set[int]] | None


class PresubmitStatus(enum.StrEnum):
  ERROR = "ERROR"
  NOTIFY = "NOTIFY"


class BannedBuiltinVisitorTestCase(unittest.TestCase):

  def _check(self, code: str) -> list[tuple[int, int, str]]:
    tree = ast.parse(code)
    visitor = banned_builtins.BannedBuiltinVisitor()
    visitor.visit(tree)
    return visitor.violations

  def test_getattr_detection(self) -> None:
    self.assertEqual(
        self._check("getattr(obj, 'prop')"),
        [(1, 1, "getattr")],
    )
    self.assertEqual(
        self._check("getattr(obj, 'prop', default)"),
        [(1, 1, "getattr")],
    )
    self.assertEqual(
        self._check("builtins.getattr(obj, 'prop')"),
        [(1, 1, "getattr")],
    )

  def test_setattr_detection(self) -> None:
    self.assertEqual(
        self._check("setattr(obj, 'prop', 123)"),
        [(1, 1, "setattr")],
    )
    self.assertEqual(
        self._check("builtins.setattr(obj, 'prop', 123)"),
        [(1, 1, "setattr")],
    )

  def test_hasattr_detection(self) -> None:
    self.assertEqual(
        self._check("hasattr(obj, 'prop')"),
        [(1, 1, "hasattr")],
    )
    self.assertEqual(
        self._check("builtins.hasattr(obj, 'prop')"),
        [(1, 1, "hasattr")],
    )

  def test_allowed_calls(self) -> None:
    self.assertEqual(self._check("obj.prop"), [])
    self.assertEqual(self._check("obj.getattr('prop')"), [])
    self.assertEqual(self._check("obj.setattr('prop', 1)"), [])
    self.assertEqual(self._check("obj.hasattr('prop')"), [])


class ConstantFinalVisitorTestCase(unittest.TestCase):

  def _check(self, code: str) -> list[tuple[int, int, str]]:
    tree = ast.parse(code)
    visitor = constant_final.ConstantFinalVisitor()
    visitor.visit(tree)
    return visitor.violations

  def test_unannotated_constant_detection(self) -> None:
    self.assertEqual(self._check("FOO = 1"), [(1, 1, "FOO")])
    self.assertEqual(
        self._check("_PRIVATE_FOO = 'bar'"), [(1, 1, "_PRIVATE_FOO")])
    self.assertEqual(
        self._check("FOO = BAR = 1"), [(1, 1, "FOO"), (1, 1, "BAR")])

  def test_annotated_non_final_constant_detection(self) -> None:
    self.assertEqual(self._check("FOO: int = 1"), [(1, 1, "FOO")])
    self.assertEqual(self._check("_BAR: str = 'val'"), [(1, 1, "_BAR")])
    self.assertEqual(
        self._check("PATTERN: re.Pattern = re.compile('a')"),
        [(1, 1, "PATTERN")],
    )

  def test_final_constant_allowed(self) -> None:
    self.assertEqual(self._check("FOO: Final = 1"), [])
    self.assertEqual(self._check("FOO: Final[int] = 1"), [])
    self.assertEqual(self._check("_BAR: typing.Final = 2"), [])
    self.assertEqual(self._check("_BAR: typing.Final[str] = 'val'"), [])

  def test_lowercase_and_camelcase_ignored(self) -> None:
    self.assertEqual(self._check("foo = 1"), [])
    self.assertEqual(self._check("my_variable: int = 2"), [])
    self.assertEqual(self._check("ClassName = int"), [])

  def test_dunders_ignored(self) -> None:
    self.assertEqual(self._check("__all__ = ['a', 'b']"), [])
    self.assertEqual(self._check("__version__ = '1.0'"), [])
    self.assertEqual(self._check("__author__ = 'me'"), [])
    self.assertEqual(self._check("__doc__ = 'doc'"), [])

  def test_type_constructs_ignored(self) -> None:
    self.assertEqual(self._check("_T = TypeVar('_T')"), [])
    self.assertEqual(self._check("P = ParamSpec('P')"), [])
    self.assertEqual(self._check("UserId = NewType('UserId', int)"), [])
    self.assertEqual(self._check("_T = typing.TypeVar('_T')"), [])

  def test_constants_in_function_or_class_ignored(self) -> None:
    code = """
def my_func():
  LOCAL_CONST = 1
  ANOTHER: int = 2

class MyClass:
  CLASS_CONST = 1
  MEMBER: int = 2
"""
    self.assertEqual(self._check(code), [])


class MockAffectedFile:

  def __init__(
      self,
      path: str,
      changed_lines: ChangedLines = None,
      action: FileAction = FileAction.ADD,
  ) -> None:
    self._path: str = path
    self._changed_lines: ChangedLines = changed_lines
    self._action: FileAction = action

  def LocalPath(self) -> str:  # noqa: N802
    return self._path

  def Action(self) -> FileAction:  # noqa: N802
    return self._action

  def ChangedContents(self) -> list[tuple[int, str]]:  # noqa: N802
    if self._changed_lines is None:
      return [(i, "") for i in range(1, 1000)]
    return [(lineno, "") for lineno in self._changed_lines]


class _PresubmitTestCase(unittest.TestCase, metaclass=abc.ABCMeta):

  def _mock_input_api(
      self,
      files: dict[str, str],
      changed_lines_map: ChangedLinesMap = None,
      default_action: FileAction = FileAction.ADD,
      description: str = "",
  ) -> mock.MagicMock:
    input_api = mock.MagicMock()
    input_api.PresubmitLocalPath.return_value = "/root"
    input_api.fnmatch.fnmatch.return_value = False
    input_api.os_path.exists.side_effect = lambda path: str(path).replace(
        "/root/", "") in files
    input_api.ReadFile.side_effect = lambda path, mode="r": files[str(
        path).replace("/root/", "")]
    input_api.change.DescriptionText.return_value = description
    input_api.change.FullDescriptionText.return_value = description

    affected_files: list[MockAffectedFile] = []
    for file_path in files:
      changed_lines: ChangedLines = None
      if changed_lines_map:
        changed_lines = changed_lines_map.get(file_path)
      affected_files.append(
          MockAffectedFile(file_path, changed_lines, action=default_action))

    def get_affected_files(
        file_filter: Callable[[MockAffectedFile], bool] = lambda _: True,
        include_deletes: bool = True,
    ) -> list[MockAffectedFile]:
      del include_deletes
      return [f for f in affected_files if file_filter(f)]

    input_api.AffectedFiles.side_effect = get_affected_files
    return input_api

  def _mock_output_api(self) -> mock.MagicMock:
    output_api = mock.MagicMock()

    def presubmit_error(
        msg: str,
        items: tuple[str, ...] = (),
        long_text: str = "",
    ) -> tuple[PresubmitStatus, str, tuple[str, ...], str]:
      return (PresubmitStatus.ERROR, msg, items, long_text)

    def presubmit_notify(msg: str) -> tuple[PresubmitStatus, str]:
      return (PresubmitStatus.NOTIFY, msg)

    output_api.PresubmitError.side_effect = presubmit_error
    output_api.PresubmitNotifyResult.side_effect = presubmit_notify
    return output_api

  @abc.abstractmethod
  def _run_check(self, input_api: Any, output_api: Any) -> list[Any]:
    raise NotImplementedError

  def _check(
      self,
      files: dict[str, str],
      changed_lines_map: ChangedLinesMap = None,
      default_action: FileAction = FileAction.ADD,
      description: str = "",
  ) -> list[Any]:
    input_api = self._mock_input_api(
        files=files,
        changed_lines_map=changed_lines_map,
        default_action=default_action,
        description=description,
    )
    return self._run_check(input_api, self._mock_output_api())

  def _assert_no_errors(
      self,
      files: dict[str, str],
      changed_lines_map: ChangedLinesMap = None,
      default_action: FileAction = FileAction.ADD,
      description: str = "",
  ) -> None:
    results = self._check(
        files=files,
        changed_lines_map=changed_lines_map,
        default_action=default_action,
        description=description,
    )
    self.assertEqual(results, [])

  def _assert_error(
      self,
      files: dict[str, str],
      description: str = "",
      expected_msg: str = "",
      expected_items: list[str] | None = None,
      expected_long_text: str = "",
  ) -> None:
    results = self._check(files=files, description=description)
    self.assertEqual(len(results), 1)
    status, msg, items, long_text = results[0]
    self.assertEqual(status, PresubmitStatus.ERROR)
    if expected_msg:
      self.assertIn(expected_msg, msg)
    if expected_items is not None:
      self.assertEqual(items, expected_items)
    if expected_long_text:
      self.assertIn(expected_long_text, long_text)

  def _assert_notify(
      self,
      files: dict[str, str],
      expected_substrings: Iterable[str],
      description: str = "",
  ) -> None:
    results = self._check(files=files, description=description)
    self.assertEqual(len(results), 1)
    status, msg = results[0]
    self.assertEqual(status, PresubmitStatus.NOTIFY)
    for substring in expected_substrings:
      self.assertIn(substring, msg)


class CheckNoBannedBuiltinsTestCase(_PresubmitTestCase):
  GETATTR_SNIPPET: ClassVar[str] = "x = getattr(obj, 'field', None)\n"
  HASATTR_SNIPPET: ClassVar[str] = "if hasattr(obj, 'field'): pass\n"

  @override
  def _run_check(self, input_api: Any, output_api: Any) -> list[Any]:
    return banned_builtins.CheckNoBannedBuiltins(input_api, output_api)

  def test_no_violations(self) -> None:
    self._assert_no_errors(files={"foo.py": "x = obj.field\n"})

  def test_getattr_error_on_new_code(self) -> None:
    self._assert_error(
        files={"foo.py": self.GETATTR_SNIPPET},
        description="Fix something",
        expected_msg="Found banned built-in function calls",
        expected_items=["foo.py:1:5: x = getattr(obj, 'field', None)"],
        expected_long_text="ALLOW_GETATTR=<REASON>",
    )

  def test_getattr_ignored_on_unchanged_line(self) -> None:
    content = ("# Line 1\n"
               f"{self.GETATTR_SNIPPET}"
               "# Line 3\n"
               "y = obj.other_field\n")
    self._assert_no_errors(
        files={"foo.py": content},
        changed_lines_map={"foo.py": {4}},
        description="Fix something",
    )

  def test_getattr_passed_with_bypass(self) -> None:
    self._assert_notify(
        files={"foo.py": self.GETATTR_SNIPPET},
        expected_substrings=(
            "Bypassing banned built-in check",
            "ALLOW_GETATTR=Need dynamic field lookup",
        ),
        description="Fix something\n\nALLOW_GETATTR=Need dynamic field lookup",
    )

  def test_hasattr_error_on_new_code(self) -> None:
    self._assert_error(
        files={"foo.py": self.HASATTR_SNIPPET},
        description="Fix something",
        expected_msg="Found banned built-in function calls",
        expected_items=["foo.py:1:4: if hasattr(obj, 'field'): pass"],
        expected_long_text="ALLOW_HASATTR=<REASON>",
    )

  def test_hasattr_passed_with_bypass(self) -> None:
    self._assert_notify(
        files={"foo.py": self.HASATTR_SNIPPET},
        expected_substrings=(
            "Bypassing banned built-in check",
            "ALLOW_HASATTR=Need dynamic check",
        ),
        description="Fix something\n\nALLOW_HASATTR=Need dynamic check",
    )

  def test_both_bypass_required(self) -> None:
    self._assert_notify(
        files={
            "foo.py": (f"{self.GETATTR_SNIPPET}"
                       "setattr(obj, 'field', 123)\n"),
        },
        expected_substrings=(
            "Bypassing banned built-in check",
            "ALLOW_GETATTR=Need dynamic lookup",
            "ALLOW_SETATTR=Need dynamic setter",
        ),
        description=("Fix something\n\n"
                     "ALLOW_GETATTR=Need dynamic lookup\n"
                     "ALLOW_SETATTR=Need dynamic setter"),
    )

  def test_partial_bypass_fails(self) -> None:
    self._assert_error(
        files={
            "foo.py": (f"{self.GETATTR_SNIPPET}"
                       "setattr(obj, 'field', 123)\n"),
        },
        description="Fix something\n\nALLOW_GETATTR=Dynamic lookup",
        expected_items=[
            "foo.py:1:5: x = getattr(obj, 'field', None)",
            "foo.py:2:1: setattr(obj, 'field', 123)",
        ],
        expected_long_text="ALLOW_SETATTR=<REASON>",
    )

  def test_placeholder_bypass_rejected(self) -> None:
    self._assert_error(
        files={"foo.py": self.GETATTR_SNIPPET},
        description="Fix something\n\nALLOW_GETATTR=TODO",
    )


class CheckConstantsMarkedFinalTestCase(_PresubmitTestCase):
  CONSTANT_SNIPPET: ClassVar[str] = "FOO = 1\n"

  @override
  def _run_check(self, input_api: Any, output_api: Any) -> list[Any]:
    return constant_final.CheckConstantsMarkedFinal(input_api, output_api)

  def test_no_violations(self) -> None:
    self._assert_no_errors(files={"foo.py": "FOO: Final = 1\n"})

  def test_unannotated_constant_error_on_new_code(self) -> None:
    self._assert_error(
        files={"foo.py": self.CONSTANT_SNIPPET},
        description="Fix something",
        expected_msg="Found module constants not annotated with Final",
        expected_items=["foo.py:1:1: FOO = 1"],
        expected_long_text="ALLOW_MUTABLE_CONSTANT=<REASON>",
    )

  def test_non_final_annotated_constant_error(self) -> None:
    self._assert_error(
        files={"foo.py": "FOO: int = 1\n"},
        description="Fix something",
        expected_items=["foo.py:1:1: FOO: int = 1"],
    )

  def test_constant_ignored_on_unchanged_line(self) -> None:
    content = ("# Line 1\n"
               f"{self.CONSTANT_SNIPPET}"
               "# Line 3\n"
               "BAR: Final = 2\n")
    self._assert_no_errors(
        files={"foo.py": content},
        changed_lines_map={"foo.py": {4}},
        description="Fix something",
    )

  def test_constant_passed_with_bypass(self) -> None:
    self._assert_notify(
        files={"foo.py": self.CONSTANT_SNIPPET},
        expected_substrings=(
            "Bypassing module constants Final check",
            "ALLOW_MUTABLE_CONSTANT=Global mutable registry",
        ),
        description=(
            "Fix something\n\nALLOW_MUTABLE_CONSTANT=Global mutable registry"),
    )

  def test_placeholder_bypass_rejected(self) -> None:
    self._assert_error(
        files={"foo.py": self.CONSTANT_SNIPPET},
        description="Fix something\n\nALLOW_MUTABLE_CONSTANT=TODO",
    )


class CheckAstCombinedTestCase(_PresubmitTestCase):
  COMBINED_AST_SNIPPET: ClassVar[str] = ("FOO = 1\n"
                                         "x = getattr(obj, 'prop')\n")

  @override
  def _run_check(self, input_api: Any, output_api: Any) -> list[Any]:
    return ast_checks.CheckAst(input_api, output_api)

  def test_combined_catches_both(self) -> None:
    results = self._check(files={"foo.py": self.COMBINED_AST_SNIPPET})
    self.assertEqual(len(results), 2)
    messages = [res[1] for res in results]
    self.assertTrue(any("banned built-in" in m for m in messages))
    self.assertTrue(
        any("constants not annotated with Final" in m for m in messages))

  def test_combined_bypasses_individually(self) -> None:
    results = self._check(
        files={"foo.py": self.COMBINED_AST_SNIPPET},
        description=(
            "Fix\n\nALLOW_GETATTR=Needed\nALLOW_MUTABLE_CONSTANT=Needed"),
    )
    self.assertEqual(len(results), 2)
    self.assertEqual(results[0][0], PresubmitStatus.NOTIFY)
    self.assertEqual(results[1][0], PresubmitStatus.NOTIFY)


class CheckNoNewToplevelFilesTestCase(_PresubmitTestCase):

  @override
  def _run_check(self, input_api: Any, output_api: Any) -> list[Any]:
    return toplevel_files.check_no_new_toplevel_files(input_api, output_api)

  def test_new_files_in_subdirectories_allowed(self) -> None:
    self._assert_no_errors(
        files={
            "crossbench/helper/new_module.py": "",
            "crossbench/probes/new_probe.py": "",
            "tests/crossbench/helper/test_new_module.py": "",
            "tests/crossbench/probes/test_new_probe.py": "",
            "config/new_config.hjson": "",
            "tools/presubmit/toplevel_files.py": "",
        })

  def test_modified_toplevel_files_allowed(self) -> None:
    self._assert_no_errors(
        files={
            "PRESUBMIT.py": "",
            "README.md": "",
            "pyproject.toml": "",
            "crossbench/config.py": "",
            "crossbench/parse.py": "",
            "tests/test_helper.py": "",
            "tests/crossbench/test_presubmit.py": "",
        },
        default_action=FileAction.MODIFY,
    )

  def test_new_toplevel_file_error_without_bypass(self) -> None:
    for disallowed_path in (
        "new_script.py",
        "crossbench/new_module.py",
        "tests/test_new_module.py",
        "tests/crossbench/test_new_module.py",
    ):
      with self.subTest(path=disallowed_path):
        self._assert_error(
            files={
                disallowed_path: "",
                "crossbench/helper/ok.py": "",
                "tests/crossbench/helper/test_ok.py": "",
            },
            description="Add new module",
            expected_msg="Found newly added file(s) in a top-level directory",
            expected_items=[disallowed_path],
            expected_long_text="ALLOW_TOPLEVEL_FILE=<REASON>",
        )

  def test_multiple_new_toplevel_files_sorted_error(self) -> None:
    self._assert_error(
        files={
            "z_script.py": "",
            "tests/crossbench/test_new_module.py": "",
            "crossbench/new_helper.py": "",
            ".new_dotfile": "",
            "a_doc.md": "",
        },
        description="Add top-level files",
        expected_items=[
            ".new_dotfile",
            "a_doc.md",
            "crossbench/new_helper.py",
            "tests/crossbench/test_new_module.py",
            "z_script.py",
        ],
    )

  def test_new_toplevel_file_passed_with_bypass(self) -> None:
    self._assert_notify(
        files={
            "new_entry.py": "",
            "crossbench/new_core.py": "",
            "tests/crossbench/test_new_module.py": "",
        },
        expected_substrings=(
            "Bypassing top-level file check (crossbench/new_core.py, "
            "new_entry.py, tests/crossbench/test_new_module.py)",
            "ALLOW_TOPLEVEL_FILE=Required CLI entry",
        ),
        description="Add entry point\n\nALLOW_TOPLEVEL_FILE=Required CLI entry",
    )

  def test_placeholder_bypass_rejected(self) -> None:
    self._assert_error(
        files={"tests/crossbench/test_new_module.py": ""},
        description="Add core module\n\nALLOW_TOPLEVEL_FILE=TODO",
    )


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
