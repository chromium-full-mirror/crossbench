# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import datetime as dt
import json
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import tabulate as tbl
from typing_extensions import TypeAlias, override

from crossbench import path as pth
from crossbench import plt
from crossbench.benchmarks.base import Benchmark
from crossbench.browsers.settings import Settings
from crossbench.browsers.viewport import Viewport
from crossbench.browsers.webdriver import WebDriverBrowser
from crossbench.cli.config.browser import BrowserConfig
from crossbench.cli.config.browser_variants import BrowserVariantsConfig
from crossbench.cli.config.env import EnvConfig, ValidationMode
from crossbench.cli.config.network import NetworkConfig
from crossbench.cli.parser import CBArgumentParser
from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.flags.base import Flags
from crossbench.helper import collection_helper, txt_helper
from crossbench.probes.perfetto_info import CategoryDescription, \
    PerfettoInfoProbe
from crossbench.runner.runner import Runner
from crossbench.runner.timing import Timing
from crossbench.stories.story import Story

if TYPE_CHECKING:
  import argparse

  from crossbench.browsers.browser import Browser
  from crossbench.cli.cli import CrossBenchCLI
  from crossbench.cli.types import Subparsers
  from crossbench.runner.run import Run
  from crossbench.types import TableData

  Categories: TypeAlias = Sequence[CategoryDescription]


class PerfettoInfoStory(Story):
  """A minimal story to keep the browser alive for querying Perfetto info."""

  @classmethod
  def all_story_names(cls) -> tuple[str, ...]:
    return ("perfetto_info",)

  def __init__(self) -> None:
    super().__init__("perfetto_info", duration=dt.timedelta(seconds=5))

  @override
  def run(self, run: Run) -> None:
    pass


class PerfettoInfoBenchmark(Benchmark):
  """A benchmark to run the PerfettoInfoStory with the PerfettoInfoProbe."""
  NAME = "perfetto_info"
  DEFAULT_STORY_CLS = PerfettoInfoStory

  def __init__(self) -> None:
    super().__init__([PerfettoInfoStory()])


class PerfettoCrossbenchSubcommand(CrossbenchSubcommand):

  def __init__(self, cli: CrossBenchCLI) -> None:
    super().__init__(cli)

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    self._parser = subparsers.add_parser(
        "perfetto", help="Perfetto related utilities")
    self._parser.set_defaults(crossbench_subcommand=self)

    self._subparsers = self.parser.add_subparsers(
        title="Perfetto Actions",
        parser_class=CBArgumentParser,
        dest="perfetto_action",
        required=True)
    self._categories_subcommand = PerfettoCategoriesSubcommand(self)
    self._data_sources_subcommand = PerfettoDataSourcesSubcommand(self)
    return self.parser

  @property
  def subparsers(self) -> Any:
    return self._subparsers

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    args.perfetto_subcommand.run(args)


class PerfettoBaseSubcommand(abc.ABC):

  def __init__(self, parent: PerfettoCrossbenchSubcommand) -> None:
    self._parent = parent
    self._parser = self.add_cli_parser()
    self._parser.set_defaults(perfetto_subcommand=self)

  def add_query_arguments(self, parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--browser",
        "-b",
        type=BrowserConfig.parse,
        default="chrome-stable",
        help="Browser configuration. Defaults to 'chrome-stable'.")
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format (json, table). Defaults to 'json'.")
    self.cli.add_debugging_arguments(parser)

  @property
  def parent(self) -> PerfettoCrossbenchSubcommand:
    return self._parent

  @property
  def cli(self) -> CrossBenchCLI:
    return self.parent.cli

  def error(self, message: str) -> None:
    self.parent.error(message)

  def fail(self, message: str) -> None:
    self.parent.fail(message)

  @abc.abstractmethod
  def add_cli_parser(self) -> argparse.ArgumentParser:
    pass

  def run(self, args: argparse.Namespace) -> None:
    browser_config: BrowserConfig = BrowserConfig.parse(args.browser)
    with self.cli.silenced_logging(capture_stderr=args.verbosity == 0):
      browser = self._get_browser(browser_config)
      categories = self._extract_perfetto_categories(browser)
    self.subcommand_run(args, categories, browser.unique_name)

  def _get_browser(self, browser_config: BrowserConfig) -> Browser:
    driver_path = None
    if driver_config := browser_config.driver:
      driver_path = driver_config.path

    browser_cls = BrowserVariantsConfig.get_browser_cls(browser_config)
    if not issubclass(browser_cls, WebDriverBrowser):
      self.error("Only webdriver-based browsers are supported, "
                 f"but got {browser_cls.type_name}")

    settings = Settings(
        cache_dir=browser_config.cache_dir,
        flags=browser_cls.default_flags(Flags()),
        network=NetworkConfig.default().create_network(
            browser_config.get_platform()),
        platform=browser_config.get_platform(),
        env_config=EnvConfig(),
        viewport=Viewport.HEADLESS,
        driver_path=driver_path)

    browser = browser_cls("browser", browser_config.path, settings)
    # WebDriver runs on the host platform and writes logs locally.
    browser.set_log_file(pth.LocalPath("perfetto_query.log"))
    browser.validate()
    return browser

  def _extract_perfetto_categories(self, browser: Browser) -> Categories:
    benchmark = PerfettoInfoBenchmark()
    perfetto_info_probe = PerfettoInfoProbe()
    with plt.PLATFORM.TemporaryDirectory(prefix="crossbench") as tmp_dir:
      out_dir = pth.LocalPath(tmp_dir) / "results"
      runner = Runner(
          out_dir=out_dir,
          browsers=(browser,),
          benchmark=benchmark,
          probes=(perfetto_info_probe,),
          env_validation_mode=ValidationMode.SKIP,
          timing=Timing(cool_down_time=dt.timedelta(seconds=0)),
          create_symlinks=False,
          throw=True,
      )
      runner.run()

      probe_result = runner.first_run.results[perfetto_info_probe]
      json_path = probe_result.json
      raw_data = json.loads(json_path.read_text(encoding="utf-8"))
      return [CategoryDescription.parse(cat) for cat in raw_data]

  @abc.abstractmethod
  def subcommand_run(self, args: argparse.Namespace, categories: Categories,
                     browser_name: str) -> None:
    pass

  def print_table(self, title: str, header_row: list[str],
                  data: TableData) -> None:
    print(f"\n{title}:")
    table: TableData = [header_row, *data]
    print(tbl.tabulate(table, headers="firstrow", tablefmt="fancy_grid"))


