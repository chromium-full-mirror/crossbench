# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pytest

from tests import test_helper
from tests.end2end.input_injection_test_helper import BaseInputInjectionTest


@pytest.fixture
def browser_config(test_chrome_name: str) -> str:
  return test_chrome_name


@pytest.mark.xdist_group("end2end-benchmark")
class TestDesktopInputInjection(BaseInputInjectionTest):
  pass


del BaseInputInjectionTest

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
