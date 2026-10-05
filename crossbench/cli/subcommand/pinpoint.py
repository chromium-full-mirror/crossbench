# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Final, final

from typing_extensions import override

from crossbench.cli.parser import CBArgumentParser
from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.parse import NumberParser, PathParser
from crossbench.pinpoint.benchmarks import pinpoint_benchmark_name
from crossbench.pinpoint.cancel_job import cancel_jobs
from crossbench.pinpoint.config import PinpointBisectJobConfig, \
    PinpointTryJobConfig
from crossbench.pinpoint.job_config import print_job_config
from crossbench.pinpoint.job_info import UrlSource
from crossbench.pinpoint.job_parser import parse_job_id, parse_job_ids
from crossbench.pinpoint.job_results import download_results
from crossbench.pinpoint.list_benchmarks import fetch_benchmarks
from crossbench.pinpoint.list_bots import fetch_bots
from crossbench.pinpoint.list_builds import list_builds
from crossbench.pinpoint.list_format import ListFormatEnum
from crossbench.pinpoint.list_jobs import EXTRA_COLUMNS, list_jobs
from crossbench.pinpoint.list_stories import fetch_stories
from crossbench.pinpoint.start_job import bisect_job, start_job
from crossbench.pinpoint.user import UserEnum, list_user
from crossbench.pinpoint.user_metrics import collect_metrics, init_metrics

_BUG_REPORT_URL: Final[str] = (
    "https://issues.chromium.org/issues/new?component=1456889")
_BUG_EPILOG: Final[str] = f"File bugs at {_BUG_REPORT_URL}"
_JOB_ID_HELP: Final[str] = (
    "The IDs of the jobs. Can be full URLs, parts of URLs with job IDs, "
    "or just the IDs. Accepts multiple values and comma-separated lists.")

if TYPE_CHECKING:
  from crossbench.cli.cli import BenchmarkClass, CrossBenchCLI
  from crossbench.cli.types import Subparsers


class PinpointBaseSubcommand(abc.ABC):

  def __init__(self, parent: PinpointSubcommand) -> None:
    self._parent = parent
    self._parser = self.add_cli_arguments()
    self._parser.set_defaults(pinpoint_subcommand=self)
    if epilog := self._parser.epilog:
      self._parser.epilog = f"{epilog.rstrip()}\n\n{_BUG_EPILOG}\n"
    else:
      self._parser.epilog = _BUG_EPILOG

  def add_url_source_argument(self, parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--url-source",
        type=UrlSource,
        choices=UrlSource.all(),
        default=UrlSource.LESZEK_PERF,
        help=("The URL source for shortened Pinpoint job links. "
              f"(default: {UrlSource.LESZEK_PERF})"))

  @abc.abstractmethod
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    pass

  @final
  def run(self, args: argparse.Namespace) -> None:
    init_metrics()
    with ThreadPoolExecutor() as executor:
      [
          f.result() for f in [
              executor.submit(self.subcommand_run, args),
              executor.submit(collect_metrics, args.action),
          ]
      ]

  @abc.abstractmethod
  def subcommand_run(self, args: argparse.Namespace) -> None:
    pass


