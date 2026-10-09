# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import gzip
import json
import zipfile
from typing import Any, Callable, Final
from unittest import mock

from google.protobuf import empty_pb2
from google.protobuf.unknown_fields import UnknownFieldSet

from crossbench import path as pth
from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.subcommand import bits_merge
from crossbench.cli.subcommand.bits_merge import BitsMergeSubcommand
from crossbench.probes.internal.summary import ResultsSummaryProbe
from tests import test_helper
from tests.crossbench.base import BaseCliTestCase, BaseCrossbenchTestCase, \
    SysExitTestException

_DEVICE_TRACE: Final[bytes] = gzip.compress(b"device trace")
_BITS_TRACE: Final[bytes] = b"bits trace"
_OFFSET_NS: Final[int] = -1790862429649081949
# Protobuf wire types.
_VARINT: Final[int] = 0
_LENGTH_DELIMITED: Final[int] = 2


def _decode_fields(data: bytes) -> list[tuple[int, int, Any]]:
  """Decodes data as (field number, wire type, value) triples.

  Decoding into a message without any known fields keeps everything in the
  UnknownFieldSet, which spares us from importing the perfetto protos.
  """
  message = empty_pb2.Empty()
  message.ParseFromString(data)
  fields = UnknownFieldSet(message)
  return [(fields[i].field_number, fields[i].wire_type, fields[i].data)
          for i in range(len(fields))]


