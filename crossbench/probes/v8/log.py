# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import concurrent.futures
import datetime as dt
import enum
import logging
import os
import re
import subprocess
from typing import TYPE_CHECKING, Callable, ClassVar, Final, Iterable, Self, \
    cast

from typing_extensions import override

from crossbench import plt
from crossbench.cli.ui import ui
from crossbench.flags.js_flags import JSFlags
from crossbench.helper import fs_helper
from crossbench.helper.path_finder import V8ToolsFinder
from crossbench.parse import DurationParser, ObjectParser, PathParser
from crossbench.probes.chromium_probe import ChromiumProbe
from crossbench.probes.probe import ProbeConfigParser, ProbeContext, ProbeKeyT
from crossbench.probes.result_location import ResultLocation

if TYPE_CHECKING:
  from typing import TypeAlias

  from crossbench import path as pth
  from crossbench.browsers.browser import Browser
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.plt.base import Platform
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.run import Run

  LogTaskT: TypeAlias = tuple[Callable[..., pth.AnyPath], tuple[object, ...]]

_LOG_FLAG: Final = "--log"
_PROF_FLAG: Final = "--prof"
_LOG_ALL_FLAG: Final = "--log-all"
DEFAULT_LOG_FLAGS: Final[tuple[str, ...]] = (
    "--log",
    "--log-code",
    "--log-deopt",
    "--log-source-code",
    "--log-source-position",
    "--log-code-disassemble",
)


class LogviewCategory(enum.StrEnum):
  flag: str

  IC = ("ic", "--log-ic")
  MAP = ("map", "--log-maps")
  CODE = ("code", "--log-code")

  def __new__(cls, value: str, flag: str) -> Self:
    member = str.__new__(cls, value)
    member._value_ = value
    member.flag = flag
    return member


