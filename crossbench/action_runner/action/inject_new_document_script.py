# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.js import JsAction

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner


@dataclasses.dataclass(frozen=True, eq=False)
class InjectNewDocumentScriptAction(JsAction):
  TYPE: ClassVar[ActionType] = ActionType.INJECT_NEW_DOCUMENT_SCRIPT

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.inject_new_document_script(self)
