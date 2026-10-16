# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Self

from crossbench.action_runner.action_runner import ActionRunner
from crossbench.action_runner.virtual_device.all import \
    DEFAULT_VIRTUAL_DEVICES, VIRTUAL_DEVICES_TUPLE
from crossbench.action_runner.virtual_device.virtual_device_config import \
    VIRTUAL_DEVICES, VirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.config import ConfigObject, ConfigParser

if TYPE_CHECKING:
  from crossbench.runner.run import Run

__all__ = [
    "ActionRunnerConfig",
    "DEFAULT_VIRTUAL_DEVICES",
    "VIRTUAL_DEVICES",
    "VIRTUAL_DEVICES_TUPLE",
    "VirtualDeviceConfig",
    "VirtualDeviceType",
]


@dataclasses.dataclass(frozen=True)
class ActionRunnerConfig(ConfigObject):
  virtual_devices: tuple[VirtualDeviceConfig, ...] = ()

  @classmethod
  def parse_str(cls, value: str) -> Self:
    logging.warning(
        "Choosing an action runner type via string (%r) is deprecated and "
        "will be removed; using default ActionRunnerConfig.", value)
    return cls()

  @classmethod
  def config_parser(cls) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "virtual_devices", type=VirtualDeviceConfig, is_list=True, default=())
    return parser

  def instantiate(self,
                  run: Run,
                  step_by_step_mode: bool = False) -> ActionRunner:
    return ActionRunner(run, self.virtual_devices, step_by_step_mode)
