# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import dataclasses
import enum
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, ClassVar, Final, TypeAlias

from immutabledict import immutabledict
from typing_extensions import Self, override

from crossbench import path as pth
from crossbench.config import ConfigEnum, ConfigError, ConfigObject
from crossbench.helper.class_helper import get_all_subclasses

if TYPE_CHECKING:
  from crossbench.plt.base import Platform

DeviceConfigValue: TypeAlias = (
    str | int | float | Sequence["DeviceConfigValue"]
    | Mapping[str, "DeviceConfigValue"])
DeviceConfigMap: TypeAlias = Mapping[str, DeviceConfigValue]
DeviceConfigFile: TypeAlias = pth.LocalPath
DeviceConfig: TypeAlias = DeviceConfigMap | DeviceConfigFile
DeviceConfigKeyPath: TypeAlias = tuple[str, ...]
# A parsed requirement and its target value, as DeviceConfigRequirement holds.
_PredicateAndTarget: TypeAlias = tuple["_Predicate", str | None]

# Operator keys, such as "$regex", start with this prefix. Device
# configuration keys never do, so the two cannot collide.
_OPERATOR_PREFIX = "$"

# Names the value to write when a requirement is not met. It may accompany
# any operator form, rather than being one of them.
_TARGET_KEY = "$target"


@dataclasses.dataclass(frozen=True)
class DeviceConfigDiscrepancy:
  """Represents a device configuration discrepancy."""
  key_path: DeviceConfigKeyPath
  expectation: str
  actual: DeviceConfigValue | None

  def __str__(self) -> str:
    path_str = ".".join(self.key_path)
    if self.actual is None:
      issue = "value was absent"
    else:
      issue = f"got {self.actual!r}"
    return f"{path_str}: {issue}, expected {self.expectation}."


@dataclasses.dataclass(frozen=True)
class DeviceConfigRequirement:
  """A predicate and its target, bound to a key in the configuration tree.

  Attributes:
    key_path: The key of the setting in the configuration tree.
    predicate: The condition the setting's value must meet.
    target: The value to write so that this requirement is met, or None.
      None means the value is not to be set, e.g. a regex without "$target":
      the requirement is only checked. Otherwise the target is written as
      is, except for "null", which deletes the setting. "" is a real value,
      written as an empty string, and is distinct from an absent setting.
  """
  key_path: DeviceConfigKeyPath
  predicate: _Predicate
  target: str | None

  @classmethod
  def parse(cls, key_path: DeviceConfigKeyPath,
            value: DeviceConfigValue) -> Self:
    """Parses a leaf value, annotating parse errors with its key path."""
    try:
      predicate, target = _Predicate.parse(value)
    except ValueError as e:
      raise DeviceConfigError(f"{'.'.join(key_path)}: {e}") from e
    return cls(key_path, predicate, target)

  def check(
      self,
      actual: DeviceConfigValue | None,
  ) -> DeviceConfigDiscrepancy | None:
    """Returns a discrepancy if the actual value fails the predicate."""
    if self.predicate.matches(actual):
      return None
    return DeviceConfigDiscrepancy(self.key_path, self.predicate.expected_str(),
                                   actual)


# The immutable, parsed requirements of a single platform.
DeviceConfigRequirements: TypeAlias = tuple[DeviceConfigRequirement, ...]


@enum.unique
class RequiredDeviceConfigMode(ConfigEnum):
  THROW = ("throw", "Raise an error and abort on discrepancies.")
  WARN = ("warn", "Log discrepancies as critical warnings and continue.")
  SET = ("set", "Set failing values to their targets for the run, "
         "then restore the original values.")


class DeviceConfigValueError(ValueError):
  """Raised when the device does not meet its config requirements."""


class DeviceConfigError(ConfigError):
  """Raised on malformed device config requirements."""


