# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from tools.presubmit.banned_builtins import BannedBuiltinVisitor
from tools.presubmit.common import AstCheckVisitor
from tools.presubmit.constant_final import ConstantFinalVisitor

if TYPE_CHECKING:
  from presubmit_support import InputApi, OutputApi

VISITORS: Final[tuple[type[AstCheckVisitor], ...]] = (
    BannedBuiltinVisitor,
    ConstantFinalVisitor,
)


class CombinedAstVisitor:
  """Single-pass AST checker running all AST visitors on each parsed file."""

  @classmethod
  def check(cls, input_api: InputApi, output_api: OutputApi) -> list[object]:
    return AstCheckVisitor.check_all(input_api, output_api, VISITORS)
