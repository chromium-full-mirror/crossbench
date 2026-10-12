# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import logging
from typing import TYPE_CHECKING, Iterable, Self, Sequence

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import exception
from crossbench.cli.config.probe import ProbeConfig, ProbeConfigError
from crossbench.config import ConfigObject
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  import crossbench.path as pth
  from crossbench.probes.probe import Probe


@dataclasses.dataclass(frozen=True)
class ProbeListConfig(ConfigObject):
  _probes: immutabledict[str, Probe] = dataclasses.field(
      compare=True, hash=True)

  @classmethod
  def from_probes(
      cls,
      probe_configs: Iterable[ProbeConfig] = (),
      probes: Iterable[Probe] = (),
  ) -> Self:
    accumulator: dict[str, Probe] = {}
    for probe_config in probe_configs:
      with exception.annotate(f"Parsing --probe={probe_config.name}"):
        probe: Probe = probe_config.new_instance()
        cls._add_probe(accumulator, probe)
    for probe in probes:
      cls._add_probe(accumulator, probe)
    return cls(immutabledict(accumulator))

  @classmethod
  def _add_probe(cls, accumulator: dict[str, Probe], probe: Probe) -> None:
    if probe.name in accumulator:
      raise ValueError(f"Duplicate probe: {probe.name}")
    accumulator[probe.name] = probe

  @classmethod
  def parse_args(cls, args: argparse.Namespace) -> Self:
    with exception.annotate_argparsing():
      config_from_args = cls.from_probes(args.probe)
      if not args.probe_config:
        return config_from_args
      probe_config_path: pth.LocalPath = args.probe_config
      config_from_file = cls.parse(probe_config_path)
      if args.no_probe:
        no_probes = frozenset(args.no_probe)
        cls._verify_no_conflicts(no_probes, config_from_args)
        config_from_file = cls._exclude(config_from_file, no_probes)
      with exception.annotate(
          f"Merging probe config ({probe_config_path.name}) with cli --probe:"):
        return config_from_file.merge(config_from_args, should_override=True)
    raise exception.UnreachableError

  @classmethod
  def parse_other(cls, value: object) -> Self:
    if isinstance(value, (tuple, list)):
      return cls.parse_sequence(value)
    return super().parse_other(value)

  @classmethod
  def parse_sequence(cls, config: Sequence[dict[str, object]]) -> Self:
    probe_configs: list[ProbeConfig] = []
    for index, probe_config in enumerate(config):
      with exception.annotate(f"Parsing probes[{index}]"):
        probe_configs.append(ProbeConfig.parse(probe_config))
    return cls.from_probes(probe_configs)

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    # Support global configs with {"probes": ...}
    if "probes" in config:
      probes_config = config["probes"]
      if isinstance(probes_config, (tuple, list)):
        return cls.parse_sequence(probes_config)
      config = ObjectParser.dict(probes_config, "probes")
    elif "browsers" in config or "flags" in config:
      raise ProbeConfigError("Missing 'probes' property in global config.")
    else:
      config = ObjectParser.dict(config, "probes")
    probe_configs: list[ProbeConfig] = []
    for probe_name, config_data in config.items():
      with exception.annotate(f"Parsing probe config probes['{probe_name}']"):
        probe_dict = ObjectParser.dict(config_data, f"probes[{probe_name!r}]")
        probe_configs.append(
            ProbeConfig.parse_probe_dict(probe_name, probe_dict))
    return cls.from_probes(probe_configs)

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise NotImplementedError

  @classmethod
  def _exclude(cls, config: Self, no_probes: frozenset[str]) -> Self:
    filtered_probes = [p for p in config.probes if p.name not in no_probes]
    return cls.from_probes(probes=filtered_probes)

  @classmethod
  def _verify_no_conflicts(cls, no_probes: frozenset[str],
                           config_from_args: Self) -> None:
    explicit_probes = {p.name for p in config_from_args.probes}
    if conflicting := (no_probes & explicit_probes):
      raise argparse.ArgumentTypeError("Cannot both enable and disable probes: "
                                       f"{', '.join(sorted(conflicting))}")

  @property
  def probes(self) -> tuple[Probe, ...]:
    return tuple(self._probes.values())

  def merge(self, other: Self, should_override: bool = False) -> Self:
    merged_probes = {probe.name: probe for probe in self.probes}
    for probe in other.probes:
      name = probe.name
      if name in merged_probes:
        if not should_override:
          raise ValueError(f"Duplicate probe: {name}")
        logging.warning("PROBES: Overriding existing probe %s!", name)
      merged_probes[name] = probe

    return type(self).from_probes(probes=merged_probes.values())
