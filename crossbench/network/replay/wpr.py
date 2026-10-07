# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Final, Iterable, Iterator, Self, TypeVar

from typing_extensions import override

from crossbench.flags.base import Flags
from crossbench.helper.path_finder import WprGoFinder
from crossbench.network.replay.base import GS_PREFIX, ReplayNetwork
from crossbench.network.replay.web_page_replay import WprReplayServer

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.browsers.browser import Browser
  from crossbench.network.base import TrafficShaper
  from crossbench.plt import Platform
  from crossbench.runner.groups.session import BrowserSessionRunGroup

  WprReplayNetworkT = TypeVar("WprReplayNetworkT", bound="WprReplayNetwork")

# use value for pylint
assert GS_PREFIX


class WprReplayNetwork(ReplayNetwork):

  def __init__(self,
               archive: pth.LocalPath | str,
               traffic_shaper: TrafficShaper | None,
               browser_platform: Platform,
               persist_server: bool,
               inject_deterministic_script: bool,
               no_archive_certificates: bool,
               response_transformations_file: pth.LocalPath | None,
               cross_platform_mode: bool,
               host: str | None,
               http_port: int | None = None,
               https_port: int | None = None,
               expected_md5_hash: bytes | str = b"") -> None:
    super().__init__(archive, traffic_shaper, browser_platform,
                     expected_md5_hash)
    self._server: WprReplayServer | None = None
    self._tmp_dir: pth.AnyPath | None = None
    self._persist_server: Final[bool] = persist_server
    self._inject_deterministic_script: Final[bool] = inject_deterministic_script
    self._no_archive_certificates: Final[bool] = no_archive_certificates
    self._response_transformations_file: (pth.LocalPath |
                                          None) = response_transformations_file
    self._cross_platform_mode: Final[bool] = cross_platform_mode
    self._wpr_go_bin: Final[pth.LocalPath] = WprGoFinder(
        self.host_platform).wpr(self._wpr_platform)
    self._host: Final[str | None] = host
    self._http_port: Final[int | None] = http_port
    self._https_port: Final[int | None] = https_port

  def set_response_transformations_file(self, file: pth.LocalPath) -> None:
    assert not self._server
    self._response_transformations_file = file

  @override
  def validate(self, browser: Browser) -> None:
    super().validate(browser)
    if (not browser.attributes().is_chromium_based and
        not self._cross_platform_mode):
      raise ValueError(
          f"Non chromium-based browser {browser.unique_name} only supports "
          "wpr replay in cross-platform mode. See ./cb.py "
          "setup-cross-platform-mode")

  @override
  def extra_flags(self, browser_attributes: BrowserAttributes) -> Flags:
    if self._cross_platform_mode:
      return Flags()

    assert self.is_running, "Extra network flags are not valid"
    assert self._server, "WPR server is not running"
    # TODO: make ports configurable.
    extra_flags = super().extra_flags(browser_attributes)
    # TODO: read this from wpr_public_hash.txt like in the recorder probe
    extra_flags["--ignore-certificate-errors-spki-list"] = (
        "PhrPvGIaAMmd29hj8BCZOq096yj7uMpRNHpn5PDxI6I=,"
        "2HcXCSKKJS0lEXLQEWhpHUfGuojiU0tiT5gOF9LP6IQ=")
    if self._traffic_shaper.is_live:
      # Only remap ports if we're not using the SOCKS proxy from the traffic
      # shaper.
      extra_flags["--host-resolver-rules"] = (
          f"MAP *:80 {self.host}:{self.http_port},"
          f"MAP *:443 {self.host}:{self.https_port},"
          "EXCLUDE localhost")

    return extra_flags

  @abc.abstractmethod
  def _create_server(self, log_dir: pth.LocalPath) -> WprReplayServer:
    pass

  @contextlib.contextmanager
  @override
  def open(self, session: BrowserSessionRunGroup) -> Iterator[Self]:
    with super().open(session):
      yield self

  def _ensure_server_started(self, session: BrowserSessionRunGroup) -> None:
    log_dir = session.browser_dir if self._persist_server else session.out_dir
    if not self._server or not self._persist_server:
      self._server = self._create_server(log_dir)
      logging.debug("Starting WPR server")
      self._server.start()
    else:
      # TODO: reset wpr server state for reuse
      logging.debug("WPR server already started")

  @contextlib.contextmanager
  @override
  def _open_replay_server(self,
                          session: BrowserSessionRunGroup) -> Iterator[None]:
    self._ensure_server_started(session)
    try:
      yield
    finally:
      if not self._persist_server and self._server:
        try:
          self._server.stop()
        finally:
          self._server = None

  @property
  @override
  def http_port(self) -> int:
    assert self._server, "WPR is not running"
    return self._server.http_port

  @property
  @override
  def https_port(self) -> int:
    assert self._server, "WPR is not running"
    return self._server.https_port

  @property
  @override
  def host(self) -> str:
    assert self._server, "WPR is not running"
    return self._server.host

  @property
  @abc.abstractmethod
  def _wpr_platform(self) -> Platform:
    pass

  @override
  def __str__(self) -> str:
    return f"WPR(archive={self.archive_path}, speed={self.traffic_shaper})"