class BitsMergeTestCase(BaseCrossbenchTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.results_dir = self.out_dir
    self.results_dir.mkdir(parents=True)
    self.output_dir = pth.LocalPath("/crossbench-test/merged")
    # The aggregated summary at the top level has no "run" section.
    self._write_json(self.results_dir / ResultsSummaryProbe.FILE_NAME,
                     {"browsers": {}})

  def _write_json(self, path: pth.LocalPath, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")

  def _create_run(self,
                  story: str = "story_a",
                  with_perfetto: bool = True,
                  with_bits: bool = True,
                  with_clock_sync: bool = True,
                  recorded_cwd: pth.LocalPath | None = None) -> pth.LocalPath:
    """Creates a run directory with perfetto and bits probe results.

    recorded_cwd is the run directory as noted in cb.results.json, which
    differs from the actual one once results have been moved.
    """
    run_dir = (
        self.results_dir / "chrome" / "stories" / story / "0" / "0_default")
    run_dir.mkdir(parents=True)
    recorded_cwd = recorded_cwd or run_dir
    probes: dict[str, Any] = {}
    if with_perfetto:
      (run_dir / "perfetto.trace.pb.gz").write_bytes(_DEVICE_TRACE)
      probes["perfetto"] = {
          "gz": [str(recorded_cwd / "perfetto.trace.pb.gz")],
      }
    if with_bits:
      bits_dir = run_dir / "bits"
      bits_dir.mkdir()
      (bits_dir / "20260101_120000.pftrace").write_bytes(_BITS_TRACE)
      bits_json: dict[str, Any] = {"bits_out_id": "20260101_120000"}
      if with_clock_sync:
        bits_json["clock_sync"] = {
            "host_realtime_ns": 1791367605185683067,
            "device_boottime_ns": 505175536601118,
            "offset_ns": _OFFSET_NS,
            "round_trip_ns": 61034512,
        }
      self._write_json(bits_dir / "bits.json", bits_json)
      recorded_bits_dir = recorded_cwd / "bits"
      probes["bits"] = {
          "pftrace": [str(recorded_bits_dir / "20260101_120000.pftrace")],
          "json": [str(recorded_bits_dir / "bits.json")],
          "csv": [str(recorded_bits_dir / "bits_channel_averages.csv")],
      }
    self._write_json(
        run_dir / ResultsSummaryProbe.FILE_NAME, {
            "cwd": str(recorded_cwd),
            "browser": {
                "label": "chrome",
                "version": "151.0.1.2",
            },
            "story": {
                "name": story,
            },
            "run": {
                "name": f"story={story}, index=0",
                "index": 0,
                "repetition": 0,
                "temperature": "0_default",
            },
            "probes": probes,
        })
    return run_dir

  def _edit_json(self, path: pth.LocalPath, edit: Callable[[dict[str, Any]],
                                                           None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    self._write_json(path, data)

  def _read_manifest(self, archive_path: pth.LocalPath) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path) as archive:
      return json.loads(archive.read("perfetto_manifest.json"))

  def _decode_single_field(self, data: bytes) -> tuple[int, int, Any]:
    fields = _decode_fields(data)
    self.assertEqual(len(fields), 1)
    return fields[0]

  def test_snapshot_packet_encoding(self) -> None:
    trace = bits_merge._BOOTTIME_SNAPSHOT_PACKET
    # Trace.packet
    field, wire_type, packet = self._decode_single_field(trace)
    self.assertEqual((field, wire_type), (1, _LENGTH_DELIMITED))
    # TracePacket.clock_snapshot
    field, wire_type, snapshot = self._decode_single_field(packet)
    self.assertEqual((field, wire_type), (6, _LENGTH_DELIMITED))
    # ClockSnapshot.clocks
    field, wire_type, clock = self._decode_single_field(snapshot)
    self.assertEqual((field, wire_type), (1, _LENGTH_DELIMITED))
    # ClockSnapshot.Clock.clock_id = BUILTIN_CLOCK_BOOTTIME, timestamp = 0
    self.assertListEqual(
        _decode_fields(clock), [(1, _VARINT, 6), (2, _VARINT, 0)])

  def test_merge_run(self) -> None:
    run_dir = self._create_run()
    archive_path = bits_merge._merge_run(run_dir, self.output_dir)
    self.assertEqual(archive_path, self.output_dir / "chrome_story_a_0.zip")
    with zipfile.ZipFile(archive_path) as archive:
      self.assertListEqual(archive.namelist(), [
          "perfetto_manifest.json",
          "perfetto.trace.pb.gz",
          "bits/20260101_120000.pftrace",
      ])
      self.assertEqual(archive.read("perfetto.trace.pb.gz"), _DEVICE_TRACE)
      self.assertEqual(
          archive.read("bits/20260101_120000.pftrace"),
          bits_merge._BOOTTIME_SNAPSHOT_PACKET + _BITS_TRACE)
      # The device trace is gzipped already.
      self.assertEqual(
          archive.getinfo("perfetto.trace.pb.gz").compress_type,
          zipfile.ZIP_STORED)
      self.assertEqual(
          archive.getinfo("bits/20260101_120000.pftrace").compress_type,
          zipfile.ZIP_DEFLATED)

  def test_merge_run_manifest(self) -> None:
    run_dir = self._create_run()
    manifest = self._read_manifest(
        bits_merge._merge_run(run_dir, self.output_dir))
    self.assertDictEqual(
        manifest, {
            "perfetto_manifest": {
                "version": 1,
                "trace_time": {
                    "clock": "BOOTTIME",
                    "file": "perfetto.trace.pb.gz",
                },
                "files": [
                    {
                        "path": "perfetto.trace.pb.gz",
                    },
                    {
                        "path": "bits/20260101_120000.pftrace",
                        "machine": {
                            "name": "bits",
                        },
                        "clocks": {
                            "clock": "BOOTTIME",
                            "sync_to": {
                                "file": "perfetto.trace.pb.gz",
                                "clock": "BOOTTIME",
                            },
                            "offset_ns": _OFFSET_NS,
                        },
                    },
                ],
                "attributes": {
                    "crossbench.browser": "chrome",
                    "crossbench.browser_version": "151.0.1.2",
                    "crossbench.story": "story_a",
                    "crossbench.run": "story=story_a, index=0",
                    "crossbench.repetition": "0",
                    "crossbench.temperature": "0_default",
                },
            },
        })

  def test_merge_run_moved_results(self) -> None:
    recorded_cwd = pth.LocalPath("/elsewhere/results/chrome/stories/s/0/0_d")
    run_dir = self._create_run(recorded_cwd=recorded_cwd)
    with zipfile.ZipFile(bits_merge._merge_run(run_dir,
                                               self.output_dir)) as archive:
      self.assertEqual(archive.read("perfetto.trace.pb.gz"), _DEVICE_TRACE)
      self.assertEqual(
          archive.read("bits/20260101_120000.pftrace"),
          bits_merge._BOOTTIME_SNAPSHOT_PACKET + _BITS_TRACE)

  def test_merge_run_archive_name_is_sanitized(self) -> None:
    run_dir = self._create_run()
    self._edit_json(
        run_dir / ResultsSummaryProbe.FILE_NAME,
        lambda results: results["browser"].update(label="Chrome Dev/2"))
    self.assertEqual(
        bits_merge._merge_run(run_dir, self.output_dir),
        self.output_dir / "Chrome_Dev_2_story_a_0.zip")

  def test_merge_run_missing_run_details(self) -> None:
    run_dir = self._create_run()
    self._edit_json(run_dir / ResultsSummaryProbe.FILE_NAME,
                    lambda results: results["story"].clear())
    with self.assertRaisesRegex(ValueError, "No story.name in"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_refuses_existing_archive(self) -> None:
    run_dir = self._create_run()
    self.output_dir.mkdir()
    archive_path = self.output_dir / "chrome_story_a_0.zip"
    archive_path.write_bytes(b"other")
    with self.assertRaisesRegex(ValueError, "exists already"):
      bits_merge._merge_run(run_dir, self.output_dir)
    self.assertEqual(archive_path.read_bytes(), b"other")

  def test_merge_run_failure_leaves_no_archive(self) -> None:
    run_dir = self._create_run()
    with (
        mock.patch(
            "crossbench.cli.subcommand.bits_merge.shutil.copyfileobj",
            side_effect=OSError("disk full")),
        self.assertRaisesRegex(OSError, "disk full"),
    ):
      bits_merge._merge_run(run_dir, self.output_dir)
    self.assertListEqual(list(self.output_dir.iterdir()), [])

  def test_merge_run_missing_perfetto_probe(self) -> None:
    run_dir = self._create_run(with_perfetto=False)
    with self.assertRaisesRegex(ValueError, "No probes.perfetto.gz in"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_missing_bits_probe(self) -> None:
    run_dir = self._create_run(with_bits=False)
    with self.assertRaisesRegex(ValueError, "No probes.bits"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_empty_bits_results(self) -> None:
    run_dir = self._create_run()
    # Probes without results are listed with a null value.
    self._edit_json(run_dir / ResultsSummaryProbe.FILE_NAME,
                    lambda results: results["probes"].update(bits=None))
    with self.assertRaisesRegex(ValueError, "No probes.bits"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_multiple_device_traces(self) -> None:
    run_dir = self._create_run()
    self._edit_json(
        run_dir / ResultsSummaryProbe.FILE_NAME,
        lambda results: results["probes"]["perfetto"]["gz"].append("b.gz"))
    with self.assertRaisesRegex(ValueError, "Expected one perfetto.gz"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_missing_trace_file(self) -> None:
    run_dir = self._create_run()
    (run_dir / "perfetto.trace.pb.gz").unlink()
    with self.assertRaisesRegex(ValueError, "Missing .*perfetto.trace.pb.gz"):
      bits_merge._merge_run(run_dir, self.output_dir)
    self.assertFalse(self.output_dir.exists())

  def test_merge_run_missing_clock_sync(self) -> None:
    run_dir = self._create_run(with_clock_sync=False)
    with self.assertRaisesRegex(ValueError, "No clock_sync in"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_run_malformed_offset(self) -> None:
    run_dir = self._create_run()
    self._edit_json(
        run_dir / "bits" / "bits.json",
        lambda bits_json: bits_json["clock_sync"].update(offset_ns="soon"))
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "offset_ns"):
      bits_merge._merge_run(run_dir, self.output_dir)

  def test_merge_results(self) -> None:
    self._create_run("story_a")
    self._create_run("story_b")
    self.assertFalse(self.output_dir.exists())
    archives = bits_merge._merge_results(self.results_dir, self.output_dir)
    self.assertListEqual(archives, [
        self.output_dir / "chrome_story_a_0.zip",
        self.output_dir / "chrome_story_b_0.zip",
    ])
    self.assertListEqual(sorted(self.output_dir.iterdir()), archives)

  def test_merge_results_ignores_symlinked_run_dirs(self) -> None:
    run_dir = self._create_run()
    (self.results_dir / "runs").mkdir()
    (self.results_dir / "runs" / "0").symlink_to(run_dir)
    (run_dir / "session").symlink_to(run_dir)
    self.assertListEqual(
        bits_merge._merge_results(self.results_dir, self.output_dir),
        [self.output_dir / "chrome_story_a_0.zip"])

  def test_merge_results_single_run_dir(self) -> None:
    run_dir = self._create_run()
    archives = bits_merge._merge_results(run_dir, self.output_dir)
    self.assertListEqual(archives, [self.output_dir / "chrome_story_a_0.zip"])

  def test_merge_results_no_runs(self) -> None:
    with self.assertRaisesRegex(ValueError, "No runs found"):
      bits_merge._merge_results(self.results_dir, self.output_dir)

  def test_merge_results_skips_incomplete_runs(self) -> None:
    self._create_run("story_a", with_bits=False)
    self._create_run("story_b")
    self._create_run("story_c", with_perfetto=False)
    with (
        mock.patch("logging.error") as mock_error,
        self.assertRaisesRegex(ValueError, "Could not merge 2 of 3 runs"),
    ):
      bits_merge._merge_results(self.results_dir, self.output_dir)
    self.assertListEqual(
        list(self.output_dir.iterdir()),
        [self.output_dir / "chrome_story_b_0.zip"])
    self.assertEqual(mock_error.call_count, 2)


_MERGE_PATCH_TARGET: Final[str] = (
    "crossbench.cli.subcommand.bits_merge._merge_results")


class BitsMergeSubcommandTest(BaseCliTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.cli_instance = CrossBenchCLI()
    self.subcommand = self.cli_instance.subcommands["bits-merge"]
    self.assertIsInstance(self.subcommand, BitsMergeSubcommand)
    self.test_dir = self.out_dir / "results"
    self.test_dir.mkdir(parents=True, exist_ok=True)
    (self.test_dir / ResultsSummaryProbe.FILE_NAME).touch()
    self.output_dir = self.out_dir / "merged"
    self.archives = [self.output_dir / "chrome_story_0.zip"]

  def test_subcommand_registered(self) -> None:
    self.assertIn("bits-merge", self.cli_instance.subcommands)

  def _run_cli_expecting_usage_error(self, *args: str) -> None:
    with (
        mock.patch(_MERGE_PATCH_TARGET) as mock_merge,
        self.assertRaises(SysExitTestException),
    ):
      self.run_cli("bits-merge", *args)
    mock_merge.assert_not_called()

  def test_run_success(self) -> None:
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits-merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_run_alias_success(self) -> None:
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits_merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_output_dir_empty(self) -> None:
    self.output_dir.mkdir()
    with mock.patch(
        _MERGE_PATCH_TARGET, return_value=self.archives) as mock_merge:
      self.run_cli("bits-merge", str(self.test_dir), str(self.output_dir))
    mock_merge.assert_called_once_with(self.test_dir, self.output_dir)

  def test_output_dir_not_empty(self) -> None:
    self.output_dir.mkdir()
    (self.output_dir / "foo").touch()
    self._run_cli_expecting_usage_error(
        str(self.test_dir), str(self.output_dir))

  def test_missing_arguments(self) -> None:
    self._run_cli_expecting_usage_error()
    self._run_cli_expecting_usage_error(str(self.test_dir))

  def test_invalid_result_dir(self) -> None:
    self._run_cli_expecting_usage_error(
        str(self.out_dir / "does_not_exist"), str(self.output_dir))

  def test_run_non_result_dir_fails(self) -> None:
    non_result_dir = self.out_dir / "not_a_result_dir"
    non_result_dir.mkdir(parents=True)
    self._run_cli_expecting_usage_error(
        str(non_result_dir), str(self.output_dir))

  def test_output_dir_is_file(self) -> None:
    self.output_dir.touch()
    self._run_cli_expecting_usage_error(
        str(self.test_dir), str(self.output_dir))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
