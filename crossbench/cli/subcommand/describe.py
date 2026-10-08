# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Sequence, TypeAlias

import tabulate as tbl
from typing_extensions import override

from crossbench.cli.config.env import ENV_CONFIG_PRESETS, EnvConfig
from crossbench.cli.config.network import NetworkConfig, NetworkType
from crossbench.cli.config.network_speed import NetworkSpeedConfig
from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.config import ConfigObject
from crossbench.helper import txt_helper
from crossbench.helper.class_helper import get_all_subclasses
from crossbench.helper.collection_helper import close_matches_message
from crossbench.probes.all import GENERAL_PURPOSE_PROBES

if TYPE_CHECKING:
  import argparse
  from collections.abc import Mapping

  from crossbench.cli.parser import CBArgumentParser
  from crossbench.cli.types import Subparsers
  from crossbench.config import ConfigParser
  from crossbench.types import TableData

  HelpData: TypeAlias = dict[str, dict[str, Any]]


def get_all_config_classes() -> list[type[ConfigObject]]:
  config_classes = list(get_all_subclasses(ConfigObject))
  filtered_classes = [
      cls for cls in config_classes if not cls.__name__.startswith("_")
  ]
  filtered_classes.sort(key=lambda cls: cls.__name__)
  return filtered_classes


