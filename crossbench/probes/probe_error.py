# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import Probe


class ProbeMissingDataError(ValueError):
  pass


class ProbeValidationError(ValueError):

  def __init__(self, probe: Probe, message: str) -> None:
    self.probe: Final[Probe] = probe
    super().__init__(f"Probe({probe.NAME}): {message}")


class ProbeIncompatibleBrowser(ProbeValidationError):

  def __init__(self,
               probe: Probe,
               browser: Browser,
               message: str = "Incompatible browser") -> None:
    # Note: The 6 spaces of explicit indentation on the second line matches the
    # expected implied indentation from the runner's exception formatter.
    # This is a bit hacky, but refactoring the exception formatter for this
    # would be overkill.
    super().__init__(
        probe, f"{message}\n"
        f"      Got: browser={browser}, platform={browser.platform}")
