# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar, Self

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_probe import BaseProbeAction

if TYPE_CHECKING:
  import datetime as dt


# Left here for backwards compatibility.
# New probe actions should not have individual class implementations.
# They should just be used as ProbeActions directly.
@dataclasses.dataclass(frozen=True, eq=False)
class DumpHtmlAction(BaseProbeAction):
  TYPE: ClassVar[ActionType] = ActionType.DUMP_HTML
  PROBE: ClassVar[str] = "dump_html"

  @property
  @override
  def probe(self) -> str:
    return self.PROBE

  @classmethod
  @override
  def create(cls: type[Self],
             suffix: str | None = None,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    if suffix:
      kwargs: immutabledict[str, str] = immutabledict({"suffix": suffix})
    else:
      kwargs = immutabledict()
    return cls(kwargs=kwargs, timeout=timeout, index=index)
