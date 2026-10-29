# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
import datetime as dt
import re
import unittest
import unittest.mock
from typing import TYPE_CHECKING, cast

from typing_extensions import override

from crossbench import path as pth
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.meminfo import MeminfoAction
from crossbench.action_runner.action.switch_tab import SwitchTabAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.benchmarks.multiwindow_memory_stress import \
    multiwindow_memory_stress_benchmark as mw_stress
from crossbench.cli.config.probe_list import ProbeListConfig
from crossbench.probes.trace_processor.trace_processor import \
    TraceProcessorProbe
from tests import test_helper
from tests.crossbench.benchmarks import helper

if TYPE_CHECKING:
  from crossbench.benchmarks.loading.config.blocks import ActionBlock


class MultiwindowMemoryStressBenchmarkTestCase(helper.BaseBenchmarkTestCase):

  @property
  @override
  def benchmark_cls(self) -> type[mw_stress.MultiwindowMemoryStressBenchmark]:
    return mw_stress.MultiwindowMemoryStressBenchmark

  @property
  @override
  def story_cls(self) -> type[mw_stress.MultiwindowMemoryStressPage]:
    return mw_stress.MultiwindowMemoryStressPage

  @property
  def story_filter_cls(
      self) -> type[mw_stress.MultiwindowMemoryStressStoryFilter]:
    return mw_stress.MultiwindowMemoryStressStoryFilter

  @override
  def setUp(self) -> None:
    super().setUp()
    self.fs.create_file(mw_stress.STRESS_ALLOC_JS, contents="/* ALLOC_MB */")
    self.fs.create_file(mw_stress.REVISIT_TAB_JS, contents="/* PHASE */")

  def _create_page(self, *args: str) -> mw_stress.MultiwindowMemoryStressPage:
    stories = self.story_filter_cls.stories_from_cli_args(
        self.parse_args(*args))
    self.assertEqual(len(stories), 1)
    page = stories[0]
    self.assertIsInstance(page, self.story_cls)
    self.assertEqual(page.name, mw_stress.STORY_NAME)
    return cast(mw_stress.MultiwindowMemoryStressPage, page)

  def _mock_run(self,
                total_memory_mb: int = 8 * 1024) -> unittest.mock.MagicMock:
    run = unittest.mock.MagicMock()
    run.browser.platform.total_memory_mb.return_value = total_memory_mb
    return run

  def _run_blocks(self,
                  page: mw_stress.MultiwindowMemoryStressPage,
                  total_memory_mb: int = 8 * 1024) -> list[ActionBlock]:
    action_runner = unittest.mock.MagicMock()
    action_runner.run = self._mock_run(total_memory_mb)
    page.run_with(action_runner, False)
    action_runner.run_interactive_page.assert_called_once()
    run_page, multiple_tabs = (
        action_runner.run_interactive_page.call_args.args)
    self.assertIs(run_page, page)
    self.assertFalse(multiple_tabs)
    return list(page.blocks)

  def _alloc_replacements(self, blocks: list[ActionBlock]) -> dict:
    alloc = cast(JsAction, blocks[1].actions[2])
    assert alloc.replacements
    return alloc.replacements.to_json()

  def test_static_page(self) -> None:
    page = self._create_page()
    self.assertEqual(page.first_url, mw_stress.STARTER_URL)
    self.assertListEqual([block.label for block in page.blocks],
                         ["stage-0-init"])
    self.assertIsNone(page.config.alloc_mb)
    self.assertIsNone(page.config.image_count)
    self.assertIsNone(page.resolved_config)
    self.assertEqual(page.details_json()["config"], page.config.to_json())
    self.assertDictEqual(
        page.config.to_json(), {
            "windows": 6,
            "tabs_per_window": 5,
            "alloc_mb": None,
            "image_count": None,
            "tab_wait": 0.4,
            "revisit_wait": 0.25,
        })

  def test_default_sizes_scale_with_memory(self) -> None:
    test_cases = (
        # total_memory_mb, alloc_mb, image_count
        (8 * 1024, 180, 10),
        (4 * 1024, 90, 5),
        (16 * 1024, 360, 20),
        (2 * 1024, 45, 2),
        (1024, 22, 2),
    )
    for total_memory_mb, alloc_mb, image_count in test_cases:
      with self.subTest(total_memory_mb=total_memory_mb):
        config = mw_stress.StressConfig()
        self.assertEqual(config.default_alloc_mb(total_memory_mb), alloc_mb)
        self.assertEqual(
            config.default_image_count(total_memory_mb), image_count)

  def test_resolve(self) -> None:
    config = mw_stress.StressConfig()
    self.assertFalse(config.is_resolved)
    resolved = config.resolve(4 * 1024)
    self.assertTrue(resolved.is_resolved)
    self.assertEqual(resolved.alloc_mb, 90)
    self.assertEqual(resolved.image_count, 5)
    # Explicit values are kept, including 0.
    config = mw_stress.StressConfig(alloc_mb=0, image_count=0)
    self.assertTrue(config.is_resolved)
    resolved = config.resolve(4 * 1024)
    self.assertEqual(resolved.alloc_mb, 0)
    self.assertEqual(resolved.image_count, 0)
    # Each value is resolved independently.
    resolved = mw_stress.StressConfig(alloc_mb=123).resolve(16 * 1024)
    self.assertEqual(resolved.alloc_mb, 123)
    self.assertEqual(resolved.image_count, 20)

  def test_run_with_scaled_sizes(self) -> None:
    page = self._create_page()
    blocks = self._run_blocks(page, total_memory_mb=16 * 1024)
    self.assertDictEqual(
        self._alloc_replacements(blocks), {
            "ALLOC_MB": 360,
            "IMAGE_COUNT": 20,
            "TAB_INDEX": "0",
            "WINDOW_INDEX": "1",
        })

  def test_run_with_explicit_sizes(self) -> None:
    page = self._create_page("--alloc-mb=80", "--image-count=6")
    blocks = self._run_blocks(page, total_memory_mb=16 * 1024)
    replacements = self._alloc_replacements(blocks)
    self.assertEqual(replacements["ALLOC_MB"], 80)
    self.assertEqual(replacements["IMAGE_COUNT"], 6)

  def test_run_once(self) -> None:
    page = self._create_page()
    run = self._mock_run()
    page.run_once(run)
    run.action_runner.run_interactive_page.assert_called_once_with(page, False)
    run.browser.close_all_tabs.assert_called_once_with()
    self.assertEqual(len(page.blocks), 1 + 6 * 2 + 1)
    resolved_config = page.resolved_config
    assert resolved_config
    self.assertEqual(resolved_config.alloc_mb, 180)
    self.assertEqual(resolved_config.image_count, 10)
    details = page.details_json()
    self.assertEqual(details["config"], resolved_config.to_json())
    actions = details["actions"]
    assert isinstance(actions, list)
    self.assertEqual(len(actions), len(page.blocks))

  def test_run_once_closes_tabs_per_iteration(self) -> None:
    page = self._create_page("--playback=2x")
    run = self._mock_run()
    page.run(run)
    self.assertEqual(run.action_runner.run_interactive_page.call_count, 2)
    self.assertEqual(run.browser.close_all_tabs.call_count, 2)

  def test_block_labels(self) -> None:
    page = self._create_page("--windows=2", "--tabs-per-window=3")
    blocks = self._run_blocks(page)
    labels = [block.label for block in blocks]
    self.assertListEqual(labels, [
        "stage-0-init",
        "stage-1-window-1",
        "stage-2-window-2",
        "cycle-window-1",
        "cycle-window-2",
        "stage-final-cooldown",
    ])
    self.assertListEqual([block.index for block in blocks],
                         list(range(len(labels))))

  def test_open_window_block(self) -> None:
    page = self._create_page()
    blocks = self._run_blocks(page)
    block = blocks[1]
    # 7 actions per tab + 1 meminfo.
    self.assertEqual(len(block.actions), 5 * 7 + 1)
    page_load_mark = cast(JsAction, block.actions[0])
    self.assertEqual(page_load_mark.script,
                     'performance.mark("page-load~0", {});')
    first_get = cast(GetAction, block.actions[1])
    self.assertEqual(first_get.target.value, "_new_window")
    self.assertEqual(
        first_get.url,
        "data:text/html,<!doctype html><html><head><title>Tab 0</title>"
        "</head><body><h2>Stress Tab</h2></body></html>")
    second_get = cast(GetAction, block.actions[8])
    self.assertEqual(second_get.target.value, "_new_tab")
    self.assertIn("<title>Tab 1</title>", second_get.url)
    revisit_mark = cast(JsAction, block.actions[4])
    self.assertEqual(revisit_mark.script,
                     'performance.mark("tab-revisit-start~open~0", {});')
    self.assertDictEqual(
        self._alloc_replacements(blocks), {
            "ALLOC_MB": 180,
            "IMAGE_COUNT": 10,
            "TAB_INDEX": "0",
            "WINDOW_INDEX": "1",
        })
    wait = cast(WaitAction, block.actions[3])
    self.assertEqual(wait.duration, dt.timedelta(milliseconds=400))
    meminfo = cast(MeminfoAction, block.actions[-1])
    self.assertEqual(meminfo.title, "after_w1_t5")
    last_meminfo = cast(MeminfoAction, blocks[6].actions[-1])
    self.assertEqual(last_meminfo.title, "after_open")

  def test_cycle_window_block(self) -> None:
    page = self._create_page("--windows=6", "--tabs-per-window=30")
    blocks = self._run_blocks(page)
    block = blocks[7]
    self.assertEqual(block.label, "cycle-window-1")
    self.assertEqual(len(block.actions), 30 * 4)
    # The start mark is created in the previous tab before switching.
    revisit_mark = cast(JsAction, block.actions[0])
    self.assertEqual(revisit_mark.script,
                     'performance.mark("tab-revisit-start~cycle~0", {});')
    switch = cast(SwitchTabAction, block.actions[1])
    assert switch.title
    self.assertEqual(switch.title.pattern, "^Tab 0$")
    revisit = cast(JsAction, block.actions[2])
    assert revisit.replacements
    self.assertDictEqual(revisit.replacements.to_json(), {
        "PHASE": "cycle",
        "TAB_INDEX": "0",
    })
    wait = cast(WaitAction, block.actions[3])
    self.assertEqual(wait.duration, dt.timedelta(milliseconds=250))
    meminfo = cast(MeminfoAction, blocks[1].actions[-1])
    self.assertEqual(meminfo.title, "after_w1_t30")

  def test_cooldown_block(self) -> None:
    page = self._create_page()
    blocks = self._run_blocks(page)
    block = blocks[-1]
    self.assertEqual(block.label, "stage-final-cooldown")
    self.assertEqual(len(block.actions), 3)
    titles = [
        cast(MeminfoAction, block.actions[0]).title,
        cast(MeminfoAction, block.actions[2]).title,
    ]
    self.assertListEqual(titles, ["after_switch", "after_cooldown"])
    wait = cast(WaitAction, block.actions[1])
    self.assertEqual(wait.duration, dt.timedelta(seconds=10))

  def test_page_config_args_not_supported(self) -> None:
    for flag in ("--urls=http://test.com", "--page-config={}"):
      with self.subTest(flag=flag):
        with self.assertRaises(SystemExit):
          self.parse_args(flag)

  def test_name(self) -> None:
    self.assertEqual(self.benchmark_cls.NAME, "multiwindow-memory-stress")
    self.assertTupleEqual(self.benchmark_cls.aliases(), ())


