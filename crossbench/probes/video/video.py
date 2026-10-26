# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, ClassVar, Final, Self, TextIO

from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.config import ConfigEnum
from crossbench.helper import collection_helper, wait
from crossbench.parse import ObjectParser
from crossbench.plt.ios import IOSPlatform
from crossbench.probes.probe import Probe, ProbeConfigParser, ProbeContext
from crossbench.probes.probe_error import ProbeIncompatibleBrowser, \
    ProbeMissingDataError
from crossbench.probes.result_location import ResultLocation
from crossbench.probes.results import EmptyProbeResult, LocalProbeResult, \
    ProbeResult

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser, Viewport
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.runner.groups.browsers import BrowsersRunGroup
  from crossbench.runner.groups.repetitions import RepetitionsRunGroup
  from crossbench.runner.run import Run
  from crossbench.runner.runner import Runner
  from crossbench.stories.story import Story


class Orientation(ConfigEnum):
  HORIZONTAL = ("horizontal", "Align horizontally.")
  VERTICAL = ("vertical", "Align vertically.")


FFMPEG_STACK_DIRECTION: Final[dict[Orientation, str]] = {
    Orientation.HORIZONTAL: "hstack",
    Orientation.VERTICAL: "vstack",
}


class VideoProbe(Probe):
  """
  General-purpose Probe that collects screen-recordings.

  It can also produce a timestrip png and creates merged versions of these files
  for visually comparing various browsers / variants / cb.stories
  """
  NAME: ClassVar = "video"
  RESULT_LOCATION: ClassVar = ResultLocation.BROWSER
  # TODO: Add Final[ClassVar] once supported.
  VIDEO_QUALITY: Final = ("-vcodec", "libx264", "-crf", "20")
  IMAGE_FORMAT: Final = "png"
  TIMESTRIP_FILE_SUFFIX: Final = f".timestrip.{IMAGE_FORMAT}"
  FRAMERATE: Final = 60
  # The recorder for physical iOS devices, compiled in setup().
  IOS_USB_RECORDER_SOURCE: Final = (
      pth.LocalPath(__file__).parent / "ios_usb_screen_recorder.swift")

  @classmethod
  @override
  def config_parser(cls) -> ProbeConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "generate_timestrip",
        aliases=("timestrip",),
        type=ObjectParser.bool,
        default=True,
        help="Produce a timestrip png")
    parser.add_argument(
        "merge_runs",
        type=ObjectParser.bool,
        default=True,
        help="Merge videos from multiple runs")
    parser.add_argument(
        "orientation",
        aliases=(
            "dir",
            "direction",
        ),
        type=Orientation,
        default=Orientation.HORIZONTAL,
        help=("Primary merge orientation for repetitions. "
              "Each further merge level will happen in the opposite direction "
              "of the previous one."))
    return parser

  def __init__(self,
               generate_timestrip: bool = True,
               merge_runs: bool = True,
               orientation: Orientation = Orientation.HORIZONTAL) -> None:
    super().__init__()
    self._generate_timestrip: Final[bool] = generate_timestrip
    self._merge_runs: Final[bool] = merge_runs
    self._orientation: Final[Orientation] = orientation
    self._ios_usb_recorder: pth.LocalPath | None = None

  @property
  def ios_usb_recorder(self) -> pth.LocalPath:
    assert self._ios_usb_recorder, "iOS recorder not compiled."
    return self._ios_usb_recorder

  @override
  def setup(self, runner: Runner) -> None:
    super().setup(runner)
    if not any(browser.platform.is_ios for browser in self.browsers):
      return
    self._ios_usb_recorder = runner.out_dir / "ios_usb_screen_recorder"
    runner.platform.sh("swiftc", "-O", self.IOS_USB_RECORDER_SOURCE, "-o",
                       self._ios_usb_recorder)

  @property
  @override
  def result_path_name(self) -> str:
    return f"{self.name}.mp4"

  @property
  def generate_timestrip(self) -> bool:
    return self._generate_timestrip

  @property
  def primary_orientation(self) -> Orientation:
    return self._orientation

  @property
  def secondary_orientation(self) -> Orientation:
    if self._orientation == Orientation.VERTICAL:
      return Orientation.HORIZONTAL
    return Orientation.VERTICAL

  @property
  def merge_runs(self) -> bool:
    return self._merge_runs

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    platform = browser.platform
    if isinstance(platform, IOSPlatform) and platform.is_simulator:
      raise ProbeIncompatibleBrowser(self, browser,
                                     "iOS simulators are not supported")

  @override
  def validate_env(self, env: RunnerEnv) -> None:
    super().validate_env(env)
    if env.repetitions > 10:
      env.handle_warning(
          f"Probe={self.NAME} might not be able to merge so many "
          f"repetitions={env.repetitions}.")
    env.check_installed(
        binaries=("ffmpeg",), message="Missing binaries for video probe: {}")
    # Check that ffmpeg can be executed
    env.check_sh_success("ffmpeg", "-version")
    if self.generate_timestrip:
      env.check_installed(
          binaries=("montage",),
          message="Missing 'montage' binary, please install imagemagick.")
      # Check that montage can be executed
      env.check_sh_success("montage", "--version")
    if any(browser.platform.is_ios for browser in env.browsers):
      # No check_installed(): macOS ships /usr/bin/swiftc as a shim that only
      # works once a toolchain is installed, so it has to be run to tell.
      env.check_sh_success(
          "swiftc",
          "--version",
          message="Cannot run swiftc, needed to record an iOS device's "
          "screen; install the Xcode command line tools: {}")
    self._pre_check_viewport_size(env)

  def _pre_check_viewport_size(self, env: RunnerEnv) -> None:
    first_viewport: Viewport = env.browsers[0].viewport
    for browser in env.browsers:
      viewport: Viewport = browser.viewport
      if viewport.is_headless:
        env.handle_warning(
            f"Cannot record video for headless browser: {browser}")
      # TODO: support fullscreen / maximised
      if not viewport.has_size:
        env.handle_warning(
            "Can only record video for browsers with explicit viewport sizes, "
            f"but got {viewport} for {browser}.")
      if viewport.x < 10 or viewport.y < 50:
        env.handle_warning(
            f"Viewport for '{browser}' might include toolbar: {viewport}")
      if viewport != first_viewport:
        env.handle_warning(
            "Video recording requires same viewport size for all browsers.\n"
            f"Viewport size for {browser} is {viewport}, "
            f"which differs from first viewport {first_viewport}. ")

  @override
  def get_context_cls(self) -> type[VideoProbeContext]:
    return VideoProbeContext

  @override
  def merge_repetitions(self, group: RepetitionsRunGroup) -> ProbeResult:
    if not self.merge_runs:
      return LocalProbeResult()
    runs = tuple(group.runs)
    if len(runs) == 1:
      # In the simple case just copy the files
      run_files = runs[0].results[self].file_list
      group_files = [group.path / f.name for f in run_files]
      for src, dest in zip(run_files, group_files, strict=True):
        self.host_platform.copy(src, dest)
      return LocalProbeResult(file=group_files)

    video_file = group.get_local_probe_result_path(self)
    group_files = [video_file]
    logging.info("VIDEO merge page repetitions")
    browser = group.browser
    video_file_inputs: list[str | pth.LocalPath] = []
    for run in runs:
      video_file_inputs += ["-i", run.results[self].file_list[0]]
    draw_text = ("fontfile='/Library/Fonts/Arial.ttf':"
                 f"text='{browser.app_name} {browser.label}':"
                 "fontsize=h/15:"
                 "y=h-line_h-10:x=10:"
                 "box=1:boxborderw=20:boxcolor=white")
    stack_direction: str = FFMPEG_STACK_DIRECTION[self.primary_orientation]
    self.host_platform.sh(
        "ffmpeg", "-hide_banner", \
        *video_file_inputs, \
        "-filter_complex",
        f"{stack_direction}=inputs={len(runs)},"
        f"drawtext={draw_text},"
        "scale=3000:-2", *self.VIDEO_QUALITY, video_file)

    if self._generate_timestrip:
      timeline_strip_file = video_file.with_suffix(self.TIMESTRIP_FILE_SUFFIX)
      logging.info("TIMESTRIP merge page repetitions")
      timeline_strips = (run.results[self].file_list[1] for run in runs)
      self.host_platform.sh("montage", *timeline_strips, "-tile", "1x",
                            "-gravity", "NorthWest", "-geometry", "x100",
                            timeline_strip_file)
      group_files.append(timeline_strip_file)

    return LocalProbeResult(file=group_files)

  @override
  def merge_browsers(self, group: BrowsersRunGroup) -> ProbeResult:
    """Merge story videos from multiple browser/configurations"""
    groups = list(group.repetitions_groups)
    if not self.merge_runs or len(groups) <= 1:
      return super().merge_browsers(group)
    grouped: dict[Story,
                  list[RepetitionsRunGroup]] = collection_helper.group_by(
                      groups,
                      key=lambda repetitions_group: repetitions_group.story)

    result_dir = group.get_local_probe_result_path(self)
    result_dir = result_dir / result_dir.stem
    result_dir.mkdir(parents=True)
    return LocalProbeResult(
        file=(self._merge_stories_for_browser(result_dir, story,
                                              repetitions_groups)
              for story, repetitions_groups in grouped.items()))

  def _merge_stories_for_browser(
      self, result_dir: pth.LocalPath, story: Story,
      repetitions_groups: list[RepetitionsRunGroup]) -> pth.LocalPath:
    story = repetitions_groups[0].story
    result_path = result_dir / f"{story.name}_combined.mp4"

    if len(repetitions_groups) == 1:
      # In the simple case just copy files
      input_file = repetitions_groups[0].results[self].file_list[0]
      self.host_platform.copy(input_file, result_path)
      return result_path

    input_files: list[str] = []
    for repetitions_group in repetitions_groups:
      result_files = repetitions_group.results[self].file_list
      input_files += ["-i", os.fspath(result_files[0])]
    stack_direction: str = FFMPEG_STACK_DIRECTION[self.secondary_orientation]
    try:
      self.host_platform.sh(
          "ffmpeg", "-hide_banner", *input_files, "-filter_complex",
          f"{stack_direction}=inputs={len(repetitions_groups)}",
          *self.VIDEO_QUALITY, result_path)
    except Exception as e:
      logging.error("Merging multiple browser video failed. "
                    "Different screen orientations are not supported yet.")
      logging.debug("Browser video merging failed: %e", e)
      raise e
    return result_path


