# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import copy
import datetime as dt
import json
import threading
from typing import TYPE_CHECKING, Any, Final
from unittest import mock

from immutabledict import immutabledict
from typing_extensions import override

from crossbench.benchmarks.blink_ai.blink_ai import BlinkAIBenchmark, \
    BlinkAIStory
from crossbench.benchmarks.blink_ai.probe import BYTES_PER_MB, \
    MIN_VRAM_INTERVAL, BlinkAIProbe, BlinkAIProbeContext
from crossbench.env.runner_env import EnvConfig, ValidationMode
from crossbench.runner.runner import Runner
from tests import test_helper
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from tests.crossbench.mock_browser import MockBrowser

SAMPLE_STORY_METRICS: Final[immutabledict[str, Any]] = immutabledict({
    "sessionCreationTimeMs": 120.5,
    "coldTimeToFirstTokenMs": 45.2,
    "coldTotalPromptTimeMs": 250.0,
    "coldChunksPerSecond": 45.8,
    "warmTimeToFirstTokenMs": [12.5, 10.2, 9.8],
    "warmTotalPromptTimeMs": [110.0, 95.0, 92.0],
    "warmChunksPerSecond": [50.2, 55.1, 56.3],
})
VRAM_STAT_NAMES: Final[tuple[str, ...]] = ("peak", "baseline", "delta")