class LocalWprReplayNetwork(WprReplayNetwork):

  @property
  @override
  def _wpr_platform(self) -> Platform:
    return self.host_platform

  @contextlib.contextmanager
  @override
  def open(self: LocalWprReplayNetwork,
           session: BrowserSessionRunGroup) -> Iterator[LocalWprReplayNetwork]:
    with super().open(session):
      with self._forward_ports(session):
        yield self

  @contextlib.contextmanager
  def _forward_ports(self, session: BrowserSessionRunGroup) -> Iterator:
    browser_platform = session.browser_platform
    need_forward_ports = (
        self._traffic_shaper.is_live and browser_platform.is_remote and
        not self._cross_platform_mode)
    if not need_forward_ports:
      yield
      return
    http_port: int = self.http_port
    https_port: int = self.https_port
    logging.info("REMOTE PORT FORWARDING: %s <= %s", self.host_platform,
                 browser_platform)
    # TODO: make ports configurable
    with browser_platform.ports.nested() as ports:
      ports.reverse_forward(http_port, http_port)
      ports.reverse_forward(https_port, https_port)
      yield
      # port cleanup happens automatically

  @override
  def _create_server(self, log_dir: pth.LocalPath) -> WprReplayServer:
    http_port: int = self._http_port or 0
    https_port: int = self._https_port or 0
    inject_scripts: Iterable[pth.AnyPath] | None = None
    if not self._inject_deterministic_script:
      inject_scripts = []
    run_as_root: bool = False
    if self._cross_platform_mode:
      http_port = 80
      https_port = 443
      run_as_root = True
    host: str = self._host or "127.0.0.1"

    return WprReplayServer(
        self.archive_path,
        self._wpr_go_bin,
        http_port=http_port,
        https_port=https_port,
        host=host,
        inject_scripts=inject_scripts,
        log_path=log_dir / "network.wpr.log",
        no_archive_certificates=self._no_archive_certificates,
        rules_file=self._response_transformations_file,
        run_as_root=run_as_root,
        platform=self.host_platform)


class RemoteWprReplayNetwork(WprReplayNetwork):

  def __init__(self,
               archive: pth.LocalPath | str,
               traffic_shaper: TrafficShaper | None,
               browser_platform: Platform,
               persist_server: bool,
               inject_deterministic_script: bool,
               no_archive_certificates: bool,
               response_transformations_file: pth.LocalPath | None,
               host: str | None,
               http_port: int | None = None,
               https_port: int | None = None,
               expected_md5_hash: bytes | str = b"") -> None:
    super().__init__(
        archive=archive,
        traffic_shaper=traffic_shaper,
        browser_platform=browser_platform,
        persist_server=persist_server,
        inject_deterministic_script=inject_deterministic_script,
        no_archive_certificates=no_archive_certificates,
        response_transformations_file=response_transformations_file,
        cross_platform_mode=False,
        host=host,
        http_port=http_port,
        https_port=https_port,
        expected_md5_hash=expected_md5_hash)

  @property
  @override
  def _wpr_platform(self) -> Platform:
    return self.browser_platform

  @classmethod
  def is_compatible(cls, platform: Platform) -> bool:
    return platform.is_android or platform.is_chromeos

  @contextlib.contextmanager
  @override
  def open(self: RemoteWprReplayNetwork,
           session: BrowserSessionRunGroup) -> Iterator[RemoteWprReplayNetwork]:
    with self._remote_temp_dir(session):
      with super().open(session):
        yield self

  @contextlib.contextmanager
  def _remote_temp_dir(self, session: BrowserSessionRunGroup) -> Iterator:
    with session.browser_platform.TemporaryDirectory() as tmp_dir:
      try:
        self._tmp_dir = tmp_dir
        yield
      finally:
        self._tmp_dir = None

  def _push_file(self, path: pth.LocalPath) -> pth.AnyPath:
    assert self._tmp_dir is not None
    remote_path = self._tmp_dir / path.name
    self.browser_platform.push(path, remote_path)
    return remote_path

  @override
  def _create_server(self, log_dir: pth.LocalPath) -> WprReplayServer:
    assert not self._cross_platform_mode

    wpr_go_bin = self._push_file(self._wpr_go_bin)
    self.browser_platform.chmod(wpr_go_bin, 0o755)
    archive: pth.AnyPath = self._push_file(self._archive_path)
    wpr_root = WprGoFinder(self.host_platform).local_path
    # Already validated on construction.
    assert wpr_root is not None
    key_file: pth.AnyPath = self._push_file(wpr_root / "ecdsa_key.pem")
    cert_file: pth.AnyPath = self._push_file(wpr_root / "ecdsa_cert.pem")
    inject_scripts: list[pth.AnyPath] = []
    if self._inject_deterministic_script:
      inject_scripts = [self._push_file(wpr_root / "deterministic.js")]
    rules_file: pth.AnyPath | None = None
    if file := self._response_transformations_file:
      rules_file = self._push_file(file)
    for script in self._get_injected_scripts():
      self._push_file(script)

    return WprReplayServer(
        archive_path=archive,
        bin_path=wpr_go_bin,
        http_port=self._http_port or 0,
        https_port=self._https_port or 0,
        key_file=key_file,
        cert_file=cert_file,
        inject_scripts=inject_scripts,
        log_path=log_dir / "network.wpr.log",
        platform=self.browser_platform,
        rules_file=rules_file)

  def _get_injected_scripts(self) -> list[pth.LocalPath]:
    if not self._response_transformations_file:
      return []

    with self._response_transformations_file.open() as f:
      transformations = json.load(f)
    assert isinstance(transformations, list)
    assert all(isinstance(t, dict) for t in transformations)

    transformations_dir: pth.LocalPath = (
        self._response_transformations_file.parent)
    scripts: list[pth.LocalPath] = []
    for transformation in transformations:
      if injected_script := transformation.get("InjectedScript"):
        script: pth.LocalPath = transformations_dir / injected_script
        if not script.exists():
          raise ValueError(
              f"{self._response_transformations_file} attempts to inject "
              f"{script} but the script was not found")
        scripts.append(script)
    return scripts
