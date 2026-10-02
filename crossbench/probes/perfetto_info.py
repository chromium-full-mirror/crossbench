# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, cast

from typing_extensions import Self, override

from crossbench import path as pth
from crossbench.config import ConfigObject, ConfigParser
from crossbench.probes.probe import Probe, ProbeContext
from crossbench.probes.result_location import ResultLocation
from third_party.protoc.gen.protos.perfetto.common.tracing_service_state_pb2 import \
    TracingServiceState

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.browsers.chromium_based.webdriver import \
      ChromiumBasedWebDriver
  from crossbench.env.runner_env import RunnerEnv
  from crossbench.probes.results import ProbeResult
  from crossbench.runner.run import Run


@dataclass(frozen=True)
class CategoryDescription(ConfigObject):
  """Description of a Perfetto trace category or data source."""

  data_source: str
  name: str
  description: str
  tags: tuple[str, ...]

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("data_source", type=str, required=True)
    parser.add_argument("name", type=str, required=True)
    parser.add_argument("description", type=str, default="")
    parser.add_argument("tags", type=str, is_list=True, default=())
    return parser

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise argparse.ArgumentTypeError(
        f"Cannot parse CategoryDescription from string: '{value}'")

  def as_dict(self) -> dict[str, Any]:
    return {
        "data_source": self.data_source,
        "name": self.name,
        "description": self.description,
        "tags": list(self.tags),
    }

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, CategoryDescription):
      return False
    return self.data_source == other.data_source and self.name == other.name

  def __hash__(self) -> int:
    return hash((self.data_source, self.name))


class PerfettoInfoProbe(Probe):
  """Probe to collect trace categories and data sources from browsers."""

  NAME: ClassVar[str] = "perfetto-info"
  RESULT_LOCATION: ClassVar[ResultLocation] = ResultLocation.LOCAL

  @override
  def get_context_cls(self) -> type[PerfettoInfoProbeContext]:
    return PerfettoInfoProbeContext

  @property
  @override
  def result_path_name(self) -> str:
    return f"{self.name}.json"

  @override
  def validate_browser(self, env: RunnerEnv, browser: Browser) -> None:
    super().validate_browser(env, browser)
    if (not browser.attributes().is_chromium_based and
        not browser.platform.is_android):
      raise argparse.ArgumentTypeError(
          f"Browser {browser.unique_name} is neither chromium-based nor "
          "running on Android. Cannot query Perfetto trace categories.")


class PerfettoInfoProbeContext(ProbeContext[PerfettoInfoProbe]):

  def __init__(self, probe: PerfettoInfoProbe, run: Run) -> None:
    super().__init__(probe, run)
    self._categories: list[CategoryDescription] = []

  @override
  def start(self) -> None:
    pass

  @override
  def stop(self) -> None:
    self._categories = self.get_categories()

  def get_categories(self) -> list[CategoryDescription]:
    categories: set[CategoryDescription] = set()
    if self.browser.platform.is_android:
      categories.update(self._get_adb_categories())
    if self.browser.attributes().is_chromium_based:
      categories.update(self._get_cdp_categories())
    return sorted(categories, key=lambda cat: (cat.data_source, cat.name))

  def _get_cdp_categories(self) -> list[CategoryDescription]:
    descriptor = cast("ChromiumBasedWebDriver",
                      self.browser).perfetto_categories()
    return [
        CategoryDescription(
            data_source="track_event",
            name=cat.name,
            description=cat.description,
            tags=tuple(cat.tags)) for cat in descriptor.available_categories
    ]

  def _get_adb_categories(self) -> list[CategoryDescription]:
    logging.debug("Querying Perfetto on Android via ADB for system categories")
    output = self.browser.platform.sh_stdout_bytes("perfetto", "--query-raw")
    state = TracingServiceState()
    state.ParseFromString(output)

    categories: list[CategoryDescription] = []
    for data_source in state.data_sources:
      ds_desc = data_source.ds_descriptor
      ds_name = ds_desc.name
      seen_descriptor = False
      if ds_desc.HasField("track_event_descriptor"):
        seen_descriptor = True
        for cat in ds_desc.track_event_descriptor.available_categories:
          categories.append(
              CategoryDescription(
                  data_source=ds_name,
                  name=cat.name,
                  description=cat.description,
                  tags=tuple(cat.tags)))
      if ds_desc.HasField("ftrace_descriptor"):
        seen_descriptor = True
        for cat in ds_desc.ftrace_descriptor.atrace_categories:
          categories.append(
              CategoryDescription(
                  data_source=ds_name,
                  name=cat.name,
                  description=cat.description,
                  tags=()))
      if (not seen_descriptor and ds_name and ds_name != "track_event"):
        categories.append(
            CategoryDescription(
                data_source=ds_name, name="", description="", tags=()))

    return categories

  @override
  def teardown(self) -> ProbeResult:
    output_path = pth.LocalPath(self.local_result_path)
    with output_path.open("w", encoding="utf-8") as f:
      json.dump([cat.as_dict() for cat in self._categories], f, indent=2)
    return self.local_result(json=(output_path,))
