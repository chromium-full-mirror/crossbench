# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from pyfakefs import fake_filesystem_unittest

from crossbench import path as pth
from crossbench import plt
from crossbench.benchmarks.loadline import LoadLine1TabletBenchmark, \
    LoadLine1TabletDebugBenchmark, LoadLine2TabletBenchmark, \
    LoadLine2TabletDebugBenchmark
from crossbench.cli.config.probe_list import ProbeListConfig
from crossbench.helper.cwd import change_cwd
from crossbench.helper.path_finder_base import default_chromium_candidates
from crossbench.probes.all import GENERAL_PURPOSE_PROBES
from tests import test_helper

if TYPE_CHECKING:
  from crossbench.probes.probe import Probe

PROBE_LOOKUP: dict[str, type[Probe]] = {
    probe_cls.NAME: probe_cls for probe_cls in GENERAL_PURPOSE_PROBES
}


class ProbeConfigTestCase(fake_filesystem_unittest.TestCase):
  """Parse all example probe configs in config/probe and config/doc/probe

  More detailed tests should go into dedicated probe/test_{PROBE_NAME}.py
  files.
  """

  def setUp(self) -> None:
    self.real_config_dir = test_helper.config_dir()
    super().setUp()
    self.setUpPyfakefs(modules_to_reload=[pth])
    self._add_real_directory(test_helper.crossbench_dir() /
                             "probes/trace_processor/queries")
    self.set_up_required_paths()

  def set_up_required_paths(self):
    chrome_dir = default_chromium_candidates(plt.PLATFORM)[0]
    self.fs.create_dir(chrome_dir / "v8")
    self.fs.create_dir(chrome_dir / "chrome")
    self.fs.create_dir(chrome_dir / ".git")

    perfetto_tools = chrome_dir / "third_party/perfetto/tools"
    self.fs.create_file(perfetto_tools / "traceconv")
    self.fs.create_file(perfetto_tools / "trace_processor")

  def _test_parse_config_dir(self,
                             real_config_dir: pathlib.Path) -> list[Probe]:
    probes: list[Probe] = []
    self._add_real_directory(real_config_dir)
    # make sure we have a fakefs path
    fake_config_dir = pathlib.Path(real_config_dir)
    for probe_config in fake_config_dir.glob("**/*.config.hjson"):
      with change_cwd(probe_config.parent):
        probes += self._parse_config(probe_config)
    return probes

  def _parse_config(self, config_file: pathlib.Path) -> tuple[Probe, ...]:
    probe_name = config_file.parent.name
    if probe_name not in PROBE_LOOKUP:
      probe_name = config_file.name.split(".")[0]
    probe_cls = PROBE_LOOKUP[probe_name]

    probes = ProbeListConfig.parse(config_file).probes
    self.assertTrue(probes)
    self.assertTrue(any(isinstance(probe, probe_cls) for probe in probes))
    for probe in probes:
      self.assertFalse(probe.is_attached)
    return probes

  def _add_real_directory(self, path: pth.LocalPath) -> None:
    self.fs.add_real_directory(path, lazy_read=True)

  def test_parse_example_configs(self):
    probe_config_presets = self.real_config_dir / "probe"
    probes = self._test_parse_config_dir(probe_config_presets)
    self.assertTrue(probes)

  def test_parse_doc_configs(self):
    probe_config_doc = self.real_config_dir / "doc/probe"
    probes = self._test_parse_config_dir(probe_config_doc)
    self.assertTrue(probes)

  def test_parse_loadline_configs(self):
    self._add_real_directory(
        LoadLine1TabletBenchmark.default_probe_config_path().parent)
    self._add_real_directory(
        LoadLine2TabletBenchmark.default_probe_config_path().parent)
    for cls in (LoadLine1TabletBenchmark, LoadLine1TabletDebugBenchmark,
                LoadLine2TabletBenchmark, LoadLine2TabletDebugBenchmark):
      probe_config = cls.default_probe_config_path()
      probes = ProbeListConfig.parse(probe_config).probes
      self.assertTrue(probes)

  def test_parse_browser_startup_config(self):
    config_path = self.real_config_dir / "benchmark/browser_startup/probe.hjson"
    self._add_real_directory(config_path.parent)
    probes = ProbeListConfig.parse(str(config_path)).probes
    self.assertTrue(probes)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
