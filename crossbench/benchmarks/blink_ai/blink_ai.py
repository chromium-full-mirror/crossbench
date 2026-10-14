# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, ClassVar, Sequence

from typing_extensions import override

from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.position import PositionConfig
from crossbench.benchmarks.base import PressBenchmark, \
    PressBenchmarkStoryFilter
from crossbench.benchmarks.loading.input_source import InputSource
from crossbench.flags.chrome import ChromeFlags
from crossbench.helper import url_helper
from crossbench.stories.press_benchmark import PressBenchmarkStory

from .probe import BlinkAIProbe

if TYPE_CHECKING:
  from crossbench.benchmarks.base import VersionParts
  from crossbench.browsers.attributes import BrowserAttributes
  from crossbench.flags.base import Flags
  from crossbench.runner.run import Run
  from crossbench.stories.story import Story


class BlinkAIStory(PressBenchmarkStory):
  NAME: ClassVar[str] = "blink_ai"
  URL: ClassVar[str] = "https://chromium-workloads.web.app/blink-ai/main/"
  URL_OFFICIAL: ClassVar[str] = (
      "https://chromium-workloads.web.app/blink-ai/main/")
  URL_LOCAL: ClassVar[str] = "http://localhost:8000/"
  DEFAULT_SUBSTORIES: ClassVar[tuple[str, ...]] = (
      "language_model",
      "multimodal_image",
      "multimodal_images",
      "multimodal_audio",
  )
  MTP_SUBSTORIES: ClassVar[tuple[str, ...]] = (
      "mtp_summary",
      "mtp_flight",
      "mtp_emoji",
      # Article summary with constrained decoding (responseConstraint).
      "mtp_constrained_summary",
  )
  TOOL_USE_SUBSTORIES: ClassVar[tuple[str, ...]] = ("tool_calling",)
  SUBSTORIES: ClassVar[tuple[str, ...]] = (
      DEFAULT_SUBSTORIES + MTP_SUBSTORIES + TOOL_USE_SUBSTORIES
  )

  @classmethod
  @override
  def default_story_names(cls) -> tuple[str, ...]:
    return cls.DEFAULT_SUBSTORIES

  @property
  def has_mtp_substory(self) -> bool:
    return any(substory in self.MTP_SUBSTORIES for substory in self.substories)

  @property
  def has_tool_use_substory(self) -> bool:
    return any(
        substory in self.TOOL_USE_SUBSTORIES for substory in self.substories
    )

  def __init__(self,
               substories: Sequence[str] = (),
               url: str | None = None) -> None:
    if not substories:
      substories = self.default_story_names()
    super().__init__(substories=substories, url=url or self.URL)

  @property
  @override
  def substory_duration(self) -> dt.timedelta:
    return dt.timedelta(seconds=100)

  @property
  @override
  def slow_duration(self) -> dt.timedelta:
    return dt.timedelta(minutes=15)

  @property
  def url_params(self) -> dict[str, str]:
    if not self.substories:
      return {}
    return {"stories": ",".join(self.substories)}

  @property
  @override
  def test_url(self) -> str:
    return url_helper.update_url_query(self.url, self.url_params)

  @override
  def get_run_url(self, run: Run) -> str:
    url = super().get_run_url(run)
    return url_helper.update_url_query(url, self.url_params)

  @override
  def setup(self, run: Run) -> None:
    url = self.get_run_url(run)
    with run.actions("Setup") as actions:
      actions.show_url(url)
      logging.info("Waiting for window.LanguageModel to become available...")
      try:
        actions.wait_js_condition(
            "return !!window.LanguageModel && window.testStatus === 'waiting'",
            0.5,
            timeout=dt.timedelta(seconds=45))
      except Exception as e:
        raise RuntimeError("Built-in AI API (window.LanguageModel) failed to"
                           " initialize within 30 seconds.") from e

  @override
  def run(self, run: Run) -> None:
    with run.actions("Running benchmark") as actions:
      logging.info("Clicking #start-button to initiate AI E2E test...")
      # Chrome's Built-in AI API strictly requires a trusted user gesture
      # to download and compile on-device models.
      if run.browser.attributes().is_chromium_based:
        input_source = InputSource.DRIVER
      else:
        input_source = InputSource.JS
      action = ClickAction.create(input_source,
                                  PositionConfig.parse_str("#start-button"))
      run.action_runner.click(action)
      actions.wait_js_condition(
          "return window.testStatus !== 'running' && "
          "window.testStatus !== 'waiting';",
          0.5,
          timeout=self.slow_duration)

      status = actions.js("return window.testStatus;")
      if status != "success":
        raise ValueError("Blink-AI Benchmark did not finish successfully. "
                         f"Final testStatus: '{status}'. ")

      metrics = actions.js("return window.metrics;")
      if not metrics or not isinstance(metrics, dict):
        raise RuntimeError("Benchmark finished without metrics. Check for a "
                           "browser tab or Mojo IPC crash.")


class BlinkAIBenchmark(PressBenchmark):
  """
  Benchmark runner for Chrome Built-in on-device AI APIs.
  """
  NAME: ClassVar[str] = "blink-ai"
  DEFAULT_STORY_CLS = BlinkAIStory
  PROBES: ClassVar[tuple[type[BlinkAIProbe], ...]] = (BlinkAIProbe,)
  STORY_FILTER_CLS: ClassVar = PressBenchmarkStoryFilter

  @classmethod
  @override
  def short_base_name(cls) -> str:
    return "blink-ai"

  @classmethod
  @override
  def base_name(cls) -> str:
    return "blink-ai"

  @classmethod
  @override
  def version(cls) -> VersionParts:
    return ("main",)

  @classmethod
  @override
  def extra_flags(cls, browser_attributes: BrowserAttributes,
                  story: Story) -> Flags:
    flags: Flags = super().extra_flags(browser_attributes, story)
    if not browser_attributes.is_chromium_based:
      return flags

    chrome_flags = ChromeFlags(flags)
    logging.info("Injecting experimental built-in AI flags for Chrome...")
    for feature in (
        ("OnDeviceModelPerformanceParams:"
         "compatible_on_device_performance_classes/*"),
        "OnDeviceModelIdleTimeout:on_device_model_idle_timeout/10s",
        "OnDeviceAiDefaultEnabled",
        "AIWriterAPI",
        "AIRewriterAPI",
    ):
      chrome_flags.features.enable(feature)
    if isinstance(story, BlinkAIStory):
      if story.has_mtp_substory:
        chrome_flags.features.enable("OnDeviceModelSpeculativeDecoding")
      if story.has_tool_use_substory:
        for tool_feature in (
            "AIPromptAPIToolUse",
            "OnDeviceModelConversationBackend",
            "AIApiFoundationalModel:model_version/v4",
        ):
          chrome_flags.features.enable(tool_feature)
    return chrome_flags
