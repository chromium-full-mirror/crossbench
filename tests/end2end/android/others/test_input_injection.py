# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

import pytest

from crossbench.benchmarks.loading.input_source import InputSource
from tests import test_helper
from tests.end2end.input_injection_test_helper import CLICK_TEST_PAGE, \
    BaseInputInjectionTest

if TYPE_CHECKING:
  from tests.test_helper import TestEnv


class TestAndroidInputInjection(BaseInputInjectionTest):

  @pytest.mark.parametrize("input_source",
                           [InputSource.TOUCH, InputSource.MOUSE])
  def test_click_ui_selector(self, browser_config: str,
                             input_source: InputSource,
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
                            "text": "Click me",
                        },
                        "verify": "button[id='clicked-button']",
                        "source": str(input_source),
                    },
                ],
            },
        },
    }

    self.run_loading_test(browser_config, page_config, test_env)

  def test_android_keycodes(self, browser_config: str,
                            test_env: TestEnv) -> None:
    self.check_input_source_supported(browser_config, InputSource.KEYBOARD)
    second_page = urllib.parse.quote("""
<!DOCTYPE html>
<html>
<body>
  <div id="page-2">Page 2</div>
</body>
</html>
""")
    page_config = {
        "pages": {
            "AndroidKeycodesTest": {
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
                        "source": str(InputSource.TOUCH),
                    },
                    {
                        "action": "get",
                        "url": f"data:text/html;charset=utf-8,{second_page}",
                        "ready_state": "complete",
                    },
                    {
                        "action": "wait_for_element",
                        "selector": "div[id='page-2']",
                        "timeout": "5s",
                    },
                    # Open Android Overview with KEYCODE_APP_SWITCH. The first
                    # KEYCODE_BACK dismisses Overview and returns to Chrome on
                    # page-2 (whereas if Overview had not opened, Chrome would
                    # have navigated back to the first page immediately).
                    {
                        "action": "text_input",
                        "keyevent": "KEYCODE_APP_SWITCH",
                        "source": str(InputSource.KEYBOARD),
                    },
                    {
                        "action": "wait",
                        "duration": "1s",
                    },
                    {
                        "action": "text_input",
                        "keyevent": "KEYCODE_BACK",
                        "source": str(InputSource.KEYBOARD),
                    },
                    {
                        "action": "wait",
                        "duration": "1s",
                    },
                    {
                        "action": "wait_for_element",
                        "selector": "div[id='page-2']",
                        "timeout": "5s",
                    },
                    # Now that Chrome is focused again, the second KEYCODE_BACK
                    # navigates back to the first page.
                    {
                        "action": "text_input",
                        "keyevent": "KEYCODE_BACK",
                        "source": str(InputSource.KEYBOARD),
                    },
                    {
                        "action": "wait_for_element",
                        "selector": "button",
                        "timeout": "5s",
                    },
                    {
                        "action": "text_input",
                        "keyevent": "KEYCODE_HOME",
                        "source": str(InputSource.KEYBOARD),
                    },
                    {
                        "action": "wait_for_condition",
                        "condition": "return !document.hasFocus();",
                        "timeout": "5s",
                    },
                ],
            },
        },
    }

    self.run_loading_test(browser_config, page_config, test_env)

  def test_mouse_move(self, browser_config: str, test_env: TestEnv) -> None:
    self.check_input_source_supported(browser_config, InputSource.MOUSE)
    test_page = urllib.parse.quote("""
<!DOCTYPE html>
<html>
<body style="margin: 0; width: 100vw; height: 100vh;">
  <script>
    let startPoint = null;
    window.addEventListener('mousemove', (e) => {
      if (!startPoint) {
        startPoint = { x: e.clientX, y: e.clientY };
        return;
      }
      if (e.clientX > startPoint.x + 50 && e.clientY > startPoint.y + 50) {
        document.body.id = 'mouse-moved';
      }
    });
  </script>
</body>
</html>
""")
    page_config = {
        "pages": {
            "MouseMoveTest": {
                "actions": [
                    {
                        "action": "get",
                        "url": f"data:text/html;charset=utf-8,{test_page}",
                        "ready_state": "complete",
                    },
                    {
                        "action": "mouse_move",
                        "waypoints": [
                            {
                                "x": 150,
                                "y": 400,
                            },
                            {
                                "x": 350,
                                "y": 400,
                            },
                            {
                                "x": 350,
                                "y": 600,
                            },
                        ],
                        "duration": "300ms",
                    },
                    {
                        "action": "wait_for_element",
                        "selector": "body[id='mouse-moved']",
                        "timeout": "5s",
                    },
                ],
            },
        },
    }

    self.run_loading_test(browser_config, page_config, test_env)


del BaseInputInjectionTest

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
