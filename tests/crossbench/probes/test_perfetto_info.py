# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from crossbench.browsers.chromium_based.webdriver import ChromiumBasedWebDriver
from crossbench.probes.perfetto_info import CategoryDescription, \
    PerfettoInfoProbe, PerfettoInfoProbeContext
from tests import test_helper
from third_party.protoc.gen.protos.perfetto.common.tracing_service_state_pb2 import \
    TracingServiceState
from third_party.protoc.gen.protos.perfetto.common.track_event_descriptor_pb2 import \
    TrackEventDescriptor


class TestPerfettoInfoProbe(unittest.TestCase):

  def _create_context(self, browser):
    run = mock.MagicMock()
    run.browser = browser
    run.get_default_probe_result_path.return_value = pathlib.Path()
    probe = PerfettoInfoProbe()
    return PerfettoInfoProbeContext(probe, run)

  def test_get_cdp_categories(self):
    browser = mock.MagicMock(spec=ChromiumBasedWebDriver)
    browser.attributes.return_value.is_chromium_based = True
    browser.platform.is_android = False

    descriptor = TrackEventDescriptor()
    cat1 = descriptor.available_categories.add()
    cat1.name = "blink"
    cat1.description = "Blink engine"
    cat1.tags.append("benchmark")
    cat1.tags.append("loading")

    cat2 = descriptor.available_categories.add()
    cat2.name = "v8"
    cat2.description = "V8 engine"
    cat2.tags.append("javascript")

    browser.perfetto_categories.return_value = descriptor

    context = self._create_context(browser)
    categories = context._get_cdp_categories()
    self.assertIsInstance(categories, list)
    self.assertEqual(len(categories), 2)
    categories_dict = {cat.name: cat for cat in categories}
    self.assertIn("blink", categories_dict)
    self.assertEqual(categories_dict["blink"].name, "blink")
    self.assertEqual(categories_dict["blink"].description, "Blink engine")
    self.assertSequenceEqual(categories_dict["blink"].tags,
                             ("benchmark", "loading"))
    self.assertEqual(categories_dict["blink"].data_source, "track_event")

    self.assertIn("v8", categories_dict)
    self.assertEqual(categories_dict["v8"].name, "v8")
    self.assertEqual(categories_dict["v8"].description, "V8 engine")
    self.assertSequenceEqual(categories_dict["v8"].tags, ("javascript",))
    self.assertEqual(categories_dict["v8"].data_source, "track_event")

  def test_get_adb_categories(self):
    browser = mock.MagicMock()
    browser.attributes.return_value.is_chromium_based = False
    browser.platform.is_android = True

    state = TracingServiceState()
    ds1 = state.data_sources.add()
    ds1.ds_descriptor.name = "linux.ftrace"
    atrace_cat = ds1.ds_descriptor.ftrace_descriptor.atrace_categories.add()
    atrace_cat.name = "sched"
    atrace_cat.description = "CPU Scheduling"

    ds2 = state.data_sources.add()
    ds2.ds_descriptor.name = "track_event"

    ds3 = state.data_sources.add()
    ds3.ds_descriptor.name = "android.heapprofd"

    serialized_state = state.SerializeToString()
    browser.platform.sh_stdout_bytes.return_value = serialized_state

    context = self._create_context(browser)
    categories = context._get_adb_categories()
    self.assertIsInstance(categories, list)
    self.assertEqual(len(categories), 2)

    # We can find elements in the set directly:
    sched_cat = next(cat for cat in categories if cat.name == "sched")
    self.assertEqual(sched_cat.description, "CPU Scheduling")
    self.assertEqual(sched_cat.data_source, "linux.ftrace")

    empty_cat = next(
        cat for cat in categories if cat.data_source == "android.heapprofd")
    self.assertEqual(empty_cat.name, "")
    self.assertEqual(empty_cat.data_source, "android.heapprofd")

  def test_get_categories_combined(self):
    browser = mock.MagicMock(spec=ChromiumBasedWebDriver)
    browser.attributes.return_value.is_chromium_based = True
    browser.platform.is_android = True

    descriptor = TrackEventDescriptor()
    cat = descriptor.available_categories.add()
    cat.name = "blink"
    cat.description = "Blink engine"
    cat.tags.append("benchmark")
    browser.perfetto_categories.return_value = descriptor

    state = TracingServiceState()
    ds = state.data_sources.add()
    ds.ds_descriptor.name = "linux.ftrace"
    atrace_cat = ds.ds_descriptor.ftrace_descriptor.atrace_categories.add()
    atrace_cat.name = "sched"
    browser.platform.sh_stdout_bytes.return_value = state.SerializeToString()

    context = self._create_context(browser)
    categories = context.get_categories()
    self.assertEqual(len(categories), 2)
    self.assertEqual(categories[0].name, "sched")
    self.assertEqual(categories[1].name, "blink")


class CategoryDescriptionTestCase(unittest.TestCase):

  def test_parse_minimal(self):
    data = {
        "data_source": "track_event",
        "name": "blink",
    }
    cat = CategoryDescription.parse(data)
    self.assertEqual(cat.data_source, "track_event")
    self.assertEqual(cat.name, "blink")
    self.assertEqual(cat.description, "")
    self.assertSequenceEqual(cat.tags, ())

  def test_parse_full(self):
    data = {
        "data_source": "track_event",
        "name": "v8",
        "description": "V8 engine",
        "tags": ["js", "v8"],
    }
    cat = CategoryDescription.parse(data)
    self.assertEqual(cat.data_source, "track_event")
    self.assertEqual(cat.name, "v8")
    self.assertEqual(cat.description, "V8 engine")
    self.assertSequenceEqual(cat.tags, ("js", "v8"))

  def test_parse_invalid_types(self):
    with self.assertRaises(ValueError):
      CategoryDescription.parse({"data_source": "track_event"})


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
