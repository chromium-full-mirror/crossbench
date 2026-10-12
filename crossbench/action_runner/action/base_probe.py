# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
from typing import TYPE_CHECKING, cast

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.action_runner.action.action import Action
from crossbench.action_runner.action.action_type import ActionType
from crossbench.probes.all import PROBE_LOOKUP

if TYPE_CHECKING:
  from crossbench.action_runner.base import ActionRunner
  from crossbench.probes.probe import Probe
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class BaseProbeAction(Action, metaclass=abc.ABCMeta):
  kwargs: immutabledict[str, object] = dataclasses.field(
      default_factory=immutabledict)

  @property
  @abc.abstractmethod
  def probe(self) -> str:
    pass

  @property
  def probe_cls(self) -> type[Probe]:
    return PROBE_LOOKUP[self.probe]

  @override
  def validate(self) -> None:
    super().validate()
    if not self.probe:
      raise ValueError(f"{self}.probe is missing")
    if self.probe not in PROBE_LOOKUP:
      raise ValueError(f"Unknown probe: {self.probe}")
    if not isinstance(self.kwargs, immutabledict):
      raise ValueError(f"{self}.kwargs must be an immutabledict, "
                       f"but got {type(self.kwargs).__name__}")

  @override
  def run_with(self, action_runner: ActionRunner) -> None:
    action_runner.invoke_probe(self)

  def kwargs_to_json(self) -> JsonDict:
    return cast("JsonDict", dict(self.kwargs))

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    # Some legacy action types derive from this class and have a different
    # action type. For serialization purposes, force the type to be Probe
    # action.
    details["type"] = str(ActionType.PROBE)
    details["probe"] = self.probe_cls.NAME
    details["kwargs"] = self.kwargs_to_json()
    return details