@dataclasses.dataclass(frozen=True)
class RequiredDeviceConfig(ConfigObject):
  """The parsed device config requirements of all platforms.

  Parsed from an inline mapping or from an hjson file holding one. Top-level
  keys name platforms and are lower-cased; their values are the requirement
  sections. Nested keys are passed through verbatim, as device settings are
  case-sensitive.

  Attributes:
    platforms: The requirements of each platform, by lower-cased name.
  """
  platforms: immutabledict[str, DeviceConfigRequirements]

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise DeviceConfigError(f"Invalid device config: {value!r}.")

  @classmethod
  @override
  def parse_dict(cls, config: dict[str, object], **kwargs) -> Self:
    cls.expect_no_extra_kwargs(kwargs)
    platforms: dict[str, DeviceConfigRequirements] = {}
    for platform, section in config.items():
      if not isinstance(section, Mapping):
        raise DeviceConfigError(f"{platform}: Invalid section: {section!r}.")
      platforms[platform.lower()] = _parse_platform_requirements(section)
    return cls(immutabledict(platforms))


def _parse_platform_requirements(
    config: DeviceConfigMap) -> DeviceConfigRequirements:
  """Parses one platform's requirement section.

  Intermediate nodes must be nested mappings, with an empty mapping denoting
  a section that imposes no requirements. Leaf nodes specify expectations and
  can be one of:
  - Exact string: "expected_val" (or "null" for an absent setting).
    A number matches numerically, e.g. 1.0 matches "1", as HJSON reads
    1.0 as 1.
  - Disjunction list: [item1, item2, ...] matching if any item matches.
  - Mapping:
      - {"$regex": "pattern"}: matches the actual value in full.
      - {"$min": "1", "$max": "9"}: a numeric range, with at least one bound.
    Keys starting with '$' are operators: a mapping containing any of them
    is a requirement rather than a section.

  Each requirement may have a target, the value that meets it:
  - An exact value is its own target, with "null" denoting deletion. A
    number targets its string form.
  - A disjunction list takes the target of its first item, if any.
  - A mapping has a target only if it names one explicitly, via "$target"
    beside its operators, e.g. {"$min": "1", "$target": "5"}. The target
    must meet the requirement it accompanies, and may be a number too.

  Raises:
    DeviceConfigError: If any requirement is malformed.
  """
  return tuple(_iter_device_config(config))


def check_device_config(
    required: DeviceConfigRequirements,
    actual: DeviceConfigMap,
    mode: RequiredDeviceConfigMode,
) -> None:
  """Compares a device config against requirements, logging or raising.

  Args:
    required:
      The parsed requirements for the platform under test.
    actual:
      The actual hierarchical device configuration dictionary.
    mode:
      The action to take on discrepancies (throw or warn). Callers handle
      SET themselves.
  """
  assert not _has_reserved_keys(actual), "Unexpected $ in device config."

  if not (discrepancies := _compare_device_config(required, actual)):
    return

  msg = _format_discrepancies(discrepancies)
  match mode:
    case RequiredDeviceConfigMode.WARN:
      logging.critical("%s", msg)
    case RequiredDeviceConfigMode.THROW:
      msg = (f"{msg}\nUse --required-device-config-mode=warn to bypass.\n"
             "Use --required-device-config-mode=set to set the values "
             "for the run.")
      raise DeviceConfigValueError(msg)
    case _:
      msg = f"Unhandled device config mode: {mode!r}.\n{msg}"
      raise DeviceConfigValueError(msg)


def _has_reserved_keys(config: DeviceConfigMap) -> bool:
  """Returns whether any config key is reserved for operator syntax.

  Device configurations are expected to have none. A requirement naming
  such a key would be parsed as an operator instead, leaving the setting
  unreachable.
  """
  return any(
      key.startswith(_OPERATOR_PREFIX) or
      (isinstance(value, Mapping) and _has_reserved_keys(value))
      for key, value in config.items())


def _format_discrepancies(discrepancies: list[DeviceConfigDiscrepancy]) -> str:
  items = "\n".join(f"  - {discrepancy}" for discrepancy in discrepancies)
  return f"Device config discrepancies:\n{items}"