class DescribeSubcommand(CrossbenchSubcommand):

  PROBE_ALIAS = ("probe", "probes")
  BENCHMARK_ALIAS = ("benchmark", "benchmarks")
  NETWORK_ALIAS = ("network", "networks")
  CONFIG_OBJECT_ALIAS = ("config", "configs", "config-object", "config-objects")
  ENV_ALIAS = ("env", "envs", "environment", "environments")
  CATEGORIES = ("all",) + (
      PROBE_ALIAS + BENCHMARK_ALIAS + NETWORK_ALIAS + CONFIG_OBJECT_ALIAS +
      ENV_ALIAS)

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    self._parser = subparsers.add_parser(
        "describe", aliases=["desc"], help="Print all benchmarks and stories")
    self._parser.set_defaults(crossbench_subcommand=self)
    return self.parser

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    describe_parser = parser
    describe_parser.add_argument(
        "category",
        nargs="?",
        default="all",
        help=("Limit output to the given category, defaults to 'all'. "
              f"Choices: {self.CATEGORIES,}"))
    describe_parser.add_argument(
        "filter",
        nargs="?",
        default=None,
        help=("Only display the given item from the provided category. "
              "By default all items are displayed. "
              "Example: describe probes v8.log"))
    describe_parser.add_argument(
        "--json",
        default=False,
        action="store_true",
        help="Print the data as json data")
    self.cli.add_debugging_arguments(describe_parser)
    return describe_parser

  def probe_names(self) -> list[str]:
    names = [probe_cls.NAME for probe_cls in GENERAL_PURPOSE_PROBES]
    names.sort()
    return names

  def benchmark_names(self) -> list[str]:
    names = [benchmark_cls.NAME for benchmark_cls in self.cli.BENCHMARKS]
    names.sort()
    return names

  def network_names(self) -> list[str]:
    names = [network_type.name for network_type in NetworkType]
    names.sort()
    return names

  def config_classes(self) -> list[type[ConfigObject]]:
    return get_all_config_classes()

  def config_object_names(self) -> list[str]:
    names = [config_cls.__name__ for config_cls in self.config_classes()]
    names.sort()
    return names

  def env_names(self) -> list[str]:
    names = list(ENV_CONFIG_PRESETS.keys())
    names.sort()
    return names

  @override
  def run(self, args: argparse.Namespace) -> None:
    category: str = args.category
    search_term: str | None = args.filter
    if category not in self.CATEGORIES and not search_term:
      search_term = category
      category = "all"
    self.describe(category, search_term, args.json)

  def run_from_help(self, args: argparse.Namespace) -> None:
    search_terms: Sequence[str] = args.search_terms
    category: str = "all"
    search_str: str = ""
    if len(search_terms) == 1:
      search_str = search_terms[0]
    elif len(search_terms) == 2:
      category, search_str = search_terms
    else:
      self.error(f"Invalid help args: {search_terms}")
    self.describe(category, search_str)

  def describe(self,
               category: str,
               search_str: str | None,
               print_json: bool = False) -> None:
    category, search_str = self._process_search_str(category, search_str)

    data: HelpData = self.help_data(category, search_str)
    if print_json:
      self.print_json(category, search_str, data)
      return
    # Create tabular format
    printed_any = False
    if category == "all" or category in self.BENCHMARK_ALIAS:
      printed_any |= self.print_benchmarks(category, search_str, data)
    if category == "all" or category in self.PROBE_ALIAS:
      printed_any |= self.print_probes(category, search_str, data)
    if category == "all" or category in self.NETWORK_ALIAS:
      printed_any |= self.print_networks(category, search_str, data)
    if category == "all" or category in self.CONFIG_OBJECT_ALIAS:
      printed_any |= self.print_config_objects(category, search_str, data)
    if category == "all" or category in self.ENV_ALIAS:
      printed_any |= self.print_envs(category, search_str, data)
    if not printed_any:
      self.no_match_error(search_str)

  def help_data(self, category: str, search_str: str | None) -> HelpData:
    data: HelpData = {
        "benchmarks": {},
        "probes": {},
        "networks": {},
        "config_objects": {},
        "envs": {},
    }
    if category == "all" or category in self.BENCHMARK_ALIAS:
      data["benchmarks"] = self._benchmark_help_data(search_str)
    if category == "all" or category in self.PROBE_ALIAS:
      data["probes"] = self._probe_help_data(search_str)
    if category == "all" or category in self.NETWORK_ALIAS:
      data["networks"] = self._network_help_data(search_str)
    if category == "all" or category in self.CONFIG_OBJECT_ALIAS:
      data["config_objects"] = self._config_object_help_data(search_str)
    if category == "all" or category in self.ENV_ALIAS:
      data["envs"] = self._env_help_data(search_str)
    return data

  def _process_search_str(self, category: str,
                          search_str: str | None) -> tuple[str, str | None]:
    if category not in self.CATEGORIES:
      message, alternative = close_matches_message(category, self.CATEGORIES,
                                                   "help category")
      if not alternative:
        self.error(message)
      else:
        category = alternative
    if not search_str:
      return category, search_str
    search_str = search_str.lower()
    if search_str in self.PROBE_ALIAS:
      category = "probe"
      search_str = None
    elif search_str in self.BENCHMARK_ALIAS:
      category = "benchmark"
      search_str = None
    elif search_str in self.NETWORK_ALIAS:
      category = "network"
      search_str = None
    elif search_str in self.ENV_ALIAS:
      category = "env"
      search_str = None
    return category, search_str

  def print_json(self, category: str, search_str: str | None,
                 data: HelpData) -> None:
    if category in self.PROBE_ALIAS:
      data = data["probes"]
      if not data:
        self.choice_error("No matching probe found:", search_str,
                          self.probe_names())
    elif category in self.BENCHMARK_ALIAS:
      data = data["benchmarks"]
      if not data:
        self.choice_error("No matching benchmark found:", search_str,
                          self.benchmark_names())
    elif category in self.NETWORK_ALIAS:
      data = data["networks"]
      if not data:
        self.choice_error("No matching network found:", search_str,
                          self.network_names())
    elif category in self.CONFIG_OBJECT_ALIAS:
      data = data["config_objects"]
      if not data:
        self.choice_error("No matching config object found:", search_str,
                          self.config_object_names())
    elif category in self.ENV_ALIAS:
      data = data["envs"]
      if not data:
        self.choice_error("No matching env found:", search_str,
                          self.env_names())
    else:
      assert category == "all", f"Got unknown category {category}"
      if not data["benchmarks"] and not data["probes"] and not data[
          "networks"] and not data["config_objects"] and not data["envs"]:
        self.no_match_error(search_str)
    print(json.dumps(data, indent=2))

  def no_match_error(self, search_str: str | None) -> None:
    base_message = ("No matching benchmarks, probes, networks, envs "
                    "or config objects found")
    self.choice_error(base_message, search_str, self.CATEGORIES)

  def choice_error(self, message: str, search_str: str | None,
                   choices: Sequence[str]) -> None:
    if search_str:
      choices_message, alternative = close_matches_message(search_str, choices)
      if alternative:
        self.error(f"{message}: '{search_str}'. {choices_message}")
        return
    choices_str = ", ".join(choices)
    self.error(f"{message}: '{search_str}'. Choices are {choices_str}")

  def print_probes(self, category: str, search_str: str | None,
                   help_data: HelpData) -> bool:
    table: TableData = [["Probe", "Help"]]
    self.format_property_table(help_data["probes"], table)
    return self.print_property_table("Probe", category, search_str, table,
                                     self.probe_names())

  def print_benchmarks(self, category: str, search_str: str | None,
                       data: HelpData) -> bool:
    table: TableData = [["Benchmark", "Property", "Value"]]
    self.format_property_table(data["benchmarks"], table)
    return self.print_property_table("Benchmark", category, search_str, table,
                                     self.benchmark_names())

  def print_networks(self, category: str, search_str: str | None,
                     help_data: HelpData) -> bool:
    table: TableData = [["Network", "Help"]]
    for network_name, network_desc in help_data["networks"].items():
      table.append([network_name, network_desc])
    return self.print_property_table("Network", category, search_str, table,
                                     self.network_names())

  def print_config_objects(self, category: str, search_str: str | None,
                           help_data: HelpData) -> bool:
    table: TableData = [["Config Object", "Property", "Value"]]
    self.format_property_table(help_data["config_objects"], table)
    return self.print_property_table("Config Objects", category, search_str,
                                     table, self.config_object_names())

  def print_envs(self, category: str, search_str: str | None,
                 help_data: HelpData) -> bool:
    table: TableData = [["Env", "Property", "Value"]]
    self.format_property_table(help_data["envs"], table)
    return self.print_property_table("Env", category, search_str, table,
                                     self.env_names())

  def format_property_table(self, data: dict[str, Any],
                            table: TableData) -> None:
    for section_name, values in data.items():
      table.append([section_name])
      for property_name, value in values.items():
        formatted_value = self._format_property_value(value)
        table.append(["", property_name, formatted_value])

  def _format_property_value(self, value: Any, max_width: int = 50) -> str:
    if value is None:
      return ""
    if isinstance(value, str):
      return "\n".join(txt_helper.wrap_lines(value, width=max_width))
    if isinstance(value, (tuple, list)):
      return "\n".join(value)
    if isinstance(value, dict):
      if not value:
        return "[]"
      return tbl.tabulate(
          value.items(), tablefmt="plain", maxcolwidths=max_width)
    return str(value)

  def print_property_table(self, name: str, category: str,
                           search_str: str | None, table: TableData,
                           choices: Sequence[str]) -> bool:
    if len(table) <= 1:
      if category != "all":
        self.choice_error(f"No matching {name} found:", search_str, choices)
      return False
    print(tbl.tabulate(table, tablefmt="fancy_grid"))
    return True

  def _benchmark_help_data(
      self,
      search_str: str | None = None,
  ) -> dict[str, Any]:
    benchmarks_data: dict[str, dict[str, Any]] = {}
    for benchmark_cls in self.cli.BENCHMARKS:
      aliases: tuple[str, ...] = benchmark_cls.aliases()
      if search_str:
        if benchmark_cls.NAME != search_str and search_str not in aliases:
          continue
      benchmark_info = benchmark_cls.describe()
      benchmark_info["help"] = f"See `{benchmark_cls.NAME} --help`"
      benchmarks_data[benchmark_cls.NAME] = benchmark_info
    return benchmarks_data

  def _probe_help_data(self, search_str: str | None) -> dict[str, Any]:
    config_parsers: list[ConfigParser] = [
        probe_cls.config_parser()
        for probe_cls in GENERAL_PURPOSE_PROBES
        if not search_str or probe_cls.NAME == search_str
    ]
    return self._config_parser_help_data(config_parsers)

  def _network_help_data(self, search_str: str | None) -> dict[str, Any]:
    network_data: dict[str, Any] = {
        network_type.name: network_type.help
        for network_type in NetworkType
        if not search_str or network_type.name.lower() == search_str
    }
    # Print config details if any network info is returned.
    if network_data:
      network_data["config"] = NetworkConfig.help()
      network_data["speed"] = NetworkSpeedConfig.help()
    return network_data

  def _env_help_data(self, search_str: str | None) -> dict[str, Any]:
    env_data: dict[str, Any] = {}
    for env_name, env_config in ENV_CONFIG_PRESETS.items():
      if search_str and env_name.lower() != search_str:
        continue
      env_dict = {}
      for field in dataclasses.fields(env_config):
        value = getattr(env_config, field.name)
        if value is not EnvConfig.IGNORE:
          env_dict[field.name] = str(value)
      env_data[env_name] = env_dict
    return env_data

  def _config_object_help_data(
      self, search_str: str | None) -> dict[str, dict[str, Any]]:
    usage_lookup: dict[str, list[str]] = defaultdict(list)
    config_parsers: list[ConfigParser] = []
    for config_object_cls in self.config_classes():
      config_parser: ConfigParser = config_object_cls.config_parser()
      config_parsers.append(config_parser)
      for arg_config_object_cls in config_parser.config_arg_types():
        usage_lookup[arg_config_object_cls.__name__].append(
            config_parser.cls_name)
    config_parsers = [
        parser for parser in config_parsers
        if not search_str or search_str == parser.cls_name.lower()
    ]
    return self._config_parser_help_data(config_parsers, usage_lookup)

  def _config_parser_help_data(
      self,
      config_parsers: list[ConfigParser],
      usage_lookup: Mapping[str, list[str]] | None = None,
  ) -> dict[str, dict[str, Any]]:
    config_data: dict[str, dict[str, Any]] = {}
    for config_parser in config_parsers:
      help_data: dict[str, str] = dict(config_parser.help_text_items)
      if usage_lookup:
        if used_in := usage_lookup[config_parser.cls_name]:
          help_data["used-in"] = ", ".join(used_in)
      config_data[config_parser.key] = help_data
    return config_data
