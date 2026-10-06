# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from crossbench import path as pth
from crossbench.cli.parser import CBArgumentParser, CBNamespace
from crossbench.parse import NumberParser, ObjectParser
from tests import test_helper


class CBNamespaceTestCase(unittest.TestCase):

  def test_init(self) -> None:
    ns = CBNamespace(foo="bar", num=42)
    self.assertEqual(ns.foo, "bar")
    self.assertEqual(ns.num, 42)

  def test_modify_before_freeze(self) -> None:
    ns = CBNamespace(foo="bar")
    ns.foo = "baz"
    self.assertEqual(ns.foo, "baz")
    ns.new_attr = 100
    self.assertEqual(ns.new_attr, 100)
    del ns.foo
    self.assertNotIn("foo", vars(ns))

  def test_freeze_blocks_mutation(self) -> None:
    ns = CBNamespace(foo="bar", num=42)
    frozen_ns = ns.freeze()
    self.assertIs(frozen_ns, ns)

    with self.assertRaisesRegex(TypeError, "Cannot modify immutable"):
      ns.foo = "baz"
    with self.assertRaisesRegex(TypeError, "Cannot modify immutable"):
      ns.new_attr = 100
    with self.assertRaisesRegex(TypeError, "Cannot delete attribute"):
      del ns.foo

    self.assertEqual(ns.foo, "bar")
    self.assertEqual(ns.num, 42)

  def test_freeze_is_idempotent(self) -> None:
    ns = CBNamespace(foo="bar")
    ns.freeze()
    with self.assertRaises(TypeError):
      ns.foo = "baz"
    ns.freeze()
    with self.assertRaises(TypeError):
      ns.foo = "baz"

  def test_nested_freeze(self) -> None:
    nested = CBNamespace(inner="value")
    parent = CBNamespace(child=nested, name="parent")
    nested.inner = "value2"
    self.assertEqual(nested.inner, "value2")

    parent.freeze()
    with self.assertRaises(TypeError):
      parent.name = "changed"
    with self.assertRaises(TypeError):
      nested.inner = "changed"