class PinpointListSubcommand(PinpointBaseSubcommand):
  """A subcommand for interacting with the Pinpoint service."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    list_parser = self._parent.subparsers.add_parser(
        "list",
        aliases=("ls",),
        help="Displays recent Pinpoint jobs.",
        formatter_class=argparse.RawTextHelpFormatter)
    list_parser.add_argument(
        "--user",
        "-u",
        type=list_user,
        default=UserEnum.ME,
        help=("Filter jobs by user. 'me' (default) shows jobs for your "
              "@google.com and @chromium.org accounts, derived from your "
              "authenticated username. 'all' shows jobs from all users. "
              "An email address can also be specified. Note: 'me' might not "
              "work correctly if your usernames differ across domains."))
    list_parser.add_argument(
        "--number",
        "-n",
        type=NumberParser.positive_int,
        default=20,
        help="The maximum number of jobs to fetch and display. (default: 20)")
    list_parser.add_argument(
        "--format",
        "-f",
        choices=[
            ListFormatEnum.TABLE,
            ListFormatEnum.JSON,
            ListFormatEnum.YAML,
            ListFormatEnum.CSV,
            ListFormatEnum.TSV,
        ],
        default=ListFormatEnum.TABLE,
        help="The output format for the list of jobs. (default: table)")
    list_parser.add_argument(
        "--truncate",
        "-t",
        type=NumberParser.positive_int,
        default=None,
        help=("Truncate cell content to the specified maximum length. "
              "Only applies to the 'table' format."))
    extra_columns_help = (
        "Additional columns to display in the list of jobs. Can be specified "
        "multiple times. Example:\n"
        "./cb.py pp ls -c=story -c=bug\n"
        "Supported columns:\n" +
        "\n".join(f"  {c.name}: {c.description}" for c in EXTRA_COLUMNS))
    list_parser.add_argument(
        "--extra-columns",
        "-c",
        nargs="*",
        action="extend",
        choices=[c.name for c in EXTRA_COLUMNS],
        help=extra_columns_help)
    list_parser.add_argument(
        "--details",
        dest="extra_columns",
        action="store_const",
        const=[column.name for column in EXTRA_COLUMNS],
        help="Shortcut to include all extra columns in the output")
    self.add_url_source_argument(list_parser)
    return list_parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    list_jobs(
        user=args.user,
        number=args.number,
        truncate=args.truncate,
        output_format=args.format,
        extra_columns=args.extra_columns,
        url_source=args.url_source,
    )


class PinpointJobSubcommand(PinpointBaseSubcommand):
  """Base class for subcommands that operate on a Pinpoint job."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    parser = self.create_parser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "job_pos",
        nargs="?",
        type=parse_job_id,
        help="The ID of the job as a positional argument. Can be a full URL, a "
        "part of a URL with a job ID, or just the ID.")
    group.add_argument(
        "--job",
        type=parse_job_id,
        help="The ID of the job. Can be a full URL, a part of a URL with a job "
        "ID, or just the ID.")
    return parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    self.job_subcommand_run(args.job_pos or args.job, args)

  @abc.abstractmethod
  def job_subcommand_run(self, job_id: str, args: argparse.Namespace) -> None:
    pass

  @abc.abstractmethod
  def create_parser(self) -> argparse.ArgumentParser:
    raise NotImplementedError


class PinpointConfigSubcommand(PinpointJobSubcommand):
  """Get the configuration of a specific Pinpoint job."""

  @override
  def create_parser(self) -> argparse.ArgumentParser:
    config_parser = self._parent.subparsers.add_parser(
        "config",
        aliases=("cfg",),
        help="Get the configuration of a specific Pinpoint job.")
    config_parser.add_argument(
        "--raw",
        action="store_true",
        help="Display the job configuration as raw JSON response from the "
        "server.")
    config_parser.add_argument(
        "--full",
        action="store_true",
        help="Display the full job configuration including all attempts. "
        "Works only if the `--raw` flag is set.")
    return config_parser

  @override
  def job_subcommand_run(self, job_id: str, args: argparse.Namespace) -> None:
    print_job_config(job_id=job_id, raw=args.raw, full=args.full)


