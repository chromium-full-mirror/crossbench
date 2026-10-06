# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import functools
from typing import TYPE_CHECKING, Any, Self

from typing_extensions import override

from crossbench.action_runner.action.base_duration import BaseDurationAction
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.config import ConfigParser
  from crossbench.types import JsonDict


@dataclasses.dataclass(frozen=True, eq=False)
class InputSourceAction(BaseDurationAction, metaclass=abc.ABCMeta):
  source: InputSource = InputSource.JS
  source_device: str | None = dataclasses.field(default=None, kw_only=True)

  @classmethod
  @override
  def create(cls: type[Self], *args: Any, **kwargs: Any) -> Self:
    source = kwargs.get("source", args[0] if args else InputSource.JS)
    if kwargs.get("source_device") is None:
      if default_device := DEFAULT_VIRTUAL_DEVICES.get(source):
        kwargs["source_device"] = default_device.name
    return super().create(*args, **kwargs)

  @classmethod
  @override
  @functools.cache
  def config_parser(cls: type[Self]) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "source", type=InputSource.parse, default=InputSource.JS)
    parser.add_argument(
        "source_device",
        type=ObjectParser.non_empty_str,
        required=False,
        default=None)
    return parser

  @property
  def input_source(self) -> InputSource:
    return self.source

  @override
  def validate(self) -> None:
    super().validate()
    self.validate_input_source()

  def validate_input_source(self) -> None:
    if self.input_source not in self.supported_input_sources():
      raise ValueError(
          f"Unsupported input source for {self.__class__.__name__}")
    if self.input_source in DEFAULT_VIRTUAL_DEVICES and not self.source_device:
      raise ValueError(f"Missing source_device for {self.__class__.__name__} "
                       f"with source {self.input_source}")

  @abc.abstractmethod
  def supported_input_sources(self) -> tuple[InputSource, ...]:
    pass

  @override
  def to_json(self) -> JsonDict:
    details = super().to_json()
    details["source"] = self.input_source
    if self.source_device:
      details["source_device"] = self.source_device
    return details
