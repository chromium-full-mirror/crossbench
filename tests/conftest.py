# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from tests import result_sink

if TYPE_CHECKING:
  import pytest


def pytest_configure(config: pytest.Config) -> None:
  luci_context = result_sink.LuciContext.from_env()
  if not result_sink.ResultSinkPlugin.is_result_sink_enabled(luci_context):
    return
  config.option.tbstyle = "long"
  config.option.showlocals = True
  if not config.pluginmanager.has_plugin("crossbench_result_sink_tb"):
    config.pluginmanager.register(
        result_sink.ResultSinkTracebackPlugin(),
        "crossbench_result_sink_tb",
    )
  if config.pluginmanager.has_plugin("crossbench_result_sink"):
    return
  if plugin := result_sink.ResultSinkPlugin.from_env(luci_context):
    config.pluginmanager.register(plugin, "crossbench_result_sink")