class PinpointBaseStartSubcommand(PinpointBaseSubcommand):
  """Base class for subcommands that start a new Pinpoint job."""

  def create_parser(self,
                    command: str,
                    aliases: tuple[str, ...] = (),
                    help_text: str | None = None) -> argparse.ArgumentParser:
    start_parser = self._parent.subparsers.add_parser(
        command,
        aliases=aliases,
        help=help_text,
        description="Starts a new Pinpoint A/B job. "
        "This command allows you to specify two configurations (base and "
        "experiment) to compare performance between them.",
        formatter_class=argparse.RawTextHelpFormatter)
    start_parser.add_argument(
        "--config",
        help="A/B job configuration in the JSON/HJSON format. "
        "Accepts a path to a configuration file, or configuration string. "
        "If the same argument is specified in the config and then provided "
        "as a command line argument, the latter overrides the former. "
        "Get more information by running `describe PinpointTryJobConfig`")
    self.add_benchmark_flag(start_parser)
    start_parser.add_argument(
        "--bot", help="The bot configuration to run on (e.g., 'linux-perf').")
    start_parser.add_argument("--story", help="The story to run.")
    start_parser.add_argument(
        "--story-tags", dest="story_tags", help="Story tags to filter stories.")
    start_parser.add_argument(
        "--repeat",
        type=NumberParser.positive_int,
        help="How many times to repeat the experiment.")
    start_parser.add_argument(
        "--bug",
        "--bug-id",
        type=NumberParser.positive_int,
        help="The bug ID to associate with the job.")
    start_parser.add_argument(
        "--commit",
        help="Git commit hash for both base and experiment builds. "
        "Accepts a commit hash, 'HEAD' (latest commit), or 'recent' "
        "(the most recent build). Defaults to 'recent'. "
        "Can be overridden by --base-commit or --exp-commit.")
    start_parser.add_argument(
        "--base-commit",
        help="Git commit hash for the base build. Accepts a commit hash, "
        "'HEAD' (latest commit), or 'recent' (the most recent build). "
        "Overrides '--commit' for the base build.")
    start_parser.add_argument(
        "--exp-commit",
        help="Git commit hash for the experiment build. Accepts a commit hash, "
        "'HEAD' (latest commit), or 'recent' (the most recent build)."
        "Overrides '--commit' for the experiment build.")
    start_parser.add_argument(
        "--base-patch",
        "--base-patch-url",
        help="Gerrit patch to apply to the base commit. Supported formats: "
        "'12345' (optional patchset: '12345/6'), 'c/12345', "
        "'crrev/c/12345', 'crrev/12345', 'crrev.com/c/12345', "
        "'crrev.com/12345', or a full URL. "
        "Note: All patches must be for chromium-review; "
        "chrome-internal-review is not supported.")
    start_parser.add_argument(
        "--exp-patch",
        "--patch",
        "--exp-patch-url",
        "--patch-url",
        help="Gerrit patch to apply to the experiment commit. Supported "
        "formats: '12345' (optional patchset: '12345/6'), 'c/12345', "
        "'crrev/c/12345', 'crrev/12345', 'crrev.com/c/12345', "
        "'crrev.com/12345', or a full URL. "
        "Note: All patches must be for chromium-review; "
        "chrome-internal-review is not supported.")

    # Extra browser args.
    start_parser.add_argument(
        "--flags",
        "--browser-flags",
        help="Chrome flags to pass to both base and experiment commits. "
        "Can be overridden by --base-flags or --exp-flags.\n"
        "Example: --flags=--no-sandbox")
    start_parser.add_argument(
        "--base-flags",
        "--base-browser-flags",
        help="Chrome flags to pass for the base commit.\n"
        "Example: --base-flags=--no-sandbox")
    start_parser.add_argument(
        "--exp-flags",
        "--exp-browser-flags",
        help="Chrome flags to pass for the experiment commit.\n"
        "Example: --exp-flags=--no-sandbox")
    start_parser.add_argument(
        "--js-flags",
        help="JavaScript flags to pass to V8 for both base and experiment "
        "commits. Can be overridden by --base-js-flags or --exp-js-flags.\n"
        "Example: --js-flags=--turbolev-future")
    start_parser.add_argument(
        "--base-js-flags",
        help="JavaScript flags to pass to V8 for the base commit.\n"
        "Example: --base-js-flags=--turbolev-future")
    start_parser.add_argument(
        "--exp-js-flags",
        help="JavaScript flags to pass to V8 for the experiment commit.\n"
        "Example: --exp-js-flags=--turbolev-future")
    start_parser.add_argument(
        "--enable-features",
        help="Chrome features to enable for both base and experiment commits. "
        "Can be overridden by --base-enable-features or --exp-enable-features."
        "\nExample: --enable-features=Feature1,Feature2")
    start_parser.add_argument(
        "--base-enable-features",
        help="Comma-separated list of Chrome features to enable for the base "
        "commit.\nExample: --base-enable-features=Feature1,Feature2")
    start_parser.add_argument(
        "--exp-enable-features",
        help="Comma-separated list of Chrome features to enable for the "
        "experiment commit.\nExample: --exp-enable-features=FeatureA,FeatureB")
    start_parser.add_argument(
        "--disable-features",
        help="Chrome features to disable for both base and experiment "
        "commits. Can be overridden by --base-disable-features or "
        "--exp-disable-features.\n"
        "Example: --disable-features=Feature1,Feature2",
    )
    start_parser.add_argument(
        "--base-disable-features",
        help="Comma-separated list of Chrome features to disable for the base "
        "commit.\nExample: --base-disable-features=Feature1,Feature2")
    start_parser.add_argument(
        "--exp-disable-features",
        help="Comma-separated list of Chrome features to disable for the "
        "experiment commit.\nExample: --exp-disable-features=FeatureA,FeatureB")
    start_parser.add_argument(
        "--enable-blink-features",
        "--blink-features",
        help="Blink features to enable for both base and experiment commits. "
        "Can be overridden by --base-blink-features or --exp-blink-features.\n"
        "Example: --enable-blink-features=Feature1,Feature2")
    start_parser.add_argument(
        "--base-blink-features",
        "--base-enable-blink-features",
        dest="base_enable_blink_features",
        help="Comma-separated list of Blink features to enable for the base "
        "commit.\nExample: --base-blink-features=Feature1,Feature2")
    start_parser.add_argument(
        "--exp-blink-features",
        "--exp-enable-blink-features",
        dest="exp_enable_blink_features",
        help="Comma-separated list of Blink features to enable for the "
        "experiment commit.\nExample: --exp-blink-features=FeatureA,FeatureB")
    start_parser.add_argument(
        "--disable-blink-features",
        help="Blink features to disable for both base and experiment commits. "
        "Can be overridden by --base-disable-blink-features or "
        "--exp-disable-blink-features.\n"
        "Example: --disable-blink-features=Feature1,Feature2")
    start_parser.add_argument(
        "--base-disable-blink-features",
        help="Comma-separated list of Blink features to disable for the base "
        "commit.\nExample: --base-disable-blink-features=Feature1,Feature2")
    start_parser.add_argument(
        "--exp-disable-blink-features",
        help="Comma-separated list of Blink features to disable for the "
        "experiment commit.\n"
        "Example: --exp-disable-blink-features=FeatureA,FeatureB")
    self.add_url_source_argument(start_parser)

    return start_parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    config = PinpointTryJobConfig.parse_and_override(
        config=args.config,
        benchmark=self.get_benchmark(args),
        bot=args.bot,
        story=args.story,
        story_tags=args.story_tags,
        repeat=args.repeat,
        bug=args.bug,
        base_commit=args.base_commit or args.commit,
        exp_commit=args.exp_commit or args.commit,
        base_patch=args.base_patch,
        exp_patch=args.exp_patch,
        base_flags=args.base_flags or args.flags,
        exp_flags=args.exp_flags or args.flags,
        base_js_flags=args.base_js_flags or args.js_flags,
        exp_js_flags=args.exp_js_flags or args.js_flags,
        base_enable_features=args.base_enable_features or args.enable_features,
        exp_enable_features=args.exp_enable_features or args.enable_features,
        base_disable_features=args.base_disable_features or
        args.disable_features,
        exp_disable_features=args.exp_disable_features or args.disable_features,
        base_enable_blink_features=args.base_enable_blink_features or
        args.enable_blink_features,
        exp_enable_blink_features=args.exp_enable_blink_features or
        args.enable_blink_features,
        base_disable_blink_features=args.base_disable_blink_features or
        args.disable_blink_features,
        exp_disable_blink_features=args.exp_disable_blink_features or
        args.disable_blink_features,
    )
    start_job(config, url_source=args.url_source)

  def add_benchmark_flag(self, parser: argparse.ArgumentParser) -> None:
    pass

  @abc.abstractmethod
  def get_benchmark(self, args: argparse.Namespace) -> str | None:
    pass


