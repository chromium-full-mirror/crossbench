# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Self

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import ObjectParser, PathParser
from crossbench.probes.trace_processor.constants import QUERIES_DIR
from crossbench.replacements import Replacements

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.plt import Platform


@dataclasses.dataclass(frozen=True)
class TraceProcessorQueryConfig(ConfigObject):
  name: str
  _sql: str

  @classmethod
  @override
  def create(
      cls,
      name: str,
      sql: str,
      replacements: Replacements | None = None,
  ) -> Self:
    if replacements:
      sql = replacements.apply(sql)
    return cls(name=name, _sql=sql)

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object],
                 **kwargs) -> TraceProcessorQueryConfig:
    keys = {"device_override", "device_lookup", "sql_device_override"}
    if keys.intersection(config) and cls is TraceProcessorQueryConfig:
      return DeviceSpecificTraceProcessorQuery.parse_dict(config, **kwargs)
    return super().parse_dict(config, **kwargs)

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    name = ObjectParser.safe_filename(value)
    if value.endswith(".sql"):
      name = name[:-4]
    else:
      value = f"{value}.sql"
    sql_path = PathParser.existing_file_path(QUERIES_DIR / value, "sql query")
    sql = sql_path.read_text(encoding="utf-8")
    return cls.create(name=name, sql=sql)

  @classmethod
  @override
  def parse_any_path(cls, path: pth.LocalPath, **kwargs) -> Self:
    return cls.parse_str(str(path))

  @classmethod
  @override
  def resolve_path(cls, path: pth.LocalPath) -> pth.LocalPath:
    return path

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("name", type=ObjectParser.safe_filename, required=True)
    parser.add_argument(
        "sql", type=ObjectParser.str_or_file_contents, required=True)
    parser.add_argument("replacements", aliases=("replace",), type=Replacements)
    return parser

  @property
  def sql(self) -> str:
    return self._sql

  def resolve_for_platform(
      self, platform: Platform) -> TraceProcessorQueryConfig | None:
    del platform
    return self


@dataclasses.dataclass(frozen=True)
class DeviceSpecificTraceProcessorQuery(TraceProcessorQueryConfig):
  device_override: immutabledict[re.Pattern, str] = dataclasses.field(
      default_factory=immutabledict)
  fallback_sql: str | None = None
  replacements: Replacements | None = None

  @classmethod
  @override
  def create(
      cls,
      name: str,
      sql: str | None = None,
      replacements: Replacements | None = None,
      device_override: dict[str, str] | None = None,
  ) -> Self:
    compiled_device_override: dict[re.Pattern, str] = {}
    for model, path in (device_override or {}).items():
      try:
        compiled_device_override[re.compile(model)] = path
      except re.error as e:
        raise ValueError(
            f"Invalid regular expression in device_override: {model}") from e
    return cls(
        name=name,
        _sql="",
        device_override=immutabledict(compiled_device_override),
        fallback_sql=sql,
        replacements=replacements,
    )

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("name", type=ObjectParser.safe_filename, required=True)
    parser.add_argument(
        "device_override",
        aliases=("device_lookup", "sql_device_override"),
        type=ObjectParser.dict,
        required=True)
    parser.add_argument("sql", type=str, required=False)
    parser.add_argument("replacements", aliases=("replace",), type=Replacements)
    return parser

  @property
  @override
  def sql(self) -> str:
    raise RuntimeError(
        "DeviceSpecificTraceProcessorQuery must be resolved for a platform "
        "before accessing its SQL.")

  def resolve_for_platform(
      self, platform: Platform) -> TraceProcessorQueryConfig | None:
    return self.resolve_for_device_model(platform.model)

  def resolve_for_device_model(
      self, device_model: str) -> TraceProcessorQueryConfig | None:
    query_path = ""

    for model_re, path in self.device_override.items():
      if model_re.fullmatch(device_model):
        if query_path and query_path != path:
          raise ValueError("Multiple conflicting mappings match device model "
                           f"'{device_model}': '{query_path}' and '{path}'")
        query_path = path

    if not query_path:
      if self.fallback_sql:
        query_path = self.fallback_sql
      else:
        return None

    value = query_path if query_path.endswith(".sql") else f"{query_path}.sql"
    sql_path = PathParser.existing_file_path(QUERIES_DIR / value, "sql query")
    sql = sql_path.read_text(encoding="utf-8")
    return TraceProcessorQueryConfig.create(
        name=self.name, sql=sql, replacements=self.replacements)
