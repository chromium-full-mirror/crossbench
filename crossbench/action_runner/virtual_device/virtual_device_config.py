# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Final, Self

from typing_extensions import override

from crossbench import exception
from crossbench.action_runner.virtual_device.virtual_device_type import \
    VirtualDeviceType
from crossbench.config import ConfigObject, ConfigParser, ObjectParser, \
    UnusedPropertiesMode

if TYPE_CHECKING:
  from crossbench.types import JsonDict


class VirtualDeviceTypeConfigParser(ConfigParser[VirtualDeviceType]):

  def __init__(self) -> None:
    super().__init__(
        VirtualDeviceType, unused_properties_mode=UnusedPropertiesMode.IGNORE)
    self.add_argument(
        "device_type",
        aliases=("type",),
        type=ObjectParser.non_empty_str,
        required=True)

  def new_instance_from_kwargs(self, kwargs: dict[str,
                                                  object]) -> VirtualDeviceType:
    return VirtualDeviceType(kwargs["device_type"])  # type: ignore


_DEVICE_TYPE_CONFIG_PARSER: Final = VirtualDeviceTypeConfigParser()

# Lazily initialized VirtualDeviceConfig class lookup.
VIRTUAL_DEVICES: dict[VirtualDeviceType, type[VirtualDeviceConfig]] = {}


@dataclasses.dataclass(frozen=True)
class VirtualDeviceConfig(ConfigObject, metaclass=abc.ABCMeta):
  name: str
  TYPE: ClassVar[VirtualDeviceType] = VirtualDeviceType.KEYBOARD

  @property
  def device_type(self) -> VirtualDeviceType:
    return self.TYPE

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    del value
    raise ValueError("VirtualDeviceConfig must be parsed from a dictionary")

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    device_type: VirtualDeviceType = _DEVICE_TYPE_CONFIG_PARSER.parse(config)
    target_cls: type[Self] = VIRTUAL_DEVICES[device_type]  # type: ignore

    config = dict(config)
    config.pop("device_type", None)
    config.pop("type", None)

    with exception.annotate_argparsing(
        f'Parsing VirtualDeviceConfig ...{{ type: "{device_type}", ...}}:'):
      device_config = target_cls.config_parser().parse(config, **kwargs)
    assert isinstance(device_config,
                      cls), (f"Expected {cls} but got {type(device_config)}")
    return device_config

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("name", type=ObjectParser.non_empty_str, required=True)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if not self.name:
      raise ValueError(f"{type(self).__name__}.name cannot be empty")

  def to_json(self) -> JsonDict:
    return {
        "name": self.name,
        "type": str(self.device_type),
    }
