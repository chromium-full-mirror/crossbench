# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import ast
import pathlib
from typing import Any

from tools.presubmit.banned_builtins import BANNED_BUILTIN_FUNCTIONS, \
    BannedBuiltinViolation
from tools.presubmit.common import GetBypassReason, GlobalSkipChecks
from tools.presubmit.constant_final import _EXCLUDED_CONSTANTS, \
    _UPPER_SNAKE_CASE_RE
from tools.presubmit.constant_final import \
    BYPASS_KEY as CONSTANT_FINAL_BYPASS_KEY
from tools.presubmit.constant_final import ConstantFinalViolation, \
    _IsFinalAnnotation, _IsTypeConstruct


class CombinedAstVisitor(ast.NodeVisitor):
  """Single-pass visitor collecting all AST check violations."""

  def __init__(self) -> None:
    super().__init__()
    self.banned_builtin_violations: list[tuple[int, int, str]] = []
    self.constant_final_violations: list[tuple[int, int, str]] = []

  def visit_Module(self, node: ast.Module) -> None:
    # Check top-level statements for constants marked Final
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
              self.constant_final_violations.append(
                  (stmt.lineno, stmt.col_offset + 1, name))
      elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        if isinstance(target, ast.Name):
          name = target.id
          if name in _EXCLUDED_CONSTANTS:
            continue
          if _UPPER_SNAKE_CASE_RE.match(name):
            if not _IsFinalAnnotation(stmt.annotation):
              self.constant_final_violations.append(
                  (stmt.lineno, stmt.col_offset + 1, name))
    self.generic_visit(node)

  def visit_Call(self, node: ast.Call) -> None:
    func_name: str | None = None
    if isinstance(node.func, ast.Name):
      func_name = node.func.id
    elif (isinstance(node.func, ast.Attribute) and
          isinstance(node.func.value, ast.Name) and
          node.func.value.id == "builtins"):
      func_name = node.func.attr

    if func_name and func_name in BANNED_BUILTIN_FUNCTIONS:
      self.banned_builtin_violations.append(
          (node.lineno, node.col_offset + 1, func_name))
    self.generic_visit(node)


def _ReportBannedBuiltins(
    input_api: Any,
    output_api: Any,
    violations: list[BannedBuiltinViolation],
) -> list[Any]:
  if not violations:
    return []

  description: str = input_api.change.FullDescriptionText()
  detected_functions = {v.func_name for v in violations}
  missing_bypasses: list[str] = []
  valid_bypasses: list[tuple[str, str]] = []

  for func_name in sorted(detected_functions):
    bypass_key = f"ALLOW_{func_name.upper()}"
    reason = GetBypassReason(description, bypass_key)
    if reason:
      valid_bypasses.append((bypass_key, reason))
    else:
      missing_bypasses.append(bypass_key)

  if not missing_bypasses:
    bypass_details = ", ".join(f"{k}={r}" for k, r in valid_bypasses)
    return [
        output_api.PresubmitNotifyResult(
            f"Bypassing banned built-in check "
            f"({', '.join(sorted(detected_functions))}) "
            f"via commit message tag(s): {bypass_details}"),
    ]

  error_items = [
      f"{v.file_path}:{v.line_number}:{v.col_offset}: {v.line_text}"
      for v in violations
  ]
  help_tags = "\n".join(f"  {key}=<REASON>" for key in missing_bypasses)
  long_text = (
      "Calling `getattr()`, `setattr()`, or `hasattr()` is strictly\n"
      "discouraged in Crossbench:\n"
      "  - For CLI args/namespaces: configure proper defaults in argument\n"
      "    parsers (parser.set_defaults) or mock fixtures.\n"
      "  - For classes/objects: use explicit attributes, dataclasses,\n"
      "    properties, or protocols instead of dynamic reflection.\n\n"
      "If dynamic attribute access is strictly necessary, provide a non-empty\n"
      "reason in your commit message footer/tags to bypass this check:\n"
      f"{help_tags}\n")
  return [
      output_api.PresubmitError(
          "Found banned built-in function calls in modified files:",
          items=error_items,
          long_text=long_text),
  ]


def _ReportConstantFinal(
    input_api: Any,
    output_api: Any,
    violations: list[ConstantFinalViolation],
) -> list[Any]:
  if not violations:
    return []

  description: str = input_api.change.FullDescriptionText()
  bypass_reason = GetBypassReason(description, CONSTANT_FINAL_BYPASS_KEY)
  if bypass_reason:
    return [
        output_api.PresubmitNotifyResult(
            f"Bypassing module constants Final check "
            f"via commit message tag: "
            f"{CONSTANT_FINAL_BYPASS_KEY}={bypass_reason}"),
    ]

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
      f"  {CONSTANT_FINAL_BYPASS_KEY}=<REASON>\n")
  return [
      output_api.PresubmitError(
          "Found module constants not annotated with Final in modified "
          "files:",
          items=error_items,
          long_text=long_text),
  ]


def CheckAst(input_api: Any, output_api: Any) -> list[Any]:
  """Performs a single-pass AST analysis across modified files."""
  results: list[Any] = []
  banned_builtin_violations: list[BannedBuiltinViolation] = []
  constant_final_violations: list[ConstantFinalViolation] = []
  root_path = pathlib.Path(input_api.PresubmitLocalPath())

  def file_filter(f: Any) -> bool:
    return f.LocalPath().endswith(".py") and not GlobalSkipChecks(
        input_api, f.LocalPath())

  for affected_file in input_api.AffectedFiles(
      file_filter=file_filter, include_deletes=False):
    file_path = affected_file.LocalPath()
    full_path = root_path / file_path
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

    visitor = CombinedAstVisitor()
    visitor.visit(tree)

    if (not visitor.banned_builtin_violations and
        not visitor.constant_final_violations):
      continue

    changed_line_numbers = {
        lineno for lineno, _ in affected_file.ChangedContents()
    }
    lines = content.splitlines()

    for lineno, col, func_name in visitor.banned_builtin_violations:
      if lineno in changed_line_numbers:
        line_text = lines[lineno -
                          1].strip() if 0 <= lineno - 1 < len(lines) else ""
        banned_builtin_violations.append(
            BannedBuiltinViolation(
                file_path=file_path,
                line_number=lineno,
                col_offset=col,
                func_name=func_name,
                line_text=line_text,
            ))

    for lineno, col, target_name in visitor.constant_final_violations:
      if lineno in changed_line_numbers:
        line_text = lines[lineno -
                          1].strip() if 0 <= lineno - 1 < len(lines) else ""
        constant_final_violations.append(
            ConstantFinalViolation(
                file_path=file_path,
                line_number=lineno,
                col_offset=col,
                target_name=target_name,
                line_text=line_text,
            ))

  results += _ReportBannedBuiltins(input_api, output_api,
                                   banned_builtin_violations)
  results += _ReportConstantFinal(input_api, output_api,
                                  constant_final_violations)
  return results
