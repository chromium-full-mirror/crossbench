# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import ast
import dataclasses
import pathlib
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
  from collections.abc import Iterable, Iterator, Sequence

  from presubmit_support import AffectedFile, InputApi, OutputApi

PLACEHOLDER_BYPASS_REASONS: Final[frozenset[str]] = frozenset(
    {"todo", "tbd", "none", "n/a", "fixme", "xxx"})

SKIPPED_PATHS: Final[tuple[str, ...]] = (
    "third_party/*",
    "*crossbench/third_party/*",
)


@dataclasses.dataclass(frozen=True)
class RawAstViolation:
  line_number: int
  col_offset: int
  name: str


@dataclasses.dataclass(frozen=True)
class ParsedPythonFile:
  path: str
  lines: list[str]
  changed_lines: set[int]
  tree: ast.Module


@dataclasses.dataclass(frozen=True)
class AstViolation:
  file_path: str
  line_number: int
  col_offset: int
  name: str
  line_text: str

  def format_error(self) -> str:
    return (f"{self.file_path}:{self.line_number}:{self.col_offset}: "
            f"{self.line_text}")

  @classmethod
  def from_raw(
      cls,
      raw_violations: Iterable[RawAstViolation],
      parsed_file: ParsedPythonFile,
  ) -> list[AstViolation]:
    return [
        cls(parsed_file.path, v.line_number, v.col_offset, v.name,
            parsed_file.lines[v.line_number - 1].strip())
        for v in raw_violations
        if v.line_number in parsed_file.changed_lines
    ]


class PresubmitCheck:

  def __init__(self, input_api: InputApi, output_api: OutputApi) -> None:
    self._input_api: Final[InputApi] = input_api
    self._output_api: Final[OutputApi] = output_api

  @property
  def input_api(self) -> InputApi:
    return self._input_api

  @property
  def output_api(self) -> OutputApi:
    return self._output_api

  @property
  def root_path(self) -> pathlib.Path:
    return pathlib.Path(self._input_api.PresubmitLocalPath())

  @property
  def description(self) -> str:
    return self._input_api.change.FullDescriptionText()

  @classmethod
  def is_skipped_path(cls, input_api: InputApi, file_path: str) -> bool:
    return any(
        input_api.fnmatch.fnmatch(file_path, pattern)
        for pattern in SKIPPED_PATHS)

  def affected_python_files(self, path_prefix: str = "") -> list[AffectedFile]:

    def file_filter(f: AffectedFile) -> bool:
      path: str = f.LocalPath()
      return (path.startswith(path_prefix) and path.endswith(".py") and
              not self.is_skipped_path(self._input_api, path))

    return list(
        self._input_api.AffectedFiles(
            file_filter=file_filter, include_deletes=False))

  @classmethod
  def changed_lines(cls, affected_file: AffectedFile) -> set[int]:
    return {lineno for lineno, _ in affected_file.ChangedContents()}

  def iter_parsed_python_files(self) -> Iterator[ParsedPythonFile]:
    for affected_file in self.affected_python_files():
      changed_lines: set[int] = self.changed_lines(affected_file)
      if not changed_lines:
        continue
      file_path: str = affected_file.LocalPath()
      full_path: pathlib.Path = self.root_path / file_path
      content: str = self._input_api.ReadFile(str(full_path), "r")
      tree: ast.Module = ast.parse(content, filename=str(full_path))
      yield ParsedPythonFile(
          file_path,
          content.splitlines(),
          changed_lines,
          tree,
      )

  @classmethod
  def parse_bypass_reason(cls, description: str, key: str) -> str | None:
    pattern: str = rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(\S.*)$"
    for match in re.finditer(pattern, description,
                             re.MULTILINE | re.IGNORECASE):
      reason: str = match.group(1).strip()
      if reason.lower() not in PLACEHOLDER_BYPASS_REASONS:
        return reason
    return None

  def bypass_reason(self, key: str) -> str | None:
    return self.parse_bypass_reason(self.description, key)


class AstCheckVisitor(ast.NodeVisitor, metaclass=abc.ABCMeta):

  def __init__(self) -> None:
    super().__init__()
    self._violations: list[RawAstViolation] = []

  @property
  def violations(self) -> tuple[RawAstViolation, ...]:
    return tuple(self._violations)

  def add_violation(self, node: ast.stmt | ast.expr, name: str) -> None:
    self._violations.append(
        RawAstViolation(node.lineno, node.col_offset + 1, name))

  @classmethod
  @abc.abstractmethod
  def report(
      cls,
      presubmit: PresubmitCheck,
      violations: Sequence[AstViolation],
  ) -> list[object]:
    raise NotImplementedError

  @classmethod
  def check(cls, input_api: InputApi, output_api: OutputApi) -> list[object]:
    return cls.check_all(input_api, output_api, (cls,))

  @classmethod
  def check_all(
      cls,
      input_api: InputApi,
      output_api: OutputApi,
      visitor_classes: Sequence[type[AstCheckVisitor]],
  ) -> list[object]:
    presubmit = PresubmitCheck(input_api, output_api)
    results: list[object] = []
    collected: dict[type[AstCheckVisitor], list[AstViolation]] = {
        v_cls: [] for v_cls in visitor_classes
    }
    for parsed_file in presubmit.iter_parsed_python_files():
      for v_cls in visitor_classes:
        visitor = v_cls()
        visitor.visit(parsed_file.tree)
        collected[v_cls].extend(
            AstViolation.from_raw(visitor.violations, parsed_file))
    for v_cls, violations in collected.items():
      results.extend(v_cls.report(presubmit, violations))
    return results
