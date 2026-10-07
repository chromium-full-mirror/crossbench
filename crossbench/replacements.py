# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Mapping, Self, cast

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import exception
from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.types import ImmutableJsonDict, Json, JsonDict


@dataclasses.dataclass(frozen=True)
class Replacements(ConfigObject):
  _replacements: ImmutableJsonDict = dataclasses.field(
      default_factory=immutabledict)

  @classmethod
  @override
  def create(
      cls,
      replacements: Mapping[str, object] | None = None,
  ) -> Self:
    dict_value = ObjectParser.dict(replacements or {}, "replacements")
    validated_replacements: JsonDict = {}
    for replace_key, replace_value in dict_value.items():
      with exception.annotate_argparsing(
          f"Parsing ...[{replace_key!r}] = {dict_value!r}"):
        key = ObjectParser.non_empty_str(replace_key, "replacement key")
        val = cast("Json",
                   ObjectParser.not_none(replace_value, "replacement value"))
        validated_replacements[key] = val
    return cls(_replacements=immutabledict(validated_replacements))

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    del value
    raise ValueError("Cannot parse replacements from string")

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    del kwargs
    return cls.create(config)

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    return parser

  def apply(self, raw_value: str) -> str:
    final_value: str = raw_value

    if self._replacements:
      for key, value in self._replacements.items():
        final_value = final_value.replace(key, str(value))

    return final_value

  def to_json(self) -> JsonDict:
    return dict(self._replacements)
