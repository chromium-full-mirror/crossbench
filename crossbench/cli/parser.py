# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import types
from typing import TYPE_CHECKING, Any, Mapping, Never, Sequence

import colorama
from typing_extensions import Self, override

from crossbench.cli.ui import ui
from crossbench.parse import ObjectParser

if TYPE_CHECKING:
  from crossbench.types import JsonDict


class CBArgumentGroup(argparse._ArgumentGroup):  # noqa: SLF001

  @override
  def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
    CBArgumentParser.validate_add_argument(self, args, kwargs)
    return super().add_argument(*args, **kwargs)

  @override
  def add_mutually_exclusive_group(self,
                                   **kwargs: Any) -> CBMutuallyExclusiveGroup:
    group = CBMutuallyExclusiveGroup(self, **kwargs)
    self._mutually_exclusive_groups.append(group)
    return group


class CBMutuallyExclusiveGroup(
    argparse._MutuallyExclusiveGroup,  # noqa: SLF001
):

  @override
  def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
    CBArgumentParser.validate_add_argument(self, args, kwargs)
    return super().add_argument(*args, **kwargs)


@dataclasses.dataclass(frozen=True)
class ArgumentHelp:
  name: str
  aliases: tuple[str, ...]
  help: str
  required: bool = False
  default: object | None = None
  choices: tuple[object, ...] | None = None

  @classmethod
  def from_action(cls, action: argparse.Action) -> ArgumentHelp:
    if action.option_strings:
      name = action.option_strings[0]
      aliases = tuple(action.option_strings[1:])
    else:
      name = action.dest
      aliases = ()
    choices = tuple(action.choices) if action.choices else None
    default = None
    if action.default not in (None, argparse.SUPPRESS):
      default = action.default
    return cls(
        name=name,
        aliases=aliases,
        help=(action.help or "").strip(),
        required=action.required,
        default=default,
        choices=choices,
    )

  def to_json(self) -> JsonDict:
    choices = [str(c) for c in self.choices] if self.choices else None
    default = str(self.default) if self.default is not None else None
    return {
        "name": self.name,
        "aliases": list(self.aliases),
        "help": self.help,
        "required": self.required,
        "default": default,
        "choices": choices,
    }


@dataclasses.dataclass(frozen=True)
class ArgumentGroupHelp:
  """Helper to extract and format argparse argument groups and arguments.

  We use this helper to wrap around private members of argparse, as argparse
  does not expose public APIs for group introspection:
  - `argparse.ArgumentParser._action_groups`: action groups on the parser.
  - `argparse._ArgumentGroup._group_actions`: actions belonging to a group.
  - `argparse._HelpAction`: default help action class.
  """
  name: str
  description: str
  arguments: tuple[ArgumentHelp, ...]

  @classmethod
  def from_action_group(
      cls,
      group: argparse._ArgumentGroup,  # noqa: SLF001
      default_title: str | None = None) -> ArgumentGroupHelp:
    actions = [
        action for action in group._group_actions  # noqa: SLF001
        if not cls.is_help_action(action)
    ]
    arguments = tuple(ArgumentHelp.from_action(action) for action in actions)
    title = cls._extract_group_title(group, default_title)
    return cls(
        name=title,
        description=(group.description or "").strip(),
        arguments=arguments,
    )

  @classmethod
  def _extract_group_title(
      cls,
      group: argparse._ArgumentGroup,  # noqa: SLF001
      default_title: str | None = None) -> str:
    if default_title:
      if not group.title:
        return default_title
      if group.title == "options":
        return default_title
    return group.title or "Options"

  @classmethod
  def from_parser(cls,
                  parser: argparse.ArgumentParser,
                  default_title: str | None = None) -> list[ArgumentGroupHelp]:
    groups: list[ArgumentGroupHelp] = []
    for group in parser._action_groups:  # noqa: SLF001
      group_help = cls.from_action_group(group, default_title=default_title)
      if group_help.arguments:
        groups.append(group_help)
    return groups

  @classmethod
  def is_help_action(cls, action: argparse.Action) -> bool:
    return isinstance(
        action, argparse._HelpAction) or action.dest == "help"  # noqa: SLF001

  def to_json(self) -> JsonDict:
    return {
        "name": self.name,
        "description": self.description,
        "arguments": [arg.to_json() for arg in self.arguments],
    }


class CBNamespace(argparse.Namespace):
  """Namespace that can be frozen in-place to prevent mutations after setup."""

  _is_frozen: bool

  def __init__(self, **kwargs: object) -> None:
    # Avoid AttributeError in __setattr__ before _is_frozen is set.
    super().__setattr__("_is_frozen", False)
    super().__init__(**kwargs)

  def freeze(self) -> Self:
    if self._is_frozen:
      return self
    for value in vars(self).values():
      if isinstance(value, CBNamespace):
        value.freeze()
    self._is_frozen = True
    return self

  def __setattr__(self, name: str, value: object) -> None:
    if self._is_frozen:
      raise TypeError(f"Cannot modify immutable {type(self).__name__}: "
                      f"attempted to set {name}={value!r}")
    super().__setattr__(name, value)

  def __delattr__(self, name: str) -> None:
    if self._is_frozen:
      raise TypeError(f"Cannot delete attribute {name!r} from immutable "
                      f"{type(self).__name__}")
    super().__delattr__(name)


