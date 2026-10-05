# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
import pathlib
import unittest
from unittest import mock

from typing_extensions import override

from crossbench import path as pth
from crossbench.benchmarks.loading.page.live import LivePage
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.browsers.settings import Settings
from crossbench.plt.android_adb import Adb
from crossbench.plt.bin import Binaries
from crossbench.plt.linux import PERF_EVENT_PARANOID_PATH
from crossbench.probes import all as all_probes
from crossbench.probes.probe_error import ProbeIncompatibleBrowser, \
    ProbeValidationError
from crossbench.probes.profiling.context.android import \
    AndroidProfilingContext, generate_simpleperf_command_line
from crossbench.probes.profiling.context.linux import LinuxProfilingContext, \
    linux_perf_probe_pprof
from crossbench.probes.profiling.enum import CallGraphMode, CleanupMode, \
    PprofMode, TargetMode, TraceconvMode
from crossbench.probes.profiling.system_profiling import RENDERER_CMD_PATH, \
    ProfilingProbe
from tests import test_helper
from tests.crossbench.mock_browser import MockChromeStable, MockFirefox, \
    MockSafari
from tests.crossbench.mock_helper import AndroidAdbMockPlatform, \
    LinuxMockPlatform, MacOsMockPlatform, MockPopen, MockPopenState
from tests.crossbench.probes.helper import GenericProbeTestCase