class PinpointStartSubcommand(PinpointBaseStartSubcommand):
  """Starts a new Pinpoint A/B job."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    start_parser = self.create_parser(
        "start", help_text="Starts a new Pinpoint A/B job.")
    start_parser.epilog = """Example:
  pinpoint start \\
    --config=config.json \\
    --benchmark=speedometer3.crossbench \\
    --bot=linux-r350-perf \\
    --story=default \\
    --story-tags=mobile,desktop \\
    --repeat=20 \\
    --bug-id=123456 \\
    --base-commit=HEAD \\
    --exp-commit=recent \\
    --base-patch-url=https://chromium-review.googlesource.com/c/v8/v8/+/12345 \\
    --exp-patch-url=https://chromium-review.googlesource.com/c/v8/v8/+/67890 \\
    --flags=--no-sandbox \\
    --base-js-flags=--flag1,--flag2 \\
    --exp-js-flags=--flag3,--flag4 \\
    --base-enable-features=feature1,feature2 \\
    --exp-enable-features=feature3,feature4 \\
    --base-disable-features=feature5,feature6 \\
    --exp-disable-features=feature7,feature8
"""
    return start_parser

  @override
  def add_benchmark_flag(self, parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--benchmark", help="The benchmark to run.")

  @override
  def get_benchmark(self, args: argparse.Namespace) -> str | None:
    return args.benchmark


class PinpointBisectSubcommand(PinpointBaseSubcommand):
  """Starts a new Pinpoint bisect job."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    parser = self._parent.subparsers.add_parser(
        "bisect",
        help="Starts a new Pinpoint bisect job.",
        description="Starts a new Pinpoint bisect job. "
        "This command allows you to specify a start and end commit "
        "to bisect a performance regression.",
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--config",
        help="Bisect job configuration in the JSON/HJSON format. "
        "Accepts a path to a configuration file, or configuration string. "
        "If the same argument is specified in the config and then provided "
        "as a command line argument, the latter overrides the former. "
        "Get more information by running `describe PinpointBisectJobConfig`")
    parser.add_argument("--benchmark", help="The benchmark to run.")
    parser.add_argument(
        "--bot", help="The bot configuration to run on (e.g., 'linux-perf').")
    parser.add_argument("--chart", help="The chart (measurement) to bisect.")
    parser.add_argument("--story", help="The story to run.")
    parser.add_argument(
        "--story-tags", dest="story_tags", help="Story tags to filter stories.")
    parser.add_argument(
        "--repeat",
        type=NumberParser.positive_int,
        help="How many times to repeat the experiment.")
    parser.add_argument(
        "--bug",
        "--bug-id",
        type=NumberParser.positive_int,
        help="The bug ID to associate with the job.")
    parser.add_argument(
        "--start-commit",
        help="Git commit hash for the start build. Accepts a commit hash, "
        "'HEAD' (latest commit), or 'recent' (the most recent build).")
    parser.add_argument(
        "--end-commit",
        help="Git commit hash for the end build. Accepts a commit hash, "
        "'HEAD' (latest commit), or 'recent' (the most recent build).")

    # Extra browser args.
    parser.add_argument(
        "--flags",
        "--browser-flags",
        help="Chrome flags to pass.\n"
        "Example: --flags=--no-sandbox")
    parser.add_argument(
        "--js-flags",
        help="JavaScript flags to pass to V8.\n"
        "Example: --js-flags=--turbolev-future")
    parser.add_argument(
        "--enable-features",
        help="Chrome features to enable.\n"
        "Example: --enable-features=Feature1,Feature2")
    parser.add_argument(
        "--disable-features",
        help="Chrome features to disable.\n"
        "Example: --disable-features=Feature1,Feature2")
    parser.add_argument(
        "--enable-blink-features",
        "--blink-features",
        help="Blink features to enable.\n"
        "Example: --enable-blink-features=Feature1,Feature2")
    parser.add_argument(
        "--disable-blink-features",
        help="Blink features to disable.\n"
        "Example: --disable-blink-features=Feature1,Feature2")
    self.add_url_source_argument(parser)

    parser.epilog = """Example:
  pinpoint bisect \\
    --config=config.json \\
    --benchmark=speedometer3.crossbench \\
    --bot=linux-r350-perf \\
    --chart=chart_name \\
    --story=default \\
    --story-tags=mobile,desktop \\
    --repeat=20 \\
    --bug-id=123456 \\
    --start-commit=HEAD \\
    --end-commit=recent \\
    --flags=--no-sandbox \\
    --js-flags=--flag1,--flag2 \\
    --enable-features=feature1,feature2 \\
    --disable-features=feature5,feature6
"""
    return parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    config = PinpointBisectJobConfig.parse_and_override(
        config=args.config,
        benchmark=args.benchmark,
        bot=args.bot,
        chart=args.chart,
        story=args.story,
        story_tags=args.story_tags,
        repeat=args.repeat,
        bug=args.bug,
        start_commit=args.start_commit,
        end_commit=args.end_commit,
        flags=args.flags,
        js_flags=args.js_flags,
        enable_features=args.enable_features,
        disable_features=args.disable_features,
        enable_blink_features=args.enable_blink_features,
        disable_blink_features=args.disable_blink_features,
    )
    bisect_job(config, url_source=args.url_source)


