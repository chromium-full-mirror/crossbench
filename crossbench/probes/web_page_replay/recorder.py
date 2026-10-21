# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING, ClassVar, Final, Iterable, Self, TypedDict

from typing_extensions import override

from crossbench.helper import fs_helper
from crossbench.helper.path_finder import WprGoFinder
from crossbench.network.replay.web_page_replay import WprRecorder
from crossbench.parse import NumberParser, ObjectParser, PathParser
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeContext
from crossbench.probes.results import EmptyProbeResult, LocalProbeResult, \
    ProbeResult, ProbeResultDict

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.browsers.browser import Browser
  from crossbench.plt.base import Platform
  from crossbench.plt.port_manager import PortScope
  from crossbench.runner.groups.base import RunGroup
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.repetitions import RepetitionsRunGroup
  from crossbench.runner.groups.stories import StoriesRunGroup
  from crossbench.runner.run import Run

  class WprRecorderKwargs(TypedDict):
    http_port: int
    https_port: int
    inject_scripts: Iterable[pth.LocalPath] | None
    key_file: pth.LocalPath | None
    cert_file: pth.LocalPath | None


class WebPageReplayProbe(Probe):
  """
  Probe to collect browser requests to webpagereplay archive which then can be
  replayed using a local proxy server.

  Chrome telemetry's webpagereplay:
  https://chromium.googlesource.com/webpagereplay/+/HEAD/README.md
  """

  NAME: ClassVar = "wpr"

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "http_port",
        type=NumberParser.port_number,
        default=8080,
        required=False)
    parser.add_argument(
        "https_port",
        type=NumberParser.port_number,
        default=8081,
        required=False)
    parser.add_argument(
        "key_file", type=PathParser.existing_file_path, required=False)
    parser.add_argument(
        "cert_file", type=PathParser.existing_file_path, required=False)
    parser.add_argument(
        "inject_scripts",
        is_list=True,
        type=PathParser.existing_file_path,
        required=False)
    parser.add_argument(
        "use_test_root_certificate",
        type=ObjectParser.bool,
        default=False,
        required=False)
    parser.add_argument(
        "record_setup",
        type=ObjectParser.bool,
        default=True,
        help="Also include the requests that are part of "
        "the setup / login steps, "
        "which might include passwords.")
    return parser

  def __init__(self,
               http_port: int = 0,
               https_port: int = 0,
               inject_scripts: Iterable[pth.LocalPath] | None = None,
               key_file: pth.LocalPath | None = None,
               cert_file: pth.LocalPath | None = None,
               use_test_root_certificate: bool = False,
               record_setup: bool = True) -> None:
    super().__init__()
    self._recorder_kwargs: Final[WprRecorderKwargs] = {
        "http_port": http_port,
        "https_port": https_port,
        "inject_scripts": inject_scripts,
        "key_file": key_file,
        "cert_file": cert_file,
    }

    self._https_port: Final[int] = https_port
    self._http_port: Final[int] = http_port
    self._use_test_root_certificate: Final[bool] = use_test_root_certificate
    self._record_setup: Final[bool] = record_setup

  @property
  def https_port(self) -> int:
    return self._https_port

  @property
  def http_port(self) -> int:
    return self._http_port

  @property
  def recorder_kwargs(self) -> WprRecorderKwargs:
    return self._recorder_kwargs

  @property
  def use_test_root_certificate(self) -> bool:
    return self._use_test_root_certificate

  @property
  def record_setup(self) -> bool:
    return self._record_setup

  @property
  @override
  def result_path_name(self) -> str:
    return "archive.wprgo"

  def is_compatible(self, browser: Browser) -> bool:
    return browser.attributes().is_chromium_based and browser.platform.is_local

  @override
  def get_context_cls(self) -> type[WprRecorderProbeContext]:
    return WprRecorderProbeContext

  @override
  def merge_repetitions(self, group: RepetitionsRunGroup) -> ProbeResult:
    results = [run.results[self].file for run in group.runs]
    return self.merge_group(results, group)

  @override
  def merge_stories(self, group: StoriesRunGroup) -> ProbeResult:
    results = [
        subgroup.results[self].file for subgroup in group.repetitions_groups
    ]
    return self.merge_group(results, group)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    results = [subgroup.results[self].file for subgroup in group.story_groups]
    return self.merge_group(results, group)

  def merge_group(self, results: list[pth.LocalPath],
                  group: RunGroup) -> ProbeResult:
    result_file = group.get_local_probe_result_path(self)
    if not results:
      return EmptyProbeResult()
    first_wprgo = results.pop(0)
    # TODO migrate to platform
    shutil.copy(first_wprgo, result_file)
    for repetition_file in results:
      self.httparchive_merge(repetition_file, result_file)
    return LocalProbeResult(file=[result_file])

  def httparchive_merge(self, input_archive: pth.LocalPath,
                        output_archive: pth.LocalPath) -> None:
    self.host_platform.sh(
        WprGoFinder(self.host_platform).httparchive(),
        "merge",
        output_archive,
        input_archive,
        output_archive,
    )

  @override
  def log_run_result(self, run: Run) -> None:
    self._log_results(run.results)

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    self._log_results(group.results)

  def _log_results(self, result_dict: ProbeResultDict) -> None:
    if self not in result_dict:
      return
    wpr_archive: pth.LocalPath = result_dict[self].file
    logging.info("-" * 80)
    logging.critical("WPR archive:")
    logging.critical("  %s [%s]", wpr_archive,
                     fs_helper.get_file_size(wpr_archive))