def _compare_device_config(
    required: DeviceConfigRequirements,
    actual: DeviceConfigMap,
) -> list[DeviceConfigDiscrepancy]:
  """Compares actual config against requirements and returns discrepancies."""
  discrepancies: list[DeviceConfigDiscrepancy] = []
  for requirement in required:
    actual_value = _get_device_config_value(actual, requirement.key_path)
    if discrepancy := requirement.check(actual_value):
      discrepancies.append(discrepancy)
  return discrepancies


def _get_device_config_value(
    config: DeviceConfigMap,
    key_path: DeviceConfigKeyPath,
) -> DeviceConfigValue | None:
  """Retrieves the value at key_path, or None if absent or unreachable."""
  current: DeviceConfigValue | None = config
  for key in key_path:
    if not isinstance(current, Mapping):
      return None
    current = current.get(key)
  return current


class DeviceConfigSetter:
  """Sets a platform's device config to meet requirements, until restored.

  Only requirements that the device fails are written. Each successful
  write is recorded with the value it replaced, so that restore() can put
  it back.
  """

  def __init__(self, platform: Platform,
               requirements: DeviceConfigRequirements) -> None:
    self._platform: Final[Platform] = platform
    self._requirements: Final[DeviceConfigRequirements] = requirements
    # Discrepancies fixed by a write; restore() writes back their actual
    # values.
    self._changed: Final[list[DeviceConfigDiscrepancy]] = []

  def apply(self) -> None:
    """Writes the target of every failing requirement, then checks them all.

    Changes made before a failure are not undone; call restore() for that.

    Raises:
      DeviceConfigValueError: If any requirement is still unmet afterwards.
      Exception: Any error from writing to the platform.
    """
    actual = self._read_device_config()
    for requirement in self._requirements:
      self._apply_requirement(requirement, actual)
    # Not check_device_config(), whose error suggests using SET mode.
    if discrepancies := _compare_device_config(self._requirements,
                                               self._read_device_config()):
      raise DeviceConfigValueError(_format_discrepancies(discrepancies))

  def _apply_requirement(self, requirement: DeviceConfigRequirement,
                         actual: DeviceConfigMap) -> None:
    if requirement.target is None:
      return
    original = _get_device_config_value(actual, requirement.key_path)
    if not (discrepancy := requirement.check(original)):
      return
    target = _written_value(requirement.target)
    logging.info("Setting device config %s %r -> %r.",
                 ".".join(requirement.key_path), original, target)
    self._platform.set_device_config_value(requirement.key_path, target)
    self._changed.append(discrepancy)

  def restore(self) -> list[str]:
    """Restores all changes made, in reverse order, best effort.

    Each change is restored at most once, so calling this again does
    nothing. A failure to restore one change does not stop the others.

    Failures are returned rather than raised, as callers often restore
    while another exception is already propagating, which raising would
    mask.

    Returns:
      A description of each failure to restore, which is also logged.
    """
    failures: list[str] = []
    while self._changed:
      if failure := self._restore_change(self._changed.pop()):
        failures.append(failure)
    return failures

  def _restore_change(self, discrepancy: DeviceConfigDiscrepancy) -> str | None:
    """Writes back the value a change replaced, returning any failure."""
    path_str = ".".join(discrepancy.key_path)
    original = discrepancy.actual
    assert original is None or isinstance(original, str)
    logging.info("Restoring device config %s to %r", path_str, original)
    try:
      self._platform.set_device_config_value(discrepancy.key_path, original)
    except Exception as e:
      logging.exception("Failed to restore device config %s", path_str)
      return f"{path_str}: {e}"
    return None

  def _read_device_config(self) -> DeviceConfigMap:
    """Reads the device config, relative to the platform's namespace."""
    return self._platform.device_config().get(self._platform.name, {})


