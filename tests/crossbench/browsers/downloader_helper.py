# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import pathlib
from unittest import mock

from typing_extensions import override

from crossbench.plt.base import Platform
from tests.crossbench.base import BaseCrossbenchTestCase


class AbstractDownloaderTestCase(BaseCrossbenchTestCase, metaclass=abc.ABCMeta):
  __test__ = False

  @override
  def setUp(self) -> None:
    super().setUp()
    self.cache_dir = pathlib.Path("crossbench/binary_cache")
    self.fs.create_dir(self.cache_dir)
    self.platform = self._create_mock_platform()

  def _create_mock_platform(self, spec: type[Platform] = Platform) -> mock.Mock:
    platform = mock.Mock(
        spec=spec,
        is_remote=False,
        is_linux=False,
        is_macos=False,
        exists=self.fs.exists,
        sh_results=[],
        path=pathlib.Path)
    platform.search_app = lambda x: x
    platform.which = pathlib.Path
    platform.local_cache_dir = lambda x: self.cache_dir / x
    platform.host_platform = platform
    return platform
