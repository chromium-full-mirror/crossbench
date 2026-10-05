# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import logging
import re
import sys
from typing import TYPE_CHECKING, Final, Iterable

from crossbench.helper import fs_helper
from crossbench.helper.version import Version
from crossbench.parse import PathParser
from crossbench.plt.base import SubprocessError
from crossbench.plt.bin import Binaries

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.config import ConfigParser
  from crossbench.plt.base import Platform
  from crossbench.plt.types import ListCmdArgs, TupleCmdArgs


@enum.unique
class PerfettoSymbolizerMode(enum.StrEnum):
  INDEX = "index"
  FIND = "find"


def add_argument(parser: ConfigParser) -> None:
  parser.add_argument(
      "traceconv",
      default=None,
      type=PathParser.file_path,
      help=("Path to the 'traceconv.py' helper on the runner platform "
            "to convert '.proto' traces to legacy '.json'. "
            "If not specified, tries to find it in a v8 or chromium checkout."))


_PROTO_SUFFIX_RE: Final[re.Pattern] = re.compile(r"\.(?:proto|pb|pb\.gz)$")
_VERSION_RE: Final[re.Pattern] = re.compile(r"Perfetto v(\d+)\.(\d+)")


class PerfettoVersion(Version):

  @classmethod
  def parse(cls, version_str: str) -> PerfettoVersion:
    if match := _VERSION_RE.search(version_str):
      parts = (int(match.group(1)), int(match.group(2)))
      return cls(parts, version_str)
    raise cls.parse_error("Could not parse perfetto version", version_str)


MIN_VERSION: Final[PerfettoVersion] = PerfettoVersion(
    (53, 0), "Perfetto v53.0-4fa2ae872")


def convert_to_json(platform: Platform, traceconv: pth.LocalPath | None,
                    input_proto: pth.LocalPath) -> pth.LocalPath | None:
  if not traceconv:
    logging.info(
        "No traceconv binary: skipping converting proto to legacy traces")
    return None
  input_name = input_proto.name
  json_name = _PROTO_SUFFIX_RE.sub(".json", input_name)
  if input_name == json_name:
    raise ValueError(f"Unsupported input file: {input_proto}")
  output_json: pth.LocalPath = input_proto.with_name(json_name)
  logging.info("Converting to legacy .json trace on local machine: %s",
               output_json)
  cmd: ListCmdArgs = [traceconv, "json", input_proto, output_json]
  if not platform.is_posix:
    python_executable: ListCmdArgs = [sys.argv[0]]
    cmd = python_executable + cmd
  try:
    platform.sh(*cmd)
    return output_json
  except Exception as e:  # noqa: BLE001
    logging.error("traceconv failure: %s", e)
    return None


def symbolizer_env(
    platform: Platform,
    symbols_paths: Iterable[pth.AnyPathLike] | pth.AnyPathLike,
    llvm_symbolizer: pth.AnyPath | None = None,
    mode: PerfettoSymbolizerMode = PerfettoSymbolizerMode.INDEX,
) -> dict[str, str]:
  """Constructs environment dict for traceconv or trace_processor."""
  env = {
      **platform.environ,
      "PERFETTO_SYMBOLIZER_MODE": str(mode),
      "PERFETTO_BINARY_PATH": platform.join_path_list(symbols_paths),
  }
  if not llvm_symbolizer:
    llvm_symbolizer = Binaries.LLVM_SYMBOLIZER.search(platform)
  if llvm_symbolizer:
    env["PATH"] = platform.join_path_list(
        (llvm_symbolizer.parent, env.get("PATH", "")))
  return env


def convert_profile_cmd(traceconv_bin: pth.AnyPath, perf_file: pth.AnyPath,
                        output_dir: pth.AnyPath) -> TupleCmdArgs:
  """Constructs command to convert a perf profile into pprof format."""
  prefix: TupleCmdArgs = (traceconv_bin,)
  if "trace_processor" in traceconv_bin.name:
    prefix = (traceconv_bin, "convert")
  return (
      *prefix,
      "profile",
      "--perf",
      "--output-dir",
      output_dir,
      perf_file,
  )


def convert_profile(platform: Platform,
                    traceconv_bin: pth.AnyPath,
                    perf_file: pth.AnyPath,
                    output_file: pth.AnyPath | None = None,
                    env: dict[str, str] | None = None) -> pth.AnyPath | None:
  """Converts a perf.data profile into pprof format using traceconv."""
  if output_file is None:
    output_file = perf_file.with_suffix(".pprof")
  with platform.TemporaryDirectory(prefix="traceconv_") as output_dir:
    cmd = convert_profile_cmd(traceconv_bin, perf_file, output_dir)
    try:
      platform.sh(*cmd, env=env)
    except SubprocessError as e:
      logging.warning("Failed to export with traceconv for %s: %s", perf_file,
                      e)
      return None
    profiles = fs_helper.sort_by_file_size(
        list(platform.iterdir(output_dir)), platform)
    if profiles and platform.file_size(profiles[-1]) > 0:
      platform.rename(profiles[-1], output_file)
      logging.info("  traceconv: generated %s", output_file.name)
      return output_file
  return None
