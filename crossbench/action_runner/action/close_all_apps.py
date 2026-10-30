# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from crossbench.action_runner.action.action import Action
from crossbench.action_runner.action.action_type import ActionType

if TYPE_CHECKING:
  from crossbench.action_runner.action_runner import ActionRunner


@dataclasses.dataclass(frozen=True, eq=False)
class CloseAllAppsAction(Action):
  """Stops the session browser and closes all running applications."""

  TYPE: ClassVar[ActionType] = ActionType.CLOSE_ALL_APPS

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.close_all_apps(self)
