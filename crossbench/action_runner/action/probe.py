# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Mapping, Self

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.action import ACTION_TIMEOUT
from crossbench.action_runner.action.action_type import ActionType
from crossbench.action_runner.action.base_probe import BaseProbeAction
from crossbench.parse import ObjectParser
from crossbench.probes.all import PROBE_LOOKUP

if TYPE_CHECKING:
  import datetime as dt

  from crossbench.config import ConfigParser


@dataclasses.dataclass(frozen=True, eq=False)
class ProbeAction(BaseProbeAction):
  TYPE: ClassVar[ActionType] = ActionType.PROBE

  probe: str = dataclasses.field(default="", kw_only=True)
  kwargs: immutabledict[str, object] = dataclasses.field(
      default_factory=immutabledict)

  @classmethod
  @override
  def create(cls: type[Self],
             probe: str = "",
             kwargs: Mapping[str, object] | None = None,
             timeout: dt.timedelta = ACTION_TIMEOUT,
             index: int = 0) -> Self:
    kwargs_immutable: immutabledict[str, object]
    if kwargs is None:
      kwargs_immutable = immutabledict()
    elif isinstance(kwargs, immutabledict):
      kwargs_immutable = kwargs
    else:
      kwargs_immutable = immutabledict(kwargs)
    return cls(
        probe=probe, kwargs=kwargs_immutable, timeout=timeout, index=index)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "probe",
        type=ObjectParser.non_empty_str,
        required=True,
        choices=PROBE_LOOKUP.keys())
    parser.add_argument("kwargs", type=immutabledict, default=immutabledict())
    return parser
