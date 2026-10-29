# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from tools.presubmit.common import AstCheckVisitor, AstViolation, \
    PresubmitCheck

if TYPE_CHECKING:
  from collections.abc import Sequence

BANNED_BUILTIN_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"getattr", "setattr", "hasattr"})


class BannedBuiltinVisitor(AstCheckVisitor):

  def _banned_func_name(self, func: ast.expr) -> str | None:
    name: str | None = None
    if isinstance(func, ast.Name):
      name = func.id
    elif (isinstance(func, ast.Attribute) and
          isinstance(func.value, ast.Name) and func.value.id == "builtins"):
      name = func.attr
    return name if name in BANNED_BUILTIN_FUNCTIONS else None

  def visit_Call(self, node: ast.Call) -> None:
    if func_name := self._banned_func_name(node.func):
      self.add_violation(node, func_name)
    self.generic_visit(node)

  @classmethod
  def _create_violation_error(
      cls,
      presubmit: PresubmitCheck,
      violations: Sequence[AstViolation],
      missing_bypasses: Sequence[str],
  ) -> object:
    help_tags: str = "\n".join(f"  {key}=<REASON>" for key in missing_bypasses)
    long_text: str = f"""\
Calling `getattr()`, `setattr()`, or `hasattr()` is strictly
discouraged in Crossbench:
  - For CLI args/namespaces: configure proper defaults in argument
    parsers (parser.set_defaults) or mock fixtures.
  - For classes/objects: use explicit attributes, dataclasses,
    properties, or protocols instead of dynamic reflection.

If dynamic attribute access is strictly necessary, provide a
non-empty reason in your commit message footer/tags to bypass this
check:
{help_tags}
"""
    return presubmit.output_api.PresubmitError(
        "Found banned built-in function calls in modified files:",
        items=[v.format_error() for v in violations],
        long_text=long_text)

  @classmethod
  def report(
      cls,
      presubmit: PresubmitCheck,
      violations: Sequence[AstViolation],
  ) -> list[object]:
    if not violations:
      return []

    detected_functions: list[str] = sorted({v.name for v in violations})
    missing_bypasses: list[str] = []
    valid_bypasses: list[tuple[str, str]] = []

    for func_name in detected_functions:
      bypass_key: str = f"ALLOW_{func_name.upper()}"
      if reason := presubmit.bypass_reason(bypass_key):
        valid_bypasses.append((bypass_key, reason))
      else:
        missing_bypasses.append(bypass_key)

    if not missing_bypasses:
      bypass_details: str = ", ".join(f"{k}={r}" for k, r in valid_bypasses)
      return [
          presubmit.output_api.PresubmitNotifyResult(
              f"Bypassing banned built-in check "
              f"({', '.join(detected_functions)}) "
              f"via commit message tag(s): {bypass_details}"),
      ]

    return [
        cls._create_violation_error(presubmit, violations, missing_bypasses),
    ]