class PinpointBenchmarkSubcommand(PinpointBaseStartSubcommand):
  """Starts a new Pinpoint A/B job for a given benchmark."""

  def __init__(self, parent: PinpointSubcommand,
               benchmark_cls: BenchmarkClass) -> None:
    self._benchmark_cls = benchmark_cls
    super().__init__(parent)

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    benchmark_name = pinpoint_benchmark_name(self._benchmark_cls.NAME)
    assert benchmark_name, "Must be a valid pinpoint benchmark name"
    start_parser = self.create_parser(
        command=self._benchmark_cls.NAME,
        aliases=self._benchmark_cls.aliases(),
        help_text=f'Starts a new "{benchmark_name}" Pinpoint A/B job.')
    start_parser.epilog = (
        f"Example:\npinpoint {self._benchmark_cls.NAME} --bot win-11-perf\n\n")
    return start_parser

  @override
  def get_benchmark(self, args: argparse.Namespace) -> str | None:
    return pinpoint_benchmark_name(self._benchmark_cls.NAME)


class PinpointCancelSubcommand(PinpointBaseSubcommand):
  """Cancel Pinpoint jobs."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    cancel_parser = self._parent.subparsers.add_parser(
        "cancel", help="Cancel Pinpoint jobs.")
    cancel_parser.add_argument(
        "job_pos", nargs="*", default=None, help=_JOB_ID_HELP)
    cancel_parser.add_argument(
        "--job", nargs="+", action="extend", default=None, help=_JOB_ID_HELP)
    cancel_parser.add_argument(
        "--reason",
        required=False,
        default="Cancelled via Pinpoint CLI.",
        help="Reason for cancellation.")
    return cancel_parser

  def _get_job_ids(self, args: argparse.Namespace) -> list[str]:
    job_pos = args.job_pos
    job_flag = args.job
    if bool(job_pos) == bool(job_flag):
      if job_pos and job_flag:
        self._parser.error("Cannot specify both positional job IDs and --job.")
      self._parser.error("Missing job ID(s).")
    raw_jobs = job_pos if job_pos else job_flag
    try:
      return parse_job_ids(raw_jobs)
    except argparse.ArgumentTypeError as e:
      self._parser.error(str(e))

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    job_ids = self._get_job_ids(args)
    cancel_jobs(job_ids=job_ids, reason=args.reason)


class PinpointBaseFilteredListSubcommand(PinpointBaseSubcommand):
  """Base subcommand class for displaying filtered string lists."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    parser = self.create_parser()
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help=("Filter results by a case-insensitive substring match. "
              "Only items containing the filter string will be shown."))
    return parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    items = self.fetch_list(args)
    filter_str = (args.filter or "").lower().strip()
    filtered_items = [item for item in items if filter_str in item.lower()]
    print("\n".join(filtered_items))

  @abc.abstractmethod
  def create_parser(self) -> argparse.ArgumentParser:
    pass

  @abc.abstractmethod
  def fetch_list(self, args: argparse.Namespace) -> list[str]:
    pass


