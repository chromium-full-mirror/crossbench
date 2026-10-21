# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
  from crossbench import path as pth


class BaseUploader(abc.ABC):

  def __init__(self, url: str) -> None:
    self._url: Final[str] = url

  @abc.abstractmethod
  def upload(self, file_path: pth.LocalPath) -> str:
    """Uploads file_path and returns the uploaded file URL/location."""
