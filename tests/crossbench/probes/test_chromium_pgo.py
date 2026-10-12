# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
from typing import Iterator
from unittest import mock

from crossbench.browsers.chromium.devtools import DevToolsCommandResult
from crossbench.probes.chromium_pgo import ChromiumPgoProbe, \
    ChromiumPgoProbeContextAndroid
from crossbench.runner.run import Run
from tests import test_helper
from tests.crossbench.probes.helper import GenericProbeTestCase


@contextlib.contextmanager
def _mock_devtools_client(
    context: ChromiumPgoProbeContextAndroid,
    response: DevToolsCommandResult) -> Iterator[mock.MagicMock]:
  client = mock.MagicMock()
  client.open.return_value.__enter__.return_value = client
  client.send_command.return_value = response
  with mock.patch.object(context, "_get_devtools_client", return_value=client):
    yield client


class ChromiumPgoProbeContextAndroidTestCase(GenericProbeTestCase):

  def create_context(self) -> ChromiumPgoProbeContextAndroid:
    mock_run = mock.MagicMock(spec=Run)
    mock_run.browser.android_package = "com.android.chrome"
    probe = ChromiumPgoProbe.config_parser().parse({})
    return ChromiumPgoProbeContextAndroid(probe, mock_run)

  def test_trigger_pgo_dump(self) -> None:
    context = self.create_context()
    result = DevToolsCommandResult(True, {"result": {}})
    with _mock_devtools_client(context, result) as client:
      self.assertTrue(context._trigger_pgo_dump())
    client.send_command.assert_called_once_with({
        "method": "NativeProfiling.dumpProfilingDataOfAllProcesses",
        "id": context.PGO_CMD_ID,
    })

  def test_trigger_pgo_dump_failure(self) -> None:
    context = self.create_context()
    error = {"code": -32601, "message": "'NativeProfiling' wasn't found"}
    result = DevToolsCommandResult(False, {"error": error})
    with _mock_devtools_client(context, result):
      self.assertFalse(context._trigger_pgo_dump())

  def test_stop_fails_fast_on_dump_error(self) -> None:
    context = self.create_context()
    error = {"code": -32601, "message": "'NativeProfiling' wasn't found"}
    result = DevToolsCommandResult(False, {"error": error})
    with _mock_devtools_client(context, result):
      with self.assertRaises(RuntimeError):
        context.stop()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
