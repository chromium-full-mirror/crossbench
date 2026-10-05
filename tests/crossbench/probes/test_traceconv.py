# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import subprocess
from unittest import mock

from crossbench import path as pth
from crossbench import plt
from crossbench.plt.bin import Binaries
from crossbench.probes.cb_perfetto import traceconv
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase
from tests.crossbench.mock_helper import LinuxMockPlatform


class PerfettoVersionTestCase(CrossbenchFakeFsTestCase):

  def test_parse(self) -> None:
    self.assertSequenceEqual(
        traceconv.PerfettoVersion.parse("Perfetto v53.0").parts, (53, 0))
    self.assertSequenceEqual(
        traceconv.PerfettoVersion.parse("Perfetto v53.1").parts, (53, 1))
    self.assertSequenceEqual(
        traceconv.PerfettoVersion.parse("Perfetto v53.0-7a9a6a0").parts,
        (53, 0))
    self.assertSequenceEqual(
        traceconv.PerfettoVersion.parse(
            "some noise Perfetto v54.2-abc (hash)").parts, (54, 2))

  def test_comparison(self) -> None:
    v53_0 = traceconv.PerfettoVersion.parse("Perfetto v53.0")
    v53_1 = traceconv.PerfettoVersion.parse("Perfetto v53.1")
    v54_0 = traceconv.PerfettoVersion.parse("Perfetto v54.0")
    v52_9 = traceconv.PerfettoVersion.parse("Perfetto v52.9")

    self.assertTrue(v53_0 >= traceconv.MIN_VERSION)
    self.assertTrue(v53_1 >= traceconv.MIN_VERSION)
    self.assertTrue(v54_0 >= traceconv.MIN_VERSION)
    self.assertTrue(v52_9 < traceconv.MIN_VERSION)


class TraceconvHelperTestCase(CrossbenchFakeFsTestCase):

  def setUp(self) -> None:
    super().setUp()
    self.platform = LinuxMockPlatform(fake_fs=self.fs)

  def test_convert_profile_cmd_traceconv(self) -> None:
    cmd = traceconv.convert_profile_cmd(
        pth.LocalPath("/usr/bin/traceconv"), pth.LocalPath("/tmp/perf.data"),
        pth.LocalPath("/tmp/out_dir"))
    self.assertEqual(cmd, (
        pth.LocalPath("/usr/bin/traceconv"),
        "profile",
        "--perf",
        "--output-dir",
        pth.LocalPath("/tmp/out_dir"),
        pth.LocalPath("/tmp/perf.data"),
    ))

  def test_convert_profile_cmd_trace_processor(self) -> None:
    cmd = traceconv.convert_profile_cmd(
        pth.LocalPath("/usr/bin/trace_processor_shell"),
        pth.LocalPath("/tmp/perf.data"), pth.LocalPath("/tmp/out_dir"))
    self.assertEqual(cmd, (
        pth.LocalPath("/usr/bin/trace_processor_shell"),
        "convert",
        "profile",
        "--perf",
        "--output-dir",
        pth.LocalPath("/tmp/out_dir"),
        pth.LocalPath("/tmp/perf.data"),
    ))

  def test_symbolizer_env_single_path(self) -> None:
    env = traceconv.symbolizer_env(self.platform, "/custom/symbols")
    self.assertEqual(env["PERFETTO_SYMBOLIZER_MODE"], "index")
    self.assertEqual(env["PERFETTO_BINARY_PATH"], "/custom/symbols")

  def test_symbolizer_env_multiple_paths(self) -> None:
    env = traceconv.symbolizer_env(
        self.platform,
        [pth.LocalPath("/symbols/a"),
         pth.LocalPath("/symbols/b")])
    self.assertEqual(env["PERFETTO_SYMBOLIZER_MODE"], "index")
    self.assertEqual(env["PERFETTO_BINARY_PATH"], "/symbols/a:/symbols/b")

  def test_symbolizer_env_llvm_symbolizer_explicit(self) -> None:
    env = traceconv.symbolizer_env(
        self.platform,
        "/symbols",
        llvm_symbolizer=pth.LocalPath("/opt/llvm/bin/llvm-symbolizer"))
    self.assertTrue(env["PATH"].startswith("/opt/llvm/bin"))

  def test_symbolizer_env_llvm_symbolizer_search(self) -> None:
    self.platform.install_mock_binary("llvm-symbolizer",
                                      "/usr/bin/llvm-symbolizer")
    with mock.patch.object(
        Binaries.LLVM_SYMBOLIZER,
        "search",
        return_value=pth.LocalPath("/usr/bin/llvm-symbolizer")):
      env = traceconv.symbolizer_env(self.platform, "/symbols")
    self.assertTrue(env["PATH"].startswith("/usr/bin"))

  def test_convert_profile_success(self) -> None:
    perf_file = pth.LocalPath("/tmp/test.perf.data")
    pprof_file = perf_file.with_suffix(".pprof")
    self.fs.create_file(perf_file)

    def mock_sh(*args, **kwargs):
      del kwargs
      out_dir = pth.LocalPath(args[args.index("--output-dir") + 1])
      self.fs.create_file(
          out_dir / "profile.1.pid.123.pb", contents="mock_pprof")

    with mock.patch.object(self.platform, "sh", side_effect=mock_sh):
      result = traceconv.convert_profile(self.platform,
                                         pth.LocalPath("/usr/bin/traceconv"),
                                         perf_file)
    self.assertEqual(result, pprof_file)
    self.assertTrue(self.platform.exists(pprof_file))

  def test_convert_profile_failure(self) -> None:
    perf_file = pth.LocalPath("/tmp/test.perf.data")
    self.fs.create_file(perf_file)
    proc = subprocess.CompletedProcess(args=["traceconv"], returncode=1)
    with mock.patch.object(
        self.platform,
        "sh",
        side_effect=plt.SubprocessError(self.platform, proc)):
      result = traceconv.convert_profile(self.platform,
                                         pth.LocalPath("/usr/bin/traceconv"),
                                         perf_file)
    self.assertIsNone(result)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
