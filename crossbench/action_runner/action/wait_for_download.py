# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_probe import BaseProbeAction
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  import datetime as dt
  import re

  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


# Left here for backwards compatibility.
# New probe actions should not have individual class implementations.
# They should just be used as ProbeActions directly.
@dataclasses.dataclass(frozen=True, eq=False)
class WaitForDownloadAction(BaseProbeAction):
  TYPE: ClassVar[ActionType] = ActionType.WAIT_FOR_DOWNLOAD
  PROBE: ClassVar[str] = "downloads"

  pattern: re.Pattern[str] | None = None

  @property
  @override
  def probe(self) -> str:
    return self.PROBE

  @classmethod
  @override
  def create(cls: type[Self],
             pattern: re.Pattern[str] | None = None,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    if pattern:
      kwargs: immutabledict[str, re.Pattern[str]] = immutabledict(
          {"pattern": pattern})
    else:
      kwargs = immutabledict()
    return cls(kwargs=kwargs, pattern=pattern, timeout=timeout, index=index)

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "pattern",
        type=ObjectParser.regexp,
        help="A regexp to search downloaded file names",
        required=True)
    return parser

  @override
  def kwargs_to_json(self) -> JsonDict:
    pattern: str | None = None
    if self.pattern:
      pattern = self.pattern.pattern
    return {"pattern": pattern}
