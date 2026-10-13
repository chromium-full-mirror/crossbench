# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import unittest

from crossbench import path as pth
from crossbench.cli.parser import ArgumentGroupHelp, ArgumentHelp, \
    CBArgumentParser, CBNamespace
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


class ArgumentHelpTest(unittest.TestCase):

  def test_from_action_options(self) -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_argument(
        "--test-flag",
        "-t",
        default="default_val",
        choices=["a", "b"],
        help="Help text")
    arg_help = ArgumentHelp.from_action(action)
    self.assertEqual(arg_help.name, "--test-flag")
    self.assertEqual(arg_help.aliases, ("-t",))
    self.assertFalse(arg_help.required)
    self.assertEqual(arg_help.default, "default_val")
    self.assertEqual(arg_help.choices, ("a", "b"))
    self.assertEqual(arg_help.help, "Help text")

    json_data = arg_help.to_json()
    self.assertEqual(json_data["name"], "--test-flag")
    self.assertEqual(json_data["aliases"], ["-t"])
    self.assertFalse(json_data["required"])
    self.assertEqual(json_data["choices"], ["a", "b"])

  def test_from_action_positional(self) -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_argument("pos_arg", help="Positional help")
    arg_help = ArgumentHelp.from_action(action)
    self.assertEqual(arg_help.name, "pos_arg")
    self.assertEqual(arg_help.aliases, ())
    self.assertTrue(arg_help.required)
    self.assertIsNone(arg_help.default)
    self.assertIsNone(arg_help.choices)
    self.assertEqual(arg_help.help, "Positional help")

  def test_from_action_required_and_default_path(self) -> None:
    parser = argparse.ArgumentParser()
    path_val = pth.LocalPath("/tmp/foo")
    action = parser.add_argument(
        "--path", required=True, default=path_val, help="Path")
    arg_help = ArgumentHelp.from_action(action)
    self.assertTrue(arg_help.required)
    self.assertEqual(arg_help.default, path_val)
    self.assertIsInstance(arg_help.default, pth.LocalPath)
    json_data = arg_help.to_json()
    self.assertTrue(json_data["required"])
    self.assertEqual(json_data["default"], "/tmp/foo")


class ArgumentGroupHelpTest(unittest.TestCase):

  def test_from_parser(self) -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group("Test Group", "Group description")
    group.add_argument("--foo", help="Foo help")
    group.add_argument("--bar", help="Bar help")

    groups = ArgumentGroupHelp.from_parser(parser)
    self.assertEqual(len(groups), 1)
    group_help = groups[0]
    self.assertEqual(group_help.name, "Test Group")
    self.assertEqual(group_help.description, "Group description")
    self.assertEqual(len(group_help.arguments), 2)
    self.assertEqual(group_help.arguments[0].name, "--foo")
    self.assertEqual(group_help.arguments[1].name, "--bar")

  def test_from_parser_default_title(self) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custom-opt", help="Custom option")

    groups = ArgumentGroupHelp.from_parser(
        parser, default_title="Custom Options")
    self.assertEqual(len(groups), 1)
    self.assertEqual(groups[0].name, "Custom Options")

  def test_extract_group_title(self) -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group("custom")
    self.assertEqual(ArgumentGroupHelp._extract_group_title(group),
                     "custom")  # noqa: SLF001
    self.assertEqual(
        ArgumentGroupHelp._extract_group_title(  # noqa: SLF001
            group, "Default"),
        "custom")

    empty_group = parser.add_argument_group("")
    self.assertEqual(
        ArgumentGroupHelp._extract_group_title(empty_group),  # noqa: SLF001
        "Options")
    self.assertEqual(
        ArgumentGroupHelp._extract_group_title(  # noqa: SLF001
            empty_group, "Default"),
        "Default")

    default_options_group = parser._action_groups[1]  # noqa: SLF001
    self.assertEqual(
        ArgumentGroupHelp._extract_group_title(  # noqa: SLF001
            default_options_group),
        "options")
    self.assertEqual(
        ArgumentGroupHelp._extract_group_title(  # noqa: SLF001
            default_options_group, "Default"),
        "Default")

  def test_crossbench_argument_parser_extract_argument_groups(self) -> None:
    parser = CBArgumentParser()
    group = parser.add_argument_group("Group A")
    group.add_argument("--flag-a", help="Flag A")
    groups = ArgumentGroupHelp.from_parser(parser)
    self.assertEqual(len(groups), 1)
    self.assertEqual(groups[0].name, "Group A")
    self.assertEqual(groups[0].arguments[0].name, "--flag-a")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