class V8LogProbe(ChromiumProbe):
  """
  Chromium-only probe that produces a v8.log file with detailed internal V8
  performance and logging information. This is useful for investigating
  internal state (opt, deopt, code objects, ic's, maps...)

  Analysis:
  - This file can be used by tools hosted on http://v8.dev/tools.
  - A cli tool is provided in v8's source in tools/v8-logviewer to inspect
    the v8.log contents in a structured way with complex filtering and sorting.
  - If prof == true, this probe will try to generate profview.json files for
    http://v8.dev/tools/head/profview. See de d8_binary and v8_checkout
    config-properties for more details (prefer using --probe=profiling for
    detailed JS and C++ profiles).
  """
  NAME: ClassVar = "v8.log"
  RESULT_LOCATION = ResultLocation.BROWSER

  _FLAG_RE: Final[re.Pattern] = re.compile("^--(?:prof|log|no-log)(?:-.*)?$")

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "log_all",
        type=ObjectParser.bool,
        default=False,
        help=("Enable all (and very slow) v8 logging "
              "(equivalent to v8's --log-all)."))
    parser.add_argument(
        "js_flags",
        aliases=("v8_log_flags",),
        type=str,
        default=list(DEFAULT_LOG_FLAGS),
        is_list=True,
        help="Manually pass --log-.* flags to V8.")
    parser.add_argument(
        "d8_binary",
        type=PathParser.file_path,
        help="Path to a D8 binary for extended log processing."
        "If not specified the $D8_PATH env variable is used and/or "
        "default build locations are tried.")
    parser.add_argument(
        "v8_checkout",
        type=PathParser.dir_path,
        help="Path to a V8 checkout for extended log processing."
        "If not specified it is auto inferred from either the provided"
        "d8_binary or standard installation locations.")
    parser.add_argument(
        "prof",
        type=ObjectParser.bool,
        default=True,
        help="Enable v8-profiling (equivalent to v8's --prof)")
    parser.add_argument(
        "profview",
        type=ObjectParser.bool,
        default=True,
        help=("Enable v8-profiling and generate profview.json files for "
              "http://v8.dev/tools/head/profview"))
    parser.add_argument(
        "logview",
        type=ObjectParser.bool,
        default=True,
        help="Enable v8-logviewer processing to extract details.")
    parser.add_default_argument(
        "categories",
        type=LogviewCategory,
        is_list=True,
        help="List of logviewer categories to process.")
    parser.add_argument(
        "prof_sampling_interval",
        aliases=("sampling_interval",),
        type=DurationParser.positive_duration_ms,
        help="Set the --prof_sampling_interval in milliseconds.")
    return parser

  def __init__(
      self,
      log_all: bool = False,
      prof: bool = True,
      profview: bool = True,
      logview: bool = True,
      categories: Iterable[LogviewCategory] | None = None,
      js_flags: Iterable[str] | None = DEFAULT_LOG_FLAGS,
      prof_sampling_interval: dt.timedelta | None = None,
      # TODO: support remote platform
      d8_binary: pth.LocalPath | None = None,
      v8_checkout: pth.LocalPath | None = None) -> None:
    super().__init__()
    self._profview: bool = profview
    self._logview: bool = logview
    self._js_flags = JSFlags()
    self._categories: tuple[LogviewCategory, ...] = tuple(
        ObjectParser.enum_list("categories", LogviewCategory, categories or ()))
    for cat in self._categories:
      self._js_flags.set(cat.flag)
    self._prof_sampling_interval: dt.timedelta = (
        prof_sampling_interval or dt.timedelta())
    self._d8_binary: pth.LocalPath | None = d8_binary
    self._v8_checkout: pth.LocalPath | None = v8_checkout
    assert isinstance(log_all,
                      bool), (f"Expected bool value, got log_all={log_all}")
    assert isinstance(prof, bool), f"Expected bool value, got log_all={prof}"

    if log_all:
      self._js_flags.set(_LOG_ALL_FLAG)
    elif prof:
      self._js_flags.set(_PROF_FLAG)
    if profview and not (log_all or prof):
      raise ValueError(f"{self}: Need prof:true with profview:true")

    if self._prof_sampling_interval:
      if not prof:
        logging.error("prof_sampling_interval has no effect without prof==True")
      # The v8 internal unit is microseconds:
      self._js_flags["--prof-sampling-interval"] = str(
          round(self._prof_sampling_interval / dt.timedelta(microseconds=1)))

    js_flags = js_flags or []
    if log_all and js_flags == DEFAULT_LOG_FLAGS:
      js_flags = []
    for flag in js_flags:
      if self._FLAG_RE.match(flag):
        self._js_flags.set(flag)
      else:
        raise ValueError(f"{self}: Non-v8.log-related flag detected: {flag}")
    if len(self._js_flags) == 0:
      raise ValueError(f"{self}: V8LogProbe has no effect")
    # Add at least one logging flag:
    if not log_all and not prof:
      self._js_flags.set(_LOG_FLAG)

  @classmethod
  @override
  def parse_str(cls: type[Self], value: str) -> Self:
    if not value:
      return super().parse_str(value)
    if value == "all":
      return cls(logview=True, categories=LogviewCategory)
    return super().parse_str(value)

  @property
  @override
  def key(self) -> ProbeKeyT:
    return super().key + (
        ("profview", self._profview),
        ("logview", self._logview),
        ("categories", self._categories),
        ("prof_sampling_interval", self._prof_sampling_interval),
        ("js_flags", str(self.js_flags)),
        ("d8_binary", str(self._d8_binary)),
        ("v8_checkout", str(self._v8_checkout)),
    )

  @property
  def js_flags(self) -> JSFlags:
    return self._js_flags.copy()

  def _has_v8_log_flag(self, flag: str) -> bool:
    return flag in self._js_flags or _LOG_ALL_FLAG in self._js_flags

  @override
  def validate_env(self, env: RunnerEnv) -> None:
    super().validate_env(env)
    if env.repetitions != 1:
      env.handle_warning(f"Probe({self.NAME}) cannot merge data over multiple "
                         f"repetitions={env.repetitions}.")

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    # --prof sometimes causes issues on enterprise chrome on linux.
    if _PROF_FLAG not in self._js_flags:
      return
    if not browser.platform.is_linux or browser.version.major <= 106:
      return
    for search_path in cast(plt.LinuxPlatform, browser.platform).SEARCH_PATHS:
      if browser.path.is_relative_to(search_path):
        logging.error(
            "Probe with V8 --prof might not work with enterprise profiles")

  @override
  def attach(self, browser: Browser) -> None:
    super().attach(browser)
    assert browser.attributes().is_chromium_based, (
        f"Expected chromium-based browser, but got {browser}")
    browser.flags.set("--no-sandbox")
    browser.js_flags.update(self._js_flags)

  def process_log_files(self,
                        log_files: list[pth.AnyPath]) -> list[pth.AnyPath]:
    if not log_files:
      return []
    if not self._profview and not self._logview:
      return []

    platform = self.host_platform
    finder = V8ToolsFinder(platform, self._d8_binary, self._v8_checkout)
    if not finder.d8_binary or not finder.tick_processor:
      logging.warning("Did not find $D8_PATH for profview processing.")
      return []

    tasks: list[LogTaskT] = []

    if self._profview:
      tasks += self._profview_tasks(log_files, platform, finder)
    if self._logview:
      tasks += self._logviewer_tasks(log_files, platform, finder)

    if not tasks:
      return []

    with (ui.spinner(title="PROBE v8.log: processing... "),
          concurrent.futures.ThreadPoolExecutor() as executor):
      futures = [executor.submit(func, *args) for func, args in tasks]
      json_list: list[pth.AnyPath] = []
      for f in concurrent.futures.as_completed(futures):
        path = f.result()
        if path:
          json_list.append(path)

    return json_list

  def _profview_tasks(
      self,
      log_files: list[pth.AnyPath],
      platform: Platform,
      finder: V8ToolsFinder,
  ) -> list[LogTaskT]:
    tasks: list[LogTaskT] = []
    if not self._has_v8_log_flag(_PROF_FLAG):
      logging.warning(
          "PROBE v8.log: V8 was not started with --prof or --log-all, "
          "skipping profview generation.")
      return tasks

    logging.info(
        "PROBE v8.log: generating profview json data "
        "for %d v8.log files. (slow)", len(log_files))
    logging.debug("v8.log files: %s", log_files)
    for log_file in log_files:
      tasks.append((_process_profview_json, (platform, finder.d8_binary,
                                             finder.tick_processor, log_file)))
    return tasks

  def _logviewer_tasks(
      self,
      log_files: list[pth.AnyPath],
      platform: Platform,
      finder: V8ToolsFinder,
  ) -> list[LogTaskT]:
    logviewer_script = finder.v8_logviewer
    if not logviewer_script:
      logging.warning("Did not find v8-logviewer script at %s",
                      logviewer_script)
      return []
    logging.info("PROBE v8.log: generating v8-logviewer json data")
    tasks: list[LogTaskT] = []
    for log_file in log_files:
      for category in LogviewCategory:
        if not self._has_v8_log_flag(category.flag):
          continue
        tasks.append(
            (_process_logviewer_json, (platform, finder.d8_binary,
                                       logviewer_script, category, log_file)))
    return tasks

  @override
  def get_context_cls(self) -> type[V8LogProbeContext]:
    return V8LogProbeContext

  @override
  def log_browsers_result(self, group: BrowsersRunGroup) -> None:
    runs: list[Run] = [run for run in group.runs if self in run.results]
    if not runs:
      return
    logging.info("-" * 80)
    logging.critical("v8.log results:")
    logging.info("  *.v8.log:        https://v8.dev/tools/head/system-analyzer")
    logging.info("  *.profview.json: https://v8.dev/tools/head/profview")
    logging.info("- " * 40)
    # Iterate over all runs again, to get proper indices:
    for i, run in enumerate(group.runs):
      if self not in run.results:
        continue
      log_files = run.results[self].file_list
      if not log_files:
        continue
      logging.info("Run %d: %s", i + 1, run.name)
      largest_log_file = log_files[-1]
      logging.critical("    %s [%s]", largest_log_file,
                       fs_helper.get_file_size(largest_log_file))
      if len(log_files) > 1:
        logging.info("    %s/.*v8.log: %d files", largest_log_file.parent,
                     len(log_files))
      profview_files = run.results[self].json_list
      if not profview_files:
        continue
      largest_profview_file = profview_files[-1]
      logging.critical("    %s [%s]", largest_profview_file,
                       fs_helper.get_file_size(largest_profview_file))
      if len(profview_files) > 1:
        logging.info("    %s/*.profview.json: %d more files",
                     largest_profview_file.parent, len(profview_files))