class CBArgumentParserTestCase(unittest.TestCase):

  def test_parse_args_returns_crossbench_namespace(self) -> None:
    parser = CBArgumentParser()
    parser.add_argument("--test-flag", default="default_value")
    args = parser.parse_args(["--test-flag=custom"])
    self.assertIsInstance(args, CBNamespace)
    self.assertEqual(args.test_flag, "custom")

  def test_parse_known_args_returns_crossbench_namespace(self) -> None:
    parser = CBArgumentParser()
    parser.add_argument("--flag", default="a")
    args, unprocessed = parser.parse_known_args(["--flag=b", "extra"])
    self.assertIsInstance(args, CBNamespace)
    self.assertEqual(args.flag, "b")
    self.assertEqual(unprocessed, ["extra"])

  def test_reject_type_bool(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError, "type=bool is forbidden"):
      parser.add_argument("--flag", type=bool)

    group = parser.add_argument_group("group")
    with self.assertRaisesRegex(ValueError, "type=bool is forbidden"):
      group.add_argument("--flag2", type=bool)

    mutex = parser.add_mutually_exclusive_group()
    with self.assertRaisesRegex(ValueError, "type=bool is forbidden"):
      mutex.add_argument("--flag3", type=bool)

    group_mutex = group.add_mutually_exclusive_group()
    with self.assertRaisesRegex(ValueError, "type=bool is forbidden"):
      group_mutex.add_argument("--flag4", type=bool)

  def test_reject_type_str(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError, "type=str is forbidden"):
      parser.add_argument("--flag", type=str)

  def test_reject_type_int_and_float(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(
        ValueError, "type=int is forbidden.*NumberParser\\.positive_int"):
      parser.add_argument("--flag", type=int)
    with self.assertRaisesRegex(
        ValueError, "type=float is forbidden.*NumberParser\\.positive_float"):
      parser.add_argument("--flag2", type=float)

  def test_reject_type_collections(self) -> None:
    parser = CBArgumentParser()
    for banned_type in (list, dict, set, tuple):
      with self.subTest(banned_type=banned_type.__name__):
        with self.assertRaisesRegex(ValueError, "is forbidden"):
          parser.add_argument(
              f"--flag-{banned_type.__name__}", type=banned_type)

  def test_reject_raw_lambda(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError, "Raw lambda parsers are forbidden"):
      parser.add_argument("--flag", type=lambda x: x)

  def test_reject_boolean_default_without_action_or_type(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError, "Boolean default without boolean"):
      parser.add_argument("--flag", default=False)
    with self.assertRaisesRegex(ValueError, "Boolean default without boolean"):
      parser.add_argument("--flag2", default=True)

  def test_reject_explicit_action_store(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError, "Redundant action='store'"):
      parser.add_argument("--flag", action="store")
    with self.assertRaisesRegex(ValueError, "Redundant action='store'"):
      parser.add_argument("--flag", action="store", default="value")

  def test_reject_action_store_boolean_default(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(
        ValueError, "Invalid action='store' with boolean default=False"):
      parser.add_argument("--flag", action="store", default=False)
    with self.assertRaisesRegex(
        ValueError, "Invalid action='store' with boolean default=True"):
      parser.add_argument("--flag", action="store", default=True)

  def test_reject_action_store_true_default_true(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError,
                                "action='store_true' with default=True"):
      parser.add_argument("--flag", action="store_true", default=True)

  def test_reject_action_store_false_default_false(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(ValueError,
                                "action='store_false' with default=False"):
      parser.add_argument("--flag", action="store_false", default=False)

  def test_reject_action_append_non_appendable_default(self) -> None:
    parser = CBArgumentParser()
    with self.assertRaisesRegex(
        ValueError, "Invalid non-appendable default=False for action='append'"):
      parser.add_argument("--flag", action="append", default=False)
    with self.assertRaisesRegex(
        ValueError, "Invalid non-appendable default='bad' for action='append'"):
      parser.add_argument("--flag", action="append", default="bad")
    with self.assertRaisesRegex(
        ValueError, "Invalid non-appendable default=123 for action='append'"):
      parser.add_argument("--flag", action="append", default=123)
    with self.assertRaisesRegex(
        ValueError,
        r"Invalid non-appendable default=set\(\) for action='append'"):
      parser.add_argument("--flag", action="append", default=set())
    with self.assertRaisesRegex(
        ValueError, r"Invalid non-appendable default=\(\) for action='append'"):
      parser.add_argument("--flag", action="append", default=())
    with self.assertRaisesRegex(
        ValueError, "Invalid non-appendable default=False for action='extend'"):
      parser.add_argument("--flag", action="extend", default=False)
    with self.assertRaisesRegex(
        ValueError,
        r"Invalid non-appendable default=set\(\) for action='extend'"):
      parser.add_argument("--flag", action="extend", default=set())
    with self.assertRaisesRegex(
        ValueError, r"Invalid non-appendable default=\(\) for action='extend'"):
      parser.add_argument("--flag", action="extend", default=())

  def test_allow_valid_arguments(self) -> None:
    parser = CBArgumentParser()
    parser.add_argument("--b1", action="store_true", default=False)
    parser.add_argument("--b2", action="store_false", default=True)
    parser.add_argument("--b3", action="store_const", const=True, default=False)
    parser.add_argument("--b4", type=ObjectParser.bool, default=False)
    parser.add_argument("--b5", type=ObjectParser.bool, default=True)
    parser.add_argument("--s1", type=ObjectParser.non_empty_str)
    parser.add_argument("--s2", type=ObjectParser.any_str)
    parser.add_argument("--i1", type=NumberParser.positive_int)
    parser.add_argument("--i2", type=NumberParser.port_number)
    parser.add_argument("--p1", type=pth.LocalPath)
    parser.add_argument("--app1", action="append")
    parser.add_argument("--app2", action="append", default=[])
    parser.add_argument("--ext1", action="extend", nargs="+", default=[])
    args = parser.parse_args([
        "--b1",
        "--b4=True",
        "--s1=hello",
        "--s2=",
        "--i1=5",
        "--i2=8080",
        "--p1=/tmp",
        "--app1=val1",
        "--app2=val2",
        "--ext1",
        "val3",
    ])
    self.assertTrue(args.b1)
    self.assertTrue(args.b2)
    self.assertFalse(args.b3)
    self.assertTrue(args.b4)
    self.assertTrue(args.b5)
    self.assertEqual(args.s1, "hello")
    self.assertEqual(args.s2, "")
    self.assertEqual(args.i1, 5)
    self.assertEqual(args.i2, 8080)
    self.assertEqual(args.p1, pth.LocalPath("/tmp"))
    self.assertEqual(args.app1, ["val1"])
    self.assertEqual(args.app2, ["val2"])
    self.assertEqual(args.ext1, ["val3"])


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
