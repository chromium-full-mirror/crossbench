# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import inspect
import re
import unittest
from typing import TYPE_CHECKING, Final, Iterator, MutableSet

from ordered_set import OrderedSet

import crossbench.benchmarks.all as all_benchmarks
from crossbench.benchmarks.base import Benchmark, SubStoryBenchmark
from crossbench.benchmarks.loading.loading_benchmark import LoadingBenchmark
from crossbench.benchmarks.memory.memory_benchmark import MemoryBenchmark
from crossbench.benchmarks.web_power.base import WebPowerBenchmarkBase
from tests import test_helper

if TYPE_CHECKING:
  from crossbench.stories.story import Story

EXCLUDED_BENCHMARKS: Final[tuple[type[Benchmark], ...]] = (
    SubStoryBenchmark,
    WebPowerBenchmarkBase,
)

_MOCK_CLASS_RE: Final[re.Pattern[str]] = re.compile(r"^Mock|Mock$")


def all_benchmark_classes() -> tuple[type[Benchmark], ...]:

  def all_subclasses(
      benchmark_cls: type[Benchmark]) -> Iterator[type[Benchmark]]:
    for sub_cls in benchmark_cls.__subclasses__():
      if _MOCK_CLASS_RE.search(sub_cls.__name__):
        continue
      # Ignore internal (e.g. PerfettoInfoBenchmark) and test benchmarks.
      if not sub_cls.__module__.startswith("crossbench.benchmarks."):
        continue
      yield from all_subclasses(sub_cls)
      if inspect.isabstract(sub_cls):
        continue
      if sub_cls in EXCLUDED_BENCHMARKS:
        continue
      yield sub_cls

  return tuple(OrderedSet(all_subclasses(Benchmark)))


ALL: Final[tuple[type[Benchmark], ...]] = all_benchmark_classes()


class AllBenchmarksTestCase(unittest.TestCase):

  def test_unique_classes(self):
    self.assertSequenceEqual(ALL, tuple(OrderedSet(ALL)))

  def test_all_benchmarks_registered(self):
    all_public_benchmark_names = set(all_benchmarks.__all__)
    actual_benchmark_names = {cls.__name__ for cls in ALL}
    self.assertEqual(actual_benchmark_names, all_public_benchmark_names)

  def test_aliases(self):
    seen_names: MutableSet[str] = OrderedSet()
    seen_aliases: MutableSet[str] = OrderedSet()
    for benchmark_cls in ALL:
      with self.subTest(benchmark_cls=benchmark_cls.__name__):
        self.assertNotIn(benchmark_cls.NAME, seen_names)
        seen_names.add(benchmark_cls.NAME)
        for alias in benchmark_cls.aliases():
          self.assertNotIn(alias, seen_aliases)
          seen_aliases.add(alias)

  def test_story_classes(self):
    seen_story_classes: MutableSet[type[Story]] = OrderedSet()
    for benchmark_cls in ALL:
      if benchmark_cls is MemoryBenchmark:
        continue
      if issubclass(benchmark_cls,
                    LoadingBenchmark) and (benchmark_cls
                                           is not LoadingBenchmark):
        continue
      if not issubclass(benchmark_cls, SubStoryBenchmark):
        continue
      self.assertNotIn(benchmark_cls.DEFAULT_STORY_CLS, seen_story_classes)
      seen_story_classes.add(benchmark_cls.DEFAULT_STORY_CLS)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