class V8LogProbeContext(ProbeContext[V8LogProbe]):

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    log_dir = super().get_default_result_path()
    self.browser_platform.mkdir(log_dir)
    return log_dir / self.probe.result_path_name

  @override
  def setup(self) -> None:
    self.session.extra_js_flags["--logfile"] = str(self.result_path)

  def start(self) -> None:
    pass

  def stop(self) -> None:
    pass

  def teardown(self) -> ProbeResult:
    log_dir = self.result_path.parent
    log_files = fs_helper.sort_by_file_size(
        self.browser_platform.glob(log_dir, "*-v8.log"), self.browser_platform)
    json_list: list[pth.AnyPath] = self.probe.process_log_files(log_files)
    return self.browser_result(file=tuple(log_files), json=json_list)


def _process_profview_json(platform: Platform, d8_binary: pth.AnyPath,
                           tick_processor: pth.AnyPath,
                           log_file: pth.AnyPath) -> pth.AnyPath:
  # The tick-processor scripts expect D8_PATH to point to the parent dir.
  result_json = log_file.with_suffix(".profview.json")
  return _run_v8_tool(platform, d8_binary, tick_processor, result_json,
                      ("--preprocess", log_file))


def _process_logviewer_json(platform: Platform, d8_binary: pth.AnyPath,
                            logviewer_script: pth.AnyPath, category: str,
                            log_file: pth.AnyPath) -> pth.AnyPath:
  output_json = log_file.with_suffix(f".logview.{category}.json")
  return _run_v8_tool(platform, d8_binary, logviewer_script, output_json,
                      (category, log_file, "--details"))


def _run_v8_tool(platform: Platform, d8_binary: pth.AnyPath,
                 tool_script: pth.AnyPath, output_file: pth.AnyPath,
                 args: tuple[pth.AnyPathLike, ...]) -> pth.AnyPath:
  env = os.environ.copy()
  env["D8_PATH"] = str(platform.local_path(d8_binary).resolve())
  with platform.local_path(output_file).open("w", encoding="utf-8") as f:
    platform.sh(tool_script, *args, env=env, stdout=f, stderr=subprocess.PIPE)
  return output_file
