# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench.action_runner.virtual_device.virtual_device_config import \
    VirtualDeviceConfig
from crossbench.parse import NumberParser

if TYPE_CHECKING:
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True)
class PointingVirtualDeviceConfig(VirtualDeviceConfig, metaclass=abc.ABCMeta):
  DEFAULT_POLLING_RATE_HZ: ClassVar[int] = 0

  # Width and height define the absolute coordinate ranges [0..width] and
  # [0..height] for the EV_ABS axes when registering the virtual pointing
  # device with uinput / evemu. If omitted (None), the platform's active
  # display resolution is used as the default range.
  width: int | None = None
  height: int | None = None
  polling_rate_hz: int = 0

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument("width", type=NumberParser.positive_int, default=None)
    parser.add_argument("height", type=NumberParser.positive_int, default=None)
    parser.add_argument(
        "polling_rate_hz",
        aliases=("polling_rate", "rate", "frequency"),
        type=NumberParser.positive_int,
        default=cls.DEFAULT_POLLING_RATE_HZ)
    return parser

  @override
  def validate(self) -> None:
    super().validate()
    if self.width is not None and self.width <= 0:
      raise ValueError(f"Expected positive width, but got {self.width}")
    if self.height is not None and self.height <= 0:
      raise ValueError(f"Expected positive height, but got {self.height}")
    if (self.width is None) != (self.height is None):
      raise ValueError(
          "Width and height must both be set or both unset, but got: "
          f"width={self.width}, height={self.height}")
    if self.polling_rate_hz <= 0:
      raise ValueError(
          f"Expected positive polling_rate_hz, but got {self.polling_rate_hz}")

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    if self.width is not None:
      details["width"] = self.width
    if self.height is not None:
      details["height"] = self.height
    if self.polling_rate_hz != self.DEFAULT_POLLING_RATE_HZ:
      details["polling_rate_hz"] = self.polling_rate_hz
    return details
