# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import contextlib
import logging
import re
import sys
import traceback as tb
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Iterator, Self

from ordered_set import OrderedSet

from crossbench.helper import collection_helper, txt_helper

if TYPE_CHECKING:
  from types import TracebackType

  from crossbench import path as pth
  from crossbench.types import JsonList

TInfoStack = tuple[str, ...]

TExceptionTypes = tuple[type[BaseException], ...]

TExceptionId = int

_TRACEBACK_SOURCE_POSITION_RE = re.compile(r'  File "([^"]+)", line (\d+)')


@dataclass
class Entry:
  traceback: list[str]
  exception: BaseException
  info_stack: TInfoStack

  def __hash__(self) -> int:
    return hash((str(self.exception), self.info_stack))

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Entry):
      return False
    return str(self.exception) == str(
        other.exception) and self.info_stack == other.info_stack


class MultiException(ValueError):
  """Default exception thrown by ExceptionAnnotator.assert_success.
  It holds on to the ExceptionAnnotator and its previously captured exceptions
  are automatically added to active ExceptionAnnotator in an
  ExceptionAnnotationScope."""

  def __init__(self, message: str, exceptions: ExceptionAnnotator) -> None:
    super().__init__(message)
    self.exceptions: Final[ExceptionAnnotator] = exceptions

  def __len__(self) -> int:
    return len(self.exceptions)

  def matching(self, *args: type[BaseException]) -> list[BaseException]:
    return self.exceptions.matching(*args)

  @property
  def annotator(self) -> ExceptionAnnotator:
    return self.exceptions


class ExceptionAnnotationScope:
  """Used in a with-scope to annotate exceptions with a TInfoStack.

  Used via the capture/annotate/info helper methods on
  ExceptionAnnotator.
  """

  def __init__(
      self,
      annotator: ExceptionAnnotator,
      exception_types: TExceptionTypes,
      ignore_exception_types: TExceptionTypes,
      entries: tuple[str, ...],
      throw_cls: type[BaseException] | None = None,
  ) -> None:
    logging.debug("EAS: %s%s", "  " * annotator.depth, " ".join(entries))
    self._annotator: Final[ExceptionAnnotator] = annotator
    self._exception_types: Final[TExceptionTypes] = exception_types
    self._ignore_exception_types: Final[TExceptionTypes] = (
        *ignore_exception_types, StopIteration, GeneratorExit,
        StopAsyncIteration)
    self._added_info_stack_entries: Final[tuple[str, ...]] = entries
    self._throw_cls: Final[type[BaseException] | None] = throw_cls
    self._previous_info_stack: TInfoStack = ()

  def __enter__(self) -> Self:
    self._previous_info_stack = self._annotator.enter(
        self._added_info_stack_entries)
    return self

  def __exit__(self, exception_type: type[BaseException] | None,
               exception_value: BaseException | None,
               traceback: TracebackType | None) -> bool:
    if not exception_value or not exception_type:
      self._annotator.leave(self._previous_info_stack)
      # False => exception not handled
      return False
    if issubclass(exception_type, self._ignore_exception_types) and (
        not issubclass(exception_type, MultiException)):
      self._annotator.leave(self._previous_info_stack)
      # False => exception not handled, directly forward
      return False
    logging.debug("Intermediate Exception: %s:%s", exception_type,
                  exception_value)
    if self._exception_types and exception_type and (
        issubclass(exception_type, MultiException) or
        issubclass(exception_type, self._exception_types)):
      # Handle matching exceptions directly here and prevent further
      # exception handling by returning True.
      self._annotator.append(exception_value)
      self._annotator.leave(self._previous_info_stack)
      if self._throw_cls:
        self._annotator.assert_success(exception_cls=self._throw_cls)
      return True
    self._annotator.leave_pending(exception_value, self._previous_info_stack)
    # False => exception not handled
    return False