class PinpointBotsSubcommand(PinpointBaseFilteredListSubcommand):
  """A subcommand for displaying available Pinpoint bots."""

  @override
  def create_parser(self) -> argparse.ArgumentParser:
    bots_parser = self._parent.subparsers.add_parser(
        "bots", help="Displays all available Pinpoint bots.")
    return bots_parser

  @override
  def fetch_list(self, args: argparse.Namespace) -> list[str]:
    return fetch_bots()


class PinpointBenchmarksSubcommand(PinpointBaseFilteredListSubcommand):
  """A subcommand for displaying available Pinpoint benchmarks."""

  @override
  def create_parser(self) -> argparse.ArgumentParser:
    benchmarks_parser = self._parent.subparsers.add_parser(
        "benchmarks", help="Displays all available Pinpoint benchmarks.")
    return benchmarks_parser

  @override
  def fetch_list(self, args: argparse.Namespace) -> list[str]:
    return fetch_benchmarks()


class PinpointStoriesSubcommand(PinpointBaseFilteredListSubcommand):
  """A subcommand for displaying available stories for a Pinpoint benchmark."""

  @override
  def create_parser(self) -> argparse.ArgumentParser:
    stories_parser = self._parent.subparsers.add_parser(
        "stories",
        help="Displays all available stories for a Pinpoint benchmark.")
    stories_parser.add_argument(
        "benchmark", help="The benchmark for which to list stories.")
    return stories_parser

  @override
  def fetch_list(self, args: argparse.Namespace) -> list[str]:
    return fetch_stories(args.benchmark)