class WprRecorderProbeContext(ProbeContext[WebPageReplayProbe]):

  def __init__(self, probe: WebPageReplayProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._wprgo_log: Final[pth.LocalPath] = self.local_result_path.with_name(
        "wpr_record.log")
    self._host: Final[str] = "127.0.0.1"
    self._recorder: Final[WprRecorder] = WprRecorder(
        platform=run.host_platform,
        log_path=self._wprgo_log,
        archive_path=self.result_path,
        bin_path=WprGoFinder(run.host_platform).wpr(run.host_platform),
        **self.probe.recorder_kwargs,
    )
    self._browser_platform: Final[Platform] = run.browser_platform
    self._ports: PortScope = run.host_platform.ports

  @override
  def setup(self) -> None:
    self._recorder.start()
    self._setup_extra_flags()
    self._setup_port_forwarding()

  def _setup_extra_flags(self) -> None:
    if not self.probe.use_test_root_certificate:
      cert_hash_file = self._recorder.cert_file.parent / "wpr_public_hash.txt"
      if not cert_hash_file.is_file():
        raise ValueError(
            f"Could not read public key hash file: {cert_hash_file}")
      cert_skip_list = ",".join(cert_hash_file.read_text().strip().splitlines())
      self.session.extra_flags[
          "--ignore-certificate-errors-spki-list"] = cert_skip_list
    # TODO: support ts_proxy traffic shaping
    # session.extra_flags["--proxy-server"] =  (
    #   "socks://{self._ts_proxy_host}:{self._ts_proxy_port}")
    # session.extra_flags["--proxy-bypass-list"] = "<-loopback>"
    self.session.extra_flags["--host-resolver-rules"] = (
        f"MAP *:80 {self._host}:{self._recorder.http_port},"
        f"MAP *:443 {self._host}:{self._recorder.https_port},"
        "EXCLUDE localhost")
    # TODO: add replay support, see:
    # https://crsrc.org/c/third_party/catapult/telemetry/telemetry/internal/backends/chrome/chrome_startup_args.py

  def _setup_port_forwarding(self) -> None:
    if self._browser_platform.is_remote:
      # TODO: Fix run.setup and teardown layering so they they're called with
      # the same active port scope.
      self._ports = self._browser_platform.ports
      self._ports.reverse_forward(self._recorder.http_port,
                                  self._recorder.http_port)
      self._ports.reverse_forward(self._recorder.https_port,
                                  self._recorder.https_port)

  def start(self) -> None:
    if not self.probe.record_setup:
      assert self._recorder, "Recorder not initialized"
      self._recorder.clear()

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    self._teardown_port_forwarding()
    self._recorder.stop()
    return LocalProbeResult(file=(self.local_result_path,))

  def _teardown_port_forwarding(self) -> None:
    if self._browser_platform.is_remote:
      self._ports.stop_reverse_forward(self._recorder.http_port)
      self._ports.stop_reverse_forward(self._recorder.https_port)
