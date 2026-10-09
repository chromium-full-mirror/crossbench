# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Merges the BITS trace of each run with the device's Perfetto trace.

BITS stamps its trace with the host's CLOCK_REALTIME, the device trace uses
the device's CLOCK_BOOTTIME. Both are zipped together with a perfetto_manifest
(https://perfetto.dev/docs/reference/perfetto-manifest) carrying the clock
offset that the bits probe recorded in bits.json, see BitsProbe.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import shutil
import zipfile
from typing import TYPE_CHECKING, Final, Iterator

from typing_extensions import override

from crossbench import path as pth
from crossbench.cli.subcommand.base import CrossbenchSubcommand
from crossbench.parse import NumberParser, ObjectParser, PathParser
from crossbench.probes.internal.summary import ResultsSummaryProbe
from crossbench.uploader import results_uploader

if TYPE_CHECKING:
  from crossbench.cli.parser import CBArgumentParser
  from crossbench.cli.types import Subparsers
  from crossbench.types import Json, JsonDict

# trace_processor ignores manifest clock offsets for proto traces without a
# ClockSnapshot, so the BITS trace is prefixed with this hand-encoded one.
#
# TODO(eladalon): Drop once a fix, e.g. github.com/google/perfetto/pull/7874,
# has shipped in the Perfetto UI and in the default trace_processor binary.
_BOOTTIME_SNAPSHOT_PACKET: Final[bytes] = (
    b"\x0a\x08"  # Trace.packet (field 1, 8 bytes)
    b"\x32\x06"  # TracePacket.clock_snapshot (field 6, 6 bytes)
    b"\x0a\x04"  # ClockSnapshot.clocks (field 1, 4 bytes)
    b"\x08\x06"  # ClockSnapshot.Clock.clock_id = BUILTIN_CLOCK_BOOTTIME
    b"\x10\x00"  # ClockSnapshot.Clock.timestamp = 0
)


class _RunResults:
  """What a run's cb.results.json says about the run and its probes' output.

  Result paths in the file are absolute as of recording time; they are
  re-rooted at the run directory, in case the results have been moved.
  """

  def __init__(self, run_dir: pth.LocalPath) -> None:
    self._run_dir = run_dir
    self._path = run_dir / ResultsSummaryProbe.FILE_NAME
    self._results: JsonDict = _read_json(self._path)
    self._recorded_cwd = pth.LocalPath(
        ObjectParser.non_empty_str(
            self._results.get("cwd"), f"cwd in {self._path}"))

  @functools.cached_property
  def archive_name(self) -> str:
    """<browser>_<story>_<repetition>.zip"""
    parts = (
        self._lookup(keys) for keys in (
            ("browser", "label"),
            ("story", "name"),
            ("run", "repetition"),
        ))
    return pth.safe_filename("_".join(map(str, parts))) + ".zip"

  @functools.cached_property
  def device_trace(self) -> pth.LocalPath:
    return self._probe_file("perfetto", "gz")

  @functools.cached_property
  def bits_trace(self) -> pth.LocalPath:
    return self._probe_file("bits", "pftrace")

  @functools.cached_property
  def clock_offset_ns(self) -> int:
    """Device CLOCK_BOOTTIME - host CLOCK_REALTIME, see BitsProbe."""
    bits_json_path = self._probe_file("bits", "json")
    bits_json = _read_json(bits_json_path)
    if "clock_sync" not in bits_json:
      raise ValueError(f"No clock_sync in {bits_json_path}")
    clock_sync = ObjectParser.dict(bits_json["clock_sync"],
                                   f"clock_sync in {bits_json_path}")
    return NumberParser.any_int(
        clock_sync.get("offset_ns"),
        f"offset_ns in {bits_json_path}",
        parse_str=False)

  @functools.cached_property
  def attributes(self) -> dict[str, str]:
    """Manifest attributes describing the run."""
    attributes = {
        "crossbench.browser": ("browser", "label"),
        "crossbench.browser_version": ("browser", "version"),
        "crossbench.story": ("story", "name"),
        "crossbench.run": ("run", "name"),
        "crossbench.repetition": ("run", "repetition"),
        "crossbench.temperature": ("run", "temperature"),
    }
    return {name: str(self._lookup(keys)) for name, keys in attributes.items()}

  def _probe_file(self, probe_name: str, suffix: str) -> pth.LocalPath:
    """The single file with the given suffix among a probe's results, e.g.
    _probe_file("bits", "json") for bits.json."""
    files = self._lookup(("probes", probe_name, suffix))
    if not isinstance(files, list) or len(files) != 1:
      raise ValueError(f"Expected one {probe_name}.{suffix} in {self._path}")
    path = pth.LocalPath(str(files[0]))
    if path.is_relative_to(self._recorded_cwd):
      path = self._run_dir / path.relative_to(self._recorded_cwd)
    if not path.is_file():
      raise ValueError(f"Missing {path}, listed in {self._path}")
    return path

  def _lookup(self, keys: tuple[str, ...]) -> Json:
    """self._results[keys[0]][keys[1]]..., raising a ValueError naming the
    file and the key path if any key is missing or maps to null."""
    value: Json = self._results
    for key in keys:
      if not isinstance(value, dict) or value.get(key) is None:
        raise ValueError(f"No {'.'.join(keys)} in {self._path}")
      value = value[key]
    return value


def _merge_results(results_dir: pth.LocalPath,
                   output_dir: pth.LocalPath) -> list[pth.LocalPath]:
  """Merges every run below results_dir; unmergeable runs are logged and
  skipped, and a ValueError raised at the end if there were any, or none."""
  archives: list[pth.LocalPath] = []
  failed = 0
  for run_dir in _run_dirs(results_dir):
    try:
      archives.append(_merge_run(run_dir, output_dir))
    except (ValueError, argparse.ArgumentTypeError, OSError) as e:
      logging.error("Could not merge the BITS output of %s: %s", run_dir, e)
      failed += 1
  if failed:
    total = failed + len(archives)
    raise ValueError(f"Could not merge {failed} of {total} runs, see above")
  if not archives:
    raise ValueError(f"No runs found in {results_dir}")
  return archives


def _merge_run(run_dir: pth.LocalPath,
               output_dir: pth.LocalPath) -> pth.LocalPath:
  """Zips the run's device trace and BITS trace with a perfetto_manifest into
  output_dir and returns the archive's path."""
  run = _RunResults(run_dir)
  archive_path = output_dir / run.archive_name
  if archive_path.exists():
    raise ValueError(f"{archive_path} exists already, not overwriting it")
  manifest = _manifest(run)
  output_dir.mkdir(parents=True, exist_ok=True)
  try:
    _write_archive(archive_path, run, manifest)
  except BaseException:
    archive_path.unlink(missing_ok=True)
    raise
  logging.critical("Merged BITS output: %s", archive_path)
  return archive_path


def _write_archive(archive_path: pth.LocalPath, run: _RunResults,
                   manifest: JsonDict) -> None:
  with zipfile.ZipFile(
      archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    archive.writestr("perfetto_manifest.json", json.dumps(manifest, indent=2))
    # Gzipped already.
    archive.write(
        run.device_trace,
        run.device_trace.name,
        compress_type=zipfile.ZIP_STORED)
    with archive.open(f"bits/{run.bits_trace.name}", "w") as member:
      member.write(_BOOTTIME_SNAPSHOT_PACKET)
      with run.bits_trace.open("rb") as source:
        shutil.copyfileobj(source, member)


def _manifest(run: _RunResults) -> JsonDict:
  device_member = run.device_trace.name
  return {
      "perfetto_manifest": {
          "version": 1,
          "trace_time": {
              "clock": "BOOTTIME",
              "file": device_member,
          },
          "files": [
              {
                  "path": device_member,
              },
              {
                  "path": f"bits/{run.bits_trace.name}",
                  "machine": {
                      "name": "bits",
                  },
                  "clocks": {
                      "clock": "BOOTTIME",
                      "sync_to": {
                          "file": device_member,
                          "clock": "BOOTTIME",
                      },
                      "offset_ns": run.clock_offset_ns,
                  },
              },
          ],
          "attributes": run.attributes,
      },
  }


def _run_dirs(results_dir: pth.LocalPath) -> Iterator[pth.LocalPath]:
  """Yields the directories of the individual runs below results_dir."""
  for results_file in sorted(results_dir.rglob(ResultsSummaryProbe.FILE_NAME)):
    if "run" in _read_json(results_file):
      yield results_file.parent


def _read_json(path: pth.LocalPath) -> JsonDict:
  return ObjectParser.dict(ObjectParser.json_file(path), str(path))


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
        type=PathParser.not_existing_path,
        help="Directory to write one archive per run to. Must not exist yet.")
    self.cli.add_debugging_arguments(parser)
    return parser

  @override
  def run(self, args: argparse.Namespace) -> None:
    _merge_results(args.result_dir, args.output_dir)