class StressConfigTestCase(unittest.TestCase):

  def test_parse_dict_defaults(self) -> None:
    config = mw_stress.StressConfig.parse_dict({})
    self.assertEqual(config, mw_stress.StressConfig())
    self.assertFalse(config.is_resolved)

  def test_parse_dict(self) -> None:
    config = mw_stress.StressConfig.parse_dict({
        "windows": 2,
        "tabs_per_window": 3,
        "alloc_mb": 0,
        "image_count": 4,
        "tab_wait": "1s",
        "revisit_wait": "0s",
    })
    self.assertEqual(
        config,
        mw_stress.StressConfig(
            windows=2,
            tabs_per_window=3,
            alloc_mb=0,
            image_count=4,
            tab_wait=dt.timedelta(seconds=1),
            revisit_wait=dt.timedelta()))
    self.assertTrue(config.is_resolved)

  def test_parse_dict_invalid(self) -> None:
    invalid_values: tuple[tuple[str, object], ...] = (
        ("windows", 0),
        ("tabs_per_window", -1),
        ("alloc_mb", -1),
        ("image_count", -1),
        ("tab_wait", "-1s"),
    )
    for name, value in invalid_values:
      with self.subTest(name=name, value=value):
        with self.assertRaises(argparse.ArgumentTypeError):
          mw_stress.StressConfig.parse_dict({name: value})

  def test_validate(self) -> None:
    with self.assertRaises(argparse.ArgumentTypeError):
      mw_stress.StressConfig(windows=0)
    with self.assertRaises(argparse.ArgumentTypeError):
      mw_stress.StressConfig(alloc_mb=-1)

  def test_parse_str(self) -> None:
    config = mw_stress.StressConfig.parse_str("3")
    self.assertEqual(config, mw_stress.StressConfig(windows=3))
    self.assertEqual(
        mw_stress.StressConfig.parse("2"), mw_stress.StressConfig(windows=2))

  def test_parse_str_invalid(self) -> None:
    for value in ("0", "-1", "foo"):
      with self.subTest(value=value):
        with self.assertRaises(argparse.ArgumentTypeError):
          mw_stress.StressConfig.parse_str(value)


