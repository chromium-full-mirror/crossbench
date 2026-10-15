# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import pathlib
import unittest
from typing import Any, Self
from unittest import mock

from immutabledict import immutabledict
from typing_extensions import override

from crossbench import path as pth
from crossbench.config import ConfigEnum, ConfigObject, ConfigParser, \
    UnusedPropertiesMode, root_dir
from crossbench.exception import MultiException
from crossbench.parse import NumberParser, ObjectParser, PathParser
from crossbench.str_enum_with_help import StrEnumWithHelp
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase


@enum.unique
class GenericEnum(StrEnumWithHelp):
  A = ("a", "A Help")
  B = ("b", "B Help")
  C = ("c", "C Help")


@enum.unique
class CustomConfigEnum(ConfigEnum):
  A = ("a", "A Help")
  B = ("b", "B Help")
  C = ("c", "C Help")


class CustomValueEnum(enum.Enum):

  @classmethod
  def _missing_(cls, value: Any) -> CustomValueEnum | None:
    if value is True:
      return CustomValueEnum.A_OR_TRUE
    if value is False:
      return CustomValueEnum.B_OR_FALSE
    return super()._missing_(value)

  DEFAULT = "default"
  A_OR_TRUE = "a"
  B_OR_FALSE = "b"


@dataclasses.dataclass(frozen=True)
class CustomBoolConfigObject(ConfigObject):
  boolean: bool

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise ValueError("Only bool values are supported")

  @classmethod
  @override
  def parse_other(cls, value: Any) -> Self:
    if not isinstance(value, bool):
      raise ValueError("Only bool values are supported")
    return cls(boolean=value)

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("boolean", type=ObjectParser.bool, required=True)
    return parser


@dataclasses.dataclass(frozen=True)
class CustomNestedConfigObject(ConfigObject):
  name: str
  option: str | None = None
  array: list[str] | None = None

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    if ":" in value:
      raise ValueError("Invalid Config")
    if not value:
      raise ValueError("Got empty input")
    return cls(name=value)

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("name", type=str, required=True)
    parser.add_argument("option", type=str, required=False)
    parser.add_argument("array", type=list)
    return parser


@dataclasses.dataclass(frozen=True)
class CustomConfigObject(ConfigObject):

  name: str
  array: list[str] | None = None
  integer: int | None = None
  float_field: float | None = None
  nested: CustomNestedConfigObject | None = None
  choices: str = ""
  generic_enum: GenericEnum = GenericEnum.A
  config_enum: CustomConfigEnum = CustomConfigEnum.A
  custom_value_enum: CustomValueEnum = CustomValueEnum.DEFAULT
  depending_nested: dict[str, Any] | None = None
  depending_many: dict[str, Any] | None = None

  @classmethod
  def default(cls) -> CustomConfigObject:
    return cls("default")

  @classmethod
  @override
  def parse_str(cls, value: str) -> CustomConfigObject:
    if ":" in value:
      raise ValueError("Invalid Config")
    if not value:
      raise ValueError("Got empty input")
    return cls(name=value)

  @classmethod
  @override
  def parse_path_like(cls, original_value: str, path: pathlib.Path,
                      **kwargs) -> Self:
    return super().parse_path(path, **kwargs)

  @classmethod
  def parse_depending_nested(cls, value: str | None,
                             nested: CustomNestedConfigObject) -> dict | None:
    if not value:
      return None
    return {
        "value": ObjectParser.non_empty_str(value),
        "nested": ObjectParser.not_none(nested, "nested"),
    }

  @classmethod
  def parse_depending_many(cls, value: str | None, array: list[Any],
                           integer: int,
                           nested: CustomNestedConfigObject) -> dict | None:
    if not value:
      return None
    return {
        "value": ObjectParser.non_empty_str(value),
        "nested": ObjectParser.not_none(nested, "nested"),
        "array": ObjectParser.not_none(array, "array"),
        "integer": NumberParser.positive_int(integer, "integer"),
    }

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[CustomConfigObject]:
    parser = cls.base_config_parser()
    parser.add_argument(
        "name", aliases=("name_alias", "name_alias2"), type=str, required=True)
    parser.add_argument("array", type=list)
    parser.add_argument("integer", type=NumberParser.positive_int)
    parser.add_argument("float_field", type=NumberParser.any_float)
    parser.add_argument("nested", type=CustomNestedConfigObject)
    parser.add_argument("generic_enum", type=GenericEnum)
    parser.add_argument("config_enum", type=CustomConfigEnum)
    parser.add_argument(
        "custom_value_enum",
        type=CustomValueEnum,
        default=CustomValueEnum.DEFAULT)
    parser.add_argument("choices", type=str, choices=("x", "y", "z"))
    parser.add_argument(
        "depending_nested",
        type=CustomConfigObject.parse_depending_nested,
        depends_on=("nested",))
    parser.add_argument(
        "depending_many",
        type=CustomConfigObject.parse_depending_many,
        depends_on=("array", "integer", "nested"))
    return parser

  @classmethod
  def base_config_parser(cls) -> ConfigParser[CustomConfigObject]:
    return ConfigParser(cls)


class CustomConfigObjectStrict(CustomConfigObject):

  @classmethod
  def base_config_parser(cls) -> ConfigParser[CustomConfigObjectStrict]:
    return ConfigParser(cls, unused_properties_mode=UnusedPropertiesMode.ERROR)


class CustomConfigObjectWithDefault(CustomConfigObject):

  @classmethod
  def base_config_parser(cls) -> ConfigParser[CustomConfigObjectWithDefault]:
    return ConfigParser(cls, default=cls.default())


class CustomConfigObjectToArgumentValue(CustomConfigObject):

  def to_argument_value(self):
    return (self.name, self.array, self.integer)


