# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import enum
import pathlib
import unittest
from typing import Any

from typing_extensions import override

from crossbench import plt
from crossbench.helper import collection_helper, fs_helper, url_helper
from crossbench.helper.cwd import change_cwd
from crossbench.helper.durations import Durations
from crossbench.helper.wait import WaitRange
from crossbench.str_enum_with_help import StrEnumWithHelp
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


class WaitTestCase(unittest.TestCase):

  def test_invalid_wait_ranges(self):
    with self.assertRaises(AssertionError):
      WaitRange(min=-1)
    with self.assertRaises(AssertionError):
      WaitRange(timeout=0)
    with self.assertRaises(AssertionError):
      WaitRange(factor=0.2)
    with self.assertRaises(AssertionError):
      WaitRange(delay=100)

  def test_range(self):
    durations = list(WaitRange(min=1, max=16, factor=2, max_iterations=5))
    self.assertSequenceEqual(durations, [(0, dt.timedelta(seconds=1)),
                                         (1, dt.timedelta(seconds=2)),
                                         (2, dt.timedelta(seconds=4)),
                                         (3, dt.timedelta(seconds=8)),
                                         (4, dt.timedelta(seconds=16))])

  def test_range_with_delay(self):
    durations = list(
        WaitRange(min=1, max=16, factor=2, max_iterations=5, delay=5.5))
    self.assertSequenceEqual(durations, [
        (0, dt.timedelta(seconds=5.5)),
        (1, dt.timedelta(seconds=1)),
        (2, dt.timedelta(seconds=2)),
        (3, dt.timedelta(seconds=4)),
        (4, dt.timedelta(seconds=8)),
    ])
    durations = list(
        WaitRange(min=1, max=16, factor=2, max_iterations=10, delay=5.5))
    self.assertSequenceEqual(durations, [
        (0, dt.timedelta(seconds=5.5)),
        (1, dt.timedelta(seconds=1)),
        (2, dt.timedelta(seconds=2)),
        (3, dt.timedelta(seconds=4)),
        (4, dt.timedelta(seconds=8)),
        (5, dt.timedelta(seconds=16)),
        (6, dt.timedelta(seconds=16)),
        (7, dt.timedelta(seconds=16)),
        (8, dt.timedelta(seconds=16)),
        (9, dt.timedelta(seconds=16)),
    ])

  def test_range_extended(self):
    durations = list(WaitRange(min=1, max=16, factor=2, max_iterations=5 + 4))
    self.assertSequenceEqual(
        durations,
        [
            (0, dt.timedelta(seconds=1)),
            (1, dt.timedelta(seconds=2)),
            (2, dt.timedelta(seconds=4)),
            (3, dt.timedelta(seconds=8)),
            (4, dt.timedelta(seconds=16)),
            # After 5 iterations the interval is no longer increased
            (5, dt.timedelta(seconds=16)),
            (6, dt.timedelta(seconds=16)),
            (7, dt.timedelta(seconds=16)),
            (8, dt.timedelta(seconds=16)),
        ])

  def test_wait_with_backoff(self):
    data: list[tuple[dt.timedelta, dt.timedelta]] = []
    delta = dt.timedelta(seconds=0.0005)
    for expected_i, (i, time_spent, time_left) in enumerate(
        WaitRange(min=0.01, max=0.05).wait_with_backoff()):
      data.append((time_spent, time_left))
      self.assertEqual(expected_i, i)
      if len(data) == 2:
        break
      plt.PLATFORM.sleep(delta)
    self.assertEqual(len(data), 2)
    first_time_spent, first_time_left = data[0]
    second_time_spent, second_time_left = data[1]
    self.assertLessEqual(first_time_spent + delta, second_time_spent)
    self.assertGreaterEqual(first_time_left, second_time_left + delta)

  def test_wait_with_backoff_max_iterations(self):
    i = 0
    for expected_i, step in enumerate(
        WaitRange(min=0.01, max=0.05, max_iterations=11).wait_with_backoff()):
      i = step.iteration
      self.assertEqual(expected_i, i)
    self.assertEqual(i, 10)

  def test_wait_with_backoff_max_iterations_delay(self):
    i = 0
    for expected_i, step in enumerate(
        WaitRange(min=0.01, max=0.05, delay=0.1,
                  max_iterations=11).wait_with_backoff()):
      i = step.iteration
      self.assertEqual(expected_i, i)
    self.assertEqual(i, 10)


class DurationsTestCase(unittest.TestCase):

  def test_single(self):
    durations = Durations()
    self.assertTrue(len(durations) == 0)
    self.assertDictEqual(durations.to_json(), {})
    with durations.measure("a"):
      pass
    self.assertGreaterEqual(durations["a"].total_seconds(), 0)
    self.assertTrue(len(durations) == 1)

  def test_invalid_twice(self):
    durations = Durations()
    with durations.measure("a"):
      pass
    with self.assertRaises(AssertionError), durations.measure("a"):
      pass
    self.assertTrue(len(durations) == 1)
    self.assertSequenceEqual(list(durations.to_json().keys()), ["a"])

  def test_multiple(self):
    durations = Durations()
    for name in ["a", "b", "c"]:
      with durations.measure(name):
        pass
    self.assertEqual(len(durations), 3)
    self.assertSequenceEqual(list(durations.to_json().keys()), ["a", "b", "c"])