class PinpointBuildsSubcommand(PinpointBaseSubcommand):
  """Displays recent successful builds for a given bot."""

  @override
  def add_cli_arguments(self) -> argparse.ArgumentParser:
    builds_parser = self._parent.subparsers.add_parser(
        "builds", help="Displays recent successful builds for a given bot.")
    builds_parser.add_argument(
        "bot", help="The bot configuration name (e.g., 'linux-r350-perf').")
    builds_parser.add_argument(
        "--limit",
        "-l",
        type=NumberParser.positive_int,
        default=10,
        help="Limits the number of recent builds to display. (default: 10)")
    return builds_parser

  @override
  def subcommand_run(self, args: argparse.Namespace) -> None:
    list_builds(args.bot, args.limit)


class PinpointResultsSubcommand(PinpointJobSubcommand):
  """Downloads results of a Pinpoint job."""

  @override
  def create_parser(self) -> argparse.ArgumentParser:
    results_parser = self._parent.subparsers.add_parser(
        "results", help="Downloads results of the given Pinpoint job.")
    results_parser.add_argument(
        "--output-directory",
        "--out-dir",
        "-o",
        type=PathParser.path,
        help=("Results will be stored in this directory. "
              "Defaults to the crossbench results directory by default."))
    results_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help=("Force download even if the output directory already exists."))
    return results_parser

  @override
  def job_subcommand_run(self, job_id: str, args: argparse.Namespace) -> None:
    download_results(
        job_id=job_id, out_dir=args.output_directory, force=args.force)


class PinpointHelpFormatter(argparse.HelpFormatter):
  """Hacks HelpFormatter for displaying a pretty Pinpoint help message."""

  @override
  def _format_action(self,
                     action: argparse.Action,
                     custom_format: bool = True) -> str:
    if not custom_format or not hasattr(action, "_get_subactions"):
      return super()._format_action(action)

    subactions = action._get_subactions()  # noqa: SLF001
    assert subactions, "Missing subactions"

    pinpoint_parts = []
    benchmark_parts = []
    for subaction in subactions:
      text = self._format_action(subaction, custom_format=False)
      if pinpoint_benchmark_name(subaction.dest):
        benchmark_parts.append(text)
      else:
        pinpoint_parts.append(text)

    return "\n".join([
        "".join(pinpoint_parts),
        "\nBenchmarks:",
        "".join(benchmark_parts),
    ])


class PinpointSubcommand(CrossbenchSubcommand):
  """A subcommand for interacting with the Pinpoint service."""

  def __init__(self, cli: CrossBenchCLI) -> None:
    super().__init__(cli)

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    self._parser = subparsers.add_parser(
        "pinpoint",
        aliases=("pp",),
        help="Interact with the Pinpoint service.",
        epilog=_BUG_EPILOG,
        formatter_class=PinpointHelpFormatter)
    self._parser.set_defaults(crossbench_subcommand=self)

    self._subparsers = self.parser.add_subparsers(
        parser_class=CBArgumentParser,
        dest="action",
        required=True,
        help="Pinpoint actions")
    self._list_subcommand = PinpointListSubcommand(self)
    self._config_subcommand = PinpointConfigSubcommand(self)
    self._start_subcommand = PinpointStartSubcommand(self)
    self._bisect_subcommand = PinpointBisectSubcommand(self)
    self._cancel_subcommand = PinpointCancelSubcommand(self)
    self._bots_subcommand = PinpointBotsSubcommand(self)
    self._benchmarks_subcommand = PinpointBenchmarksSubcommand(self)
    self._stories_subcommand = PinpointStoriesSubcommand(self)
    self._builds_subcommand = PinpointBuildsSubcommand(self)
    self._results_subcommand = PinpointResultsSubcommand(self)
    self._benchmark_subcommands: list[PinpointBenchmarkSubcommand] = []
    for benchmark_cls in self.cli.BENCHMARKS:
      if pinpoint_benchmark_name(benchmark_cls.NAME):
        self._benchmark_subcommands.append(
            PinpointBenchmarkSubcommand(self, benchmark_cls))
    return self.parser

  @property
  def subparsers(self) -> Subparsers:
    return self._subparsers

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    args.pinpoint_subcommand.run(args)