class ConfigParserTestCase(unittest.TestCase):

  @override
  def setUp(self):
    super().setUp()
    self.parser = ConfigParser(CustomConfigObject)

  def test_invalid_type(self):
    with self.assertRaises(TypeError):
      self.parser.add_argument("foo", type="something")

  def test_invalid_alias(self):
    with self.assertRaises(ValueError):
      self.parser.add_argument("foo", aliases=("foo",), type=str)
    with self.assertRaises(ValueError):
      self.parser.add_argument(
          "foo", aliases=("foo_alias", "foo_alias"), type=str)

  def test_duplicate(self):
    self.parser.add_argument("foo", type=str)
    with self.assertRaises(ValueError):
      self.parser.add_argument("foo", type=str)
    with self.assertRaises(ValueError):
      self.parser.add_argument("foo2", aliases=("foo",), type=str)

  def test_invalid_string_depends_on(self):
    with self.assertRaises(TypeError):
      self.parser.add_argument(
          "custom",
          type=CustomConfigObject.parse_depending_nested,
          depends_on="other")

  def test_invalid_depends_on_nof_arguments(self):
    with self.assertRaises(TypeError) as cm:
      self.parser.add_argument("any", type=lambda x: x, depends_on=("other",))
    self.assertIn("arguments", str(cm.exception))

  def test_invalid_depends_on(self):
    with self.assertRaises(ValueError):
      self.parser.add_argument("any", type=None, depends_on=("other",))

    with self.assertRaises((ValueError, TypeError)):
      # Raises ValueError on Python 3.11 because depends_on is not allowed.
      # Raises TypeError on Python 3.12 because GenericEnum can't be called
      # with multiple parameters.
      self.parser.add_argument("enum", type=GenericEnum, depends_on=("other",))
    with self.assertRaises(ValueError):
      self.parser.add_argument("enum", type=ConfigEnum, depends_on=("other",))

    for primitive_type in (bool, float, int, str):
      with self.assertRaises(TypeError):
        self.parser.add_argument(
            "param", type=primitive_type, depends_on=("other",))

  def test_recursive_depends_on(self):
    self.parser.add_argument(
        "x", type=lambda value, y: value + y, depends_on=("y",))
    self.parser.add_argument(
        "y", type=lambda value, x: value + x, depends_on=("x",))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      self.parser.parse({"x": 1, "y": 100})
    self.assertIn("Recursive", str(cm.exception))

  def test_invalid_default_arg(self):
    with self.assertRaisesRegex(ValueError, "default"):
      self.parser.add_argument("name_1", type=str, default=None, required=False)
    with self.assertRaisesRegex(ValueError, "default"):
      self.parser.add_argument("name_1", type=str, default=None, required=True)
    with self.assertRaisesRegex(ValueError, "default"):
      self.parser.add_argument("name_2", type=str, default="", required=True)
    with self.assertRaisesRegex(ValueError, "default"):
      self.parser.add_argument("name_3", type=str, default=123, required=False)

  def test_default_str_arg(self):
    self.parser.add_argument("name_1", type=str, default="", required=False)

  def test_default(self):
    self.parser.add_argument("name", type=str, required=True)
    with self.assertRaisesRegex(argparse.ArgumentTypeError, r"(?i)no value"):
      self.parser.parse({})
    parser = ConfigParser(
        CustomConfigObject, default=CustomConfigObject.default())
    config = parser.parse({})
    self.assertEqual(config, CustomConfigObject.default())

  def test_empty_title(self):
    with self.assertRaisesRegex(ValueError, "title"):
      ConfigParser(CustomConfigObject, title="")

  def test_empty_key(self):
    with self.assertRaisesRegex(ValueError, "key"):
      ConfigParser(CustomConfigObject, key="")

  def test_title(self):
    parser = ConfigParser(CustomConfigObject, title=None)
    self.assertEqual(parser.title, "CustomConfigObject parser")
    parser = ConfigParser(CustomConfigObject)
    self.assertEqual(parser.title, "CustomConfigObject parser")
    parser = ConfigParser(CustomConfigObject, title="ParsyMcParser")
    self.assertEqual(parser.title, "ParsyMcParser")

  def test_key(self):
    parser = ConfigParser(CustomConfigObject, None)
    self.assertEqual(parser.key, "CustomConfigObject")
    parser = ConfigParser(CustomConfigObject)
    self.assertEqual(parser.key, "CustomConfigObject")
    parser = ConfigParser(CustomConfigObject, "ParsyMcParser")
    self.assertEqual(parser.key, "ParsyMcParser")
    parser = ConfigParser(CustomConfigObject, "ParsyMcParser",
                          "Parsy parser for McParser")
    self.assertEqual(parser.key, "ParsyMcParser")
    self.assertEqual(parser.title, "Parsy parser for McParser")

  def test_invalid_default(self):
    with self.assertRaises(TypeError) as cm:
      ConfigParser(CustomConfigObject, default="something else")
    self.assertIn("instance", str(cm.exception))

  def test_config_object_to_argument_value(self):
    result = CustomConfigObjectToArgumentValue.config_parser().parse(
        {"name": "custom-name"})
    self.assertIsInstance(result, CustomConfigObjectToArgumentValue)
    parser = ConfigParser(dict)
    parser.add_argument("data", type=CustomConfigObjectToArgumentValue)

    result = parser.parse({})
    self.assertDictEqual(result, {"data": None})
    result = parser.parse({"data": {"name": "a name"}})
    self.assertDictEqual(result, {"data": ("a name", None, None)})
    result = parser.parse(
        {"data": {
            "name": "a name",
            "integer": 1,
            "array": [1, 2],
        }})
    self.assertDictEqual(result, {"data": ("a name", [1, 2], 1)})

  def test_has_all_required_args(self):
    config_parser = CustomConfigObjectToArgumentValue.config_parser()
    self.assertTrue(config_parser.has_all_required_args({"name": "a name"}))
    self.assertTrue(
        config_parser.has_all_required_args({"name_alias": "a name"}))
    self.assertFalse(config_parser.has_all_required_args({"integer": 1}))

  def test_has_any_args(self):
    config_parser = CustomConfigObjectToArgumentValue.config_parser()
    self.assertTrue(config_parser.has_any_args({"name": "a name"}))
    self.assertTrue(config_parser.has_any_args({"name_alias": "a name"}))
    self.assertTrue(config_parser.has_any_args({"integer": 1}))
    self.assertFalse(config_parser.has_any_args({"invalid": 1}))

  def test_parse_bool_false(self):
    config = CustomBoolConfigObject.parse(False)
    assert isinstance(config, CustomBoolConfigObject)
    self.assertFalse(config.boolean)

  def test_parse_str(self):
    config_parser = ConfigParser(CustomConfigObject)
    with self.assertRaisesRegex(ValueError, "empty"):
      config_parser.parse("")
    obj = config_parser.parse("custom string")
    self.assertEqual(obj.name, "custom string")

  def test_default_argument_required_conflict(self):
    config_parser = ConfigParser(CustomConfigObject)
    config_parser.add_argument("required_arg", type=int, required=True)
    with self.assertRaisesRegex(ValueError, "required_arg"):
      config_parser.add_default_argument("default", type=bool)

  def test_existing_default_argument_required_conflict(self):
    config_parser = ConfigParser(CustomConfigObject)
    config_parser.add_default_argument("default_one", type=bool)
    with self.assertRaisesRegex(ValueError, "default_one"):
      config_parser.add_argument("required_arg", type=int, required=True)

  def test_default_argument_twice(self):
    config_parser = ConfigParser(CustomConfigObject)
    config_parser.add_default_argument("default_one", type=bool)
    with self.assertRaisesRegex(ValueError, "default_one"):
      config_parser.add_default_argument("default_two", type=bool)

  def test_default_argument(self):

    @dataclasses.dataclass
    class CustomObject:
      str_value: str = ""
      other: str = ""

    config_parser = ConfigParser(CustomObject)
    with self.assertRaises(ValueError):
      config_parser.parse("")
    config_parser.add_argument("other", type=str)
    with self.assertRaises(ValueError):
      config_parser.parse("")
    config_parser.add_default_argument("str_value", type=str)
    obj = config_parser.parse("custom string")
    self.assertEqual(obj.str_value, "custom string")

  def test_mutually_exclusive(self):
    parser = ConfigParser(dict)
    parser.add_argument("foo", type=int)
    parser.add_argument("bar", type=int)
    parser.set_mutually_exclusive("foo", "bar")

    # Only one is fine
    parser.parse({"foo": 1})
    parser.parse({"bar": 2})
    # None is fine if not required
    parser.parse({})

    # Both should fail
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"foo": 1, "bar": 2})

  def test_mutually_exclusive_unknown_arg(self):
    parser = ConfigParser(dict)
    parser.add_argument("foo", type=int)
    with self.assertRaisesRegex(ValueError, "not found"):
      parser.set_mutually_exclusive("foo", "unknown")

  def test_mutually_exclusive_multiple(self):
    parser = ConfigParser(dict)
    parser.add_argument("foo", type=int)
    parser.add_argument("bar", type=int)
    parser.add_argument("baz", type=int)
    parser.set_mutually_exclusive("foo", "bar", "baz")

    # Only one is fine
    self.assertEqual(
        parser.parse({"foo": 1}), {
            "foo": 1,
            "bar": None,
            "baz": None,
        })

    # Multiple should fail
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"foo": 1, "bar": 2})
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"foo": 1, "baz": 3})
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"foo": 1, "bar": 2, "baz": 3})

  def test_mutually_exclusive_groups(self):
    parser = ConfigParser(dict)
    parser.add_argument("a", type=int)
    parser.add_argument("b", type=int)
    parser.add_argument("c", type=int)
    parser.add_argument("d", type=int)
    parser.set_mutually_exclusive("a", "b")
    parser.set_mutually_exclusive("c", "d")

    # Fine
    parser.parse({"a": 1, "c": 3})
    parser.parse({"a": 1, "d": 4})
    parser.parse({"b": 2, "c": 3})

    # Fails
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"a": 1, "b": 2})
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"c": 3, "d": 4})

  def test_mutually_exclusive_defaults(self):
    parser = ConfigParser(dict)
    parser.add_argument("foo", type=int, default=10)
    parser.add_argument("bar", type=int)
    parser.set_mutually_exclusive("foo", "bar")

    # Fine, only foo is not None
    self.assertEqual(parser.parse({}), {"foo": 10, "bar": None})
    self.assertEqual(parser.parse({"foo": 11}), {"foo": 11, "bar": None})
    # bar=2 and foo will have default=10
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({"bar": 2})

    parser = ConfigParser(dict)
    parser.add_argument("foo", type=int, default=10)
    parser.add_argument("bar", type=int, default=20)
    parser.set_mutually_exclusive("foo", "bar")
    with self.assertRaisesRegex(ValueError, "mutually exclusive"):
      parser.parse({})

  def test_parse_local_path(self):
    parser = ConfigParser(dict)
    parser.add_argument("path", type=pth.LocalPath)
    parser.add_argument("parsed_path", type=PathParser.path)

    # Test path resolution for relative paths
    result = parser.parse({"path": "~/foo/bar", "parsed_path": "./baz"})
    expected = pth.LocalPath("~/foo/bar").expanduser().resolve()
    expected_parsed = pth.LocalPath("./baz").expanduser().resolve()
    self.assertEqual(result["path"], expected)
    self.assertEqual(result["parsed_path"], expected_parsed)


