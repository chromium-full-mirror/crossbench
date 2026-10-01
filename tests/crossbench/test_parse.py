# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import datetime as dt
import enum
import json
import math
import pathlib
import unittest
from typing import Any
from urllib import parse as urlparse

from typing_extensions import override

from crossbench import path as pth
from crossbench.parse import DurationParseError, DurationParser, \
    NumberParser, ObjectParser, PathParser, TimeUnit
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase
from third_party.protoc import trace_config_pb2


class DurationParserTestCase(unittest.TestCase):

  def test_parse_negative(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_duration(-1)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_duration("-1")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_or_zero_duration("-1")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_or_zero_duration(dt.timedelta(seconds=-1))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_duration("-1")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_duration(dt.timedelta(seconds=-1))
    self.assertIn("-1", str(cm.exception))
    self.assertEqual(DurationParser.any_duration("-1.5").total_seconds(), -1.5)

  def test_parse_zero(self):
    self.assertEqual(DurationParser.any_duration("0").total_seconds(), 0)
    self.assertEqual(DurationParser.any_duration("0s").total_seconds(), 0)
    self.assertEqual(DurationParser.any_duration("0.0").total_seconds(), 0)
    self.assertEqual(
        DurationParser.positive_or_zero_duration("0.0").total_seconds(), 0)
    invalid: Any
    for invalid in (-1, 0, "-1", "0", "invalid", dt.timedelta(0),
                    dt.timedelta(seconds=-1)):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        DurationParser.positive_duration(invalid)
      self.assertIn(str(invalid), str(cm.exception))
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        DurationParser.positive_duration(invalid)
      self.assertIn(str(invalid), str(cm.exception))

  def test_parse_empty(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_duration("")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.any_duration("")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_or_zero_duration("")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_duration("")

  def test_invalid_suffix(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.positive_duration("100XXX")
    self.assertIn("Unknown duration format", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_duration("X0XX")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.positive_duration("100X0XX")

  def test_no_unit(self):
    self.assertEqual(
        DurationParser.positive_duration("200"), dt.timedelta(seconds=200))
    self.assertEqual(
        DurationParser.positive_duration(200), dt.timedelta(seconds=200))
    self.assertEqual(
        DurationParser.positive_duration_ms("200"),
        dt.timedelta(milliseconds=200))
    self.assertEqual(
        DurationParser.positive_duration_ms(200),
        dt.timedelta(milliseconds=200))

  def test_time_unit(self):
    self.assertEqual(DurationParser.time_unit("10x"), dt.timedelta(seconds=10))
    self.assertEqual(
        DurationParser.time_unit("0.5x"), dt.timedelta(seconds=0.5))
    self.assertEqual(DurationParser.time_unit("10s"), dt.timedelta(seconds=10))
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.any_duration("10x")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.time_unit("-10x")

  def test_milliseconds(self):
    self.assertEqual(
        DurationParser.positive_duration("27.5ms"),
        dt.timedelta(milliseconds=27.5))
    self.assertEqual(
        DurationParser.positive_duration(dt.timedelta(milliseconds=27.5)),
        dt.timedelta(milliseconds=27.5))
    self.assertEqual(
        DurationParser.positive_duration("27.5 millis"),
        dt.timedelta(milliseconds=27.5))
    self.assertEqual(
        DurationParser.positive_duration("27.5 milliseconds"),
        dt.timedelta(milliseconds=27.5))

  def test_seconds(self):
    self.assertEqual(
        DurationParser.positive_duration("27.5s"), dt.timedelta(seconds=27.5))
    self.assertEqual(
        DurationParser.positive_duration("1 sec"), dt.timedelta(seconds=1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 secs"),
        dt.timedelta(seconds=27.5))
    self.assertEqual(
        DurationParser.positive_duration("1 second"), dt.timedelta(seconds=1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 seconds"),
        dt.timedelta(seconds=27.5))

  def test_minutes(self):
    self.assertEqual(
        DurationParser.positive_duration("27.5m"), dt.timedelta(minutes=27.5))
    self.assertEqual(
        DurationParser.positive_duration("1 min"), dt.timedelta(minutes=1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 mins"),
        dt.timedelta(minutes=27.5))
    self.assertEqual(
        DurationParser.positive_duration("1 minute"), dt.timedelta(minutes=1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 minutes"),
        dt.timedelta(minutes=27.5))

  def test_duration_or_user_input(self):
    self.assertEqual(
        DurationParser.duration_or_user_input("input"), dt.timedelta.max)
    self.assertEqual(
        DurationParser.duration_or_user_input("10s"), dt.timedelta(seconds=10))
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_or_user_input("-1s")

  def test_hours(self):
    self.assertEqual(
        DurationParser.positive_duration("27.5h"), dt.timedelta(hours=27.5))
    self.assertEqual(
        DurationParser.positive_duration("0.1 h"), dt.timedelta(hours=0.1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 hrs"), dt.timedelta(hours=27.5))
    self.assertEqual(
        DurationParser.positive_duration("1 hour"), dt.timedelta(hours=1))
    self.assertEqual(
        DurationParser.positive_duration("27.5 hours"),
        dt.timedelta(hours=27.5))

  def test_duration_range(self):
    self.assertEqual(DurationParser.duration_range()(0), dt.timedelta())
    self.assertEqual(DurationParser.duration_range()("-10s"),
                     dt.timedelta(seconds=-10))
    self.assertEqual(DurationParser.duration_range()("10s"),
                     dt.timedelta(seconds=10))
    self.assertEqual(DurationParser.duration_range()(dt.timedelta(hours=1)),
                     dt.timedelta(hours=1))

    range_1_to_10 = DurationParser.duration_range(
        min=dt.timedelta(seconds=1), max=dt.timedelta(seconds=10))
    self.assertEqual(range_1_to_10("1s"), dt.timedelta(seconds=1))
    self.assertEqual(range_1_to_10("5.5s"), dt.timedelta(seconds=5.5))
    self.assertEqual(range_1_to_10("10s"), dt.timedelta(seconds=10))
    self.assertEqual(
        range_1_to_10(dt.timedelta(seconds=1)), dt.timedelta(seconds=1))

    range_str = DurationParser.duration_range(min="1s", max="10s")
    self.assertEqual(range_str("5s"), dt.timedelta(seconds=5))

    range_int = DurationParser.duration_range(min=0, max=100)
    self.assertEqual(range_int(50), dt.timedelta(seconds=50))

    range_ms = DurationParser.duration_range(
        min=100, max=500, default_time_unit=TimeUnit.MILLISECOND)
    self.assertEqual(range_ms(250), dt.timedelta(milliseconds=250))
    self.assertEqual(range_ms("250ms"), dt.timedelta(milliseconds=250))

    range_inf = DurationParser.duration_range(min=-math.inf, max=math.inf)
    self.assertEqual(range_inf("-10s"), dt.timedelta(seconds=-10))
    self.assertEqual(range_inf("100h"), dt.timedelta(hours=100))

    range_min_inf = DurationParser.duration_range(min=-math.inf, max=10)
    self.assertEqual(range_min_inf("-100s"), dt.timedelta(seconds=-100))
    self.assertEqual(range_min_inf("10s"), dt.timedelta(seconds=10))

    range_max_inf = DurationParser.duration_range(min=10, max=math.inf)
    self.assertEqual(range_max_inf("10s"), dt.timedelta(seconds=10))
    self.assertEqual(range_max_inf("100s"), dt.timedelta(seconds=100))

    range_max_only = DurationParser.duration_range(max=10)
    self.assertEqual(range_max_only("-100s"), dt.timedelta(seconds=-100))
    self.assertEqual(range_max_only(0), dt.timedelta())
    self.assertEqual(range_max_only(10), dt.timedelta(seconds=10))

    range_none_min = DurationParser.duration_range(min=None, max=10)
    self.assertEqual(range_none_min("-100s"), dt.timedelta(seconds=-100))
    self.assertEqual(range_none_min(10), dt.timedelta(seconds=10))

    self.assertEqual(
        DurationParser._duration_range("5s", dt.timedelta(seconds=1),
                                       dt.timedelta(seconds=10)),
        dt.timedelta(seconds=5))
    self.assertEqual(
        DurationParser._duration_range("-10s"), dt.timedelta(seconds=-10))
    self.assertEqual(DurationParser._duration_range("0s"), dt.timedelta())

  def test_duration_range_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(max=10)(11)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(max=10)("10.1s")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)(0)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)("0.5s")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)(11)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)("10.1s")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=0, max=10)("-1s")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)("invalid")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max=10)("")
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=-math.inf, max=10)(15)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=10, max=math.inf)(5)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser._duration_range("0.5s", dt.timedelta(seconds=1),
                                     dt.timedelta(seconds=10))
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min="invalid", max=10)
    with self.assertRaises(argparse.ArgumentTypeError):
      DurationParser.duration_range(min=1, max="invalid")

    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      DurationParser.duration_range(min=1, max=10, name="custom_dur")(0.5)
    self.assertIn(
        "Expected 0:00:01 <= custom_dur <= 0:00:10, but got: 0:00:00.500000",
        str(cm.exception))

    with self.assertRaises(AssertionError):
      DurationParser.duration_range(min=1, max=1)
    with self.assertRaises(AssertionError):
      DurationParser.duration_range(min=10, max=1)
    with self.assertRaises(AssertionError):
      DurationParser.duration_range(
          min=dt.timedelta(seconds=5), max=dt.timedelta(seconds=2))


