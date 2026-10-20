# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Merges the BITS trace of each run with the device's Perfetto trace, see
crossbench.probes.bits.merge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.parse import PathParser
from crossbench.probes.bits import merge as bits_merge
from crossbench.uploader import results_uploader

if TYPE_CHECKING:
  import argparse

  from crossbench.cli.parser import CBArgumentParser
  from crossbench.cli.types import Subparsers


class BitsMergeSubcommand(CrossbenchSubcommand):
  """A subcommand for merging BITS traces with the device's Perfetto traces."""

  @override
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    self._parser = subparsers.add_parser(
        "bits-merge",
        aliases=("bits_merge",),
        help=("Zips the BITS trace of every run together with the device's "
              "Perfetto trace and a perfetto_manifest that aligns their "
              "clocks, so that trace_processor (and thus the Perfetto UI) "
              "loads both onto a common timeline."))
    self._parser.set_defaults(crossbench_subcommand=self)
    return self.parser

  @override
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    parser.add_argument(
        "result_dir",
        type=results_uploader.result_dir,
        help="Path to the benchmark result directory.")
    parser.add_argument(
        "output_dir",
        type=PathParser.not_existing_or_empty_path,
        help="Directory to write one archive per run to. Must be empty or "
        "not exist yet.")
    self.cli.add_debugging_arguments(parser)
    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    bits_merge.merge_results(args.result_dir, args.output_dir)
