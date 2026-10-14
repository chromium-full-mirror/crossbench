# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import ast
import pathlib
from typing import Any, Final, NamedTuple

from tools.presubmit.common import GetBypassReason, GlobalSkipChecks

BANNED_BUILTIN_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"getattr", "setattr", "hasattr"})


class BannedBuiltinViolation(NamedTuple):
  file_path: str
  line_number: int
  col_offset: int
  func_name: str
  line_text: str


class BannedBuiltinVisitor(ast.NodeVisitor):

  def __init__(self) -> None:
    super().__init__()
    self.violations: list[tuple[int, int, str]] = []

  def visit_Call(self, node: ast.Call) -> None:
    func_name: str | None = None
    if isinstance(node.func, ast.Name):
      func_name = node.func.id
    elif (isinstance(node.func, ast.Attribute) and
          isinstance(node.func.value, ast.Name) and
          node.func.value.id == "builtins"):
      func_name = node.func.attr

    if func_name and func_name in BANNED_BUILTIN_FUNCTIONS:
      self.violations.append((node.lineno, node.col_offset + 1, func_name))
    self.generic_visit(node)


def CheckNoBannedBuiltins(input_api: Any, output_api: Any) -> list[Any]:
  results: list[Any] = []
  violations: list[BannedBuiltinViolation] = []
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

    visitor = BannedBuiltinVisitor()
    visitor.visit(tree)
    if not visitor.violations:
      continue

    changed_line_numbers = {
        lineno for lineno, _ in affected_file.ChangedContents()
    }
    lines = content.splitlines()
    for lineno, col, func_name in visitor.violations:
      if lineno in changed_line_numbers:
        line_text = lines[lineno -
                          1].strip() if 0 <= lineno - 1 < len(lines) else ""
        violations.append(
            BannedBuiltinViolation(
                file_path=file_path,
                line_number=lineno,
                col_offset=col,
                func_name=func_name,
                line_text=line_text,
            ))

  if not violations:
    return results

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
    results.append(
        output_api.PresubmitNotifyResult(
            f"Bypassing banned built-in check "
            f"({', '.join(sorted(detected_functions))}) "
            f"via commit message tag(s): {bypass_details}"))
    return results

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
  results.append(
      output_api.PresubmitError(
          "Found banned built-in function calls in modified files:",
          items=error_items,
          long_text=long_text))
  return results
