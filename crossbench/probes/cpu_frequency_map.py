# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import dataclasses
import enum
import re
from typing import TYPE_CHECKING, Final, Hashable, Mapping, Pattern, Self, \
    TypeAlias

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import exception
from crossbench import path as pth
from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.plt.base import Platform

# Directory exposing info & controls for the frequency of all CPUs.
_CPUS_DIR: Final = pth.AnyPosixPath("/sys/devices/system/cpu")

# Used to specify behavior for all CPUs.
_WILDCARD_CONFIG_KEY: Final = "*"

# Matches the CPU names exposed by the system in _CPUS_DIR.
_CPU_NAME_REGEX: Final[Pattern[str]] = re.compile("cpu[0-9]+$")


class _ExtremeFrequency(enum.StrEnum):
  MAX = "max"
  MIN = "min"


if TYPE_CHECKING:
  FrequencyType: TypeAlias = _ExtremeFrequency | int


class CPUFrequencyMap(ConfigObject, metaclass=abc.ABCMeta):

  @abc.abstractmethod
  def get_target_frequencies(
      self, platform: Platform) -> immutabledict[pth.AnyPosixPath, int]:
    raise NotImplementedError

  @property
  @abc.abstractmethod
  def key(self) -> Hashable:
    raise NotImplementedError

  @classmethod
  @override
  def parse_dict(cls, config: Mapping[str, object],
                 **kwargs) -> CPUFrequencyMap:
    cls.expect_no_extra_kwargs(kwargs)
    if _WILDCARD_CONFIG_KEY in config:
      return WildcardCPUFrequencyMap.create(config)
    return ExplicitCPUFrequencyMap.create(config)

  @classmethod
  @override
  def parse_str(cls, value: str) -> CPUFrequencyMap:
    return CPUFrequencyMap.parse_dict({_WILDCARD_CONFIG_KEY: value})

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    return ConfigParser(cls)

  @classmethod
  def _parse_frequency(cls, value: object) -> FrequencyType:
    if value == _ExtremeFrequency.MIN:
      return _ExtremeFrequency.MIN

    if value == _ExtremeFrequency.MAX:
      return _ExtremeFrequency.MAX

    try:
      return NumberParser.positive_zero_int(value)
    except argparse.ArgumentTypeError as e:
      raise argparse.ArgumentTypeError(
          f"Invalid value in CPU frequency map: {value}. Should "
          'have been one of "max"|"min"|<int>|"<int>"') from e

  def _get_target_frequency(self, platform: Platform, cpu_name: str,
                            frequency: FrequencyType) -> int:
    if not platform.exists(_CPUS_DIR):
      # TODO(crbug.com/372862708): If different devices indeed use different
      # dirs, consider making this configurable in the jSON.
      raise FileNotFoundError(
          f"{_CPUS_DIR} not found. Either {platform} does not support setting "
          "CPU frequency or the CPUs are exposed in another path and that "
          "requires extra support.")

    cpu_dir: pth.AnyPosixPath = self._get_cpu_dir(cpu_name)
    if not platform.is_dir(cpu_dir):
      raise ValueError(f"Invalid CPU name: {cpu_name}.")

    available_frequencies: list[int] = [
        NumberParser.positive_zero_int(f)
        for f in platform.cat(cpu_dir / "scaling_available_frequencies").rstrip(
            "\n").rstrip(" ").split(" ")
    ]
    if frequency == _ExtremeFrequency.MIN:
      return min(available_frequencies)
    if frequency == _ExtremeFrequency.MAX:
      return max(available_frequencies)
    if frequency in available_frequencies:
      assert isinstance(frequency, int)
      return frequency
    raise ValueError(f"Target frequency {frequency} for {cpu_name} "
                     f"not allowed in {platform}. Available frequencies: "
                     f"{available_frequencies}")

  def _get_cpu_dir(self, cpu_name: str) -> pth.AnyPosixPath:
    # Create new AnyPosixPath so pyfakefs is happy in tests.
    return pth.AnyPosixPath(_CPUS_DIR / cpu_name / "cpufreq")


@dataclasses.dataclass(frozen=True)
class WildcardCPUFrequencyMap(CPUFrequencyMap):
  target_frequency: FrequencyType

  @classmethod
  @override
  def create(
      cls,
      frequencies: Mapping[str, object] | None = None,
      target_frequency: FrequencyType | None = None,
  ) -> Self:
    if target_frequency is not None:
      assert not frequencies, (
          "Cannot have target_frequency and frequencies at the same time")
      return cls(target_frequency=cls._parse_frequency(target_frequency))
    if not frequencies or len(
        frequencies) != 1 or _WILDCARD_CONFIG_KEY not in frequencies:
      raise argparse.ArgumentTypeError(
          f"A wildcard ({_WILDCARD_CONFIG_KEY}) in "
          "the CPU frequency map should be the only key.")
    parsed_target_frequency = cls._parse_frequency(
        frequencies[_WILDCARD_CONFIG_KEY])
    return cls(target_frequency=parsed_target_frequency)

  @override
  def get_target_frequencies(
      self, platform: Platform) -> immutabledict[pth.AnyPosixPath, int]:
    return immutabledict({
        self._get_cpu_dir(p.name):
            self._get_target_frequency(platform, p.name, self.target_frequency)
        for p in platform.iterdir(_CPUS_DIR)
        if _CPU_NAME_REGEX.match(p.name)
    })

  @property
  @override
  def key(self) -> Hashable:
    return self.target_frequency


@dataclasses.dataclass(frozen=True)
class ExplicitCPUFrequencyMap(CPUFrequencyMap):
  frequencies: immutabledict[str, FrequencyType] = dataclasses.field(
      default_factory=immutabledict)

  @classmethod
  @override
  def create(
      cls,
      frequencies: Mapping[str, object] | None = None,
  ) -> Self:
    typed_map: dict[str, FrequencyType] = {}
    for k, v in (frequencies or {}).items():
      with exception.annotate_argparsing(f"Parsing cpu frequency: {k}, {v}"):
        typed_map[ObjectParser.non_empty_str(k)] = cls._parse_frequency(v)
    return cls(frequencies=immutabledict(typed_map))

  @override
  def get_target_frequencies(
      self, platform: Platform) -> immutabledict[pth.AnyPosixPath, int]:
    return immutabledict({
        self._get_cpu_dir(cpu_name):
            self._get_target_frequency(platform, cpu_name, config_frequency)
        for cpu_name, config_frequency in self.frequencies.items()
    })

  @property
  @override
  def key(self) -> Hashable:
    return self.frequencies