class CBArgumentParser(argparse.ArgumentParser):
  """Disables flag abbreviation and exit-on-error, and emits CBNamespace."""

  def __init__(self, **kwargs) -> None:
    kwargs["exit_on_error"] = False
    allow_abbrev = kwargs.pop("allow_abbrev", False)
    super().__init__(allow_abbrev=allow_abbrev, **kwargs)

  @classmethod
  def validate_add_argument(cls, container: object, args: Sequence[object],
                            kwargs: Mapping[str, object]) -> None:
    arg_name: str = (f"'{'/'.join(str(a) for a in args)}'"
                     if args else "argument")
    container_name: str = type(container).__name__
    cls._validate_add_argument_type(container_name, arg_name, kwargs)
    cls._validate_add_argument_action(container_name, arg_name, kwargs)

  @classmethod
  def _validate_add_argument_type(cls, container_name: str, arg_name: str,
                                  kwargs: Mapping[str, object]) -> None:
    arg_type = kwargs.get("type")
    if arg_type is None:
      return
    if (isinstance(arg_type, types.FunctionType) and
        arg_type.__name__ == "<lambda>"):
      raise ValueError(
          f"Raw lambda parsers are forbidden for {arg_name} in "
          f"{container_name}. Define a reusable helper in crossbench.parse "
          "or use a ConfigObject.")
    if arg_type not in (bool, str, int, float, list, dict, set, tuple):
      return
    assert isinstance(arg_type, type)
    prefix = (f"Direct use of type={arg_type.__name__} is forbidden for "
              f"{arg_name} in {container_name}:")
    if arg_type is bool:
      raise ValueError(
          f"{prefix} bool('False') evaluates to True. Use "
          "action='store_true', action='store_false', action='store_const', "
          "or type=ObjectParser.bool instead.")
    if arg_type is str:
      raise ValueError(
          f"{prefix} argparse arguments are strings by default; "
          "use ObjectParser.non_empty_str or ObjectParser.any_str if string "
          "validation is needed.")
    if arg_type is int:
      raise ValueError(f"{prefix} use NumberParser.* (e.g. "
                       "NumberParser.positive_int, NumberParser.port_number, "
                       "NumberParser.any_int) instead.")
    if arg_type is float:
      raise ValueError(
          f"{prefix} use NumberParser.* (e.g. "
          "NumberParser.positive_float, NumberParser.positive_zero_float, "
          "NumberParser.any_float) instead.")
    raise ValueError(
        f"{prefix} use a dedicated parser from crossbench.parse or a "
        "ConfigObject.")

  @classmethod
  def _validate_add_argument_action(cls, container_name: str, arg_name: str,
                                    kwargs: Mapping[str, object]) -> None:
    action = kwargs.get("action")
    default = kwargs.get("default")
    arg_type = kwargs.get("type")

    match action:
      case "store":
        if isinstance(default, bool):
          raise ValueError(
              f"Invalid action='store' with boolean default={default!r} for "
              f"{arg_name} in {container_name}. Use action='store_true' or "
              "action='store_false' (or type=ObjectParser.bool) instead.")
        raise ValueError(
            f"Redundant action='store' for {arg_name} in {container_name}. "
            "'store' is the default action in argparse.")
      case None:
        if isinstance(default, bool) and arg_type != ObjectParser.bool:
          raise ValueError(
              f"Boolean default without boolean action or type for "
              f"{arg_name} in {container_name}. Use action='store_true', "
              "action='store_false', action='store_const', or "
              "type=ObjectParser.bool.")
      case "store_true":
        if default is True:
          raise ValueError(
              f"action='store_true' with default=True for {arg_name} in "
              f"{container_name} is invalid (flag can never be set to False). "
              "Use action='store_false' or default=False instead.")
      case "store_false":
        if default is False:
          raise ValueError(
              f"action='store_false' with default=False for {arg_name} in "
              f"{container_name} is invalid (flag can never be set to True). "
              "Use action='store_true' or default=True instead.")
      case "append" | "append_const" | "extend":
        if (default is not None and default is not argparse.SUPPRESS and
            not isinstance(default, list)):
          raise ValueError(
              f"Invalid non-appendable default={default!r} for "
              f"action={action!r} in {arg_name} for {container_name}. "
              "Expected list or None.")

  @override
  def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
    self.validate_add_argument(self, args, kwargs)
    return super().add_argument(*args, **kwargs)

  @override
  def add_argument_group(self, *args: Any, **kwargs: Any) -> CBArgumentGroup:
    group = CBArgumentGroup(self, *args, **kwargs)
    self._action_groups.append(group)
    return group

  @override
  def add_mutually_exclusive_group(self,
                                   **kwargs: Any) -> CBMutuallyExclusiveGroup:
    group = CBMutuallyExclusiveGroup(self, **kwargs)
    self._mutually_exclusive_groups.append(group)
    return group

  @override
  def parse_known_args(  # type: ignore[override]
      self,
      args: Sequence[str] | None = None,
      namespace: argparse.Namespace
      | None = None,
  ) -> tuple[CBNamespace, list[str]]:
    if namespace is None:
      namespace = CBNamespace()
    parsed_namespace, unprocessed = super().parse_known_args(
        args=args, namespace=namespace)
    assert isinstance(parsed_namespace, CBNamespace)
    return parsed_namespace, unprocessed

  @override
  def parse_args(  # type: ignore[override]
      self,
      args: Sequence[str] | None = None,
      namespace: argparse.Namespace | None = None,
  ) -> CBNamespace:
    if namespace is None:
      namespace = CBNamespace()
    parsed_namespace = super().parse_args(args=args, namespace=namespace)
    assert isinstance(parsed_namespace, CBNamespace)
    return parsed_namespace

  def fail(self, message: str) -> None:
    super().error(message)

  def exit(self, status: int = 0, message: str | None = None) -> Never:
    if message:
      if status == 0:
        logging.info(message)
      else:
        # Hack to get red colored output
        if ui.COLOR_LOGGING:
          print(str(colorama.Fore.RED))
        logging.critical(message)
        if ui.COLOR_LOGGING:
          print(str(colorama.Style.RESET_ALL))
    sys.exit(status)