class ChangeCWDTestCase(CrossbenchFakeFsTestCase):

  def test_basic(self):
    old_cwd = pathlib.Path.cwd()
    new_cwd = pathlib.Path("/foo/bar").absolute()
    new_cwd.mkdir(parents=True)
    with change_cwd(new_cwd):
      self.assertNotEqual(old_cwd, pathlib.Path.cwd())
      self.assertEqual(new_cwd, pathlib.Path.cwd())
    self.assertEqual(old_cwd, pathlib.Path.cwd())
    self.assertNotEqual(new_cwd, pathlib.Path.cwd())


class FileSizeTestCase(CrossbenchFakeFsTestCase):

  def test_empty(self):
    test_file = pathlib.Path("test.txt")
    test_file.touch()
    size = fs_helper.get_file_size(test_file)
    self.assertEqual(size, "0.00 B")

  def test_bytes(self):
    test_file = pathlib.Path("test.txt")
    self.fs.create_file(test_file, st_size=501)
    size = fs_helper.get_file_size(test_file)
    self.assertEqual(size, "501.00 B")

  def test_kib(self):
    test_file = pathlib.Path("test.txt")
    self.fs.create_file(test_file, st_size=1024 * 2)
    size = fs_helper.get_file_size(test_file)
    self.assertEqual(size, "2.00 KiB")

  def test_kib_fraction(self):
    test_file = pathlib.Path("test.txt")
    self.fs.create_file(test_file, st_size=int(1024 * 2.51))
    size = fs_helper.get_file_size(test_file)
    self.assertEqual(size, "2.51 KiB")

  def test_sort_by_file_size(self):
    small = pathlib.Path("smol")
    medium = pathlib.Path("medium")
    large = pathlib.Path("laaaarge")
    self.fs.create_file(small, st_size=100)
    self.fs.create_file(medium, st_size=200)
    self.fs.create_file(large, st_size=300)
    result = fs_helper.sort_by_file_size([small, medium, large])
    self.assertSequenceEqual(result, [small, medium, large])
    result = fs_helper.sort_by_file_size([medium, large, small])
    self.assertSequenceEqual(result, [small, medium, large])
    result = fs_helper.sort_by_file_size([large, medium, small])
    self.assertSequenceEqual(result, [small, medium, large])


class GroupByTestCase(unittest.TestCase):

  def test_empty(self):
    grouped: dict[str, Any] = collection_helper.group_by([], key=str)
    self.assertDictEqual({}, grouped)

  def test_basic(self):
    grouped: dict[str,
                  list[int]] = collection_helper.group_by([1, 1, 1, 2, 2, 3],
                                                          key=str)
    self.assertSequenceEqual(list(grouped.keys()), ["1", "2", "3"])
    self.assertDictEqual({"1": [1, 1, 1], "2": [2, 2], "3": [3]}, grouped)

  def test_basic_out_of_order(self):
    grouped: dict[str,
                  list[int]] = collection_helper.group_by([2, 3, 2, 1, 1, 1],
                                                          key=str)
    self.assertSequenceEqual(list(grouped.keys()), ["1", "2", "3"])
    self.assertDictEqual({"1": [1, 1, 1], "2": [2, 2], "3": [3]}, grouped)

  def test_basic_input_order(self):
    grouped: dict[str,
                  list[int]] = collection_helper.group_by([2, 3, 2, 1, 1, 1],
                                                          key=str,
                                                          sort_key=None)
    self.assertSequenceEqual(list(grouped.keys()), ["2", "3", "1"])
    self.assertDictEqual({"1": [1, 1, 1], "2": [2, 2], "3": [3]}, grouped)

  def test_basic_custom_order(self):
    grouped: dict[str, list[int]] = collection_helper.group_by(
        [2, 3, 2, 1, 1, 1], key=str, sort_key=lambda item: int(item[0]))
    self.assertSequenceEqual(list(grouped.keys()), ["1", "2", "3"])
    self.assertDictEqual({"1": [1, 1, 1], "2": [2, 2], "3": [3]}, grouped)
    # Try reverse sorting
    grouped: dict[str, list[int]] = collection_helper.group_by(
        [2, 3, 2, 1, 1, 1], key=str, sort_key=lambda item: -int(item[0]))
    self.assertSequenceEqual(list(grouped.keys()), ["3", "2", "1"])
    self.assertDictEqual({"1": [1, 1, 1], "2": [2, 2], "3": [3]}, grouped)

  def test_custom_key(self):
    grouped: dict[int, list[int]] = collection_helper.group_by(
        [1.1, 1.2, 1.3, 2.1, 2.2, 3.1], key=int)
    self.assertDictEqual({1: [1.1, 1.2, 1.3], 2: [2.1, 2.2], 3: [3.1]}, grouped)

  def test_custom_value(self):
    grouped: dict[str, list[int]] = collection_helper.group_by(
        [1, 1, 1, 2, 2, 3], key=str, value=lambda x: x * 100)
    self.assertDictEqual({
        "1": [100, 100, 100],
        "2": [200, 200],
        "3": [300],
    }, grouped)

  def test_custom_group(self):
    grouped: dict[str, list[Any]] = collection_helper.group_by_custom(
        [1, 1, 1, 2, 2, 3], key=str, group=lambda key: ["custom"])
    self.assertDictEqual(
        {
            "1": ["custom", 1, 1, 1],
            "2": ["custom", 2, 2],
            "3": ["custom", 3],
        }, grouped)

  def test_custom_group_out_of_order(self):
    grouped: dict[str, list[Any]] = collection_helper.group_by_custom(
        [1, 1, 1, 3, 2, 2], key=str, group=lambda key: ["custom"])
    self.assertDictEqual(
        {
            "1": ["custom", 1, 1, 1],
            "2": ["custom", 2, 2],
            "3": ["custom", 3],
        }, grouped)