class BlinkAITestCase(helper.SubStoryTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.platform.gpu_vram_used = mock.Mock(return_value={})

  @property
  @override
  def benchmark_cls(self):
    return BlinkAIBenchmark

  @property
  @override
  def story_cls(self):
    return BlinkAIStory

  @property
  def probe_cls(self):
    return BlinkAIProbe

  @property
  def probe_context_cls(self):
    return BlinkAIProbeContext

  def _setup_run_js_expect(
      self,
      browser: MockBrowser,
      probe_results: dict[str, Any],
      status: str = "success",
  ) -> None:
    # wait_js_condition for window.LanguageModel
    browser.expect_js(result=True)
    # JS click for #start-button
    browser.expect_js(result=None)
    # wait_js_condition for window.testStatus !== 'running'
    browser.expect_js(result=True)
    # window.testStatus check
    browser.expect_js(result=status)
    if status == "success":
      # window.metrics check in story run()
      browser.expect_js(result=probe_results)
    # window.metrics in probe (JsonResultProbeContext)
    browser.expect_js(result=json.dumps(probe_results))

  def _run_vram_probe_context(
      self,
      samples: list[dict[str, float]],
      js_metrics: dict[str, Any],
  ) -> dict[str, Any]:
    all_sampled = threading.Event()
    call_count = 0

    def side_effect() -> dict[str, float]:
      nonlocal call_count
      result = samples[min(call_count, len(samples) - 1)]
      call_count += 1
      if call_count >= len(samples):
        all_sampled.set()
      return result

    probe = BlinkAIProbe(vram_interval=MIN_VRAM_INTERVAL)

    mock_browser = mock.Mock()
    mock_browser.platform = self.platform
    mock_browser.host_platform = self.platform

    mock_run = mock.Mock()
    mock_run.browser = mock_browser
    mock_run.get_default_probe_result_path = mock.Mock(
        return_value=self.out_dir / "blink_ai.json")
    mock_run.results = mock.Mock()

    mock_actions = mock.MagicMock()
    mock_actions.__enter__.return_value = mock_actions
    mock_actions.js.return_value = json.dumps(js_metrics)
    mock_run.actions = mock.MagicMock(return_value=mock_actions)

    context = BlinkAIProbeContext(probe, mock_run)
    with mock.patch.object(
        self.platform, "gpu_vram_used", side_effect=side_effect):
      context.setup()
      context.start()
      self.assertTrue(all_sampled.wait(timeout=5.0))
      context.stop()

    data = context.to_json(mock_actions)
    assert isinstance(data, dict)
    return data

  def _assert_vram_stats(
      self,
      data: dict[str, Any],
      peak_mb: float,
      baseline_mb: float,
      gpu_id: str | None = None,
      check_flat_gpu: bool = False,
  ) -> None:
    expected = {
        "peak": peak_mb,
        "baseline": baseline_mb,
        "delta": peak_mb - baseline_mb,
    }
    if gpu_id is None:
      for stat, val_mb in expected.items():
        self.assertEqual(data["vram"][f"{stat}_mb"], val_mb)
        self.assertEqual(data[f"vram_{stat}_mb"], val_mb)
        self.assertEqual(data[f"vram_{stat}_bytes"],
                         round(val_mb * BYTES_PER_MB))
      return

    self.assertDictEqual(
        data["vram"][gpu_id],
        {
            f"{stat}_mb": val_mb for stat, val_mb in expected.items()
        },
    )
    if check_flat_gpu:
      for stat, val_mb in expected.items():
        self.assertEqual(data[f"vram_{gpu_id}_{stat}_mb"], val_mb)
        self.assertEqual(data[f"vram_{gpu_id}_{stat}_bytes"],
                         round(val_mb * BYTES_PER_MB))

  def test_run_default(self):
    # Default should include all substories
    stories = self.story_cls.default()
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)

    probe_results: dict[str, Any] = {
        "downloadTimeMs": 500.5,
        **SAMPLE_STORY_METRICS,
    }
    for substory in self.story_cls.default_story_names():
      probe_results[substory] = dict(SAMPLE_STORY_METRICS)

    repetitions = 2
    for _ in range(repetitions):
      for browser in self.browsers:
        self._setup_run_js_expect(browser, probe_results)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True,
    )

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    # Verification
    expected_query = ("?stories=language_model%2Cmultimodal_image"
                      "%2Cmultimodal_images%2Cmultimodal_audio")
    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.story_cls.URL + expected_query, urls)
      self.assertSequenceEqual(browser.expected_js, [])

  def test_run_single_story(self):
    stories = self.story_cls.from_names(["language_model"])
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)

    probe_results = {"downloadTimeMs": 500.5, **SAMPLE_STORY_METRICS}

    repetitions = 1
    for _ in range(repetitions):
      for browser in self.browsers:
        self._setup_run_js_expect(browser, probe_results)

    for browser in self.browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True,
    )

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    for browser in self.browsers:
      urls = self.filter_splashscreen_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.story_cls.URL + "?stories=language_model", urls)
      self.assertSequenceEqual(browser.expected_js, [])

  def test_custom_url(self):
    custom_url = "http://test.example.com/blink_ai"
    stories = self.story_cls.from_names(["language_model"], url=custom_url)
    self.assertEqual(len(stories), 1)
    story = stories[0]
    self.assertDictEqual(story.url_params, {"stories": "language_model"})
    self.assertEqual(story.test_url, custom_url + "?stories=language_model")

  def test_run_error(self):
    stories = self.story_cls.from_names(["language_model"])
    benchmark = self.benchmark_cls(stories)

    probe_results: dict[str, Any] = {}
    repetitions = 1
    active_browsers = self.browsers[:1]
    for _ in range(repetitions):
      for browser in active_browsers:
        self._setup_run_js_expect(browser, probe_results, status="failed")

    for browser in active_browsers:
      browser.expected_js = copy.deepcopy(browser.expected_js)

    runner = Runner(
        self.out_dir,
        active_browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True,
        in_memory_result_db=True,
    )

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      with self.assertRaises(ValueError) as cm_err:
        runner.run()
      self.assertIn(
          "Blink-AI Benchmark did not finish successfully",
          str(cm_err.exception),
      )
    cm.assert_called_once()

    for browser in active_browsers:
      self.assertSequenceEqual(browser.expected_js, [])

  def test_multimodal_stories(self):
    stories = self.story_cls.from_names(
        ["multimodal_image", "multimodal_audio"])
    self.assertEqual(len(stories), 1)
    story = stories[0]
    self.assertDictEqual(story.url_params,
                         {"stories": "multimodal_image,multimodal_audio"})
    self.assertEqual(
        story.test_url,
        self.story_cls.URL + "?stories=multimodal_image%2Cmultimodal_audio",
    )

  def test_substories_and_default(self):
    default_stories = self.story_cls.default_story_names()
    self.assertEqual(
        default_stories,
        (
            "language_model",
            "multimodal_image",
            "multimodal_images",
            "multimodal_audio",
        ),
    )
    for mtp_story in ("mtp_summary", "mtp_flight", "mtp_emoji"):
      self.assertIn(mtp_story, self.story_cls.SUBSTORIES)
      self.assertNotIn(mtp_story, default_stories)

    default_story = self.story_cls.default()[0]
    self.assertFalse(default_story.has_mtp_substory)
    default_flags = self.benchmark_cls.extra_flags(
        self.browsers[0].attributes(), default_story)
    self.assertIn(
        "OnDeviceModelIdleTimeout:on_device_model_idle_timeout/10s",
        str(default_flags),
    )
    self.assertNotIn("OnDeviceModelSpeculativeDecoding", str(default_flags))

    mtp_story_obj = self.story_cls.from_names(["mtp_summary"])[0]
    self.assertTrue(mtp_story_obj.has_mtp_substory)
    mtp_flags = self.benchmark_cls.extra_flags(self.browsers[0].attributes(),
                                               mtp_story_obj)
    self.assertIn("OnDeviceModelSpeculativeDecoding", str(mtp_flags))

  def test_mtp_stories(self):
    stories = self.story_cls.from_names(
        ["mtp_summary", "mtp_flight", "mtp_emoji"])
    self.assertEqual(len(stories), 1)
    story = stories[0]
    self.assertTrue(story.has_mtp_substory)
    self.assertDictEqual(story.url_params,
                         {"stories": "mtp_summary,mtp_flight,mtp_emoji"})
    self.assertEqual(
        story.test_url,
        self.story_cls.URL + "?stories=mtp_summary%2Cmtp_flight%2Cmtp_emoji",
    )

  def test_mtp_constrained_story(self):
    name = "mtp_constrained_summary"
    self.assertIn(name, self.story_cls.MTP_SUBSTORIES)
    self.assertNotIn(name, self.story_cls.default_story_names())
    story = self.story_cls.from_names([name])[0]
    self.assertTrue(story.has_mtp_substory)
    self.assertDictEqual(story.url_params, {"stories": name})
    flags = self.benchmark_cls.extra_flags(self.browsers[0].attributes(), story)
    self.assertIn("OnDeviceModelSpeculativeDecoding", str(flags))

  def test_vram_probe_context_single_gpu(self):
    samples = [
        {
            "gpu_0": 100.0,
        },
        {
            "gpu_0": 150.0,
        },
        {
            "gpu_0": 200.0,
        },
        {
            "gpu_0": 120.0,
        },
    ]
    data = self._run_vram_probe_context(samples, {"downloadTimeMs": 10.0})
    self.assertEqual(data["downloadTimeMs"], 10.0)
    self._assert_vram_stats(data, peak_mb=200.0, baseline_mb=100.0)
    self._assert_vram_stats(
        data, peak_mb=200.0, baseline_mb=100.0, gpu_id="gpu_0")

  def test_vram_probe_context_multi_gpu(self):
    samples = [
        {
            "gpu_0": 100.0,
            "gpu_1": 200.0,
        },
        {
            "gpu_0": 150.0,
            "gpu_1": 250.0,
        },
        {
            "gpu_0": 300.0,
            "gpu_1": 220.0,
        },
        {
            "gpu_0": 100.0,
            "gpu_1": 200.0,
        },
    ]
    data = self._run_vram_probe_context(samples,
                                        {"sessionCreationTimeMs": 50.0})
    self.assertEqual(data["sessionCreationTimeMs"], 50.0)
    self._assert_vram_stats(data, peak_mb=550.0, baseline_mb=300.0)
    self._assert_vram_stats(
        data,
        peak_mb=300.0,
        baseline_mb=100.0,
        gpu_id="gpu_0",
        check_flat_gpu=True,
    )
    self._assert_vram_stats(
        data,
        peak_mb=250.0,
        baseline_mb=200.0,
        gpu_id="gpu_1",
        check_flat_gpu=True,
    )

  def test_vram_probe_context_no_gpu(self):
    data = self._run_vram_probe_context([{}], {"downloadTimeMs": 10.0})
    self.assertEqual(data, {"downloadTimeMs": 10.0})

  def test_vram_probe_config_parser(self):
    parser = BlinkAIProbe.config_parser()
    probe = parser.parse({"vram_interval": "2s"})
    self.assertEqual(probe.vram_interval, dt.timedelta(seconds=2))

  def test_vram_probe_invalid_interval(self):
    with self.assertRaises(ValueError):
      BlinkAIProbe(vram_interval=dt.timedelta(seconds=0.01))

  def test_run_with_vram(self):
    stories = self.story_cls.from_names(["language_model"])
    benchmark = self.benchmark_cls(stories)
    probe_results = {"downloadTimeMs": 500.5, **SAMPLE_STORY_METRICS}

    for browser in self.browsers:
      self._setup_run_js_expect(browser, probe_results)
      browser.expected_js = copy.deepcopy(browser.expected_js)

    self.platform.gpu_vram_used = mock.Mock(side_effect=[{
        "gpu_0": 100.0,
    }, {
        "gpu_0": 250.0,
    }] + [{
        "gpu_0": 150.0,
    }] * 20)

    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=EnvConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=1,
        throw=True,
        in_memory_result_db=True,
    )

    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()

    expected_vram_keys = tuple(f"vram_{stat}_{unit}" for stat in VRAM_STAT_NAMES
                               for unit in ("mb", "bytes"))
    summary_file = self.out_dir / "blink_ai.json"
    self.assertTrue(summary_file.exists())
    summary_content = json.loads(summary_file.read_text())
    for browser in self.browsers:
      browser_data = summary_content[browser.unique_name]["data"]
      for key in expected_vram_keys:
        self.assertIn(key, browser_data)
      self.assertIn("vram/peak_mb", browser_data)

    story_json_files = [
        f for f in self.out_dir.glob("**/blink_ai.json") if f != summary_file
    ]
    self.assertTrue(len(story_json_files) > 0)
    for json_file in story_json_files:
      content = json.loads(json_file.read_text())
      for key in expected_vram_keys:
        self.assertIn(key, content)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
