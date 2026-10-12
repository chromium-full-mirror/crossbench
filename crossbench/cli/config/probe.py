# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import logging
import re
from typing import TYPE_CHECKING, Final, Self

from typing_extensions import override

from crossbench import exception
from crossbench.config import ConfigError, ConfigObject
from crossbench.helper.collection_helper import close_matches_message
from crossbench.parse import ObjectParser
from crossbench.probes.all import PROBE_LOOKUP

if TYPE_CHECKING:
  from collections.abc import Mapping

  from crossbench.probes.probe import Probe


class ProbeConfigError(ConfigError):
  pass


_PROBE_CONFIG_RE: Final[re.Pattern] = re.compile(
    r"(?P<probe_name>[\w.-]+):?(?P<config>.*)", re.MULTILINE | re.DOTALL)


@dataclasses.dataclass(frozen=True)
class ProbeConfig(ConfigObject):
  probe_cls: type[Probe]
  # Full source including probe name:
  # 1. "v8.log:{log_all:true}"
  # 2. "v8.log:presetName"
  src_str: str = ""
  # Config string without the probe name, used for with default arguments,
  # passed on to the probe_cls ConfigParser.parse_str.
  # 1. ""
  # 2. "presetName"
  config_str: str | None = None
  # Config dict passed to the probe_cls ConfigParser.parse_dict.
  config_dict: Mapping[str, object] | None = None

  def __post_init__(self) -> None:
    if not self.probe_cls:
      raise ValueError(f"{type(self).__name__}.cls cannot be None.")
    if self.config_dict and self.config_str:
      raise ValueError(f"{type(self).__name__}: "
                       "Cannot have both config_dict and config_str value.")

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    # Variant: known probe
    if probe_cls := PROBE_LOOKUP.get(value):
      return cls(probe_cls, src_str=value)
    if cls.has_path_prefix(value):
      raise ProbeConfigError(f"Probe config path does not exist: {value}")
    if probe := cls._parse_inline_config(value):
      return probe
    probe_cls = cls._handle_unknown_probe_name("", value)
    return cls(probe_cls, src_str=value)

  @classmethod
  def _parse_inline_config(cls, value: str) -> Self | None:
    match = _PROBE_CONFIG_RE.match(value)
    if not match:
      return None
    probe_name: str = match["probe_name"]
    config_str: str = match["config"]
    probe_cls: type[Probe] | None = PROBE_LOOKUP.get(probe_name)
    if not probe_cls:
      return None
    config: dict[str, object] = {"name": probe_name}
    inline_config: dict = {}
    if cls.is_path_like(config_str) and config_str.endswith(
        (".json", ".hjson")):
      # Variant, hjson path: "name:path/to/config.hjson"
      inline_config = ObjectParser.hjson_file(config_str)
    elif cls.is_hjson_like(config_str):
      # Variant, inline hjson: "name:{hjson}"
      inline_config = ObjectParser.inline_hjson(config_str)
    else:
      return cls(probe_cls, src_str=value, config_str=config_str)
    if inline_config.get("name", probe_name) is not probe_name:
      raise ProbeConfigError("Inline hjson cannot redefine 'name'.")
    config.update(inline_config)
    return cls.parse_dict(config, src_str=value)

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    probe_name = ObjectParser.non_empty_str(config.pop("name"), "name")
    return cls.parse_probe_dict(probe_name, config, **kwargs)

  @classmethod
  def parse_probe_dict(cls, probe_name: str, config: dict[str, object],
                       **kwargs) -> Self:
    if direct_probe_cls := PROBE_LOOKUP.get(probe_name):
      return cls(direct_probe_cls, config_dict=config, **kwargs)
    probe_cls: type[Probe] = cls._handle_dict_unknown_probe_name(probe_name)
    return cls(probe_cls, config_dict=config, **kwargs)

  @classmethod
  def _handle_dict_unknown_probe_name(cls, probe_name: str) -> type[Probe]:
    msg = ""
    if ":" in probe_name or "}" in probe_name:
      msg = "\n    Likely missing quotes for --probe argument.\n"
    return cls._handle_unknown_probe_name(msg, probe_name)

  @classmethod
  def _handle_unknown_probe_name(cls, msg: str, value: str) -> type[Probe]:
    error_message, alternative = close_matches_message(value,
                                                       PROBE_LOOKUP.keys(),
                                                       "Probe name")
    error_message += msg
    logging.error(error_message)
    if alternative:
      return PROBE_LOOKUP[alternative]
    raise ProbeConfigError(error_message)

  def new_instance(self) -> Probe:
    info: list[str] = []
    if self.src_str:
      info.append(f"Parsing: {self.src_str!r}")
    with exception.annotate_argparsing(*info):
      if config_str := self.config_str:
        return self.probe_cls.parse_str(config_str)
      return self.probe_cls.parse_dict(
          dict(self.config_dict) if self.config_dict else {})
    raise exception.UnreachableError

  @property
  def name(self) -> str:
    return self.probe_cls.NAME
