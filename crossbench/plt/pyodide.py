# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from typing import TYPE_CHECKING, Final, Protocol

import google.cloud.storage.blob as gcloud_blob  # type: ignore
from typing_extensions import override

from crossbench.plt import linux as plt_linux

if TYPE_CHECKING:
  from crossbench import path as pth

try:
  import js
except ImportError:
  js = None


def is_pyodide_env() -> bool:
  return sys.platform == "emscripten"


class WebAdb(Protocol):
  serial: str

  def gcsGetMetadata(self, url: str) -> str:  # noqa: N802
    ...

  def gcsDownloadFile(self, url: str, dest: str) -> None:  # noqa: N802
    ...

  def isInterrupted(self) -> bool:  # noqa: N802
    ...

  def acknowledgeInterrupt(self) -> None:  # noqa: N802
    ...

  def root(self) -> None:
    ...

  def unroot(self) -> None:
    ...

  def push(self, src: str, dest: str) -> None:
    ...

  def pull(self, src: str, dest: str) -> None:
    ...

  def shell(self, cmd: str) -> str | bytes:
    ...

  def startDevTools(self) -> str:  # noqa: N802
    ...

  def stopDevTools(self) -> str:  # noqa: N802
    ...

  def switchTab(self, url: str = "about:blank") -> str:  # noqa: N802
    ...

  def sendCdpCommand(self, method: str, params: str) -> str:  # noqa: N802
    ...

  def spawnProcess(self, cmd: str) -> int:  # noqa: N802
    ...

  def readProcessLog(self, proc_id: int, offset: int) -> str:  # noqa: N802
    ...

  def killProcess(self, proc_id: int) -> None:  # noqa: N802
    ...


class PyodideGcsBlob(gcloud_blob.Blob):
  """GCS Blob wrapper for Pyodide WebAssembly environment."""

  def __init__(
      self,
      gcs_url: str,
      md5_hash: str = "",
      size: int = 0,
      webadb: WebAdb | None = None,
  ) -> None:
    self._gcs_url: Final[str] = gcs_url
    self._md5_hash: str = md5_hash
    self._size: int = size
    self._webadb: WebAdb | None = webadb
    if self._webadb is None and js is not None:
      self._webadb = js.webadb

  @property
  @override
  # Blob.md5_hash is defined via untyped _scalar_property("md5Hash").
  def md5_hash(self) -> str:  # pyrefly: ignore[bad-override]
    return self._md5_hash

  @property
  @override
  def size(self) -> int:
    return self._size

  @override
  def reload(self, *args: object, **kwargs: object) -> None:
    del args, kwargs
    if self._webadb is None:
      raise RuntimeError("webadb is unavailable in Pyodide.")
    raw_meta = self._webadb.gcsGetMetadata(self._gcs_url)
    if not raw_meta:
      raise FileNotFoundError(f"GCS metadata missing for {self._gcs_url}")
    meta = json.loads(str(raw_meta))
    self._md5_hash = str(meta.get("md5Hash", ""))
    self._size = int(meta.get("size", 0))

  @override
  def download_to_filename(self, filename: str, *args: object,
                           **kwargs: object) -> None:
    del args, kwargs
    if self._webadb is None:
      raise RuntimeError("webadb is unavailable in Pyodide.")
    self._webadb.gcsDownloadFile(self._gcs_url, filename)

  @override
  def exists(self, *args: object, **kwargs: object) -> bool:
    del args, kwargs
    if not self._md5_hash:
      try:
        self.reload()
      except FileNotFoundError:
        return False
    return bool(self._md5_hash)


class PyodidePlatform(plt_linux.LinuxPlatform):
  """Host platform running inside Pyodide/Emscripten WebAssembly."""

  def __init__(self, webadb: WebAdb | None = None) -> None:
    super().__init__()
    if webadb is None and js is not None:
      webadb = js.webadb
    self._webadb: Final[WebAdb | None] = webadb

  @property
  def is_pyodide(self) -> bool:
    return True

  @override
  def get_gcs_blob(self, gcs_url: str) -> PyodideGcsBlob:
    return PyodideGcsBlob(gcs_url, webadb=self._webadb)

  @override
  def lookup_binary_override(
      self, binary_name: pth.AnyPathLike) -> pth.AnyPath | None:
    if str(binary_name) == "wpr":
      for candidate in (
          self.local_cache_dir("webpagereplay") / "android" / "arm64" / "wpr",
          self.local_cache_dir("webpagereplay") / "wpr",
          self.local_path("/third_party/webpagereplay/wpr"),
          self.local_path("/cache/webpagereplay/android/arm64/wpr"),
      ):
        if self.is_file(candidate):
          return candidate
    return super().lookup_binary_override(binary_name)

  @override
  def sleep(self, seconds: float | dt.timedelta) -> None:
    total_secs = (
        seconds.total_seconds()
        if isinstance(seconds, dt.timedelta) else float(seconds))
    if total_secs <= 0:
      return
    start = time.time()
    while time.time() - start < total_secs:
      if self._webadb and self._webadb.isInterrupted():
        self._webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt("Benchmark execution interrupted by user")
      step = min(0.05, total_secs - (time.time() - start))
      if step <= 0:
        break
      time.sleep(step)