class PathParserTestCase(CrossbenchFakeFsTestCase):

  def test_existing_path(self):
    path = pth.LocalPath("foo.txt")
    self.assertFalse(path.exists())
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.existing_path(str(path))
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.existing_path(path)
    path.touch()
    self.assertEqual(path, PathParser.existing_path(str(path)))
    self.assertEqual(path, PathParser.existing_path(path))

  def test_not_existing_path(self):
    path = pth.LocalPath("foo.txt")
    self.assertFalse(path.exists())
    self.assertEqual(path, PathParser.not_existing_path(str(path)))
    self.assertEqual(path, PathParser.not_existing_path(path))
    path.touch()
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.not_existing_path(str(path))
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.not_existing_path(path)

  def test_value_has_path_prefix(self):
    self.assertTrue(PathParser.value_has_path_prefix("./foo"))
    self.assertTrue(PathParser.value_has_path_prefix("../foo"))
    self.assertTrue(PathParser.value_has_path_prefix("/foo"))
    self.assertTrue(PathParser.value_has_path_prefix("~/foo"))
    self.assertTrue(PathParser.value_has_path_prefix(r"C:\foo"))
    self.assertFalse(PathParser.value_has_path_prefix("foo"))
    self.assertFalse(PathParser.value_has_path_prefix("foo/bar"))
    self.assertFalse(PathParser.value_has_path_prefix(""))
    self.assertFalse(PathParser.value_has_path_prefix("/"))