class VideoProbeContext(ProbeContext[VideoProbe]):
  IMAGE_FORMAT: Final = "png"
  FFMPEG_TIMELINE_TEXT: Final = (
      "drawtext="
      "fontfile=/Library/Fonts/Arial.ttf:"
      "text='%{eif\\:t\\:d}.%{eif\\:t*100-floor(t)*100\\:d}s':"
      "fontsize=h/16:"
      "y=h-line_h-5:x=5:"
      "box=1:boxborderw=15:boxcolor=white")

  # The iOS device recorder prints READY once it has written its first
  # frame; the run waits for that so the recording covers it from the start.
  IOS_RECORDER_READY_WAIT: Final = wait.WaitRange(
      min=dt.timedelta(milliseconds=50),
      max=dt.timedelta(milliseconds=50),
      timeout=dt.timedelta(seconds=15))

  # How long the iOS device recorder gets to finish its file once told to stop.
  IOS_RECORDER_STOP_TIMEOUT: Final = dt.timedelta(seconds=10)

  def __init__(self, probe: VideoProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._record_process: subprocess.Popen | None = None
    self._recorder_log_file: TextIO | None = None

  @override
  def get_default_result_path(self) -> pth.AnyPath:
    if self.browser_platform.is_ios:
      return self.run.get_local_probe_result_path(self.probe)
    return super().get_default_result_path()

  @property
  def _recorder_platform(self) -> plt.Platform:
    # iOS devices are recorded over USB from the host.
    if self.browser_platform.is_ios:
      return self.host_platform
    return self.browser_platform

  @property
  def _recorder_log_path(self) -> pth.LocalPath:
    return self.local_result_path.with_suffix(".recorder.log")

  def start(self) -> None:
    browser = self.run.browser
    cmd = self._record_cmd(browser.viewport)
    logging.debug("Screen recorder cmd: %s", cmd)
    if self._recorder_platform.is_remote:
      self._recorder_log_file = None
    else:
      self._recorder_log_file = self._recorder_log_path.open(
          "w", encoding="utf-8")
    self._record_process = self._recorder_platform.popen(
        *cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdout=self._recorder_log_file)
    if self._record_process.poll():
      raise ValueError("Could not start screen recorder")
    if self.browser_platform.is_ios:
      self._wait_for_ios_recorder_ready()
      return
    # TODO: Add common start-story-delay on runner for these cases.
    self.host_platform.sleep(1)

  def _wait_for_ios_recorder_ready(self) -> None:
    assert self._record_process
    try:
      for _ in wait.wait_with_backoff(self.IOS_RECORDER_READY_WAIT):
        if self._ios_recorder_is_ready():
          return
    except TimeoutError as e:
      # Only the error raised here should be reported, so stop the recorder
      # for good rather than leaving it to stop() and teardown().
      self.stop_process()
      raise RuntimeError("iOS screen recorder not ready after "
                         f"{self.IOS_RECORDER_READY_WAIT.timeout}, "
                         f"see {self._recorder_log_path}") from e

  def _ios_recorder_is_ready(self) -> bool:
    """Whether the recorder has printed READY; raises if it has exited."""
    assert self._record_process
    if self._record_process.poll() is not None:
      self.stop_process()
      raise RuntimeError("iOS screen recorder exited before becoming ready, "
                         f"see {self._recorder_log_path}")
    if not self._recorder_log_path.exists():
      return False
    log = self._recorder_log_path.read_text(encoding="utf-8")
    return "READY" in log.splitlines()

  def _record_cmd(self, viewport: Viewport) -> tuple[str, ...]:
    if self.browser_platform.is_linux:
      env_display = os.environ.get("DISPLAY", ":0.0")
      return ("ffmpeg", "-hide_banner", "-video_size",
              f"{viewport.width}x{viewport.height}", "-f", "x11grab",
              "-framerate", str(self.probe.FRAMERATE), "-i",
              f"{env_display}+{viewport.x},{viewport.y}", str(self.result_path))
    if self.browser_platform.is_macos:
      return ("/usr/sbin/screencapture", "-v",
              f"-R{viewport.x},{viewport.y},{viewport.width},{viewport.height}",
              str(self.result_path))
    if self.browser_platform.is_android:
      return ("screenrecord", str(self.result_path))
    if self.browser_platform.is_ios:
      browser_platform = self.browser_platform
      assert isinstance(browser_platform, IOSPlatform)
      # The capture device is published under the device's name.
      return (
          str(self.probe.ios_usb_recorder),
          browser_platform.model,
          str(self.result_path),
          str(self.probe.FRAMERATE),
      )
    raise ValueError("Invalid platform")

  def stop(self) -> None:
    if not self._record_process:
      # Gone already, which is reported already.
      return
    if self.browser_platform.is_macos:
      assert not self._record_process.poll(), (
          "screencapture stopped early. "
          "Please ensure that the parent application has screen recording "
          "permissions")
      # The mac screencapture stops on the first (arbitrary) input.
      self._record_process.communicate(input=b"stop")
    elif self.browser_platform.is_ios:
      assert not self._record_process.poll(), "screencapture stopped early."
      self._stop_ios_recorder()
    elif self.browser_platform.is_android:
      assert not self._record_process.poll(), ("screencapture stopped early. ")
      self.browser_platform.send_signal(
          self._record_process, signal=self.browser_platform.signals.SIGINT)
    else:
      self._recorder_platform.terminate(self._record_process)

  def _stop_ios_recorder(self) -> None:
    """Lets the recorder finish its file; raises if it did not."""
    process = self._record_process
    assert process
    # Closing its stdin tells the recorder to finish the file.
    try:
      process.communicate(
          timeout=self.IOS_RECORDER_STOP_TIMEOUT.total_seconds())
    except subprocess.TimeoutExpired:
      logging.warning("iOS screen recorder did not stop in %s",
                      self.IOS_RECORDER_STOP_TIMEOUT)
      self.host_platform.terminate_gracefully(process)
    returncode = process.poll()
    if returncode == 0:
      return
    # The file is unplayable without a proper finish, so take it away from
    # teardown().
    self.stop_process()
    raise RuntimeError("iOS screen recorder did not finish its file (exit "
                       f"code {returncode}), see {self._recorder_log_path}")

  def teardown(self) -> ProbeResult:
    if self._recorder_log_file:
      self._recorder_log_file.close()
    if not self._record_process:
      # Gone already, which is reported already.
      return EmptyProbeResult()
    self.stop_process()
    if not self._recorder_platform.is_file(self.result_path):
      raise ProbeMissingDataError(
          f"No screen recording video found at: {self.result_path}")
    if not self.browser_platform.is_ios:
      # Copy files
      browser_result = self.browser_result(file=(self.result_path,))
      self._default_result_path = browser_result.file
    assert self.host_platform.exists(self.result_path)

    if not self.probe.generate_timestrip:
      return LocalProbeResult(file=(self.local_result_path,))

    with tempfile.TemporaryDirectory() as tmp_dir:
      self._convert_to_constant_framerate()
      timestrip_file = self._create_time_strip(
          self.host_platform.local_path(tmp_dir))
    return LocalProbeResult(file=(self.local_result_path, timestrip_file))

  def stop_process(self) -> None:
    if self._record_process:
      self._recorder_platform.terminate_gracefully(
          self._record_process, timeout=5)
      self._record_process = None

  def _convert_to_constant_framerate(self) -> None:
    # On some platforms (android for certain) we get VFR videos which confuse
    # the next video extraction / conversion steps.
    vfr_video_result = (
        self.local_result_path.parent / f"vfr_{self.result_path.name}")
    self.local_result_path.rename(vfr_video_result)
    self.host_platform.sh(
        "ffmpeg", "-hide_banner", \
        "-fflags", "+igndts", \
        "-i", vfr_video_result, \
        "-filter:v", "fps=60", \
        "-fps_mode:v", "cfr",
        # Use the decoder timebase.
        "-copytb", "0", \
        *self.probe.VIDEO_QUALITY,
        self.result_path,
    )
    if not self.local_result_path.exists() or self.local_result_path.stat(
    ).st_size == 0:
      vfr_video_result.rename(self.result_path)
      logging.error("Could not generate constant FPS video: %s",
                    self.result_path)
    else:
      vfr_video_result.unlink()

  def _create_time_strip(self, tmpdir: pth.LocalPath) -> pth.LocalPath:
    logging.info("TIMESTRIP")
    progress_dir = tmpdir / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    timeline_dir = tmpdir / "timeline"
    timeline_dir.mkdir(exist_ok=True)
    # Try detect scene changes / steps
    self.host_platform.sh(
        "ffmpeg", "-hide_banner", "-i", self.result_path, \
        "-filter_complex", "scale=3000:-2,"
        "select='gt(scene\\,0.011)'," + self.FFMPEG_TIMELINE_TEXT, \
        "-fps_mode", "cfr", \
        "-framerate", str(self.probe.FRAMERATE), \
          f"{progress_dir}/%02d.{self.IMAGE_FORMAT}")
    # Extract at regular intervals of 100ms, assuming 60fps input
    every_nth_frame = self.probe.FRAMERATE / 20
    safe_duration = 10
    safe_duration = 2
    self.host_platform.sh(
        "ffmpeg", "-hide_banner", \
        "-i", self.result_path, \
        "-filter_complex",
        f"trim=duration={safe_duration},"
        "scale=3000:-2,"
        f"select=not(mod(n\\,{every_nth_frame}))," + self.FFMPEG_TIMELINE_TEXT,
        f"{timeline_dir}/%02d.{self.IMAGE_FORMAT}")

    timeline_strip_file = self.local_result_path.with_suffix(
        self.probe.TIMESTRIP_FILE_SUFFIX)
    self.runner.platform.sh("montage", f"{timeline_dir}/*.{self.IMAGE_FORMAT}",
                            "-tile", "x1", "-gravity", "NorthWest", "-geometry",
                            "x100", timeline_strip_file)
    return timeline_strip_file