def _iter_device_config(
    config: DeviceConfigMap,
    prefix: DeviceConfigKeyPath = (),
) -> Iterator[DeviceConfigRequirement]:
  """Yields the leaf requirements of a hierarchical config.

  Leaf keys may contain delimiters (such as 'namespace/key' for Android
  device_config or 'ro.build.version' for getprop) and are treated as atomic
  leaf keys within their parent section.
  """
  for key, value in config.items():
    key_path = (*prefix, key)
    if isinstance(value, Mapping):
      # A mapping holding an operator key is a requirement. Any other
      # mapping is a subsection; an empty one imposes no requirements.
      has_operator = any(k.startswith(_OPERATOR_PREFIX) for k in value)
      if not has_operator:
        yield from _iter_device_config(value, key_path)
        continue
    yield DeviceConfigRequirement.parse(key_path, value)


def _written_value(target: str) -> str | None:
  """Returns the value a target leaves on the device, None if deleted."""
  return None if target == "null" else target


def _is_number(value: object) -> bool:
  """Returns True for an int or float, but not for a bool."""
  return isinstance(value, int | float) and not isinstance(value, bool)


class _Predicate(abc.ABC):
  """Abstract predicate for validating a device configuration value."""

  @staticmethod
  def parse(value: DeviceConfigValue) -> _PredicateAndTarget:
    """Parses a leaf configuration into a predicate and its target value.

    See DeviceConfigRequirement.target.

    Raises:
      ValueError: If the value is not a valid leaf configuration.
    """
    match value:
      case str():
        return _ValuePredicate.parse_str(value)
      case int() | float() if _is_number(value):
        return _NumericRangePredicate(value, value), str(value)
      case Mapping():
        return _MappingPredicate.parse_mapping(value)
      # Strings and bytes are sequences, but are not requirement lists.
      case Sequence() if not isinstance(value, (str, bytes)):
        return _AnyOfPredicate.parse_sequence(value)
      case _:
        raise ValueError(f"Invalid config: {value!r}.")

  @abc.abstractmethod
  def matches(self, actual: DeviceConfigValue | None) -> bool:
    """Returns True if the actual value matches the predicate condition."""

  @abc.abstractmethod
  def expected_str(self) -> str:
    """Returns a string describing the expected requirement."""


@dataclasses.dataclass(frozen=True)
class _ValuePredicate(_Predicate):
  """Matches an exact string value, or absent/None if expected is 'null'."""
  expected: str

  @classmethod
  def parse_str(cls, value: str) -> _PredicateAndTarget:
    """Parses an exact value, which is its own target."""
    return cls(value), value

  @override
  def matches(self, actual: DeviceConfigValue | None) -> bool:
    if actual is None:
      return self.expected == "null"
    return actual == self.expected

  @override
  def expected_str(self) -> str:
    return repr(self.expected)


class _MappingPredicate(_Predicate):
  """Predicate parsable from a mapping of operator keys it declares."""

  KEYS: ClassVar[tuple[str, ...]]

  @staticmethod
  def parse_mapping(mapping: DeviceConfigMap) -> _PredicateAndTarget:
    """Parses a mapping leaf into a predicate and its "$target", if any."""
    if not mapping:
      raise ValueError("Invalid empty configuration mapping.")
    assert None not in mapping.values()
    operators = {k: v for k, v in mapping.items() if k != _TARGET_KEY}
    assert operators
    predicate = _MappingPredicate._parse_operators(operators)
    target = mapping.get(_TARGET_KEY)
    if _is_number(target):
      target = str(target)
    assert isinstance(target, str | None)
    assert target is None or predicate.matches(_written_value(target))
    return predicate, target

  @staticmethod
  def _parse_operators(operators: DeviceConfigMap) -> _Predicate:
    keys = list(operators.keys())
    present = frozenset(keys)
    for predicate in _MAPPING_PREDICATES:
      if present.issubset(predicate.KEYS):
        return predicate.from_mapping(operators)
    raise ValueError(f"Invalid config: unknown or conflicting keys {keys!r}.")

  @classmethod
  @abc.abstractmethod
  def from_mapping(cls, mapping: DeviceConfigMap) -> Self:
    """Parses a mapping whose keys this predicate owns."""


