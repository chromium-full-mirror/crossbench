# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Self

from crossbench.action_runner.android_input_action_runner import \
    AndroidInputActionRunner
from crossbench.action_runner.base import ActionRunner
from crossbench.action_runner.chromeos_input_action_runner import \
    ChromeOSInputActionRunner
from crossbench.action_runner.virtual_device.all import \
    DEFAULT_VIRTUAL_DEVICES, VIRTUAL_DEVICES_TUPLE
from crossbench.action_runner.virtual_device.virtual_device_config import \
    VIRTUAL_DEVICES, VirtualDeviceConfig
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.config import ConfigEnum, ConfigObject, ConfigParser

__all__ = [
    "ActionRunnerConfig",
    "ActionRunnerType",
    "DEFAULT_VIRTUAL_DEVICES",
    "VIRTUAL_DEVICES",
    "VIRTUAL_DEVICES_TUPLE",
    "VirtualDeviceConfig",
    "VirtualDeviceType",
]

if TYPE_CHECKING:
  from crossbench.plt.base import Platform
  from crossbench.runner.run import Run


class ActionRunnerType(ConfigEnum):
  AUTO = (
      "auto",
      "Uses the best-fit default action runner based on the browser platform.")
  BASIC = ("basic", str(ActionRunner.__doc__))
  ANDROID = ("android", str(AndroidInputActionRunner.__doc__))
  CHROMEOS = ("chromeos", str(ChromeOSInputActionRunner.__doc__))


@dataclasses.dataclass(frozen=True)
class ActionRunnerConfig(ConfigObject):
  type: ActionRunnerType = ActionRunnerType.AUTO
  virtual_devices: tuple[VirtualDeviceConfig, ...] = ()

  @classmethod
  def parse_str(cls, value: str) -> Self:
    runner_type: ActionRunnerType = ActionRunnerType.parse(value)
    return cls(type=runner_type)

  @classmethod
  def config_parser(cls) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "type", type=ActionRunnerType, default=ActionRunnerType.AUTO)
    parser.add_argument(
        "virtual_devices", type=VirtualDeviceConfig, is_list=True, default=())
    return parser

  def instantiate(self,
                  platform: Platform,
                  run: Run,
                  step_by_step_mode: bool = False) -> ActionRunner:
    match self.type:
      case ActionRunnerType.ANDROID:
        return AndroidInputActionRunner(run, self.virtual_devices,
                                        step_by_step_mode)
      case ActionRunnerType.CHROMEOS:
        return ChromeOSInputActionRunner(run, self.virtual_devices,
                                         step_by_step_mode)
      case ActionRunnerType.BASIC:
        # TODO: rename
        return ActionRunner(run, self.virtual_devices, step_by_step_mode)
      case ActionRunnerType.AUTO:
        return self.instantiate_default(platform, run, step_by_step_mode)
      case _:
        raise ValueError(f"Unsupported action runner type: {self.type}")

  def instantiate_default(self,
                          platform: Platform,
                          run: Run,
                          step_by_step_mode: bool = False) -> ActionRunner:
    if platform.is_android:
      return AndroidInputActionRunner(run, self.virtual_devices,
                                      step_by_step_mode)
    if platform.is_chromeos:
      return ChromeOSInputActionRunner(run, self.virtual_devices,
                                       step_by_step_mode)
    return ActionRunner(run, self.virtual_devices, step_by_step_mode)
