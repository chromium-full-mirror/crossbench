# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse

from typing_extensions import override

from crossbench import path as pth
from crossbench.benchmarks.speedometer.speedometer_3_1 import \
    Speedometer31Benchmark, Speedometer31Probe, Speedometer31ProbeContext, \
    Speedometer31Story
from crossbench.cli.config.network import NetworkConfig, NetworkType
from tests import test_helper
from tests.crossbench.benchmarks.speedometer.helper import \
    Speedometer3BaseTestCase


class Speedometer31TestCase(Speedometer3BaseTestCase):

  @property
  @override
  def benchmark_cls(self):
    return Speedometer31Benchmark

  @property
  @override
  def story_cls(self):
    return Speedometer31Story

  @property
  @override
  def probe_cls(self):
    return Speedometer31Probe

  @property
  @override
  def probe_context_cls(self):
    return Speedometer31ProbeContext

  @property
  @override
  def name(self):
    return "speedometer_3.1"

  def _create_local_checkout(self) -> pth.LocalPath:
    assert self.benchmark_cls.LOCAL_DIR
    # Re-wrap ROOT_DIR so the comparison uses the fake-fs path class.
    local_dir = pth.LocalPath(pth.ROOT_DIR) / self.benchmark_cls.LOCAL_DIR
    self.fs.create_file(local_dir / "index.html")
    return local_dir

  def _namespace(self, **kwargs) -> argparse.Namespace:
    args = self.Namespace(**kwargs)
    args.network_config = NetworkConfig.default()
    return args

  def test_local_dir(self):
    self.assertEqual(
        str(self.benchmark_cls.LOCAL_DIR), "third_party/speedometer/v3.1")

  def test_default_network_config(self):
    local_dir = self._create_local_checkout()
    args = self._namespace()
    config = self.benchmark_cls.default_network_config(args)
    self.assertEqual(config.type, NetworkType.LOCAL)
    self.assertEqual(pth.LocalPath(config.path), local_dir)
    self.assertEqual(config.url, self.benchmark_cls.LOCAL_FILE_SERVER_URL)
    network = config.create_network(self.platform)
    self.assertTrue(network.is_local_file_server)

  def test_default_network_config_no_checkout(self):
    args = self._namespace()
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "local-serve dir"):
      self.benchmark_cls.default_network_config(args)

  def test_default_network_config_explicit_url(self):
    self._create_local_checkout()
    for url in (self.story_cls.URL, self.story_cls.URL_OFFICIAL,
                "http://custom.example.com/"):
      args = self._namespace(custom_benchmark_url=url)
      self.assertTrue(
          self.benchmark_cls.default_network_config(args).is_default())


#  Don't expose abstract BaseTestCase to test runner
del Speedometer3BaseTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
