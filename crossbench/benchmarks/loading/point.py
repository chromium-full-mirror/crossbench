# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING, Self

from typing_extensions import override

from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.types import JsonDict


# Represents a single point on a screen.
@dataclasses.dataclass(frozen=True)
class Point(ConfigObject):
  """Configuration object representing a 2D screen coordinate in pixels.

  Attributes:
    x: The horizontal offset in pixels from the left edge of the screen.
    y: The vertical offset in pixels from the top edge of the screen.
  """

  x: int
  y: int

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    parts = ObjectParser.non_empty_str(value, "point").split(",")
    if len(parts) != 2:
      raise ValueError(
          f"Expected 'x,y' format for {cls.__name__}, but got {value!r}")
    return cls(
        x=NumberParser.any_int(parts[0].strip(), "x"),
        y=NumberParser.any_int(parts[1].strip(), "y"))

  @classmethod
  @override
  @functools.cache
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("x", type=NumberParser.any_int, required=True)
    parser.add_argument("y", type=NumberParser.any_int, required=True)
    return parser

  def to_json(self) -> JsonDict:
    return {"x": self.x, "y": self.y}
