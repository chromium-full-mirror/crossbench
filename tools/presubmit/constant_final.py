# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final, NamedTuple

from tools.presubmit.common import PresubmitCheck

if TYPE_CHECKING:
  import pathlib

  from presubmit_support import InputApi, OutputApi

_UPPER_SNAKE_CASE_RE: Final[re.Pattern[str]] = re.compile(
    r"^_?[A-Z][A-Z0-9_]*$")
_EXCLUDED_CONSTANTS: Final[frozenset[str]] = frozenset({
    "__all__",
    "__author__",
    "__doc__",
    "__version__",
})
_TYPE_CONSTRUCT_NAMES: Final[frozenset[str]] = frozenset({
    "NewType",
    "ParamSpec",
    "TypeAliasType",
    "TypeVar",
    "TypeVarTuple",
})
BYPASS_KEY: Final[str] = "ALLOW_MUTABLE_CONSTANT"


class ConstantFinalViolation(NamedTuple):
  file_path: str
  line_number: int
  col_offset: int
  target_name: str
  line_text: str


def _IsFinalAnnotation(annotation: ast.AST | None) -> bool:
  if annotation is None:
    return False
  if isinstance(annotation, ast.Name):
    return annotation.id == "Final"
  if isinstance(annotation, ast.Attribute):
    return annotation.attr == "Final"
  if isinstance(annotation, ast.Subscript):
    return _IsFinalAnnotation(annotation.value)
  return False


def _IsTypeConstruct(value: ast.AST | None) -> bool:
  if value is None:
    return False
  if isinstance(value, ast.Call):
    func = value.func
    if isinstance(func, ast.Name):
      return func.id in _TYPE_CONSTRUCT_NAMES
    if isinstance(func, ast.Attribute):
      return func.attr in _TYPE_CONSTRUCT_NAMES
  return False


class ConstantFinalVisitor(ast.NodeVisitor):

  def __init__(self) -> None:
    super().__init__()
    self.violations: list[tuple[int, int, str]] = []

  def visit_Module(self, node: ast.Module) -> None:
    for stmt in node.body:
      if isinstance(stmt, ast.Assign):
        if _IsTypeConstruct(stmt.value):
          continue
        for target in stmt.targets:
          if isinstance(target, ast.Name):
            name = target.id
            if name in _EXCLUDED_CONSTANTS:
              continue
            if _UPPER_SNAKE_CASE_RE.match(name):
              self.violations.append((stmt.lineno, stmt.col_offset + 1, name))
      elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        if isinstance(target, ast.Name):
          name = target.id
          if name in _EXCLUDED_CONSTANTS:
            continue
          if _UPPER_SNAKE_CASE_RE.match(name):
            if not _IsFinalAnnotation(stmt.annotation):
              self.violations.append((stmt.lineno, stmt.col_offset + 1, name))
    self.generic_visit(node)


def CheckConstantsMarkedFinal(
    input_api: InputApi,
    output_api: OutputApi,
) -> list[object]:
  presubmit = PresubmitCheck(input_api, output_api)
  results: list[object] = []
  violations: list[ConstantFinalViolation] = []
  root_path: pathlib.Path = presubmit.root_path

  for affected_file in presubmit.affected_python_files():
    file_path: str = affected_file.LocalPath()
    full_path: pathlib.Path = root_path / file_path
    try:
      content = input_api.ReadFile(str(full_path), "r")
    except (OSError, UnicodeDecodeError) as e:
      results.append(
          output_api.PresubmitError(f"Could not read {file_path}: {e}"))
      continue
    try:
      tree = ast.parse(content, filename=str(full_path))
    except SyntaxError as e:
      results.append(
          output_api.PresubmitError(f"Syntax error in {file_path}: {e}"))
      continue

    visitor = ConstantFinalVisitor()
    visitor.visit(tree)
    if not visitor.violations:
      continue

    changed_line_numbers = presubmit.changed_lines(affected_file)
    lines = content.splitlines()
    for lineno, col, target_name in visitor.violations:
      if lineno in changed_line_numbers:
        line_text = lines[lineno -
                          1].strip() if 0 <= lineno - 1 < len(lines) else ""
        violations.append(
            ConstantFinalViolation(
                file_path=file_path,
                line_number=lineno,
                col_offset=col,
                target_name=target_name,
                line_text=line_text,
            ))

  if not violations:
    return results

  bypass_reason = presubmit.bypass_reason(BYPASS_KEY)
  if bypass_reason:
    results.append(
        output_api.PresubmitNotifyResult(
            f"Bypassing module constants Final check "
            f"via commit message tag: {BYPASS_KEY}={bypass_reason}"))
    return results

  error_items = [
      f"{v.file_path}:{v.line_number}:{v.col_offset}: {v.line_text}"
      for v in violations
  ]
  long_text = (
      "Module-level UPPER_SNAKE constants must be annotated with `Final`\n"
      "(e.g., `NAME: Final = ...` or `NAME: Final[Type] = ...`).\n"
      "If a mutable module global or non-final constant is strictly\n"
      "necessary, provide a non-empty reason in your commit message\n"
      "footer/tags:\n"
      f"  {BYPASS_KEY}=<REASON>\n")
  results.append(
      output_api.PresubmitError(
          "Found module constants not annotated with Final in modified files:",
          items=error_items,
          long_text=long_text))
  return results