class ExceptionAnnotator:
  """Collects exceptions with full backtraces and user-provided info stacks.

  Additional stack information is constructed from active
  ExceptionAnnotationScopes.
  """

  def __init__(self,
               throw: bool = False,
               throw_cls: type[BaseException] | None = None) -> None:
    self._exceptions: OrderedSet[Entry] = OrderedSet()
    self.throw: Final[bool] = throw
    self._throw_cls: Final[type[BaseException] | None] = throw_cls
    # The info_stack adds additional meta information to handle exceptions.
    # Unlike the source-based backtrace, this can contain dynamic information
    # for easier debugging.
    self._info_stack: TInfoStack = ()
    # Associates raised exception with the info_stack at that time for later
    # use in the `handle` method.
    # This is cleared whenever we enter a  new ExceptionAnnotationScope.
    self._pending_exceptions: dict[TExceptionId, TInfoStack] = {}
    self._depth = 0

  @property
  def is_success(self) -> bool:
    return len(self._exceptions) == 0

  @property
  def info_stack(self) -> TInfoStack:
    return self._info_stack

  @property
  def exceptions(self) -> list[Entry]:
    return list(self._exceptions)

  @property
  def depth(self) -> int:
    return self._depth

  def __getitem__(self, key: int) -> Entry:
    return self._exceptions[key]

  def __len__(self) -> int:
    return len(self._exceptions)

  def __iter__(self) -> Iterator[Entry]:
    return iter(self._exceptions)

  def enter(self, added_info_stack_entries: tuple[str, ...]) -> tuple[str, ...]:
    self._depth += 1
    self._pending_exceptions.clear()
    previous_stack = self._info_stack
    self._info_stack = previous_stack + added_info_stack_entries
    return previous_stack

  def leave(self, previous_stack: tuple[str, ...]) -> None:
    self._depth -= 1
    self._info_stack = previous_stack

  def leave_pending(self, exception_value: BaseException,
                    previous_stack: tuple[str, ...]) -> None:
    # Certain FFI/interop exception types (e.g. pyodide.ffi.JsException)
    # do not implement __hash__ and cannot be stored as dictionary keys.
    # We use id() to work around that.
    exc_id = id(exception_value)
    if exc_id not in self._pending_exceptions:
      self._pending_exceptions[exc_id] = self.info_stack
    self._info_stack = previous_stack

  def matching(self, *args: type[BaseException]) -> list[BaseException]:
    result = []
    for entry in self._exceptions:
      exception = entry.exception
      if isinstance(exception, *args):
        result.append(exception)
    return result

  def assert_success(
      self,
      message: str | None = None,
      exception_cls: type[BaseException] = MultiException,
  ) -> None:
    if self.is_success:
      return
    if message is None:
      message = "{}"
    message = message.format(self)
    if issubclass(exception_cls, MultiException):
      exception = exception_cls(message, self)
      raise exception
    raise exception_cls(message)

  def info(self, *stack_entries: str) -> ExceptionAnnotationScope:
    """Only sets info stack entries, exceptions are passed-through."""
    return ExceptionAnnotationScope(self, (), (), stack_entries)

  def capture(
      self,
      *stack_entries: str,
      exceptions: TExceptionTypes = (Exception,),
      ignore: TExceptionTypes = (),
  ) -> ExceptionAnnotationScope:
    """Sets info stack entries and captures exceptions.
    - Does not rethrow captured exceptions
    - Does not directly throw a MultiExceptions, unless assert_success()
      is called. """
    return ExceptionAnnotationScope(self, exceptions, ignore, stack_entries,
                                    self._throw_cls)

  @contextlib.contextmanager
  def annotate(
      self,
      *stack_entries,
      exceptions: TExceptionTypes = (Exception,),
      ignore: TExceptionTypes = (),
  ) -> Iterator[Self]:
    """Sets info stack entries and rethrows an annotated
      MultiException by default ."""
    with self.capture(*stack_entries, exceptions=exceptions, ignore=ignore):
      yield self
    self.assert_success()

  def extend(self,
             annotator: ExceptionAnnotator,
             is_nested: bool = False) -> None:
    if is_nested:
      self._extend_with_prepended_stack_info(annotator)
    else:
      self._exceptions.update(annotator.exceptions)

  def _extend_with_prepended_stack_info(self,
                                        annotator: ExceptionAnnotator) -> None:
    if annotator == self:
      return
    for entry in annotator.exceptions:
      merged_info_stack = self.info_stack + entry.info_stack
      merged_entry = Entry(entry.traceback, entry.exception, merged_info_stack)
      self._exceptions.add(merged_entry)

  def append(self, exception: BaseException) -> None:
    traceback_str = tb.format_exc()
    logging.debug("Intermediate Exception %s:%s", type(exception), exception)
    logging.debug(traceback_str)
    traceback: list[str] = traceback_str.splitlines()
    if isinstance(exception, KeyboardInterrupt):
      # Fast exit on KeyboardInterrupts for a better user experience.
      sys.exit(0)
    if isinstance(exception, MultiException):
      # Directly add exceptions from nested annotators.
      self.extend(exception.exceptions, is_nested=True)
    else:
      stack = self._pending_exceptions.get(id(exception), self.info_stack)
      self._exceptions.add(Entry(traceback, exception, stack))
    if self.throw:
      raise  # noqa: PLE0704

  def log(self, message: str, separator: str = "=") -> None:
    if self.is_success:
      return
    logging.error(separator * 80)
    if len(self._exceptions) == 1:
      logging.error("%s:", message)
    else:
      logging.error("%s (1/%d):", message, len(self._exceptions))
    logging.error(separator * 80)
    for entry in self._exceptions:
      logging.debug(entry.exception)
      logging.debug("\n".join(entry.traceback))
      logging.debug("-" * 80)
    is_first_entry = True
    for info_stack, entries in self.grouped_entries().items():
      logging_level = logging.ERROR if is_first_entry else logging.DEBUG
      is_first_entry = False
      if info_stack:
        logging.log(logging_level, self.format_info_stack(info_stack))
      for entry in entries:
        for log_line in self.format_log_entry(entry):
          logging.log(logging_level, log_line)
        logging_level = logging.DEBUG
      logging.log(logging_level, "-" * 80)

  def grouped_entries(self) -> dict[TInfoStack, list[Entry]]:
    return collection_helper.group_by(
        self._exceptions, key=lambda entry: entry.info_stack, sort_key=None)

  def write_txt(self, txt_path: pth.LocalPath) -> pth.LocalPath | None:
    if self.is_success:
      return None
    with txt_path.open("w", encoding="utf-8") as f:
      f.write("=" * 80 + "\n")
      f.write(f"ERRORS: {len(self._exceptions)}\n")
      f.write("=" * 80 + "\n")
      for info_stack, entries in self.grouped_entries().items():
        if info_stack:
          f.write(self.format_info_stack(info_stack) + "\n")
        for entry in entries:
          for log_line in self.format_log_entry(entry):
            f.write(log_line)
            f.write("\n")
          f.write("Traceback:\n")
          f.write("\n".join(entry.traceback) + "\n")
        f.write("-" * 80 + "\n")
    return txt_path

  def format_log_entry(self, entry: Entry) -> tuple[str, ...]:
    return (
        "- " * 40,
        f"Type: {txt_helper.type_name(type(entry.exception))}:",
        f"      {self.format_exception(entry)}",
    )

  def format_info_stack(self, info_stack: TInfoStack) -> str:
    info = "Info: "
    joiner = "\n" + (" " * (len(info) - 2)) + "> "
    return f"{info}{joiner.join(info_stack)}"

  def error_messages(self) -> list[str]:
    return [self.format_exception(entry) for entry in self._exceptions]

  def to_json(self) -> JsonList:
    return [{
        "info_stack": entry.info_stack,
        "type": txt_helper.type_name(type(entry.exception)),
        "title": self.format_exception(entry),
        "trace": entry.traceback,
    } for entry in self._exceptions]

  def format_exception(self, entry: Entry) -> str:
    if isinstance(entry.exception, AssertionError):
      return self.format_assertion_error(entry)
    if msg := str(entry.exception).strip():
      return msg
    return entry.traceback[-2].strip()

  def format_assertion_error(self, entry: Entry) -> str:
    msg = str(entry.exception).strip()
    source_position = ""
    for line in reversed(entry.traceback):
      if match := _TRACEBACK_SOURCE_POSITION_RE.search(line):
        file_path, line_no = match.groups()
        file_name = file_path.split("/")[-1]
        source_position = f"{file_name}:{line_no}"
        break
    if source_position:
      return f"{msg} in {source_position}"
    return msg

  def __str__(self) -> str:
    if len(self._exceptions) == 1:
      entry = self._exceptions[0]
      stack = "\n\t".join(entry.info_stack)
      return f"{stack}: {entry.exception}"

    return "\n".join(
        f"{entry.info_stack}: {entry.exception}" for entry in self._exceptions)


