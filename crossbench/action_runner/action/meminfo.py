# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Iterable, Self

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_probe import BaseProbeAction
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.config import ConfigParser


# Left here for backwards compatibility.
# New probe actions should not have individual class implementations.
# They should just be used as ProbeActions directly.
@dataclasses.dataclass(frozen=True, eq=False)
class MeminfoAction(BaseProbeAction):
  TYPE: ClassVar[ActionType] = ActionType.MEMINFO
  PROBE: ClassVar[str] = "meminfo"

  browser: bool = True
  packages: tuple[str, ...] = ()
  title: str | None = None
  system: bool = False

  @property
  @override
  def probe(self) -> str:
    return self.PROBE

  @classmethod
  @override
  def create(cls: type[Self],
             browser: bool = True,
             packages: Iterable[str] = (),
             title: str | None = None,
             system: bool = False,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    packages = tuple(packages)
    kwargs: immutabledict[str, object] = immutabledict({
        "browser": browser,
        "system": system,
        "packages": packages,
        "title": title,
    })
    return cls(
        kwargs=kwargs,
        browser=browser,
        packages=packages,
        title=title,
        system=system,
        timeout=timeout,
        index=index)

  @classmethod
  @override
  @functools.lru_cache(maxsize=1)
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("browser", type=ObjectParser.bool, default=True)
    parser.add_argument(
        "packages", type=ObjectParser.non_empty_str, default=(), is_list=True)
    parser.add_argument("system", type=ObjectParser.bool, default=False)
    parser.add_argument("title", type=ObjectParser.non_empty_str, default=None)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if not self.browser and not self.system and not self.packages:
      raise ValueError(f"{self} requires at least one of browser, system, "
                       "or packages to be specified.")
