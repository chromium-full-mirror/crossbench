# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

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


del BaseInputInjectionTest

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
