# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import re
from typing import TYPE_CHECKING

from typing_extensions import override

from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.chrome.webdriver import ChromeWebDriverAndroid
from crossbench.browsers.chromium.webdriver import FLAGS_WEBVIEW

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.settings import Settings
  from crossbench.browsers.version import BrowserVersion

_WEBVIEW_SYSUPDATE_CURRENT_PKG_RE = re.compile(
    r"Current WebView package.*:.*\(([a-z.]*),\s+(\d+\.\d+\.\d+\.\d+)\)")


# TODO: crbug.com/393058910 - Replace this Webview class stub placeholder
# once Webview class is properly created.
class Webview(ChromeWebDriverAndroid, metaclass=abc.ABCMeta):

  @classmethod
  @override
  def attributes(cls) -> BrowserAttributes:
    return ((super().attributes() & ~BrowserAttributes.CHROME)
            | BrowserAttributes.WEBVIEW)

  def __init__(self,
               label: str,
               path: pth.AnyPath | None = None,
               settings: Settings | None = None) -> None:
    super().__init__(label, path, settings)
    self._chrome_command_line_path: pth.AnyPath = FLAGS_WEBVIEW

  @override
  def _extract_version(self) -> BrowserVersion:
    webview_provider = self.platform.sh_stdout("settings", "get", "global",
                                               "webview_provider").strip()
    if webview_provider == "null":
      # If webview_provider is null, we need to use dumpsys webviewupdate
      # to get the webview provider package name.
      dumpsys_output = self.platform.adb.dumpsys("webviewupdate")
      for line in dumpsys_output.splitlines():
        if match := re.search(_WEBVIEW_SYSUPDATE_CURRENT_PKG_RE, line):
          webview_provider = match.group(1)
          break

    return self.version_cls().parse(self.platform.app_version(webview_provider))