@dataclasses.dataclass(frozen=True)
class _RegexPredicate(_MappingPredicate):
  """Matches if the actual value matches a regular expression pattern."""
  KEYS = ("$regex",)

  pattern: re.Pattern[str]

  @classmethod
  @override
  def from_mapping(cls, mapping: DeviceConfigMap) -> Self:
    raw_regex = mapping.get("$regex")
    if not isinstance(raw_regex, str):
      raise ValueError(f"Invalid $regex: expected str, got {raw_regex!r}.")
    try:
      pattern = re.compile(raw_regex)
    except re.error as e:
      raise ValueError(f"Invalid $regex: {raw_regex!r} ({e}).") from e
    return cls(pattern)

  @override
  def matches(self, actual: DeviceConfigValue | None) -> bool:
    return isinstance(actual, str) and bool(self.pattern.fullmatch(actual))

  @override
  def expected_str(self) -> str:
    return f"a full match for pattern '{self.pattern.pattern}'"


@dataclasses.dataclass(frozen=True)
class _NumericRangePredicate(_MappingPredicate):
  """Matches if the actual value is a number within [min, max]."""
  KEYS = ("$min", "$max")

  min: float | None = None
  max: float | None = None

  def __post_init__(self) -> None:
    assert self.min is not None or self.max is not None
    if self.min is not None and self.max is not None and self.min > self.max:
      raise ValueError(f"$min ({self.min}) cannot exceed $max ({self.max}).")

  @classmethod
  @override
  def from_mapping(cls, mapping: DeviceConfigMap) -> Self:
    min_val = mapping.get("$min")
    max_val = mapping.get("$max")
    return cls(
        float(str(min_val)) if min_val is not None else None,
        float(str(max_val)) if max_val is not None else None,
    )

  @override
  def matches(self, actual: DeviceConfigValue | None) -> bool:
    if not isinstance(actual, str):
      return False
    try:
      value = float(actual)
    except ValueError:
      return False  # Could be 'auto' or some other allowed key word.
    return ((self.min is None or value >= self.min) and
            (self.max is None or value <= self.max))

  @override
  def expected_str(self) -> str:
    if self.min == self.max:
      return f"numeric value {self.min}"
    if self.min is not None and self.max is not None:
      return f"numeric value between {self.min} and {self.max}"
    if self.min is not None:
      return f"numeric value >= {self.min}"
    assert self.max is not None
    return f"numeric value <= {self.max}"


@dataclasses.dataclass(frozen=True)
class _AnyOfPredicate(_Predicate):
  """Matches if any of the sub-predicates match."""
  predicates: tuple[_Predicate, ...]

  @classmethod
  def parse_sequence(
      cls,
      sequence: Sequence[DeviceConfigValue],
  ) -> _PredicateAndTarget:
    """Parses a list of alternatives, taking the first one's target."""
    if not sequence:
      raise ValueError(f"Invalid empty requirement list: {sequence!r}.")
    predicates, targets = zip(*map(_Predicate.parse, sequence), strict=True)
    # The first alternative's target is assumed to be the canonical one.
    return cls(predicates), targets[0]

  @override
  def matches(self, actual: DeviceConfigValue | None) -> bool:
    return any(p.matches(actual) for p in self.predicates)

  @override
  def expected_str(self) -> str:
    options = ", ".join(p.expected_str() for p in self.predicates)
    return f"any of ({options})"


_MAPPING_PREDICATES: tuple[type[_MappingPredicate], ...] = (
    _RegexPredicate,
    _NumericRangePredicate,
)
assert set(_MAPPING_PREDICATES) == get_all_subclasses(_MappingPredicate), (
    "Every mapping predicate must be listed.")
_MAPPING_KEYS = [key for p in _MAPPING_PREDICATES for key in p.KEYS]
assert all(key.startswith(_OPERATOR_PREFIX) for key in _MAPPING_KEYS)
assert _TARGET_KEY not in _MAPPING_KEYS, "$target accompanies any form."
# Disjoint keys guarantee that at most one predicate matches, regardless of
# the order of _MAPPING_PREDICATES.
assert len(_MAPPING_KEYS) == len(set(_MAPPING_KEYS)), "Overlapping keys."