class PerfettoCategoriesSubcommand(PerfettoBaseSubcommand):

  @override
  def add_cli_parser(self) -> argparse.ArgumentParser:
    categories_parser = self.parent.subparsers.add_parser(
        "categories",
        aliases=["cats"],
        help="List available trace categories from a browser / os")
    self.add_query_arguments(categories_parser)
    return categories_parser

  @override
  def subcommand_run(self, args: argparse.Namespace, categories: Categories,
                     browser_name: str) -> None:
    categories = [cat for cat in categories if cat.name]
    if args.format == "table":
      self.print_categories_table(browser_name, categories)
    else:
      self.print_categories_json(categories)

  def print_categories_table(self, browser_name: str,
                             categories: list[CategoryDescription]) -> None:
    header = ["Data Source", "Name", "Description", "Tags"]
    data: TableData = []
    for category in categories:
      description = category.description
      if description:
        description = "\n".join(txt_helper.wrap_lines(description, width=60))
      tags = "\n".join(category.tags)
      data.append([category.data_source, category.name, description, tags])
    self.print_table(f"Categories for {browser_name}", header, data)

  def print_categories_json(self,
                            categories: list[CategoryDescription]) -> None:
    print(json.dumps([cat.as_dict() for cat in categories], indent=2))


class PerfettoDataSourcesSubcommand(PerfettoBaseSubcommand):

  @override
  def add_cli_parser(self) -> argparse.ArgumentParser:
    data_sources_parser = self.parent.subparsers.add_parser(
        "data_sources",
        aliases=["sources", "ds"],
        help=("List available Perfetto data sources from "
              "a browser and their categories"))
    self.add_query_arguments(data_sources_parser)
    return data_sources_parser

  @override
  def subcommand_run(self, args: argparse.Namespace, categories: Categories,
                     browser_name: str) -> None:
    data_sources = collection_helper.group_by(
        categories,
        key=lambda cat: cat.data_source,
        value=lambda cat: cat,
        sort_key=str)

    # Filter out empty-name category placeholders and sort
    for ds, cats in data_sources.items():
      data_sources[ds] = [cat for cat in cats if cat.name]
      data_sources[ds].sort(key=lambda cat: cat.name)

    if args.format == "table":
      self.print_data_sources_table(browser_name, data_sources)
    else:
      self.print_data_sources_json(data_sources)

  def print_data_sources_json(
      self, data_sources: Mapping[str, Sequence[CategoryDescription]]) -> None:
    out = {
        data_source_name: [cat.as_dict() for cat in cats]
        for data_source_name, cats in data_sources.items()
    }
    print(json.dumps(out, indent=2))

  def print_data_sources_table(
      self, browser_name: str,
      data_sources: Mapping[str, Sequence[CategoryDescription]]) -> None:
    header = ["Data Source", "Categories Count", "Categories"]
    data: TableData = []
    for data_source, categories in sorted(data_sources.items()):
      count = len(categories)
      categories_str = ", ".join(category.name for category in categories)
      if count > 5:
        categories_str = "\n".join(
            txt_helper.wrap_lines(categories_str, width=60))
      data.append([data_source, str(count), categories_str or "-"])
    self.print_table(f"Data Sources for {browser_name}", header, data)
