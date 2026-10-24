#!/usr/bin/env vpython3
# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import os
import pathlib
import sys
from typing import Final

FILE_PATH: Final = pathlib.Path(__file__).absolute()
TEST_DIR: Final = FILE_PATH.parent
REPO_DIR: Final = FILE_PATH.parents[2]

if REPO_DIR not in sys.path:
  sys.path.insert(0, str(REPO_DIR))

from tests import test_helper  # noqa: E402

if __name__ == "__main__":
  os.chdir(REPO_DIR)
  test_helper.run_pytest(TEST_DIR, "-n", "auto", retries=1)