# Expose simpler name
Annotator = ExceptionAnnotator


def annotate(
    *stack_entries: str,
    exceptions: TExceptionTypes = (Exception,),
    ignore: TExceptionTypes = (),
    throw_cls: type[BaseException] | None = MultiException,
) -> ExceptionAnnotationScope:
  """Use to annotate an exception.
  By default this will throw a MultiException which can keep track of
  more annotations."""
  return ExceptionAnnotator(throw_cls=throw_cls).capture(
      *stack_entries, exceptions=exceptions, ignore=ignore)


class ArgumentTypeMultiException(MultiException, argparse.ArgumentTypeError):
  pass


def annotate_argparsing(
    *stack_entries: str,
    exceptions: TExceptionTypes = (Exception,),
) -> ExceptionAnnotationScope:
  """Use this to annotate argument parsing-related code blocks to get more
  readable annotated exception back.
  - Wraps multiple exception in an ArgumentTypeMultiException
  - Single ArgumentTypeError are raised directly
  """
  return annotate(
      *stack_entries,
      exceptions=exceptions,
      throw_cls=ArgumentTypeMultiException)


class UnreachableError(RuntimeError):
  """Used for making checker tools happy in places where it's not directly
  obvious that we always return, for instance due to using one of the above
  exception annotations that could in theory mute exceptions and create an
  additional return path.
  """

  def __init__(self) -> None:
    super().__init__("Unreachable Code")