class MultiwindowMemoryStressProbeConfigTestCase(unittest.TestCase):

  def test_default_probe_config(self) -> None:
    probe_config_path = (
        mw_stress.MultiwindowMemoryStressBenchmark.default_probe_config_path())
    self.assertTrue(probe_config_path.is_file())
    probes = {
        probe.name: probe
        for probe in ProbeListConfig.parse(probe_config_path).probes
    }
    self.assertSetEqual(set(probes), {"trace_processor", "perfetto", "meminfo"})
    trace_processor = probes["trace_processor"]
    assert isinstance(trace_processor, TraceProcessorProbe)
    self.assertEqual(len(trace_processor.metric_definitions), 1)
    self._check_sql_modules(trace_processor.metric_definitions[0],
                            trace_processor.module_paths)
    self._check_polarity(trace_processor.metric_definitions[0])

  def _check_polarity(self, metric_definition: str) -> None:
    metric_specs = re.findall(r"metric_spec: \{.*?\n\}", metric_definition,
                              re.DOTALL)
    self.assertTrue(metric_specs)
    for metric_spec in metric_specs:
      self.assertTrue("polarity: LOWER_IS_BETTER" in metric_spec or
                      "polarity: HIGHER_IS_BETTER" in metric_spec)

  def test_perfetto_config_histograms(self) -> None:
    perfetto_config = (mw_stress.MultiwindowMemoryStressBenchmark
                       .default_probe_config_path().parent /
                       "perfetto_minimal.txtpb").read_text()
    self.assertIn('name: "org.chromium.histogram_sample"', perfetto_config)
    histograms = re.findall(r'histogram_name: "([\w.]+)"', perfetto_config)
    self.assertIn("Memory.Renderer.PrivateMemoryFootprint", histograms)
    self.assertIn("Browser.Tabs.TotalSwitchDuration3", histograms)
    self.assertEqual(len(histograms), len(set(histograms)))

  def _check_sql_modules(self, metric_definition: str,
                         module_paths: tuple[pth.LocalPath, ...]) -> None:
    tables = dict(
        re.findall(r'table_name: "(\w+)"\s+module_name: "([\w.]+)"',
                   metric_definition))
    self.assertDictEqual(
        tables, {
            "tab_timing_by_tab_index":
                "sql_packages.multiwindow_memory_stress.tab_timing",
            "tab_revisit_by_tab_index":
                "sql_packages.multiwindow_memory_stress.tab_revisit",
            "uma_histogram_summaries":
                "sql_packages.multiwindow_memory_stress.uma",
            "meminfo_total_output":
                "sql_packages.multiwindow_memory_stress.meminfo",
            "cpu_usage_stat_output":
                "sql_packages.multiwindow_memory_stress.cpu",
        })
    for table_name, module_name in tables.items():
      with self.subTest(module_name=module_name):
        package, *module = module_name.split(".")
        sql_files = [
            path / pth.LocalPath(*module).with_suffix(".sql")
            for path in module_paths
            if path.name == package
        ]
        self.assertEqual(len(sql_files), 1)
        self.assertIn(f"CREATE VIEW {table_name} AS", sql_files[0].read_text())


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