class SystemProfilingProbeTestCase(GenericProbeTestCase):

  @override
  def setUp(self):
    super().setUp()
    self.fs.add_real_file(RENDERER_CMD_PATH)

  def test_simpleperf_command_line_with_tid(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.RENDERER_MAIN_ONLY,
            app_name="com.android.chrome",
            renderer_pid=1234,
            renderer_main_tid=5678,
            call_graph_mode=CallGraphMode.DWARF,
            frequency=None,
            count=None,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-t",
                "5678",
                "--call-graph",
                "dwarf",
                "--post-unwind=yes",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_pid(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.RENDERER_PROCESS_ONLY,
            app_name="com.android.chrome",
            renderer_pid=1234,
            renderer_main_tid=5678,
            call_graph_mode=CallGraphMode.DWARF,
            frequency=None,
            count=None,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-p",
                "1234",
                "--call-graph",
                "dwarf",
                "--post-unwind=yes",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_app(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.BROWSER_APP_ONLY,
            app_name="com.chrome.beta",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.DWARF,
            frequency=None,
            count=None,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "--app",
                "com.chrome.beta",
                "--call-graph",
                "dwarf",
                "--post-unwind=yes",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_systemwide(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.DWARF,
            frequency=None,
            count=None,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "--call-graph",
                "dwarf",
                "--post-unwind=yes",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_frequency(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.FRAME_POINTER,
            frequency=1234,
            count=None,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "--call-graph",
                "fp",
                "-f",
                "1234",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_count(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.FRAME_POINTER,
            frequency=None,
            count=5,
            cpus=(),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "--call-graph",
                "fp",
                "-c",
                "5",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_cpu(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.FRAME_POINTER,
            frequency=None,
            count=None,
            cpus=(
                0,
                1,
                2,
            ),
            events=(),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "--call-graph",
                "fp",
                "--cpu",
                "0,1,2",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_events(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.NO_CALL_GRAPH,
            frequency=1234,
            count=5,
            cpus=(),
            events=(
                "cpu-cycles",
                "instructions",
            ),
            grouped_events=(),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "-f",
                "1234",
                "-c",
                "5",
                "-e",
                "cpu-cycles,instructions",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_grouped_events(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.NO_CALL_GRAPH,
            frequency=1234,
            count=5,
            cpus=(),
            events=(),
            grouped_events=(
                "cpu-cycles",
                "instructions",
            ),
            add_counters=(),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "-f",
                "1234",
                "-c",
                "5",
                "--group",
                "cpu-cycles,instructions",
                "-o",
                output_path,
            ])

  def test_simpleperf_command_line_with_add_counters(self):
    output_path = pathlib.Path("simpleperf.perf.data")
    self.assertSequenceEqual(
        generate_simpleperf_command_line(
            target=TargetMode.SYSTEM_WIDE,
            app_name="org.chromium.chrome",
            renderer_pid=None,
            renderer_main_tid=None,
            call_graph_mode=CallGraphMode.NO_CALL_GRAPH,
            frequency=1234,
            count=5,
            cpus=(),
            events=("sched:sched_switch",),
            grouped_events=(),
            add_counters=(
                "cpu-cycles",
                "instructions",
            ),
            output_path=output_path), [
                "simpleperf",
                "record",
                "-a",
                "-f",
                "1234",
                "-c",
                "5",
                "-e",
                "sched:sched_switch",
                "--add-counter",
                "cpu-cycles,instructions",
                "--no-inherit",
                "-o",
                output_path,
            ])

  def test_parse_target_preset(self):
    probe = ProfilingProbe()
    self.assertEqual(probe.target, TargetMode.AUTO)
    probe = ProfilingProbe.parse_str("browser_app_only")
    self.assertEqual(probe.target, TargetMode.BROWSER_APP_ONLY)
    probe = ProfilingProbe.parse_str("renderer_process_only")
    self.assertEqual(probe.target, TargetMode.RENDERER_PROCESS_ONLY)
    probe = ProfilingProbe.parse_str("renderer_main_only")
    self.assertEqual(probe.target, TargetMode.RENDERER_MAIN_ONLY)

  def test_pprof_default_auto(self):
    probe = ProfilingProbe()
    self.assertEqual(probe.pprof_mode, PprofMode.AUTO)
    self.assertEqual(probe.traceconv_mode, TraceconvMode.AUTO)

  def test_run_pprof_method(self):
    probe = ProfilingProbe(pprof=PprofMode.ALWAYS)
    mock_browser1 = mock.Mock()
    self.assertTrue(probe.run_pprof(mock_browser1))

    probe = ProfilingProbe(pprof=PprofMode.NEVER)
    mock_browser2 = mock.Mock()
    self.assertFalse(probe.run_pprof(mock_browser2))

    probe = ProfilingProbe()

    mock_browser3 = mock.Mock()
    mock_browser3.platform.is_linux = False
    self.assertFalse(probe.run_pprof(mock_browser3))

    mock_browser4 = mock.Mock()
    mock_browser4.platform = LinuxMockPlatform(fake_fs=self.fs)
    mock_browser4.platform.install_mock_binary("pprof", "/usr/bin/pprof4")
    mock_browser4.platform.install_mock_binary("gcert", "/usr/bin/gcert4")
    self.assertTrue(probe.run_pprof(mock_browser4))

    mock_browser5 = mock.Mock()
    mock_browser5.platform = LinuxMockPlatform(fake_fs=self.fs)
    mock_browser5.platform.install_mock_binary("gcert", "/usr/bin/gcert5")
    self.assertFalse(probe.run_pprof(mock_browser5))

    mock_browser6 = mock.Mock()
    mock_browser6.platform = LinuxMockPlatform(fake_fs=self.fs)
    mock_browser6.platform.install_mock_binary("pprof", "/usr/bin/pprof6")
    self.assertFalse(probe.run_pprof(mock_browser6))

  def test_validate_pprof(self):
    probe = ProfilingProbe()
    mock_browser = mock.Mock()
    mock_browser.attributes().is_chromium_based = False
    mock_browser.platform = LinuxMockPlatform(fake_fs=self.fs)
    mock_browser.platform.install_mock_binary("pprof", "/usr/bin/pprof")
    mock_browser.platform.install_mock_binary("gcert", "/usr/bin/gcert")
    mock_browser.platform.install_mock_binary("gcertstatus",
                                              "/usr/bin/gcertstatus")
    mock_browser.platform.install_mock_binary("perf", "/usr/bin/perf")
    mock_browser.platform.expect_sh("/usr/bin/gcertstatus")
    mock_browser.host_platform = mock_browser.platform
    mock_env = mock.Mock()
    probe.validate_browser(mock_env, mock_browser)
    self.assertTrue(probe.run_pprof(mock_browser))

  def test_validate_linux_perf_paranoid(self) -> None:
    probe = ProfilingProbe(pprof=False)
    mock_browser = mock.Mock()
    mock_browser.attributes().is_chromium_based = False
    mock_browser.platform = LinuxMockPlatform(fake_fs=self.fs)
    mock_browser.platform.install_mock_binary("perf", "/usr/bin/perf")
    mock_browser.host_platform = mock_browser.platform
    mock_env = mock.Mock()

    self.fs.create_file(PERF_EVENT_PARANOID_PATH, contents="2\n")
    probe.validate_browser(mock_env, mock_browser)

    mock_browser.platform.rm(PERF_EVENT_PARANOID_PATH)
    self.fs.create_file(PERF_EVENT_PARANOID_PATH, contents="4\n")
    with self.assertRaisesRegex(ProbeValidationError,
                                "kernel.perf_event_paranoid=4"):
      probe.validate_browser(mock_env, mock_browser)

  def test_resolve_target_mode(self):
    probe = ProfilingProbe()
    self.assertEqual(probe.target, TargetMode.AUTO)

    macos_platform = MacOsMockPlatform()
    MockChromeStable.setup_fs(self.fs, macos_platform)
    macos_browser = MockChromeStable(
        "macos_chrome", settings=Settings(platform=macos_platform))
    self.assertEqual(
        probe.resolve_target_mode(macos_browser),
        TargetMode.RENDERER_PROCESS_ONLY)

    linux_platform = LinuxMockPlatform()
    MockChromeStable.setup_fs(self.fs, linux_platform)
    linux_browser = MockChromeStable(
        "linux_chrome", settings=Settings(platform=linux_platform))
    self.assertEqual(
        probe.resolve_target_mode(linux_browser), TargetMode.BROWSER_APP_ONLY)

    # For explicitly set targets, it should always return that target
    probe = ProfilingProbe(target=TargetMode.SYSTEM_WIDE)
    self.assertEqual(
        probe.resolve_target_mode(macos_browser), TargetMode.SYSTEM_WIDE)
    self.assertEqual(
        probe.resolve_target_mode(linux_browser), TargetMode.SYSTEM_WIDE)

  def test_create_non_defaults(self):
    probe = ProfilingProbe.parse_dict({
        "js": False,
        "browser_process": True,
        "spare_renderer_process": True,
        "v8_interpreted_frames": False,
        "pprof": False,
        "cleanup": "never",
        "target": "renderer_process_only",
        "pin_renderer_main_core": 3,
        "call_graph_mode": "dwarf",
        "frequency": 1200,
        "count": 430,
        "cpu": [1, 2, 3],
        "events": ["instructions", "cache-misses"],
        "grouped_events": ["cache-references", "cache-misses"],
        "add_counters": ["aa", "bb"],
    })
    self.assertTrue(probe.key)
    self.assertFalse(probe.sample_js)
    self.assertTrue(probe.sample_browser_process)
    self.assertEqual(probe.pprof_mode, PprofMode.NEVER)
    self.assertEqual(probe.cleanup_mode, CleanupMode.NEVER)
    self.assertEqual(probe.target, TargetMode.RENDERER_PROCESS_ONLY)
    self.assertTrue(probe.start_profiling_after_setup(probe.target))
    self.assertEqual(probe.pin_renderer_main_core, 3)
    self.assertEqual(probe.call_graph_mode, CallGraphMode.DWARF)
    self.assertEqual(probe.frequency, 1200)
    self.assertEqual(probe.count, 430)
    self.assertSequenceEqual(probe.cpu, (1, 2, 3))
    self.assertSequenceEqual(probe.events, ("instructions", "cache-misses"))
    self.assertSequenceEqual(probe.grouped_events,
                             ("cache-references", "cache-misses"))
    self.assertSequenceEqual(probe.add_counters, ("aa", "bb"))

  def test_v8_interpreted_frames_default(self):
    probe = ProfilingProbe()
    self.assertTrue(probe.expose_v8_interpreted_frames)

    probe = ProfilingProbe(js=False)
    self.assertFalse(probe.expose_v8_interpreted_frames)

    probe = ProfilingProbe(js=True, v8_interpreted_frames=False)
    self.assertFalse(probe.expose_v8_interpreted_frames)

    with self.assertRaisesRegex(AssertionError,
                                "Cannot expose V8 interpreted frames"):
      ProfilingProbe(js=False, v8_interpreted_frames=True)

    probe = ProfilingProbe.parse_dict({"js": False})
    self.assertFalse(probe.expose_v8_interpreted_frames)

    probe = ProfilingProbe.parse_dict({"js": True})
    self.assertTrue(probe.expose_v8_interpreted_frames)

  def test_create_custom_frequency(self):
    probe = ProfilingProbe.parse_dict({"freq": "max"})
    self.assertEqual(probe.frequency, "max")
    probe = ProfilingProbe.parse_dict({"freq": 333})
    self.assertEqual(probe.frequency, 333)

  def test_create_invalid_frequency(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "frequency"):
      _ = ProfilingProbe.parse_dict({"freq": -100})
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "frequency"):
      _ = ProfilingProbe.parse_dict({"freq": "maaaaxxx"})

  def test_spare_renderer(self):
    browser_a = self.browsers[0]
    browser_b = self.browsers[0]

    probe_spare = ProfilingProbe(spare_renderer_process=True)
    browser_a.attach_probe(probe_spare)
    self.assertNotIn("SpareRendererForSitePerProcess",
                     browser_b.features.disabled)

    probe_no_spare = ProfilingProbe(spare_renderer_process=False)
    browser_b.attach_probe(probe_no_spare)
    self.assertIn("SpareRendererForSitePerProcess", browser_b.features.disabled)

  def test_attach_unsupported(self):
    probe = ProfilingProbe()

    macos_platform = MacOsMockPlatform()
    test_browsers = (MockSafari, MockFirefox, MockChromeStable)
    for browser_cls in test_browsers:
      browser_cls.setup_fs(self.fs, macos_platform)
      name = browser_cls.__name__
      browser_cls(
          name, settings=Settings(platform=macos_platform)).attach_probe(probe)

    linux_platform = LinuxMockPlatform()
    for browser_cls in test_browsers:
      browser_cls.setup_fs(self.fs, linux_platform)
    with self.assertRaises(AssertionError):
      MockFirefox(
          "firefox",
          settings=Settings(platform=linux_platform)).attach_probe(probe)
    MockChromeStable(
        "chrome",
        settings=Settings(platform=linux_platform)).attach_probe(probe)

  def test_validate_linux_auto_pprof_no_fail(self) -> None:
    probe = ProfilingProbe(pprof=PprofMode.AUTO)
    env = mock.Mock()
    browser = mock.Mock()
    browser.platform = LinuxMockPlatform(fake_fs=self.fs)
    browser.platform.install_mock_binary("perf", "/usr/bin/perf")
    probe._validate_linux(env, browser)
    env.check_installed.assert_not_called()

  def test_validate_linux_always_pprof_checks_binary(self) -> None:
    probe = ProfilingProbe(pprof=PprofMode.ALWAYS)
    env = mock.Mock()
    browser = mock.Mock()
    browser.platform = LinuxMockPlatform(fake_fs=self.fs)
    browser.platform.install_mock_binary("perf", "/usr/bin/perf")
    probe._validate_linux(env, browser)
    env.check_installed.assert_called_once_with(
        binaries=[Binaries.PPROF], platform=browser.platform)

  def test_validate_linux_always_traceconv_checks_binary(self) -> None:
    probe = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    env = mock.Mock()
    browser = mock.Mock()
    browser.platform = LinuxMockPlatform(fake_fs=self.fs)
    browser.platform.install_mock_binary("perf", "/usr/bin/perf")
    probe._validate_linux(env, browser)
    env.check_installed.assert_called_once_with(
        binaries=[Binaries.TRACE_PROCESSOR_SHELL], platform=browser.platform)

  def test_validate_non_linux_pprof_traceconv(self) -> None:
    env = mock.Mock(repetitions=1)
    browser = mock.Mock()
    browser.attributes().is_chromium_based = False
    browser.platform = MacOsMockPlatform(fake_fs=self.fs)
    browser.platform.install_mock_binary("xctrace", "/usr/bin/xctrace")

    probe_auto = ProfilingProbe()
    probe_auto.validate_browser(env, browser)

    probe_pprof = ProfilingProbe(pprof=PprofMode.ALWAYS)
    with self.assertRaisesRegex(ProbeIncompatibleBrowser, "'pprof'"):
      probe_pprof.validate_browser(env, browser)

    probe_traceconv = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    with self.assertRaisesRegex(ProbeIncompatibleBrowser, "'traceconv'"):
      probe_traceconv.validate_browser(env, browser)

  def test_validate_android_always_traceconv_checks_binary(self) -> None:
    probe = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    env = mock.Mock()
    host_platform = LinuxMockPlatform(fake_fs=self.fs)
    adb = mock.Mock(spec=Adb, host_platform=host_platform, serial_id="777")
    browser = mock.Mock()
    browser.host_platform = host_platform
    browser.platform = AndroidAdbMockPlatform(
        host_platform, adb=adb, fake_fs=self.fs)
    browser.platform.which = mock.Mock(return_value="/system/bin/simpleperf")
    probe._validate_android(env, browser)
    env.check_installed.assert_called_once_with(
        binaries=[Binaries.TRACE_PROCESSOR_SHELL], platform=host_platform)

  def test_run_traceconv_android(self) -> None:
    probe = ProfilingProbe(traceconv=TraceconvMode.AUTO)
    host_platform1 = LinuxMockPlatform(fake_fs=self.fs)
    adb1 = mock.Mock(spec=Adb, host_platform=host_platform1, serial_id="777")
    browser1 = mock.Mock()
    browser1.host_platform = host_platform1
    browser1.platform = AndroidAdbMockPlatform(
        host_platform1, adb=adb1, fake_fs=self.fs)
    self.assertFalse(probe.run_traceconv(browser1))

    host_platform2 = LinuxMockPlatform(fake_fs=self.fs)
    host_platform2.install_mock_binary("trace_processor_shell",
                                       "/usr/bin/trace_processor_shell")
    adb2 = mock.Mock(spec=Adb, host_platform=host_platform2, serial_id="777")
    browser2 = mock.Mock()
    browser2.host_platform = host_platform2
    browser2.platform = AndroidAdbMockPlatform(
        host_platform2, adb=adb2, fake_fs=self.fs)
    self.assertTrue(probe.run_traceconv(browser2))



class LinuxProfilingContextTestCase(GenericProbeTestCase):

  @override
  def setup_platform(self) -> LinuxMockPlatform:
    return LinuxMockPlatform()

  @override
  def setUp(self) -> None:
    super().setUp()
    self.platform.fake_fs = self.fs
    self.fs.add_real_file(RENDERER_CMD_PATH)
    self.probe = ProfilingProbe()
    self.run = mock.Mock()
    self.run.is_remote = False
    self.run.browser = mock.Mock()
    self.run.browser.platform = self.platform
    self.run.browser.version = ChromiumVersion((120, 0, 0, 0))
    self.run.browser.path = pathlib.Path("/tmp/chrome/chrome")
    self.run.browser_platform = self.platform
    self.run.host_platform = self.platform
    self.run.browser_tmp_dir = pathlib.Path("/tmp/test_result")
    self.run.result_path = pth.LocalPath("/tmp/test_result")
    self.run.out_dir = pth.LocalPath("/tmp/test_result")
    self.run.session = mock.Mock()
    self.run.session.extra_js_flags = {}
    self.run.actions = mock.MagicMock()
    self.run.get_default_probe_result_path = mock.Mock(
        return_value=pth.LocalPath("/tmp/test_result"))

  def test_auto_infer_pprof_true(self) -> None:
    self.platform.install_mock_binary("pprof", "/usr/bin/pprof")
    self.platform.install_mock_binary("gcert", "/usr/bin/gcert")
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertTrue(context.run_pprof)

  def test_auto_infer_pprof_false_missing_pprof(self) -> None:
    self.platform.install_mock_binary("gcert", "/usr/bin/gcert")
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertFalse(context.run_pprof)

  def test_auto_infer_pprof_false_missing_gcert(self) -> None:
    self.platform.install_mock_binary("pprof", "/usr/bin/pprof")
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertFalse(context.run_pprof)

  def test_explicit_pprof_true(self) -> None:
    self.probe = ProfilingProbe(pprof=PprofMode.ALWAYS)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertTrue(context.run_pprof)

  def _mock_stop(self, context: LinuxProfilingContext) -> None:
    other_perf = context.result_path / "chrome_renderer_111_1.perf.data"
    renderer_perf = context.result_path / "chrome_renderer_111_2.perf.data"
    self.fs.create_file(other_perf, contents="x" * 200)
    self.fs.create_file(renderer_perf, contents="x" * 100)
    self.fs.create_file(context.run.out_dir / "jit-1234.dump", contents="jit")
    debug_dir = context.result_path / "debug"
    self.platform.expect_sh(
        f"perf --buildid-dir {debug_dir} script -i {other_perf} -F pid"
        " | head -n1",
        result="9999\n")
    self.platform.expect_sh(
        f"perf --buildid-dir {debug_dir} script -i {renderer_perf} -F pid"
        " | head -n1",
        result="1234\n")

  def test_run_renderer_process_only(self) -> None:
    self.platform.install_mock_binary("perf", "/usr/bin/perf")
    self.fs.create_file(PERF_EVENT_PARANOID_PATH, contents="2\n")
    probe = ProfilingProbe.parse_dict({
        "js": False,
        "pprof": False,
        "cleanup": True,
        "frequency": 100,
        "call_graph_mode": "no_call_graph",
        "target": "renderer_process_only",
    })
    for browser in self.browsers:
      browser._version = ChromiumVersion((125, 0, 0, 0))
      browser.get_renderer_pid = mock.Mock(return_value=1234)
      browser.get_renderer_main_tid = mock.Mock(return_value=5678)

    stories = [LivePage("google", "https://google.com")]
    runner = self.create_runner(
        stories, js_side_effects=[], repetitions=1, throw=True)
    runner.attach_probe(probe)

    for browser in self.browsers:
      self.assertIn("--no-sandbox", browser.flags)
      self.assertIn("--enable-benchmarking-api", browser.flags)
      self.assertIn("SpareRendererForSitePerProcess", browser.features.disabled)
      cmd_prefix = browser.flags["--renderer-cmd-prefix"]
      self.assertIn("--perf-freq=100", cmd_prefix)
      self.assertIn("--perf-call-graph=no_call_graph", cmd_prefix)

    with mock.patch.object(
        LinuxProfilingContext,
        "stop",
        autospec=True,
        side_effect=self._mock_stop):
      runner.run()

    self.assertTrue(runner.is_success)
    for run in runner.runs:
      expected_perf = run.out_dir / "profiling/chrome_renderer_111_2.perf.data"
      self.assertSequenceEqual(run.results[probe].file_list, [expected_perf])
      self.assertFalse((run.out_dir / "jit-1234.dump").exists())
      self.assertTrue((run.out_dir / "profiling/jitdump").is_dir())
      self.assertTrue((run.out_dir / "profiling/debug").is_dir())

  def test_browser_process_profiling(self) -> None:
    probe = ProfilingProbe(
        js=False, pprof=PprofMode.NEVER, browser_process=True, frequency=100)
    self.run.browser.pid = 4321
    self.run.out_dir = pth.LocalPath("/tmp")
    self.run.probes = ()
    perf_proc = MockPopen()
    self.platform.popens.append(perf_proc)

    context = LinuxProfilingContext(probe, self.run)
    perf_file = context.result_path / "browser.perf.data"
    context.setup()
    self.assertEqual(perf_proc.state, MockPopenState.UNUSED)

    self.platform.expect_sh("perf", "record", "--call-graph=fp", "--freq=100",
                            "--clockid=mono", f"--output={perf_file}",
                            "--pid=4321")
    context.start()
    self.assertEqual(perf_proc.state, MockPopenState.RUNNING)

    self.fs.create_file(perf_file, contents="perf_data")

    context.stop()
    self.assertEqual(perf_proc.state, MockPopenState.TERMINATED)

    result = context.teardown()
    self.assertSequenceEqual(result.file_list, [perf_file])

  def test_auto_infer_traceconv_true(self) -> None:
    self.platform.install_mock_binary("trace_processor_shell",
                                      "/usr/bin/trace_processor_shell")
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertTrue(context.run_traceconv)

  def test_auto_infer_traceconv_false(self) -> None:
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertFalse(context.run_traceconv)

  def test_explicit_traceconv_true(self) -> None:
    self.platform.install_mock_binary("trace_processor_shell",
                                      "/usr/bin/trace_processor_shell")
    self.probe = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    self.assertTrue(context.run_traceconv)
    self.assertIsNotNone(context.traceconv_bin)

  def test_explicit_traceconv_missing_binary_fails_setup(self) -> None:
    self.probe = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    with self.assertRaises(AssertionError):
      context.setup()

  def test_teardown_auto_cleanup_with_exported_profile(self) -> None:
    self.platform.install_mock_binary("trace_processor_shell",
                                      "/usr/bin/trace_processor_shell")
    self.probe = ProfilingProbe(
        traceconv=TraceconvMode.ALWAYS, cleanup=CleanupMode.AUTO, js=False)
    result_path = self.run.result_path
    perf_file = result_path / "test.perf.data"
    self.fs.create_file(perf_file)
    debug_dir = result_path / "debug"
    jitdump_dir = result_path / "jitdump"
    self.fs.create_dir(debug_dir)
    self.fs.create_dir(jitdump_dir)
    jitted_file = result_path / "test.perf.data.jitted"
    self.fs.create_file(jitted_file)
    so_file = result_path / "jitted-123.so"
    self.fs.create_file(so_file)

    def mock_sh(*args, **kwargs):
      del kwargs
      if "trace_processor_shell" in str(args[0]):
        out_dir = pth.LocalPath(args[args.index("--output-dir") + 1])
        self.fs.create_file(
            out_dir / "profile.1.pid.123.pb", contents="mock_pprof")

    self.platform.sh = mock.Mock(side_effect=mock_sh)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    with mock.patch("time.sleep"):
      result = context.teardown()
    pprof_file = perf_file.with_suffix(".pprof")
    self.assertEqual(result.get("pprof"), pprof_file)
    self.assertFalse(self.platform.exists(debug_dir))
    self.assertFalse(self.platform.exists(jitdump_dir))
    self.assertFalse(self.platform.exists(jitted_file))
    self.assertFalse(self.platform.exists(so_file))

  def test_teardown_export_to_traceconv(self) -> None:
    self.platform.install_mock_binary("trace_processor_shell",
                                      "/usr/bin/trace_processor_shell")
    self.probe = ProfilingProbe(
        traceconv=TraceconvMode.ALWAYS, cleanup=CleanupMode.NEVER, js=False)
    perf_file = self.run.result_path / "test.perf.data"
    pprof_file = perf_file.with_suffix(".pprof")
    self.fs.create_file(perf_file)

    def mock_sh(*args, **kwargs):
      del kwargs
      if "trace_processor_shell" in str(args[0]):
        out_dir = pth.LocalPath(args[args.index("--output-dir") + 1])
        self.fs.create_file(
            out_dir / "profile.1.pid.123.pb", contents="mock_pprof")

    self.platform.sh = mock.Mock(side_effect=mock_sh)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    with mock.patch("time.sleep"):
      result = context.teardown()
    self.assertEqual(result.get("pprof"), pprof_file)
    self.assertTrue(self.platform.exists(pprof_file))
    self.assertTrue(self.platform.exists(perf_file))

  def test_teardown_always_cleanup_without_exported_profile(self) -> None:
    self.probe = ProfilingProbe(
        pprof=PprofMode.NEVER,
        traceconv=TraceconvMode.NEVER,
        cleanup=CleanupMode.ALWAYS,
        js=True)
    perf_file = self.run.result_path / "test.perf.data"
    jitted_file = self.run.result_path / "test.perf.data.jitted"
    self.fs.create_file(perf_file, contents="raw_perf")

    def mock_sh(*args, **kwargs):
      del kwargs
      if "inject" in args:
        self.fs.create_file(jitted_file, contents="jitted_perf")

    self.platform.sh = mock.Mock(side_effect=mock_sh)
    context = LinuxProfilingContext(self.probe, self.run)
    context.setup_v8_log_path = mock.Mock()
    context.setup()
    with mock.patch("time.sleep"), mock.patch(
        "multiprocessing.Pool") as mock_pool:
      mock_pool.return_value.__enter__.return_value.imap.side_effect = map
      result = context.teardown()
    self.assertFalse(self.platform.exists(jitted_file))
    self.assertSequenceEqual(result.file_list, [perf_file])

  def test_linux_perf_probe_pprof_pre_symbolized(self) -> None:
    self.platform.install_mock_binary("pprof", "/usr/bin/pprof")
    pprof_file = self.run.result_path / "test.pprof"
    self.fs.create_file(pprof_file, contents="data")
    self.platform.sh_stdout = mock.Mock(
        return_value="https://pprof.example.com")
    url = linux_perf_probe_pprof(pprof_file, "run_info", platform=self.platform)
    self.assertEqual(url, "https://pprof.example.com")
    self.platform.sh_stdout.assert_called_once()
    called_args = self.platform.sh_stdout.call_args[0]
    self.assertNotIn("-symbolize=force", called_args)

  def test_android_teardown_export_to_traceconv(self) -> None:
    self.platform.install_mock_binary("trace_processor_shell",
                                      "/usr/bin/trace_processor_shell")
    adb = mock.Mock(spec=Adb, host_platform=self.platform, serial_id="777")
    android_platform = AndroidAdbMockPlatform(self.platform, adb=adb)
    self.run.browser.platform = android_platform
    self.run.browser.host_platform = self.platform
    self.run.browser.app_path = None
    self.run.browser.driver_path = None
    self.run.browser.attributes().is_chromium_based = True
    self.run.browser_platform = android_platform
    self.probe = ProfilingProbe(traceconv=TraceconvMode.ALWAYS)
    context = AndroidProfilingContext(self.probe, self.run)
    perf_file = pth.LocalPath(context.result_path)
    pprof_file = perf_file.with_suffix(".pprof")
    self.fs.create_file(perf_file, contents="perf_data")

    def mock_sh(*args, **kwargs):
      del kwargs
      if "trace_processor_shell" in str(args[0]):
        out_dir = pth.LocalPath(args[args.index("--output-dir") + 1])
        self.fs.create_file(
            out_dir / "profile.1.pid.123.pb", contents="mock_pprof")

    self.platform.sh = mock.Mock(side_effect=mock_sh)
    with mock.patch.object(context, "_stop_existing_simpleperf"):
      context.setup()
    result = context.teardown()
    self.assertEqual(result.get("pprof"), pprof_file)
    self.assertEqual(result.perfetto, perf_file)


class EnumTestCase(unittest.TestCase):

  def test_cleanup_mode(self):
    self.assertIs(CleanupMode(True), CleanupMode.ALWAYS)
    self.assertIs(CleanupMode(False), CleanupMode.NEVER)

    self.assertIs(CleanupMode("always"), CleanupMode.ALWAYS)
    self.assertIs(CleanupMode("never"), CleanupMode.NEVER)
    self.assertIs(CleanupMode("auto"), CleanupMode.AUTO)

  def test_target_mode(self):
    self.assertIs(
        TargetMode("renderer_main_only"), TargetMode.RENDERER_MAIN_ONLY)
    self.assertIs(
        TargetMode("RENDERER_MAIN_ONLY"), TargetMode.RENDERER_MAIN_ONLY)

  def test_call_graph_mode(self):
    self.assertIs(CallGraphMode("fp"), CallGraphMode.FRAME_POINTER)
    self.assertIs(CallGraphMode("FP"), CallGraphMode.FRAME_POINTER)

  def test_pprof_mode(self) -> None:
    self.assertIs(PprofMode(True), PprofMode.ALWAYS)
    self.assertIs(PprofMode(False), PprofMode.NEVER)
    self.assertIs(PprofMode("always"), PprofMode.ALWAYS)
    self.assertIs(PprofMode("never"), PprofMode.NEVER)
    self.assertIs(PprofMode("auto"), PprofMode.AUTO)

  def test_traceconv_mode(self) -> None:
    self.assertIs(TraceconvMode(True), TraceconvMode.ALWAYS)
    self.assertIs(TraceconvMode(False), TraceconvMode.NEVER)
    self.assertIs(TraceconvMode("always"), TraceconvMode.ALWAYS)
    self.assertIs(TraceconvMode("never"), TraceconvMode.NEVER)
    self.assertIs(TraceconvMode("auto"), TraceconvMode.AUTO)

    probe = ProfilingProbe.parse_dict({"traceconv": True})
    self.assertIs(probe.traceconv_mode, TraceconvMode.ALWAYS)
    probe = ProfilingProbe.parse_dict({"traceconv": False})
    self.assertIs(probe.traceconv_mode, TraceconvMode.NEVER)
    probe = ProfilingProbe.parse_dict({"traceconv": "auto"})
    self.assertIs(probe.traceconv_mode, TraceconvMode.AUTO)
    probe = ProfilingProbe.parse_dict({"traceconv": "always"})
    self.assertIs(probe.traceconv_mode, TraceconvMode.ALWAYS)
    probe = ProfilingProbe.parse_dict({"traceconv": "never"})
    self.assertIs(probe.traceconv_mode, TraceconvMode.NEVER)



# Remove import that's used to avoid circular import issues.
del all_probes

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
