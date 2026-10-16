# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import pathlib
import tempfile
import urllib.parse
from typing import Any

import pytest

from crossbench.cli.cli import CrossBenchCLI
from tests import test_helper


def _run_loading_test(browser_config: str,
                      page_config: Any,
                      test_env: Any,
                      probe_config_file: pathlib.Path | None = None) -> None:
  with tempfile.NamedTemporaryFile(
      suffix="page.config.json", mode="w",
      encoding="utf-8") as page_config_file:
    json.dump(page_config, page_config_file)
    page_config_file.flush()

    cli = CrossBenchCLI()

    args = [
        "loading",
        f"--browser={browser_config}",
        f"--page-config={page_config_file.name}",
        f"--out-dir={test_env.results_dir}",
        "--env-validation=skip",
        "--action-runner=unified",
        *list(test_env.cq_flags),
    ]
    if probe_config_file:
      args.append(f"--probe-config={probe_config_file}")

    cli.run(args)


def _run_loading_test_with_probes(browser_config: str, page_config: Any,
                                  test_env: Any, probe_config: Any) -> None:
  with tempfile.NamedTemporaryFile(
      suffix="probe.config.json", mode="w",
      encoding="utf-8") as probe_config_file:
    json.dump(probe_config, probe_config_file)
    probe_config_file.flush()

    _run_loading_test(browser_config, page_config, test_env,
                      pathlib.Path(probe_config_file.name))


def test_download(browser_config, test_env):
  test_page = urllib.parse.quote("""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Download Test</title>
  </head>
  <body>
    <a
      id="download"
      href="data:text/plain;charset=utf-8,A Car"
      download="car.txt">
      Download
    </a>
  </body>
</html>
""")

  page_config = {
      "pages": {
          "DownloadTest": {
              "actions": [{
                  "action": "get",
                  "url": f"data:text/html;charset=utf-8,{test_page}",
                  "ready_state": "complete",
              }, {
                  "action": "click",
                  "position": "#download",
              }, {
                  "action": "wait_for_download",
                  "timeout": "10s",
                  "pattern": "car.txt",
              }],
          },
      },
  }

  probe_config = {
      "probes": {
          "downloads": {
              "clear_downloads": True,
              "save_downloads": True,
          },
      },
  }

  _run_loading_test_with_probes(browser_config, page_config, test_env,
                                probe_config)


def _webview_shell_config(device_id, adb_path) -> str:
  return json.dumps({
      "browser": "org.chromium.webview_shell",
      "driver": {
          "type": "adb",
          "device_id": device_id,
          "adb_bin": adb_path,
      },
  })


@pytest.mark.legacy_android_sdk
def test_webview(device_id, adb_path, test_env) -> None:
  browser_config = _webview_shell_config(device_id, adb_path)
  test_page = urllib.parse.quote("""
<!DOCTYPE html>
<html>
<head>
  <title>Loading Test</title>
</head>
<body>
  <div id="content">
    <p>Hello World</p>
  </div>
</body>
</html>
""")

  page_config = {
      "pages": {
          "LoadingTest": {
              "actions": [{
                  "action": "get",
                  "url": f"data:text/html;charset=utf-8,{test_page}",
                  "ready_state": "complete",
              }],
          },
      },
  }

  _run_loading_test(browser_config, page_config, test_env)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