class ConfigObjectTestCase(CrossbenchFakeFsTestCase):

  def test_help(self):
    help_text = CustomConfigObject.config_parser().help
    self.assertIn("name", help_text)
    self.assertIn("array", help_text)
    self.assertIn("integer", help_text)
    self.assertIn("nested", help_text)
    self.assertIn("generic_enum", help_text)
    self.assertIn("config_enum", help_text)
    self.assertIn("custom_value_enum", help_text)
    self.assertIn("choices", help_text)
    self.assertIn("depending_nested", help_text)
    self.assertIn("depending_many", help_text)

  def test_has_path_prefix(self):
    for value in ("/foo/bar", "~/foo/bar", "../foo/bar", "..\\foo\\bar",
                  "./foo/bar", "C:\\foo\\bar", "C:/foo/bar"):
      with self.subTest(value=value):
        self.assertTrue(CustomConfigObject.has_path_prefix(value))
        self.assertTrue(CustomConfigObject.is_path_like(value))
    for value in ("foo/bar", "foo:bar", "foo", "{foo:'/foo/bar'}", "http://foo",
                  "c://", "c://bar", "C:../bar", "..//foo", "..//foo/bar",
                  "~:bar", "~.bar", "~//df", "foo/~bar", "foo~bar/foo",
                  "http://someurl.com/~myproject/index.html", None, 123, {}):
      with self.subTest(value=value):
        self.assertFalse(CustomConfigObject.has_path_prefix(value))

  def test_is_path_like(self):
    for value in ("foo/bar", "foo\\bar"):
      with self.subTest(value=value):
        self.assertFalse(CustomConfigObject.has_path_prefix(value))
        self.assertTrue(CustomConfigObject.is_path_like(value))
    for value in ("adb:foo/bar", "adb:foo\\bar:local", "http://foo/bar", None,
                  123, {}):
      with self.subTest(value=value):
        self.assertFalse(CustomConfigObject.has_path_prefix(value))
        self.assertFalse(CustomConfigObject.is_path_like(value))

  def test_is_hjson_like(self):
    for value in ("{}", " {}", " { foo: 2} "):
      with self.subTest(value=value):
        self.assertTrue(CustomConfigObject.is_hjson_like(value))
    for value in ("{", "2", " bar/foo{}asdf", None, 123, {}):
      with self.subTest(value=value):
        self.assertFalse(CustomConfigObject.is_hjson_like(value))

  def test_parse_invalid_str(self):
    invalid: Any
    for invalid in ("", None, 1, []):
      with self.assertRaises(argparse.ArgumentTypeError):
        CustomConfigObject.parse(invalid)

  def test_parse_dict_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse({})
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse({"name": "foo", "array": 1})
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse({"name": "foo", "name_alias": "foo"})
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse({"name": "foo", "array": [], "integer": "a"})
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse_dict({
          "name": "foo",
          "array": [],
          "integer": "a",
      })

  def test_parse_dict(self):
    config = CustomConfigObject.parse({"name": "foo"})
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "foo")
    config = CustomConfigObject.parse({"name": "foo", "array": []})
    self.assertEqual(config.name, "foo")
    self.assertSequenceEqual(config.array, [])
    data = {"name": "foo", "array": [1, 2, 3], "integer": 153}
    config = CustomConfigObject.parse(dict(data))
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "foo")
    assert config.array
    self.assertSequenceEqual(config.array, [1, 2, 3])
    self.assertEqual(config.integer, 153)
    config_2 = CustomConfigObject.parse_dict(dict(data))
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config, config_2)

  def test_load_dict_extra_kwargs(self):
    config = CustomConfigObject.parse({
        "name": "foo",
    }, array=[], integer=123)
    self.assertEqual(config.name, "foo")
    self.assertSequenceEqual(config.array, [])
    self.assertEqual(config.integer, 123)

  def test_load_dict_extra_kwargs_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse({
          "name": "foo",
      }, array=123, integer=[])
    self.assertIn("array", str(cm.exception))

  def test_load_dict_extra_kwargs_duplicate_invalid(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse({
          "name": "foo",
      }, name="bar")
    self.assertIn("name", str(cm.exception))

  def test_load_dict_extra_kwargs_duplicate(self):
    config = CustomConfigObject.parse({
        "name": "foo",
    }, name="foo", integer=123)
    self.assertEqual(config.name, "foo")
    self.assertEqual(config.integer, 123)
    config = CustomConfigObject.parse({
        "name": "foo",
    }, name=None, integer=999)
    self.assertEqual(config.name, "foo")
    self.assertEqual(config.integer, 999)

  def test_load_dict_unused(self):
    config_data = {"name": "foo", "unused_data": 666}
    config = CustomConfigObject.parse(config_data)
    self.assertTrue(config_data)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "foo")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObjectStrict.parse(config_data)
    self.assertIn("unused_data", str(cm.exception))
    self.assertTrue(config_data)

  def test_load_dict_unused_extra_kwargs(self):
    config_data = {"name": "foo", "unused_data": 666}
    config = CustomConfigObject.parse(config_data, other_unused=999)
    self.assertTrue(config_data)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "foo")
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObjectStrict.parse(config_data, other_unused=999)
    self.assertIn("unused_data", str(cm.exception))
    self.assertIn("other_unused", str(cm.exception))
    self.assertTrue(config_data)

  def test_load_dict_default(self):
    self.assertIsNone(CustomConfigObject.config_parser().default)
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse({})
    self.assertIsNone(CustomConfigObject.config_parser().default,
                      CustomConfigObjectWithDefault.default())
    config = CustomConfigObjectWithDefault.parse({})
    self.assertEqual(config, CustomConfigObjectWithDefault.default())

  def test_parse_dict_alias(self):
    config = CustomConfigObject.parse({"name_alias": "foo"})
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "foo")

  def test_parse_dict_custom_value_enum(self):
    config = CustomConfigObject.parse({"name_alias": "foo"})
    assert isinstance(config, CustomConfigObject)
    self.assertIs(config.custom_value_enum, CustomValueEnum.DEFAULT)
    for config_value, result in ((CustomValueEnum.A_OR_TRUE,
                                  CustomValueEnum.A_OR_TRUE),
                                 ("a", CustomValueEnum.A_OR_TRUE),
                                 (True, CustomValueEnum.A_OR_TRUE),
                                 (CustomValueEnum.B_OR_FALSE,
                                  CustomValueEnum.B_OR_FALSE),
                                 ("b", CustomValueEnum.B_OR_FALSE),
                                 (False, CustomValueEnum.B_OR_FALSE),
                                 ("default", CustomValueEnum.DEFAULT)):
      config = CustomConfigObject.parse({
          "name_alias": "foo",
          "custom_value_enum": config_value,
      })
      self.assertIs(config.custom_value_enum, result)

  def test_parse_dict_custom_value_enum_invalid(self):
    invalid: Any
    for invalid in (1, 2, {}, "A", "B"):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        CustomConfigObject.parse({
            "name_alias": "foo",
            "custom_value_enum": invalid,
        })
      self.assertIn(f"{invalid}", str(cm.exception))

  def test_parse_str(self):
    config = CustomConfigObject.parse("a name")
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "a name")

  def test_parse_path_missing_file_str(self):
    path = pathlib.Path("/invalid.file")
    self.assertFalse(path.exists())
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse(str(path))

  def test_parse_path_missing_file(self):
    path = pathlib.Path("/invalid.file")
    self.assertFalse(path.exists())
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse(path)

  def test_parse_path_missing_file_by_type(self):
    path = pathlib.Path("invalid.file")
    self.assertFalse(path.exists())
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse(path)

  def test_parse_path_empty_file(self):
    path = pathlib.Path("test_file.json")
    self.assertFalse(path.exists())
    path.touch()
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse(path)

  def test_parse_path_invalid_json_file(self):
    path = pathlib.Path("test_file.json")
    path.write_text("{{", encoding="utf-8")
    with self.assertRaises(argparse.ArgumentTypeError):
      CustomConfigObject.parse(path)

  def test_parse_path_empty_json_object(self):
    path = pathlib.Path("test_file.json")
    with path.open("w", encoding="utf-8") as f:
      json.dump({}, f)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse(path)
    self.assertIn("non-empty data", str(cm.exception))

  def test_parse_path_invalid_json_array(self):
    path = pathlib.Path("test_file.json")
    with path.open("w", encoding="utf-8") as f:
      json.dump([], f)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse(path)
    self.assertIn("non-empty data", str(cm.exception))

  def test_parse_path_minimal(self):
    path = pathlib.Path("test_file.json")
    with path.open("w", encoding="utf-8") as f:
      json.dump({"name": "Config Name"}, f)
    config = CustomConfigObject.parse(path)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "Config Name")
    self.assertIsNone(config.array)
    self.assertIsNone(config.integer)
    self.assertIsNone(config.nested)
    config_2 = CustomConfigObject.parse(str(path))
    self.assertEqual(config, config_2)

  TEST_DICT: immutabledict[str, Any] = immutabledict({
      "name": "Config Name",
      "array": [1, 3],
      "integer": 166,
  })

  def test_parse_path_full(self):
    path = pathlib.Path("test_file.json")
    with path.open("w", encoding="utf-8") as f:
      json.dump(dict(self.TEST_DICT), f)
    config = CustomConfigObject.parse(path)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "Config Name")
    assert config.array
    self.assertSequenceEqual(config.array, [1, 3])
    self.assertEqual(config.integer, 166)
    self.assertIsNone(config.nested)
    config_2 = CustomConfigObject.parse(str(path))
    self.assertEqual(config, config_2)

  def test_parse_dict_full(self):
    config = CustomConfigObject.parse_dict(dict(self.TEST_DICT))
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "Config Name")
    assert config.array
    self.assertSequenceEqual(config.array, [1, 3])
    self.assertEqual(config.integer, 166)
    self.assertIsNone(config.nested)

  TEST_DICT_NESTED: immutabledict[str, str] = immutabledict(
      {"name": "a nested name"})

  def test_parse_dict_nested(self):
    test_dict = dict(self.TEST_DICT)
    test_dict["nested"] = dict(self.TEST_DICT_NESTED)
    config = CustomConfigObject.parse_dict(test_dict)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.name, "Config Name")
    assert config.array
    self.assertSequenceEqual(config.array, [1, 3])
    self.assertEqual(config.integer, 166)
    self.assertEqual(config.nested,
                     CustomNestedConfigObject(name="a nested name"))

  def test_parse_dict_nested_file(self):
    path = pathlib.Path("nested.json")
    self.assertFalse(path.exists())
    with path.open("w", encoding="utf-8") as f:
      json.dump(dict(self.TEST_DICT_NESTED), f)
    test_dict = dict(self.TEST_DICT)
    test_dict["nested"] = str(path)
    config = CustomConfigObject.parse_dict(test_dict)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.nested,
                     CustomNestedConfigObject(name="a nested name"))

  def test_parse_nested_long(self):
    test_dict = dict(self.TEST_DICT)
    long_string = "abcd" * 1_000
    test_dict["nested"] = long_string
    config = CustomConfigObject.parse_dict(test_dict)
    assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.nested.name, long_string)

  def test_parse_nested_long_os_error(self):
    test_dict = dict(self.TEST_DICT)
    long_string = "abcd" * 100
    test_dict["nested"] = long_string

    def raise_os_error(self):
      raise OSError("Invalid file name")

    with mock.patch.object(pathlib.Path, "is_file", raise_os_error):
      config = CustomConfigObject.parse_dict(test_dict)
      assert isinstance(config, CustomConfigObject)
    self.assertEqual(config.nested.name, long_string)

  def test_parse_missing_depending(self):
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse({"name": "foo", "depending_nested": "a value"})
    self.assertIn("depending_nested", str(cm.exception))
    self.assertIn("Expected nested", str(cm.exception))
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse({
          "name": "foo",
          "depending_nested": "a value",
          "nested": None,
      })
    self.assertIn("depending_nested", str(cm.exception))
    self.assertIn("Expected nested", str(cm.exception))

  def test_parse_depending_simple(self):
    config = CustomConfigObject.parse({
        "name": "foo",
        "nested": "nested string value",
        "depending_nested": "a value",
    })
    self.assertDictEqual(config.depending_nested, {
        "value": "a value",
        "nested": config.nested,
    })

  def test_parse_generic_enum(self):
    test_dict = dict(self.TEST_DICT)
    test_dict["generic_enum"] = "b"
    config = CustomConfigObject.parse_dict(test_dict)
    self.assertIs(config.generic_enum, GenericEnum.B)
    test_dict = dict(self.TEST_DICT)
    test_dict["generic_enum"] = "c"
    config = CustomConfigObject.parse_dict(test_dict)
    self.assertIs(config.generic_enum, GenericEnum.C)

  def test_parse_generic_enum_invalid(self):
    test_dict = dict(self.TEST_DICT)
    test_dict["generic_enum"] = "unknown value"
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse_dict(test_dict)
    error_message = str(cm.exception).lower()
    self.assertIn("choices are", error_message)
    self.assertIn("generic_enum", error_message)

  def test_parse_config_enum(self):
    test_dict = dict(self.TEST_DICT)
    test_dict["config_enum"] = "b"
    config = CustomConfigObject.parse_dict(test_dict)
    self.assertIs(config.config_enum, CustomConfigEnum.B)
    test_dict = dict(self.TEST_DICT)
    test_dict["config_enum"] = "c"
    config = CustomConfigObject.parse_dict(test_dict)
    self.assertIs(config.config_enum, CustomConfigEnum.C)

  def test_parse_custom_enum_invalid(self):
    test_dict = dict(self.TEST_DICT)
    test_dict["config_enum"] = "unknown value"
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      CustomConfigObject.parse_dict(test_dict)
    error_message = str(cm.exception).lower()
    self.assertIn("choices are", error_message)
    self.assertIn("config_enum", error_message)

  def test_parse_templated_config_missing_arg_name_throws(self):
    config = {"template": {"name": "$[ARG]"}, "args": {"": ""}}

    with self.assertRaisesRegex(MultiException,
                                "Template args must only contain"):
      CustomConfigObject.parse(config)

  def test_parse_templated_config_lowercase_arg_name_throws(self):
    config = {"template": {"name": "$[arg]"}, "args": {"arg": "my name"}}

    with self.assertRaisesRegex(MultiException,
                                "Template args must only contain"):
      CustomConfigObject.parse(config)

  def test_parse_templated_config_space_beginning_arg_name_throws(self):
    config = {"template": {"name": "$[ ARG]"}, "args": {" ARG": "my name"}}

    with self.assertRaisesRegex(MultiException,
                                "Template args must only contain"):
      CustomConfigObject.parse(config)

  def test_parse_templated_config_space_end_arg_name_throws(self):
    config = {"template": {"name": "$[ARG ]"}, "args": {"ARG ": "my name"}}

    with self.assertRaisesRegex(MultiException,
                                "Template args must only contain"):
      CustomConfigObject.parse(config)

  def test_parse_templated_config_missing_arg_throws(self):
    config = {
        "template": {
            "name": "$[MISSING_ARG]",
        },
        "args": {
            "ARG": "arg_value",
        },
    }

    with self.assertRaisesRegex(MultiException, "MISSING_ARG"):
      config = CustomConfigObject.parse(config)

  def test_parse_templated_config_multiple_missing_args_throws(self):
    config = {
        "template": {
            "name": "$[MISSING_ARG] $[MISSING_ARG2]",
        },
        "args": {
            "ARG": "arg_value",
        },
    }

    with self.assertRaises(MultiException) as cm:
      CustomConfigObject.parse(config)
    self.assertIn("'MISSING_ARG'", str(cm.exception))
    self.assertIn("'MISSING_ARG2'", str(cm.exception))

  def test_parse_templated_config_unsupported_arg_throws(self):
    config = {
        "template": {
            "name": "text and $[DICT_ARG]",
        },
        "args": {
            "DICT_ARG": {
                "key": "value",
            },
        },
    }

    with self.assertRaisesRegex(argparse.ArgumentTypeError,
                                "can not be substituted"):
      CustomConfigObject.parse(config)

  def test_parse_templated_config_dict_arg(self):
    config = {
        "template": {
            "name": "top level",
            "nested": "$[ARG]",
        },
        "args": {
            "ARG": {
                "name": "nested",
            },
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.nested.name, "nested")

  def test_parse_templated_config_empty_arg(self):
    config = {"template": {"name": "$[ARG]"}, "args": {"ARG": ""}}

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "")

  def test_parse_templated_config_string_only(self):
    config = {"template": {"name": "$[ARG]"}, "args": {"ARG": "arg_value"}}

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "arg_value")

  def test_parse_templated_config_unused_arg(self):
    config = {
        "template": {
            "name": "$[ARG]",
        },
        "args": {
            "ARG": "arg_value",
            "UNUSED_ARG": "unused",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "arg_value")

  def test_parse_templated_config_string_multiple(self):
    config = {
        "template": {
            "name": "$[ONE]$[TWO]$[THREE]$[FOUR]",
        },
        "args": {
            "ONE": "1",
            "TWO": "2",
            "THREE": "3",
            "FOUR": "4",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "1234")

  def test_parse_templated_config_string_multiple_mixed(self):
    config = {
        "template": {
            "name": "[$[ONE]_$[TWO]_$[THREE]_$[FOUR]]",
        },
        "args": {
            "ONE": "1",
            "TWO": 2,
            "THREE": 3.0,
            "FOUR": 4.56,
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "[1_2_3.0_4.56]")

  def test_parse_templated_config_string_nested_matches(self):
    config = {
        "template": {
            "name": "$[$[$[ARG]]]",
        },
        "args": {
            "ARG": "ARG2",
            "ARG2": "ARG3",
            "ARG3": "the true arg",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "the true arg")

  def test_parse_template_full_string_substitute_finishes_substitution(self):
    config = {
        "template": {
            "name": "$[ARG]",
        },
        "args": {
            "ARG": "prefix$[ARG2]",
            "ARG2": "name",
        },
    }

    config = CustomConfigObject.parse(config)

    self.assertEqual(config.name, "prefixname")

  def test_parse_templated_config_int(self):
    config = {
        "template": {
            "name": "name",
            "integer": "$[ARG]",
        },
        "args": {
            "ARG": 4,
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.integer, 4)

  def test_parse_templated_config_float(self):
    config = {
        "template": {
            "name": "name",
            "float_field": "$[ARG]",
        },
        "args": {
            "ARG": 1.3,
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.float_field, 1.3)

  def test_parse_templated_config_filepath(self):
    template_path_str = "template_file.hjson"
    template = {
        "name": "$[ARG]",
    }

    path = pathlib.Path(template_path_str)
    with path.open("w", encoding="utf-8") as f:
      json.dump(template, f)

    args = {"template": template_path_str, "args": {"ARG": "arg_value"}}

    config = CustomConfigObject.parse(args)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "arg_value")

  def test_parse_templated_config_two_layer_filepath(self):
    nested_path_str = "nested.hjson"
    nested = {"name": "$[ARG]"}

    path = pathlib.Path(nested_path_str)
    with path.open("w", encoding="utf-8") as f:
      json.dump(nested, f)

    template_path_str = "template_file.hjson"
    template = {
        "name": "top level",
        "nested": nested_path_str,
    }

    path = pathlib.Path(template_path_str)
    with path.open("w", encoding="utf-8") as f:
      json.dump(template, f)

    args = {"template": template_path_str, "args": {"ARG": "arg_value"}}

    config = CustomConfigObject.parse(args)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.nested.name, "arg_value")

  def test_parse_templated_config_two_level_template(self):
    config = {
        "template": {
            "name": "$[TOP_LEVEL_ARG]",
            "nested": {
                "template": {
                    "name": "$[SECOND_LEVEL_ARG]",
                },
                "args": {
                    "SECOND_LEVEL_ARG": "second-level-name",
                },
            },
        },
        "args": {
            "TOP_LEVEL_ARG": "top-level-name",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "top-level-name")
    self.assertEqual(config.nested.name, "second-level-name")

  def test_parse_templated_config_two_level_template_files(self):
    nested_path_str = "nested.hjson"
    nested = {
        "template": {
            "name": "$[NESTED_NAME]",
        },
        "args": {
            "NESTED_NAME": "nested",
        },
    }

    path = pathlib.Path(nested_path_str)
    with path.open("w", encoding="utf-8") as f:
      json.dump(nested, f)

    config = {
        "template": {
            "name": "$[TOP_LEVEL_ARG]",
            "nested": nested_path_str,
        },
        "args": {
            "TOP_LEVEL_ARG": "top-level-name",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "top-level-name")
    self.assertEqual(config.nested.name, "nested")

  def test_parse_templated_config_single_escaped_value(self):
    config = {
        "template": {
            "name": "some text $[[ARG] on either side",
        },
        "args": {
            "PLACEHOLDER": "nothing",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "some text $[ARG] on either side")

  def test_parse_templated_config_nested_escaped_value(self):
    config = {
        "template": {
            "name": "$[[$[[ARG]]",
        },
        "args": {
            "PLACEHOLDER": "nothing",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "$[[$[ARG]]")

  def test_parse_templated_config_escaped_value_and_non_escaped(self):
    config = {
        "template": {
            "name": "$[[ARG] $[ARG]",
        },
        "args": {
            "ARG": "arg_value",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "$[ARG] arg_value")

  def test_parse_template_single_unbound_arg(self):
    config = {
        "template": {
            "name": "$[ARG]",
            "nested": {
                "template": {
                    "name": "$[ARG]",
                },
                "unbound_args": ["ARG"],
            },
        },
        "args": {
            "ARG": "from-top-level",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "from-top-level")
    self.assertEqual(config.nested.name, "from-top-level")

  def test_parse_template_multiple_unbound_arg(self):
    config = {
        "template": {
            "name": "$[ARG]",
            "nested": {
                "template": {
                    "name": "$[ARG] $[ARG2]",
                },
                "unbound_args": ["ARG", "ARG2"],
            },
        },
        "args": {
            "ARG": "hello",
            "ARG2": "world",
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.name, "hello")
    self.assertEqual(config.nested.name, "hello world")

  def test_parse_template_unbound_arg_undefined(self):
    config = {
        "template": {
            "name": "$[ARG]",
            "nested": {
                "template": {
                    "name": "$[NOT_AN_ARG]",
                },
                "unbound_args": ["NOT_AN_ARG"],
            },
        },
        "args": {
            "ARG": "hello",
        },
    }
    with self.assertRaisesRegex(MultiException, "'NOT_AN_ARG'"):
      config = CustomConfigObject.parse(config)

  def test_self_referencing_arg_throws(self):
    config = {
        "template": {
            "name": "$[ARG]",
        },
        "args": {
            "ARG": "some other $[ARG] text",
        },
    }
    with self.assertRaisesRegex(MultiException, "self-referencing"):
      config = CustomConfigObject.parse(config)

  def test_self_referencing_detection_escaped_arg(self):
    config = {
        "template": {
            "name": "$[ARG]",
        },
        "args": {
            "ARG": "some other $[[ARG] text",
        },
    }
    config = CustomConfigObject.parse(config)

  def test_self_referencing_detection_arg_name_no_arg_sequence(self):
    config = {
        "template": {
            "name": "$[ARG]",
        },
        "args": {
            "ARG": "some other arg text",
        },
    }
    config = CustomConfigObject.parse(config)

  def test_parse_nested_templated_config_urls(self):
    config = {
        "template": {
            "name": "name",
            "nested": "$[ARG]",
        },
        "args": {
            "ARG": {
                "name": "https://www.google.com",
            },
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)

    self.assertEqual(config.nested.name, "https://www.google.com")

  def test_parse_templated_config_filepaths_in_template_list(self):
    template_dir = pathlib.Path("/templates")
    template_dir.mkdir()
    (template_dir / "test_file").write_text("test file")
    template_path = template_dir / "template.hjson"
    template = {"name": "$[NAME]", "array": ["./test_file"]}

    with template_path.open("w", encoding="utf-8") as f:
      json.dump(template, f)

    config_dict = {"template": str(template_path), "args": {"NAME": "name"}}
    config = CustomConfigObject.parse(config_dict)
    self.assertIsInstance(config, CustomConfigObject)
    self.assertEqual(config.name, "name")
    self.assertEqual(config.array[0], "/templates/test_file")

  def test_parse_templated_config_relative_filepaths_as_str_preserved(self):
    config = {"template": "./templates/template.hjson", "args": {"UNUSED": ""}}
    config_file = pathlib.Path("/config.hjson")
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    template_dir = pathlib.Path("/templates")
    template_dir.mkdir()

    name_file = template_dir / "name.weird_extension"
    name_file.write_text("name")

    template_file = template_dir / "template.hjson"
    template = {"name": "./name.weird_extension"}
    template_file.write_text(json.dumps(template, indent=2), encoding="utf-8")

    config = CustomConfigObject.parse("/config.hjson")
    self.assertIsInstance(config, CustomConfigObject)
    self.assertEqual(config.name, "/templates/name.weird_extension")

  def test_template_list_spread_in_non_list_does_nothing(self):
    config = {
        "template": {
            "name": "$[...NAME]",
        },
        "args": {
            "NAME": ["my name"],
        },
    }
    config = CustomConfigObject.parse(config)
    self.assertEqual(config.name, "$[...NAME]")

  def test_template_list_spread_non_list_value_throws(self):
    config = {
        "template": {
            "array": ["some", "string", "values", "$[...ARG]"],
        },
        "args": {
            "ARG": "arg_value",
        },
    }
    with self.assertRaisesRegex(MultiException, "is not a list"):
      config = CustomConfigObject.parse(config)

  def test_template_list_spread_end(self):
    config = {
        "template": {
            "name": "name",
            "array": ["some", "string", "values", "$[...ARG]"],
        },
        "args": {
            "ARG": ["arg_value"],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertEqual(len(config.array), 4)
    self.assertEqual(config.array[3], "arg_value")

  def test_template_list_spread_beginning(self):
    config = {
        "template": {
            "name": "name",
            "array": [
                "$[...ARG]",
                "some",
                "string",
                "values",
            ],
        },
        "args": {
            "ARG": ["arg_value"],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertEqual(len(config.array), 4)
    self.assertEqual(config.array[0], "arg_value")

  def test_template_list_spread_middle(self):
    config = {
        "template": {
            "name": "name",
            "array": [
                "some",
                "string",
                "$[...ARG]",
                "values",
            ],
        },
        "args": {
            "ARG": ["arg_value"],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertEqual(len(config.array), 4)
    self.assertEqual(config.array[2], "arg_value")

  def test_template_list_spread_multiple_middle(self):
    config = {
        "template": {
            "name": "name",
            "array": [
                "some",
                "string",
                "$[...ARG]",
                "values",
            ],
        },
        "args": {
            "ARG": ["arg_value", "another arg value"],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertEqual(len(config.array), 5)
    self.assertEqual(config.array[2], "arg_value")
    self.assertEqual(config.array[3], "another arg value")

  def test_template_list_spread_multi_level_substitution(self):
    config = {
        "template": {
            "name": "name",
            "array": [
                "some",
                "string",
                "$[...ARG]",
                "values",
            ],
        },
        "args": {
            "ARG": {
                "template": ["$[ARG2]"],
                "args": {
                    "ARG2": "list entry",
                },
            },
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertEqual(len(config.array), 4)
    self.assertEqual(config.array[2], "list entry")

  def test_template_list_spread_empty_substitution(self):
    config = {
        "template": {
            "name": "name",
            "array": [
                "some",
                "string",
                "$[...ARG]",
                "values",
            ],
        },
        "args": {
            "ARG": [],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertSequenceEqual(config.array, ["some", "string", "values"])

  def test_parse_template_unbound_list_spread_arg(self):
    config = {
        "template": {
            "name": "name",
            "nested": {
                "template": {
                    "name": "name",
                    "array": [
                        "first",
                        "$[...ARG]",
                        "third",
                    ],
                },
                "unbound_args": ["ARG"],
            },
        },
        "args": {
            "ARG": ["second"],
        },
    }

    config = CustomConfigObject.parse(config)
    self.assertIsInstance(config, CustomConfigObject)
    self.assertSequenceEqual(config.nested.array, ["first", "second", "third"])


class ConfigEnumTestCase(unittest.TestCase):

  def test_parse_invalid(self):
    for invalid in ("", None):
      with self.assertRaises(argparse.ArgumentTypeError) as cm:
        CustomConfigEnum.parse(invalid)
      error_message = str(cm.exception)
      self.assertIn("Choices are", error_message)
      self.assertIn("CustomConfigEnum", error_message)

  def test_parse(self):
    for value, result in ((CustomConfigEnum.A,
                           CustomConfigEnum.A), ("a", CustomConfigEnum.A),
                          (CustomConfigEnum.B,
                           CustomConfigEnum.B), ("c", CustomConfigEnum.C)):
      self.assertIs(CustomConfigEnum.parse(value), result)


class ConfigRootDirTestCase(CrossbenchFakeFsTestCase):

  def test_root_dir_standard(self):
    with mock.patch("crossbench.config.__file__",
                    "/path/to/root/crossbench/config.py"):
      self.fs.create_file("/path/to/root/crossbench/config.py")
      self.assertEqual(str(root_dir()), "/path/to/root")

  def test_root_dir_flattened(self):
    with mock.patch("crossbench.config.__file__", "/path/to/root/config.py"):
      self.fs.create_file("/path/to/root/config.py")
      self.fs.create_dir("/path/to/root/config")
      self.assertEqual(str(root_dir()), "/path/to/root")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
