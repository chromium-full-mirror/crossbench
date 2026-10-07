# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import pathlib
import tempfile
import urllib.parse
from typing import Any, Final

import pytest

from crossbench.benchmarks.loading.input_source import InputSource
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
        "--action-runner=android",
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


_CLICK_TEST_PAGE: Final[str] = urllib.parse.quote("""
<!DOCTYPE html>
<html>
<body>
  <button id="button">Click me</button>
  <script>
    const button = document.getElementById('button');

    button.addEventListener('click',
    function() {
      button.id = "clicked-button";
    });
  </script>
</body>
</html>
""")


@pytest.mark.parametrize("input_source", [
    InputSource.JS,
    InputSource.TOUCH,
    InputSource.MOUSE,
    InputSource.DRIVER,
])
def test_click(browser_config, input_source, test_env) -> None:
  page_config = {
      "pages": {
          "ClickTest": {
              "actions": [
                  {
                      "action": "get",
                      "url": f"data:text/html;charset=utf-8,{_CLICK_TEST_PAGE}",
                      "ready_state": "complete",
                  },
                  {
                      "action": "click",
                      "position": {
                          "selector": "button[id='button']",
                          "required": True,
                          "scroll_into_view": True,
                          "wait": True,
                      },
                      "verify": "button[id='clicked-button']",
                      "source": str(input_source),
                  },
              ],
          },
      },
  }

  _run_loading_test(browser_config, page_config, test_env)


@pytest.mark.parametrize("input_source", [InputSource.TOUCH, InputSource.MOUSE])
def test_click_ui_selector(browser_config, input_source, test_env) -> None:
  page_config = {
      "pages": {
          "ClickTest": {
              "actions": [
                  {
                      "action": "get",
                      "url": f"data:text/html;charset=utf-8,{_CLICK_TEST_PAGE}",
                      "ready_state": "complete",
                  },
                  {
                      "action": "click",
                      "position": {
                          "text": "Click me",
                      },
                      "verify": "button[id='clicked-button']",
                      "source": str(input_source),
                  },
              ],
          },
      },
  }

  _run_loading_test(browser_config, page_config, test_env)


@pytest.mark.parametrize("input_source", [InputSource.KEYBOARD, InputSource.JS])
def test_keyboard(browser_config, input_source, test_env) -> None:
  test_text = "abcd"
  expected_text_json = json.dumps(test_text)

  test_page = urllib.parse.quote(f"""
<!DOCTYPE html>
<html>
<body>
  <textarea id="input"
    autofocus
    autocomplete="off"
    autocorrect="off"
    autocapitalize="off"
    spellcheck="false"></textarea>
  <script>
    const input = document.getElementById('input');
    const inputTimestamps = [];

    input.addEventListener('input', function() {{
      inputTimestamps.push(performance.now());
    }});

    function check() {{
      if (input.value !== {expected_text_json}) {{
        return;
      }}

      // Verify timing for KEYBOARD input source.
      // JS input sets the value in a single operation without delays.
      if (inputTimestamps.length > 1) {{
        const totalDuration =
            inputTimestamps[inputTimestamps.length - 1] - inputTimestamps[0];
        // For 4 characters over 2s duration, each character delay is ~500ms.
        // Total elapsed time between 1st and 4th character input events
        // should be ~1500ms (acceptable range: 500ms to 4000ms).
        if (totalDuration < 500 || totalDuration > 4000) {{
          console.error('Total typing duration out of bounds:', totalDuration);
          return;
        }}

        // Each individual character delay should be ~500ms (range: 100-1500ms).
        for (let i = 1; i < inputTimestamps.length; i++) {{
          const delta = inputTimestamps[i] - inputTimestamps[i - 1];
          if (delta < 100 || delta > 1500) {{
            console.error('Interval out of bounds:', i, delta);
            return;
          }}
        }}
      }}

      input.id = 'typed-input';
    }}

    input.addEventListener('input', check);
    input.addEventListener('change', check);
    input.addEventListener('keyup', check);
    setInterval(check, 100);
  </script>
</body>
</html>
""")

  page_config = {
      "pages": {
          "KeyboardTest": {
              "actions": [
                  {
                      "action": "get",
                      "url": f"data:text/html;charset=utf-8,{test_page}",
                      "ready_state": "complete",
                  },
                  {
                      "action": "js",
                      "script": "document.getElementById('input').focus();",
                  },
                  {
                      "action": "wait",
                      "duration": "1s",
                  },
                  {
                      "action": "text_input",
                      "text": test_text,
                      "duration": "2s",
                      "source": str(input_source),
                  },
                  {
                      "action": "wait_for_element",
                      "selector": "textarea[id='typed-input']",
                      "timeout": "15s",
                  },
              ],
          },
      },
  }

  try:
    _run_loading_test(browser_config, page_config, test_env)
  except NotImplementedError as e:
    if "uinput injection is only supported on Android SDK" in str(e):
      pytest.skip(f"Skipping keyboard test on unsupported Android SDK: {e}")
    raise


def test_scroll(browser_config, test_env) -> None:

  test_page = urllib.parse.quote("""
<!DOCTYPE html>
<html>
<head>
  <title>Scroll Test</title>
  <style>
    #scrollable-area {
      height: 200px;
      overflow-y: auto;
    }
    #content {
      height: 500px;
    }
  </style>
</head>
<body>
  <div id="no-scroll"></div>
  <div id="scrollable-area">
    <div id="content">
    </div>
  </div>
  <script>
    const scrollableArea = document.getElementById('scrollable-area');
    scrollableArea.addEventListener('scroll', function() {
      document.getElementById('no-scroll').id = 'yes-scroll';
    });
  </script>
</body>
</html>
""")

  page_config = {
      "pages": {
          "ClickTest": {
              "actions": [
                  {
                      "action": "get",
                      "url": f"data:text/html;charset=utf-8,{test_page}",
                      "ready_state": "complete",
                  },
                  {
                      "action": "wait_for_element",
                      "selector": "div[id='scrollable-area']",
                      "timeout": "10s",
                  },
                  {
                      "action": "scroll",
                      "selector": "div[id='scrollable-area']",
                      "required": True,
                      "source": "touch",
                      "distance": 50,
                  },
                  {
                      "action": "wait_for_element",
                      "selector": "div[id='yes-scroll']",
                      "timeout": "1s",
                  },
                  {
                      "action":
                          "wait_for_condition",
                      "condition":
                          "return !!document.getElementById('yes-scroll')",
                      "timeout":
                          "1s",
                  },
              ],
          },
      },
  }

  _run_loading_test(browser_config, page_config, test_env)


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
