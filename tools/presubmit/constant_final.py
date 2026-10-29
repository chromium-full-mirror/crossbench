# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

from tools.presubmit.common import AstCheckVisitor, AstViolation, \
    PresubmitCheck

if TYPE_CHECKING:
  from collections.abc import Sequence

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


class ConstantFinalVisitor(AstCheckVisitor):

  def _is_final_annotation(self, annotation: ast.AST | None) -> bool:
    if isinstance(annotation, ast.Name):
      return annotation.id == "Final"
    if isinstance(annotation, ast.Attribute):
      return annotation.attr == "Final"
    if isinstance(annotation, ast.Subscript):
      return self._is_final_annotation(annotation.value)
    return False

  def _is_type_construct(self, value: ast.AST | None) -> bool:
    if not isinstance(value, ast.Call):
      return False
    func: ast.expr = value.func
    if isinstance(func, ast.Name):
      return func.id in _TYPE_CONSTRUCT_NAMES
    if isinstance(func, ast.Attribute):
      return func.attr in _TYPE_CONSTRUCT_NAMES
    return False

  def _is_constant_name(self, name: str) -> bool:
    return (name not in _EXCLUDED_CONSTANTS and
            bool(_UPPER_SNAKE_CASE_RE.match(name)))

  def _check_assign(self, stmt: ast.Assign) -> None:
    if self._is_type_construct(stmt.value):
      return
    for target in stmt.targets:
      if isinstance(target, ast.Name) and self._is_constant_name(target.id):
        self.add_violation(stmt, target.id)

  def _check_ann_assign(self, stmt: ast.AnnAssign) -> None:
    target: ast.expr = stmt.target
    if not isinstance(target, ast.Name):
      return
    if not self._is_constant_name(target.id):
      return
    if not self._is_final_annotation(stmt.annotation):
      self.add_violation(stmt, target.id)

  def visit_Module(self, node: ast.Module) -> None:
    for stmt in node.body:
      if isinstance(stmt, ast.Assign):
        self._check_assign(stmt)
      elif isinstance(stmt, ast.AnnAssign):
        self._check_ann_assign(stmt)

  @classmethod
  def report(
      cls,
      presubmit: PresubmitCheck,
      violations: Sequence[AstViolation],
  ) -> list[object]:
    if not violations:
      return []

    if bypass_reason := presubmit.bypass_reason(BYPASS_KEY):
      return [
          presubmit.output_api.PresubmitNotifyResult(
              f"Bypassing module constants Final check "
              f"via commit message tag: {BYPASS_KEY}={bypass_reason}"),
      ]

    long_text: str = f"""\
Module-level UPPER_SNAKE constants must be annotated with `Final`
(e.g., `NAME: Final = ...` or `NAME: Final[Type] = ...`).
If a mutable module global or non-final constant is strictly
necessary, provide a non-empty reason in your commit message
footer/tags:
  {BYPASS_KEY}=<REASON>
"""
    return [
        presubmit.output_api.PresubmitError(
            "Found module constants not annotated with Final in modified "
            "files:",
            items=[v.format_error() for v in violations],
            long_text=long_text),
    ]
