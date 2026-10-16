# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import tempfile
import urllib.parse
from typing import TYPE_CHECKING, Final, Mapping

import pytest

from crossbench import path as pth
from crossbench.action_runner.virtual_device.all import DEFAULT_VIRTUAL_DEVICES
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.cli.cli import CrossBenchCLI
from crossbench.cli.config.browser import BrowserConfig

if TYPE_CHECKING:
  from crossbench import plt
  from tests.test_helper import TestEnv

CLICK_TEST_PAGE: Final[str] = urllib.parse.quote("""
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


class BaseInputInjectionTest:

  def get_test_platform(self, browser_config: str) -> plt.Platform:
    return BrowserConfig.parse(browser_config).get_platform()

  def supports_native_input(self, platform: plt.Platform) -> bool:
    return platform.is_linux or platform.is_android or platform.is_chromeos

  def check_input_source_supported(self, browser_config: str,
                                   input_source: InputSource) -> None:
    if input_source not in DEFAULT_VIRTUAL_DEVICES:
      return
    platform = self.get_test_platform(browser_config)
    if not self.supports_native_input(platform):
      pytest.skip(
          f"Native input injection ('{input_source}') is not supported on "
          f"{platform}")
    if platform.is_headless:
      pytest.skip(
          f"Native input injection ('{input_source}') requires a display on "
          f"{platform}")

  def run_loading_test(self, browser_config: str, page_config: Mapping[str,
                                                                       object],
                       test_env: TestEnv) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
      page_config_file = pth.LocalPath(tmp_dir) / "page.config.json"
      page_config_file.write_text(json.dumps(page_config), encoding="utf-8")

      cli = CrossBenchCLI()

      args = [
          "loading",
          f"--browser={browser_config}",
          f"--page-config={page_config_file}",
          f"--out-dir={test_env.results_dir}",
          "--env-validation=skip",
          "--throw",
          *list(test_env.cq_flags),
      ]
      platform = self.get_test_platform(browser_config)
      if platform.is_headless:
        args.append("--headless")

      try:
        cli.run(args)
      except NotImplementedError as e:
        if "uinput injection is only supported on Android SDK" in str(e):
          pytest.skip(f"Skipping test on unsupported Android SDK: {e}")
        raise

  @pytest.mark.parametrize("input_source", [
      InputSource.JS,
      InputSource.TOUCH,
      InputSource.MOUSE,
      InputSource.DRIVER,
  ])
  def test_click(self, browser_config: str, input_source: InputSource,
                 test_env: TestEnv) -> None:
    self.check_input_source_supported(browser_config, input_source)
    page_config = {
        "pages": {
            "ClickTest": {
                "actions": [
                    {
                        "action":
                            "get",
                        "url":
                            f"data:text/html;charset=utf-8,{CLICK_TEST_PAGE}",
                        "ready_state":
                            "complete",
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

    self.run_loading_test(browser_config, page_config, test_env)

  @pytest.mark.parametrize("input_source",
                           [InputSource.KEYBOARD, InputSource.JS])
  def test_keyboard(self, browser_config: str, input_source: InputSource,
                    test_env: TestEnv) -> None:
    self.check_input_source_supported(browser_config, input_source)
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

    self.run_loading_test(browser_config, page_config, test_env)

  @pytest.mark.parametrize("input_source", [InputSource.TOUCH, InputSource.JS])
  def test_scroll(self, browser_config: str, input_source: InputSource,
                  test_env: TestEnv) -> None:
    self.check_input_source_supported(browser_config, input_source)
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
            "ScrollTest": {
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
                        "source": str(input_source),
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

    self.run_loading_test(browser_config, page_config, test_env)
