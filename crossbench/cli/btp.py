#!/usr/bin/env vpython3
# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import logging
from typing import Final, Sequence

from perfetto.batch_trace_processor import api as btp_api
from perfetto.trace_uri_resolver.resolver import TraceUriResolver

from crossbench import path as pth
from crossbench.cli.config.probe_list import ProbeListConfig
from crossbench.cli.parser import CBArgumentParser
from crossbench.parse import PathParser
from crossbench.probes.trace_processor.constants import QUERIES_DIR
from crossbench.probes.trace_processor.helper import \
    CBBatchTraceProcessorConfig
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe

DEFAULT_CONFIG_PATH: Final[pth.LocalPath] = (
    pth.ROOT_DIR / "config" / "benchmark" / "loadline" / "probe_config.hjson")


class MergedTraceUriResolver(TraceUriResolver):

  def __init__(self, result_path: pth.LocalPath) -> None:

    def metadata(path: pth.LocalPath) -> dict[str, str]:
      parts: tuple[str, ...] = path.parts
      return {
          "cb_browser": parts[-7],
          "cb_story": parts[-5],
          "cb_run": parts[-4],
          "cb_temperature": parts[-3],
      }

    listdir = list(result_path.glob("*/stories/**/merged_trace.zip"))

    self._resolved = [
        TraceUriResolver.Result(trace=str(path), metadata=metadata(path))
        for path in listdir
    ]

  def resolve(self) -> list[TraceUriResolver.Result]:
    return self._resolved


class BTPUtil:

  def __init__(self) -> None:
    self.parser = CBArgumentParser(
        description=("Runs trace processor queries in a batch mode on existing "
                     "benchmark results, without re-running the benchmark "
                     "itself."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    self.parser.add_argument(
        "--result-dir",
        type=PathParser.existing_path,
        default=pth.LATEST_RESULT_DIR,
        help="Path to the benchmark result directory.")
    self.parser.add_argument(
        "--probe-config",
        type=PathParser.existing_file_path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the trace_processor probe config.")
    self.parser.add_argument(
        "--output-dir",
        type=PathParser.path,
        default=pth.ROOT_DIR,
        help="Path to the directory where output files will be placed.")
    self.parser.add_argument(
        "--extra-query",
        type=str,
        default=[],
        action="append",
        help=("Name of the query to compute (the query must be present in the "
              "trace_processor/queries/ dir). Repeat for multiple queries."))

  def run(self, argv: Sequence[str]) -> None:
    args = self.parser.parse_args(argv)

    probe_config = ProbeListConfig.parse(args.probe_config)
    tp: TraceProcessorProbe | None = None
    for probe in probe_config.probes:
      if isinstance(probe, TraceProcessorProbe):
        tp = probe
    assert tp, "Could not find TraceProcessorProbe"

    btp_conf = CBBatchTraceProcessorConfig(
        bin_path=tp.trace_processor_bin,
        load_failure_handling=btp_api.FailureHandling.INCREMENT_STAT,
        execute_failure_handling=btp_api.FailureHandling.INCREMENT_STAT)

    with btp_api.BatchTraceProcessor(
        traces=MergedTraceUriResolver(args.result_dir), config=btp_conf) as btp:
      queries = list(tp.queries) + args.extra_query
      for query in queries:
        query_path = QUERIES_DIR / f"{query}.sql"
        csv_file = args.output_dir / f"{pth.safe_filename(query)}.csv"
        btp.query_and_flatten(query_path.read_text()).to_csv(
            path_or_buf=csv_file, index=False)
        print(f"Query result written into {csv_file}")

    stats = btp.stats()
    if stats.load_failures + stats.execute_failures > 0:
      logging.error(
          "Failures registered during BTP run: "
          "%s load failures, %s execution failures.", stats.load_failures,
          stats.execute_failures)