class ObjectParserTestCase(CrossbenchFakeFsTestCase):

  @override
  def setUp(self):
    super().setUp()
    self._json_test_data = {"int": 1, "array": [1, "2"]}

  def test_parse_any_str(self):
    self.assertEqual(ObjectParser.any_str(""), "")
    self.assertEqual(ObjectParser.any_str("1234"), "1234")

  def test_parse_any_str_invalid(self):
    invalid: Any
    for invalid in (None, 1, [], {}, [1], ["a"], {"a": "a"}):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        ObjectParser.any_str(invalid)
      self.assertIn(str(invalid), str(cm.exception))

  def test_parse_non_empty_str(self):
    self.assertEqual(ObjectParser.non_empty_str("a string"), "a string")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ObjectParser.non_empty_str("")
    self.assertIn("empty", str(cm.exception))

  def test_parse_str_or_file_contents(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty string"):
      ObjectParser.str_or_file_contents("")
    self.assertEqual(
        ObjectParser.str_or_file_contents("some data"), "some data")
    self.assertEqual(ObjectParser.str_or_file_contents("test.txt"), "test.txt")

  def test_parse_str_or_file_contents_file(self):
    path = pathlib.Path("./test.txt")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, str(path)):
      ObjectParser.str_or_file_contents(path)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, str(path)):
      ObjectParser.str_or_file_contents("./test.txt")
    self.fs.create_file(path, contents="test file contents")
    self.assertEqual(
        ObjectParser.str_or_file_contents(path), "test file contents")
    self.assertEqual(ObjectParser.str_or_file_contents(str(path)), "test.txt")
    self.assertEqual(
        ObjectParser.str_or_file_contents("./test.txt"), "test file contents")

  def test_parse_httpx_url_str(self):
    for valid in ("http://foo.com", "https://foo.com", "http://localhost:800"):
      self.assertEqual(ObjectParser.httpx_url_str(valid), valid)
    invalid: Any
    for invalid in ("", "ftp://localhost:32", "http://///"):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        _ = ObjectParser.httpx_url_str(invalid)
      self.assertIn(invalid, str(cm.exception))

  def test_parse_any_int(self):
    self.assertEqual(NumberParser.any_int("-123456"), -123456)
    self.assertEqual(NumberParser.any_int(-123456), -123456)
    self.assertEqual(NumberParser.any_int(float(-123456)), -123456)
    self.assertEqual(NumberParser.any_int("-1"), -1)
    self.assertEqual(NumberParser.any_int(-1), -1)
    self.assertEqual(NumberParser.any_int(float(-1)), -1)
    self.assertEqual(NumberParser.any_int("0"), 0)
    self.assertEqual(NumberParser.any_int(0), 0)
    self.assertEqual(NumberParser.any_int(float(0)), 0)
    self.assertEqual(NumberParser.any_int("1"), 1)
    self.assertEqual(NumberParser.any_int(1), 1)
    self.assertEqual(NumberParser.any_int("123456"), 123456)
    self.assertEqual(NumberParser.any_int(123456), 123456)

  def test_parse_any_int_strict(self):
    self.assertEqual(NumberParser.any_int(float(0), parse_str=False), 0)
    self.assertEqual(NumberParser.any_int(1, parse_str=False), 1)

  def test_parse_any_int_invalid(self):
    invalid: Any
    for invalid in ("", "-1.2", -1.2, "1.2", 1.2, "100.001", 100.001, "Nan",
                    math.nan, "inf", math.inf, "-inf", -math.inf, "invalid",
                    None):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.any_int(invalid)

  def test_parse_any_int_invalid_strict(self):
    invalid: Any
    for invalid in ("", "-1.2", -1.2, "1.2", 1.2, "100.001", 100.001, "Nan",
                    math.nan, "inf", math.inf, "-inf", -math.inf, "invalid",
                    None):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.any_int(invalid, parse_str=False)

  def test_parse_optional_int(self):
    self.assertIsNone(NumberParser.optional_int(None))
    self.assertIsNone(NumberParser.optional_int(""))
    self.assertEqual(NumberParser.optional_int("1"), 1)
    self.assertEqual(NumberParser.optional_int(1), 1)
    self.assertEqual(NumberParser.optional_int("0"), 0)
    self.assertEqual(NumberParser.optional_int(0), 0)
    self.assertEqual(NumberParser.optional_int("-5"), -5)
    self.assertEqual(NumberParser.optional_int(-5), -5)

  def test_parse_optional_int_invalid(self):
    invalid: Any
    for invalid in ("1.2", 1.2, "Nan", math.nan, "inf", math.inf, "-inf",
                    -math.inf, "invalid"):
      with self.assertRaises(
          argparse.ArgumentTypeError, msg=f"invalid={invalid!r}"):
        _ = NumberParser.optional_int(invalid)

  def test_parse_positive_int(self):
    self.assertEqual(NumberParser.positive_int("1"), 1)
    self.assertEqual(NumberParser.positive_int(1), 1)
    self.assertEqual(NumberParser.positive_int("123"), 123)
    self.assertEqual(NumberParser.positive_int(123), 123)

  def test_parse_positive_int_invalid(self):
    invalid: Any
    for invalid in ("", "0", 0, "-1", -1, "-1.2", -1.2, "1.2", 1.2, "Nan",
                    math.nan, "inf", math.inf, "-inf", -math.inf, "invalid",
                    None):
      with self.assertRaises(
          argparse.ArgumentTypeError, msg=f"invalid={invalid!r}"):
        _ = NumberParser.positive_int(invalid)

  def test_parse_int_range(self):
    self.assertEqual(NumberParser.int_range(min=0, max=10)("1"), 1)
    self.assertEqual(NumberParser.int_range(min=0, max=10)(1), 1)
    self.assertEqual(NumberParser.int_range(min=0, max=200)("123"), 123)
    self.assertEqual(NumberParser.int_range(min=0, max=200)(123), 123)
    self.assertEqual(NumberParser.int_range(min=-100, max=200)("-12"), -12)
    self.assertEqual(NumberParser.int_range(min=-100, max=200)(-12), -12)

  def test_parse_int_range_invalid(self):
    with self.assertRaises(AssertionError):
      NumberParser.int_range(1, 1)
    with self.assertRaises(AssertionError):
      NumberParser.int_range(10, 1)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.int_range(-1, 10)(-2)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.int_range(-1, 10)(11)

  def test_parse_positive_int_invalid_strict(self):
    invalid: Any
    for invalid in ("", "0", 0, "1", "-1", -1, float(-1), "-1.2", -1.2, "1.2",
                    1.2, "Nan", math.nan, "inf", math.inf, "-inf", -math.inf,
                    "invalid", None):
      with self.assertRaises(
          argparse.ArgumentTypeError, msg=f"invalid={invalid!r}"):
        _ = NumberParser.positive_int(invalid, parse_str=False)

  def test_parse_positive_zero_int(self):
    self.assertEqual(NumberParser.positive_zero_int("1"), 1)
    self.assertEqual(NumberParser.positive_zero_int(1), 1)
    self.assertEqual(NumberParser.positive_zero_int(float(1)), 1)
    self.assertEqual(NumberParser.positive_zero_int("0"), 0)
    self.assertEqual(NumberParser.positive_zero_int(0), 0)

  def test_parse_positive_zero_int_invalid(self):
    invalid: Any
    for invalid in ("", "-1", -1, "-1.2", -1.2, "1.2", 1.2, "NaN", math.nan,
                    "inf", math.inf, "-inf", -math.inf, "invalid", None):
      with self.assertRaises(
          argparse.ArgumentTypeError, msg=f"invalid={invalid!r}"):
        _ = NumberParser.positive_zero_int(invalid)

  def test_parse_any_float(self):
    self.assertEqual(NumberParser.any_float("-1.2"), -1.2)
    self.assertEqual(NumberParser.any_float(-1.2), -1.2)
    self.assertEqual(NumberParser.any_float("-1"), -1.0)
    self.assertEqual(NumberParser.any_float(-1), -1.0)
    self.assertEqual(NumberParser.any_float("0"), 0.0)
    self.assertEqual(NumberParser.any_float(0), 0.0)
    self.assertEqual(NumberParser.any_float("0.0"), 0.0)
    self.assertEqual(NumberParser.any_float(0.0), 0.0)
    self.assertEqual(NumberParser.any_float("0.1"), 0.1)
    self.assertEqual(NumberParser.any_float(0.1), 0.1)

  def test_parse_float_invalid(self):
    invalid: Any
    for invalid in ("", "abc", "NaN", "inf", "-inf", "invalid"):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.positive_zero_float(invalid)

  def test_parse_positive_zero_float(self):
    self.assertEqual(NumberParser.positive_zero_float("1"), 1.0)
    self.assertEqual(NumberParser.positive_zero_float("0"), 0.0)
    self.assertEqual(NumberParser.positive_zero_float("0.0"), 0.0)
    self.assertEqual(NumberParser.positive_zero_float("1.23"), 1.23)

  def test_parse_positive_zero_float_invalid(self):
    invalid: Any
    for invalid in ("", "-1", "-1.2", "NaN", "inf", "-inf", "invalid"):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.positive_zero_float(invalid)

  def test_parse_positive_float(self):
    self.assertEqual(NumberParser.positive_float("1"), 1.0)
    self.assertEqual(NumberParser.positive_float(1), 1.0)
    self.assertEqual(NumberParser.positive_float("1.23"), 1.23)
    self.assertEqual(NumberParser.positive_float(1.23), 1.23)

  def test_parse_positive_float_invalid(self):
    invalid: Any
    for invalid in ("", "0", 0, "0.0", 0.0, "-1", -1, "-1.2", "NaN", "inf",
                    "-inf", "invalid"):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.positive_float(invalid)

  def test_parse_float_range(self):
    self.assertEqual(NumberParser.float_range()(0.0), 0.0)
    self.assertEqual(NumberParser.float_range()(100.0), 100.0)
    self.assertEqual(NumberParser.float_range(min=1, max=2)("1"), 1.0)
    self.assertEqual(NumberParser.float_range(min=0, max=1)(1), 1.0)
    self.assertEqual(NumberParser.float_range(min=0, max=1)("0"), 0.0)
    self.assertEqual(NumberParser.float_range(min=0, max=1)(0), 0.0)
    self.assertEqual(NumberParser.float_range(min=0, max=1)("0.0"), 0.0)
    self.assertEqual(NumberParser.float_range(min=0, max=1)(0.0), 0.0)
    self.assertEqual(NumberParser.float_range(min=0, max=11)("1.23"), 1.23)
    self.assertEqual(NumberParser.float_range(min=0, max=11)(1.23), 1.23)
    self.assertEqual(NumberParser.float_range(min=-2, max=11)("-1.1"), -1.1)
    self.assertEqual(NumberParser.float_range(min=-2, max=11)(-1.1), -1.1)
    self.assertEqual(NumberParser._float_range("1.5", 1.0, 2.0), 1.5)

  def test_parse_float_range_invalid(self):
    with self.assertRaises(AssertionError):
      NumberParser.float_range(1, 1)
    with self.assertRaises(AssertionError):
      NumberParser.float_range(10, 1.0)
    with self.assertRaises(AssertionError):
      NumberParser.float_range(-10.1, -11.0)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.float_range(1, 2)(0.9)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.float_range(1, 2)(2.1)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.float_range(0, 10)(float("nan"))
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.float_range(0, 10)(float("inf"))
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser._float_range(0.9, 1.0, 2.0)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      NumberParser.float_range(1, 10, name="custom_float")(0.5)
    self.assertIn("Expected 1 <= custom_float <= 10, but got: 0.5",
                  str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.int_range(-1.1, 10.1)(-1.2)
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.int_range(-1.1, 10.1)(10.2)

  def test_parse_port_number(self):
    self.assertEqual(NumberParser.port_number(1), 1)
    self.assertEqual(NumberParser.port_number("1"), 1)
    self.assertEqual(NumberParser.port_number(440), 440)
    self.assertEqual(NumberParser.port_number("440"), 440)
    self.assertEqual(NumberParser.port_number(65535), 65535)
    self.assertEqual(NumberParser.port_number("65535"), 65535)

  def test_parse_port_number_zer(self):
    self.assertEqual(NumberParser.port_number_zero(0), 0)
    self.assertEqual(NumberParser.port_number_zero("0"), 0)
    self.assertEqual(NumberParser.port_number(1), 1)
    self.assertEqual(NumberParser.port_number("1"), 1)
    self.assertEqual(NumberParser.port_number_zero(440), 440)
    self.assertEqual(NumberParser.port_number_zero("440"), 440)
    self.assertEqual(NumberParser.port_number_zero(65535), 65535)
    self.assertEqual(NumberParser.port_number_zero("65535"), 65535)

  def test_parse_port_number_invalid(self):
    invalid: Any
    for invalid in ("", "-1", "-1.2", "6553500", 6553500, "inf", "-inf",
                    "invalid", 0, "0"):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.port_number(invalid)

  def test_parse_port_number_invalid_zero(self):
    invalid: Any
    for invalid in (
        "",
        "-1",
        "-1.2",
        "6553500",
        "inf",
        "-inf",
        "invalid",
    ):
      with self.assertRaises(argparse.ArgumentTypeError):
        _ = NumberParser.port_number_zero(invalid)

  def test_power_of_two_with_unit(self):
    self.assertEqual(NumberParser.power_of_two_with_unit("4M"), "4M")
    self.assertEqual(NumberParser.power_of_two_with_unit("256K"), "256K")
    self.assertEqual(NumberParser.power_of_two_with_unit("1G"), "1G")
    self.assertEqual(NumberParser.power_of_two_with_unit(1024), "1024")

  def test_power_of_two_with_unit_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.power_of_two_with_unit("3M")
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.power_of_two_with_unit("0")
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.power_of_two_with_unit("abc")
    with self.assertRaises(argparse.ArgumentTypeError):
      NumberParser.power_of_two_with_unit("1.5M")

  def _json_file_test_helper(self, parser) -> Any:
    with self.assertRaises(argparse.ArgumentTypeError):
      parser("file")

    path = pathlib.Path("file.json")
    self.assertFalse(path.exists())
    with self.assertRaises(argparse.ArgumentTypeError):
      parser(path)

    path.touch()
    with self.assertRaises(argparse.ArgumentTypeError):
      parser(path)

    with path.open("w", encoding="utf-8") as f:
      f.write("{invalid json data")
    with self.assertRaises(argparse.ArgumentTypeError):
      parser(path)
    # Test very long lines too.
    with path.open("w", encoding="utf-8") as f:
      f.write("{\n invalid json data" + "." * 100)
    with self.assertRaises(argparse.ArgumentTypeError):
      parser(path)

    with path.open("w", encoding="utf-8") as f:
      f.write("""{
              'a': {},
              'c': }}
              """)
    with self.assertRaises(argparse.ArgumentTypeError):
      parser(path)

    with path.open("w", encoding="utf-8") as f:
      json.dump(self._json_test_data, f)
    str_result = parser(str(path))
    path_result = parser(path)
    self.assertEqual(str_result, path_result)
    return str_result

  def test_parse_json_file(self):
    result = self._json_file_test_helper(ObjectParser.json_file)
    self.assertDictEqual(self._json_test_data, result)

  def test_parse_json_file_path(self):
    result = self._json_file_test_helper(PathParser.json_file_path)
    self.assertEqual(pathlib.Path("file.json"), result)

  def test_parse_hjson_file_path(self):
    result = self._json_file_test_helper(PathParser.hjson_file_path)
    self.assertEqual(pathlib.Path("file.json"), result)

  def test_parse_inline_hjson(self):
    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                r"(?i)non-empty string"):
      ObjectParser.inline_hjson("")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "braces"):
      ObjectParser.inline_hjson("{")
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "braces"):
      ObjectParser.inline_hjson("[]")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.inline_hjson("{invalid json}")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.inline_hjson("{'asdfas':'asdf}")
    self.assertDictEqual(
        self._json_test_data,
        ObjectParser.inline_hjson(json.dumps(self._json_test_data)))

  def test_parse_dir_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.dir_path("")
    file = pathlib.Path("file")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.dir_path(file)
    self.assertIn("does not exist", str(cm.exception))
    file.touch()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.dir_path(file)
    self.assertIn("not a folder", str(cm.exception))
    folder = pathlib.Path("folder")
    folder.mkdir()
    self.assertEqual(folder, PathParser.dir_path(folder))
    self.assertEqual(folder, PathParser.dir_path(str(folder)))

  def test_parse_non_empty_dir_path(self):
    folder = pathlib.Path("folder")
    folder.mkdir()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.non_empty_dir_path(folder)
    self.assertIn("empty", str(cm.exception))
    (folder / "foo").touch()
    self.assertEqual(folder, PathParser.non_empty_dir_path(folder))
    self.assertEqual(folder, PathParser.non_empty_dir_path(str(folder)))

  def test_parse_non_empty_file_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.non_empty_file_path("")
    folder = pathlib.Path("folder")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.non_empty_file_path(folder)
    self.assertIn("does not exist", str(cm.exception))
    folder.mkdir()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.non_empty_file_path(folder)
    self.assertIn("not a file", str(cm.exception))
    file = pathlib.Path("file")
    file.touch()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      self.assertEqual(file, PathParser.non_empty_file_path(file))
    self.assertIn("is an empty file", str(cm.exception))

    with file.open("w", encoding="utf-8") as f:
      f.write("fooo")
    self.assertEqual(file, PathParser.non_empty_file_path(file))

  def test_parse_existing_file_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.existing_file_path("")
    folder = pathlib.Path("folder")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.existing_file_path(folder)
    self.assertIn("does not exist", str(cm.exception))
    folder.mkdir()
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      PathParser.existing_file_path(folder)
    self.assertIn("not a file", str(cm.exception))
    file = pathlib.Path("file")
    file.touch()
    self.assertEqual(file, PathParser.existing_file_path(file))

  def test_parse_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.path("")
    folder = pathlib.Path("folder")
    folder.mkdir()
    self.assertEqual(folder, PathParser.path(folder))
    file = pathlib.Path("file")
    file.touch()
    self.assertEqual(file, PathParser.path(file))

  def test_parse_any_path_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.any_path("")
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.any_path(None)

  def test_parse_any_path(self):
    folder = pathlib.Path("folder")
    folder_pure = pathlib.PurePath(folder)
    self.assertEqual(folder_pure, PathParser.any_path(folder))
    folder.mkdir()
    self.assertEqual(folder_pure, PathParser.any_path(folder))
    file = pathlib.Path("file")
    file_pure = pathlib.PurePath(file)
    self.assertEqual(file_pure, PathParser.any_path(file))
    file.touch()
    self.assertEqual(file_pure, PathParser.any_path(file))

  def test_parse_optional_any_path_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      PathParser.optional_any_path("")

  def test_parse_optional_any_path(self):
    self.assertIsNone(PathParser.optional_any_path(None))
    folder = pathlib.Path("folder")
    folder_pure = pathlib.PurePath(folder)
    self.assertEqual(folder_pure, PathParser.optional_any_path(folder))

  def test_parse_bool_success(self):
    self.assertIs(ObjectParser.bool("true"), True)
    self.assertIs(ObjectParser.bool("True"), True)
    self.assertIs(ObjectParser.bool(True), True)
    self.assertIs(ObjectParser.bool("false"), False)
    self.assertIs(ObjectParser.bool("False"), False)
    self.assertIs(ObjectParser.bool(False), False)

  def test_parse_bool_success_strict(self):
    self.assertIs(ObjectParser.bool(True, strict=True), True)
    self.assertIs(ObjectParser.bool(False, strict=True), False)

  def test_parse_bool_invalid(self):
    invalid: Any
    for invalid in (1, 0, "1", "0", "", None, [], ()):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.bool(invalid)
        ObjectParser.bool(invalid, strict=True)

  def test_parse_bool_invalid_strict(self):
    invalid: Any
    for invalid in (None, "False", "false", "True", "true"):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.bool(invalid, strict=True)

  def test_parse_optional_bool(self):
    self.assertIsNone(ObjectParser.optional_bool(None))
    self.assertIsNone(ObjectParser.optional_bool(""))
    self.assertIs(ObjectParser.optional_bool("true"), True)
    self.assertIs(ObjectParser.optional_bool("false"), False)

  def test_parse_optional_bool_invalid(self):
    invalid: Any
    for invalid in (1, 0, "1", "0", [], ()):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.optional_bool(invalid)
        ObjectParser.optional_bool(invalid, strict=True)

  def test_parse_optional_bool_invalid_strict(self):
    invalid: Any
    for invalid in ("False", "false", "True", "true"):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.optional_bool(invalid, strict=True)

  def test_parse_datetime_success(self):
    now = dt.datetime.now()
    self.assertIs(ObjectParser.datetime(now), now)
    date = dt.date(2024, 1, 1)
    self.assertEqual(ObjectParser.datetime(date), dt.datetime(2024, 1, 1, 0, 0))
    self.assertEqual(
        ObjectParser.datetime("2024-01-01T12:00:00Z"),
        dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
    )
    self.assertEqual(
        ObjectParser.datetime("2024-01-01T12:00:00+00:00"),
        dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
    )
    self.assertEqual(
        ObjectParser.datetime("2024-01-01 12:00:00"),
        dt.datetime(2024, 1, 1, 12, 0, 0),
    )
    self.assertEqual(
        ObjectParser.datetime("2024-01-01"),
        dt.datetime(2024, 1, 1, 0, 0),
    )
    self.assertEqual(
        ObjectParser.datetime("  2024-01-01 12:00:00  "),
        dt.datetime(2024, 1, 1, 12, 0, 0),
    )

  def test_parse_datetime_invalid(self):
    invalid: Any
    for invalid in (None, 1, [], {}, "invalid", "", "2024-99-99"):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.datetime(invalid)

  def test_parse_optional_datetime(self):
    self.assertIsNone(ObjectParser.optional_datetime(None))
    self.assertIsNone(ObjectParser.optional_datetime(""))
    self.assertEqual(
        ObjectParser.optional_datetime("2024-01-01 12:00:00"),
        dt.datetime(2024, 1, 1, 12, 0, 0),
    )

  def test_parse_optional_datetime_invalid(self):
    invalid: Any
    for invalid in (1, [], {}, "invalid", "2024-99-99"):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.optional_datetime(invalid)

  def test_parse_sh_cmd(self):
    self.assertSequenceEqual(
        ObjectParser.sh_cmd("ls -al ."), ["ls", "-al", "."])
    self.assertSequenceEqual(
        ObjectParser.sh_cmd("ls -al '.'"), ["ls", "-al", "."])
    self.assertSequenceEqual(
        ObjectParser.sh_cmd(";ls -al '.'"), [";ls", "-al", "."])
    self.assertSequenceEqual(
        ObjectParser.sh_cmd(("ls", "-al", ".")), ["ls", "-al", "."])

  def test_parse_sh_cmd_invalid(self):
    invalid: Any
    for invalid in (1, "", None, [], 'ls -al ".'):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.sh_cmd(invalid)

  def test_parse_dict_invalid(self):
    invalid: Any
    for invalid in (1, 0, "1", "0", "", None, [], ()):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.dict(invalid)

  def test_parse_dict(self):
    self.assertDictEqual(ObjectParser.dict({}), {})
    self.assertDictEqual(ObjectParser.dict({"A": 2}), {"A": 2})

  def test_parse_non_empty_dict_invalid(self):
    invalid: Any
    for invalid in (1, 0, "1", "0", "", None, [], (), {}):
      with self.assertRaises(argparse.ArgumentTypeError):
        ObjectParser.non_empty_dict(invalid)

  def test_parse_non_empty_dict(self):
    result = ObjectParser.non_empty_dict({"a": 1})
    self.assertDictEqual(result, {"a": 1})

  def test_parse_unique_sequence(self):
    self.assertSequenceEqual(ObjectParser.unique_sequence([]), [])
    self.assertSequenceEqual(ObjectParser.unique_sequence(()), ())
    self.assertSequenceEqual(ObjectParser.unique_sequence([1, 2, 3]), [1, 2, 3])
    self.assertSequenceEqual(ObjectParser.unique_sequence((1, 2, 3)), (1, 2, 3))

  def test_parse_unique_sequence_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ObjectParser.unique_sequence([1, 1, 2, 2, 2, 3, 5, 5])
    self.assertIn("duplicates", str(cm.exception))
    self.assertIn("1, 2, 5", str(cm.exception))

  def test_parse_unique_sequence_custom_exception(self):

    class CustomException(Exception):
      pass

    with self.assertRaises(CustomException):
      ObjectParser.unique_sequence([1, 1], error_cls=CustomException)

  def test_parse_unique_sequence_custom_name(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ObjectParser.unique_sequence([1, 1], name="custom test name")
    self.assertIn("custom test name", str(cm.exception))

  def test_str_list(self):
    self.assertSequenceEqual(ObjectParser.str_list([]), [])
    self.assertSequenceEqual(ObjectParser.str_list(""), [])
    self.assertSequenceEqual(ObjectParser.str_list(None), [])
    self.assertSequenceEqual(ObjectParser.str_list("a,b, c"), ["a", "b", "c"])
    self.assertSequenceEqual(ObjectParser.str_list("a"), ["a"])
    self.assertSequenceEqual(
        ObjectParser.str_list(["a", "b, c"]), ["a", "b, c"])
    self.assertSequenceEqual(ObjectParser.str_list([1, 2]), ["1", "2"])
    self.assertSequenceEqual(ObjectParser.str_list((1, "2, 3")), ["1", "2, 3"])

  def test_str_list_invalid(self):
    invalid: Any
    for invalid in (1, 1.2):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ObjectParser.str_list(invalid)

  def test_str_tuple(self):
    self.assertEqual(ObjectParser.str_tuple([]), ())
    self.assertEqual(ObjectParser.str_tuple(""), ())
    self.assertEqual(ObjectParser.str_tuple(None), ())
    self.assertEqual(ObjectParser.str_tuple("a,b, c"), ("a", "b", "c"))
    self.assertEqual(ObjectParser.str_tuple("a"), ("a",))
    self.assertEqual(ObjectParser.str_tuple(["a", "b, c"]), ("a", "b, c"))
    self.assertEqual(ObjectParser.str_tuple([1, 2]), ("1", "2"))
    self.assertEqual(ObjectParser.str_tuple((1, "2, 3")), ("1", "2, 3"))
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.str_tuple(123)

  def test_parse_sequence(self):
    self.assertSequenceEqual(ObjectParser.sequence([]), [])
    self.assertSequenceEqual(ObjectParser.sequence([1, 2]), [1, 2])
    self.assertSequenceEqual(ObjectParser.sequence(()), ())
    self.assertSequenceEqual(ObjectParser.sequence((1, 2)), (1, 2))

  def test_parse_sequence_invalid(self):
    invalid: Any
    for invalid in ("", "1", 1, {}, {"a": 1}, set(), {(1, 2)}):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ObjectParser.sequence(invalid)

  def test_parse_iterable(self):
    self.assertSequenceEqual(list(ObjectParser.iterable([])), [])
    self.assertSequenceEqual(list(ObjectParser.iterable([1, 2])), [1, 2])
    self.assertSequenceEqual(tuple(ObjectParser.iterable((1, 2))), (1, 2))
    self.assertSetEqual(set(ObjectParser.iterable({1, 2})), {1, 2})

  def test_parse_iterable_invalid(self):
    invalid: Any
    for invalid in ("", "1", 1, None, 1.2):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ObjectParser.iterable(invalid)

  def test_parse_non_empty_sequence(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = ObjectParser.non_empty_sequence([])
    self.assertSequenceEqual(ObjectParser.non_empty_sequence([1, 2]), [1, 2])
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = ObjectParser.non_empty_sequence(())
    self.assertSequenceEqual(ObjectParser.non_empty_sequence((1, 2)), (1, 2))

  def test_parse_non_empty_sequence_invalid(self):
    invalid: Any
    for invalid in ("", "1", 1, {}, {"a": 1}, set(), {(1, 2)}, (), []):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ObjectParser.non_empty_sequence(invalid)

  def test_parse_fuzzy_url_invalid(self):
    invalid = ("foo", "x64/123", "x64/www.google.com")
    for url in invalid:
      with self.subTest(url=url):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, url):
          ObjectParser.fuzzy_url(url)

  def test_parse_fuzzy_url(self):
    expected = (
        ("/foo/bar", "file:///foo/bar"),
        ("C:/foo/bar", "file://C:/foo/bar"),
        ("1234.com", "https://1234.com"),
        ("http://1234.com", "http://1234.com"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://localhost", "http://localhost"),
        ("127.0.0.1", "https://127.0.0.1"),
        ("localhost", "https://localhost"),
        ("test.com", "https://test.com"),
        ("test.com/", "https://test.com/"),
        ("test.com/1234", "https://test.com/1234"),
        ("test.com/bar", "https://test.com/bar"),
        ("test.com/bar?x=1", "https://test.com/bar?x=1"),
        ("test.com:1234", "https://test.com:1234"),
        ("test.com:1234/", "https://test.com:1234/"),
        ("test.com:1234/56", "https://test.com:1234/56"),
        ("test.com:1234/56/", "https://test.com:1234/56/"),
        ("test.com:1234/bar", "https://test.com:1234/bar"),
        ("test.com:1234/bar?x=1", "https://test.com:1234/bar?x=1"),
        ("localhost:8123", "https://localhost:8123"),
        ("localhost:8123", "https://localhost:8123"),
        ("localhost:8123/", "https://localhost:8123/"),
        ("localhost:8123/77", "https://localhost:8123/77"),
        ("localhost:8123/77/", "https://localhost:8123/77/"),
        ("localhost:8123/bar", "https://localhost:8123/bar"),
        ("localhost:8123/bar?x=1", "https://localhost:8123/bar?x=1"),
        ("data:text/html,this is some data",
         "data:text/html,this is some data"),
        ("chrome://extensions", "chrome://extensions"),
    )
    for url, result in expected:
      with self.subTest(url=url):
        self.assertEqual(ObjectParser.fuzzy_url_str(url), result)
        parsed = ObjectParser.fuzzy_url(url)
        self.assertEqual(urlparse.urlunparse(parsed), result)

  def test_parse_fuzzy_url_default_scheme(self):
    expected = ("test.com", "test.com/", "test.com/bar", "test.com/bar?x=1",
                "test.com:1234", "test.com:1234/", "test.com:1234/bar",
                "test.com:1234/bar?x=1", "localhost:8123", "localhost:8123/",
                "localhost:8123/bar", "localhost:8123/bar?x1")
    for url in expected:
      with self.subTest(url=url):
        result_default = f"https://{url}"
        self.assertEqual(ObjectParser.fuzzy_url_str(url), result_default)
        parsed = ObjectParser.fuzzy_url(url)
        self.assertEqual(urlparse.urlunparse(parsed), result_default)
        result_custom = f"ftp://{url}"
        self.assertEqual(
            ObjectParser.fuzzy_url_str(url, default_scheme="ftp"),
            result_custom)
        parsed = ObjectParser.fuzzy_url(url, default_scheme="ftp")
        self.assertEqual(urlparse.urlunparse(parsed), result_custom)

  def test_parse_url(self):
    expected = (
        ("file:///foo/bar", "file:///foo/bar"),
        ("about:blank", "about:blank"),
        ("http://test.com/bar", "http://test.com/bar"),
        ("https://test.com/bar", "https://test.com/bar"),
        ("http://test.com", "http://test.com"),
        ("https://test.com/", "https://test.com/"),
        ("http://test.com/bar", "http://test.com/bar"),
        ("https://test.com/bar?x=1", "https://test.com/bar?x=1"),
        ("http://test.com:1234", "http://test.com:1234"),
        ("https://test.com:1234/", "https://test.com:1234/"),
        ("http://test.com:1234/bar", "http://test.com:1234/bar"),
        ("https://test.com:1234/bar?x=1", "https://test.com:1234/bar?x=1"),
        ("http://localhost:8123", "http://localhost:8123"),
        ("https://localhost:8123/", "https://localhost:8123/"),
        ("http://localhost:8123/bar", "http://localhost:8123/bar"),
        ("https://localhost:8123/bar?x=1", "https://localhost:8123/bar?x=1"),
        ("data:text/html,this is some data",
         "data:text/html,this is some data"),
    )
    for url, result in expected:
      with self.subTest(url=url):
        self.assertEqual(ObjectParser.url_str(url), result)
        self.assertEqual(ObjectParser.fuzzy_url_str(url), result)
        parsed = ObjectParser.url(url)
        self.assertEqual(urlparse.urlunparse(parsed), result)
        parsed_fuzzy = ObjectParser.fuzzy_url(url)
        self.assertEqual(urlparse.urlunparse(parsed_fuzzy), result)

  def test_parse_url_invalid(self):
    invalid: Any
    for invalid in (None, "", {}, "http:// foo .com/bar", "htt p://foo.com",
                    "http://foo.com:-123/bar"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.url(invalid)
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.url_str(invalid)
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.httpx_url_str(invalid)
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.fuzzy_url_str(invalid)
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.fuzzy_url(invalid)

  def test_parse_httpx_url_str_invalid(self):
    invalid: Any
    for invalid in ("ftp://foo.com:123/bar", "ssh://test.com"):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          _ = ObjectParser.httpx_url_str(invalid)

  def test_parse_url_scheme(self):
    url = "ftp://foo.com"
    parsed = ObjectParser.url(url)
    self.assertEqual(urlparse.urlunparse(parsed), url)
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = ObjectParser.url(url, schemes=("https",))
    parsed = ObjectParser.url(
        url, schemes=(
            "https",
            "ftp",
        ))
    self.assertEqual(urlparse.urlunparse(parsed), url)

  def test_parse_regexp(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.regexp("\\")
    pattern = ObjectParser.regexp("^abc$")
    self.assertEqual(pattern.pattern, "^abc$")

  def test_base_url(self):
    res = ObjectParser.base_url("https://example.com/foo")
    self.assertEqual(res.scheme, "https")
    self.assertEqual(res.netloc, "example.com")
    self.assertEqual(res.path, "/foo")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.base_url("")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.base_url(None)  # type: ignore
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.base_url("http://[::1")

  def test_not_none(self):
    self.assertEqual(ObjectParser.not_none(123), 123)
    self.assertEqual(ObjectParser.not_none("test"), "test")
    self.assertFalse(ObjectParser.not_none(False))
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.not_none(None)

  def test_safe_filename(self):
    self.assertEqual(ObjectParser.safe_filename("simple_name"), "simple_name")
    self.assertEqual(
        ObjectParser.safe_filename("name with spaces"), "name_with_spaces")
    self.assertEqual(
        ObjectParser.safe_filename("name/with:chars?"), "name_with_chars_")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.safe_filename("")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.safe_filename(None)

  def test_bytes_or_file_contents_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.bytes_or_file_contents(None)

  def test_bytes_or_file_contents(self):
    result: bytes = ObjectParser.bytes_or_file_contents("some data")
    self.assertEqual(result, b"some data")

    file = pathlib.Path("file")
    with file.open("w", encoding="utf-8") as f:
      f.write("some data")
    result = ObjectParser.bytes_or_file_contents(file)
    self.assertEqual(result, b"some data")

  def test_proto_or_file_textproto(self):
    text_proto_file = pathlib.Path("trace_config.textproto")
    text_config: str = """
      buffers: {
            size_kb: 123456
            fill_policy: DISCARD
        }
    """
    parser = ObjectParser.proto_or_file(trace_config_pb2.TraceConfig)
    proto_instance: trace_config_pb2.TraceConfig = parser(text_config)
    self.assertEqual(len(proto_instance.buffers), 1)
    self.assertEqual(proto_instance.buffers[0].size_kb, 123456)

    with text_proto_file.open("w", encoding="utf-8") as f:
      f.write(text_config)
    proto_instance_2 = parser(text_proto_file)
    self.assertEqual(len(proto_instance_2.buffers), 1)
    self.assertEqual(proto_instance_2.buffers[0].size_kb, 123456)
    self.assertEqual(proto_instance, proto_instance_2)

  def test_proto_or_file_invalid(self):
    text_proto_file = pathlib.Path("trace_config.textproto")
    text_config: str = """
      buffers-invalid: {
            size_kb: 123456
            fill_policy: DISCARD
        }
    """
    parser = ObjectParser.proto_or_file(trace_config_pb2.TraceConfig)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "buffers-invalid"):
      parser(text_config)

    with text_proto_file.open("w", encoding="utf-8") as f:
      f.write(text_config)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "buffers-invalid"):
      parser(text_proto_file)

  def test_proto_or_file_binary(self):
    text_proto_file = pathlib.Path("trace_config.textproto")
    binary_proto_file = pathlib.Path("trace_config.proto")
    text_config: str = """
      buffers: {
            size_kb: 123456
            fill_policy: DISCARD
        }
    """
    with text_proto_file.open("w", encoding="utf-8") as f:
      f.write(text_config)
    parser = ObjectParser.proto_or_file(trace_config_pb2.TraceConfig)
    proto_instance = parser(text_proto_file)
    with binary_proto_file.open("wb") as f:
      f.write(proto_instance.SerializeToString())

    proto_instance_2 = parser(binary_proto_file)
    self.assertEqual(len(proto_instance_2.buffers), 1)
    self.assertEqual(proto_instance_2.buffers[0].size_kb, 123456)
    self.assertEqual(proto_instance, proto_instance_2)

  def test_proto_or_file_binary_invalid_format(self):
    binary_proto_file = pathlib.Path("trace_config.proto")
    self.fs.create_file(binary_proto_file, contents="invalid data")
    parser = ObjectParser.proto_or_file(trace_config_pb2.TraceConfig)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, "TraceConfig"):
      parser(binary_proto_file)

  def test_parse_enum_list(self):

    class DummyEnum(enum.Enum):
      A = "a"
      B = "b"
      C = "c"

    self.assertSequenceEqual(
        ObjectParser.enum_list("DummyEnum", DummyEnum, "a,b,c"),
        [DummyEnum.A, DummyEnum.B, DummyEnum.C])
    self.assertSequenceEqual(
        ObjectParser.enum_list("DummyEnum", DummyEnum, ["a", "b", "c"]),
        [DummyEnum.A, DummyEnum.B, DummyEnum.C])
    self.assertSequenceEqual(
        ObjectParser.enum_list("DummyEnum", DummyEnum,
                               (DummyEnum.A, DummyEnum.B)),
        [DummyEnum.A, DummyEnum.B])
    self.assertSequenceEqual(
        ObjectParser.enum_list("DummyEnum", DummyEnum, ""), [])
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.enum_list("DummyEnum", DummyEnum, "invalid_value")
    with self.assertRaises(argparse.ArgumentTypeError):
      ObjectParser.enum_list("DummyEnum", DummyEnum, 123)

  def test_md5_hash(self):
    self.assertEqual(ObjectParser.md5_hash(""), b"")
    self.assertEqual(ObjectParser.md5_hash(b""), b"")
    hex_str = "8375843a6828b282eef16042c21e903b"
    expected_bytes = bytes.fromhex(hex_str)
    self.assertEqual(ObjectParser.md5_hash(hex_str), expected_bytes)
    self.assertEqual(ObjectParser.md5_hash(hex_str.upper()), expected_bytes)
    self.assertEqual(ObjectParser.md5_hash(f"  {hex_str}  "), expected_bytes)
    self.assertEqual(ObjectParser.md5_hash(expected_bytes), expected_bytes)

  def test_md5_hash_invalid(self):
    for invalid in ("123", "g" * 32, b"short", b"a" * 32, 12345):
      with self.subTest(invalid=invalid):
        with self.assertRaises(argparse.ArgumentTypeError):
          ObjectParser.md5_hash(invalid)


class TimeUnitTestCase(unittest.TestCase):

  def test_parse_microseconds(self):
    for unit in ("us", "micros", "microseconds"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.MICROSECOND)

  def test_parse_milliseconds(self):
    for unit in ("ms", "millis", "milliseconds"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.MILLISECOND)

  def test_parse_seconds(self):
    for unit in ("s", "sec", "secs", "second", "seconds"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.SECOND)

  def test_parse_minutes(self):
    for unit in ("m", "min", "mins", "minute", "minutes"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.MINUTE)

  def test_parse_hours(self):
    for unit in ("h", "hrs", "hour", "hours"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.HOUR)

  def test_parse_days(self):
    for unit in ("d", "day", "days"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.DAY)

  def test_parse_weeks(self):
    for unit in ("w", "week", "weeks"):
      self.assertIs(TimeUnit.parse(unit), TimeUnit.WEEK)

  def test_parse_invalid(self):
    invalid: Any
    for invalid in ("months", "yy", "ww", "i"):
      with self.assertRaises(DurationParseError):
        TimeUnit.parse(invalid)

  def test_to_timedelta(self):
    self.assertEqual(
        TimeUnit.MICROSECOND.timedelta(123), dt.timedelta(microseconds=123))
    self.assertEqual(
        TimeUnit.MILLISECOND.timedelta(123), dt.timedelta(milliseconds=123))
    self.assertEqual(TimeUnit.SECOND.timedelta(123), dt.timedelta(seconds=123))
    self.assertEqual(TimeUnit.MINUTE.timedelta(123), dt.timedelta(minutes=123))
    self.assertEqual(TimeUnit.HOUR.timedelta(123), dt.timedelta(hours=123))
    self.assertEqual(TimeUnit.DAY.timedelta(123), dt.timedelta(days=123))
    self.assertEqual(TimeUnit.WEEK.timedelta(123), dt.timedelta(weeks=123))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
