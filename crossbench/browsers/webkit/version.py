# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import re

from typing_extensions import override

from crossbench.browsers.version import BrowserVersion, \
    BrowserVersionChannel, VersionParseResult

_SIMPLE_VERSION_RE = re.compile(
    r"webkit(?:[ -]nightly)?[ -]?"
    r"(?P<parts>\d+)(?:@main)?", re.I)


class WebKitVersion(BrowserVersion):

  @classmethod
  @override
  def default_channel(cls) -> BrowserVersionChannel:
    return BrowserVersionChannel.PRE_ALPHA

  @classmethod
  @override
  def _parse(cls, full_version: str) -> VersionParseResult:
    if "webkit" not in full_version.lower():
      raise cls.parse_error("Could not extract version number", full_version)
    full_version = full_version.strip()
    if matches := _SIMPLE_VERSION_RE.fullmatch(full_version):
      part = int(matches["parts"])
      return VersionParseResult((part,), BrowserVersionChannel.PRE_ALPHA,
                                f"WebKit Nightly {part}")
    raise cls.parse_error("Invalid version", full_version)

  @property
  @override
  def has_complete_parts(self) -> bool:
    return True

  @override
  def _channel_name(self, channel: BrowserVersionChannel) -> str:
    if channel == BrowserVersionChannel.PRE_ALPHA:
      return "nightly"
    raise ValueError(f"Unsupported channel: {channel}")

  @property
  @override
  def key(self) -> tuple[tuple[int, ...], BrowserVersionChannel]:
    return (self.parts, self._channel)