class ConcatFilesTestCase(CrossbenchFakeFsTestCase):

  @override
  def setUp(self):
    super().setUp()
    self.platform = plt.PLATFORM

  def test_single(self):
    input_file = pathlib.Path("input")
    self.fs.create_file(input_file, contents="input content")
    output = pathlib.Path("ouput")
    self.platform.concat_files([input_file], output)
    self.assertEqual(output.read_text(encoding="utf-8"), "input content")

  def test_multiple(self):
    input_a = pathlib.Path("input_1")
    self.fs.create_file(input_a, contents="AAA")
    input_b = pathlib.Path("input_2")
    self.fs.create_file(input_b, contents="BBB")
    output = pathlib.Path("ouput")
    self.platform.concat_files([input_a, input_b], output)
    self.assertEqual(output.read_text(encoding="utf-8"), "AAABBB")


class StrEnumWithHelpTestCase(unittest.TestCase):

  @enum.unique
  class TestEnum(StrEnumWithHelp):
    A = ("a", "help a")
    B = ("b", "help b")

  def test_lookup(self):
    self.assertIs(self.TestEnum("a"), self.TestEnum.A)
    self.assertIs(self.TestEnum("b"), self.TestEnum.B)
    self.assertIs(self.TestEnum["A"], self.TestEnum.A)
    self.assertIs(self.TestEnum["B"], self.TestEnum.B)

  def test_value_help(self):

    self.assertEqual(self.TestEnum.A.name, "A")
    self.assertEqual(self.TestEnum.B.name, "B")
    self.assertEqual(self.TestEnum.A.value, "a")
    self.assertEqual(self.TestEnum.B.value, "b")
    self.assertEqual(self.TestEnum.A.help, "help a")
    self.assertEqual(self.TestEnum.B.help, "help b")

  def test_in(self):
    self.assertIn(self.TestEnum.A, self.TestEnum)
    self.assertIn(self.TestEnum.B, self.TestEnum)

  def test_str(self):
    self.assertEqual(str(self.TestEnum.A), "a")
    self.assertEqual(str(self.TestEnum.B), "b")

  def test_list(self):
    self.assertEqual(len(self.TestEnum), 2)
    self.assertSequenceEqual(
        list(self.TestEnum), [self.TestEnum.A, self.TestEnum.B])

  def test_help_items(self):
    self.assertSequenceEqual(self.TestEnum.help_text_items(),
                             [("'a'", "help a"), ("'b'", "help b")])


class UpdateUrlQueryTestCase(unittest.TestCase):

  def test_empty(self):
    self.assertEqual("http://test.com",
                     url_helper.update_url_query("http://test.com", {}))
    self.assertEqual("https://test.com",
                     url_helper.update_url_query("https://test.com", {}))
    self.assertEqual(
        "https://test.com?foo=bar",
        url_helper.update_url_query("https://test.com?foo=bar", {}))

  def test_empty_add(self):
    self.assertEqual(
        "http://test.com?foo=bar",
        url_helper.update_url_query("http://test.com", {"foo": "bar"}))
    self.assertEqual(
        "http://test.com?foo=bar#status",
        url_helper.update_url_query("http://test.com#status", {"foo": "bar"}))
    self.assertEqual(
        "http://test.com?xyz=10&foo=bar#status",
        url_helper.update_url_query("http://test.com?xyz=10#status",
                                    {"foo": "bar"}))

  def test_override(self):
    self.assertEqual(
        "http://test.com?foo=bar",
        url_helper.update_url_query("http://test.com?foo=BAR", {"foo": "bar"}))
    self.assertEqual(
        "http://test.com?foo=bar#status",
        url_helper.update_url_query("http://test.com?foo=BAR#status",
                                    {"foo": "bar"}))
    self.assertEqual(
        "http://test.com?foo=bar&xyz=10#status",
        url_helper.update_url_query("http://test.com?foo=BAR&xyz=10#status",
                                    {"foo": "bar"}))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
