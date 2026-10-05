# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import unittest

from crossbench.pinpoint.job_parser import parse_job_id, parse_job_ids
from tests import test_helper


class JobParserTest(unittest.TestCase):

  def test_parse_job_id_valid(self):
    self.assertEqual(parse_job_id("123456"), "123456")
    self.assertEqual(parse_job_id("123abc"), "123abc")
    self.assertEqual(parse_job_id("  123ABC  "), "123abc")
    self.assertEqual(parse_job_id("go/j_/123456"), "123456")
    self.assertEqual(parse_job_id("http://go/j_/123456"), "123456")
    self.assertEqual(parse_job_id("j_/123abc"), "123abc")
    self.assertEqual(parse_job_id("go/l_/r/123456"), "123456")
    self.assertEqual(parse_job_id("http://go/l_/r/123456"), "123456")
    self.assertEqual(parse_job_id("l_/r/123abc"), "123abc")

  def test_parse_job_id_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("not_a_job_id")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("12345g")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("   ")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("/")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("go/j_/")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("go/j_/not_a_job_id")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("go/l_/r/")
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_id("go/l_/r/not_a_job_id")

  def test_parse_job_ids_valid(self):
    self.assertEqual(parse_job_ids(["123456"]), ["123456"])
    self.assertEqual(parse_job_ids(["123abc", "456def"]), ["123abc", "456def"])
    self.assertEqual(parse_job_ids(["123abc, 456def"]), ["123abc", "456def"])
    self.assertEqual(
        parse_job_ids(["go/l_/r/123abc", "456def,789abc"]),
        ["123abc", "456def", "789abc"],
    )

  def test_parse_job_ids_deduplication(self):
    self.assertEqual(
        parse_job_ids(["123abc", "123abc", "456def"]),
        ["123abc", "456def"],
    )
    self.assertEqual(parse_job_ids(["123ABC, 123abc"]), ["123abc"])

  def test_parse_job_ids_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_ids([])
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_ids([""])
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_ids(["not_a_job_id"])
    with self.assertRaises(argparse.ArgumentTypeError):
      parse_job_ids(["123abc, invalid"])


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
