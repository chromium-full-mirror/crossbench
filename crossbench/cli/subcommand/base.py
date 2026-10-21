# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, ClassVar, Final, Sequence

from crossbench.cli.parser import CBArgumentParser, CBNamespace

if TYPE_CHECKING:
  import argparse

  from crossbench.cli.cli import CrossBenchCLI
  from crossbench.cli.types import Subparsers


class CrossbenchSubcommand(abc.ABC):

  NAME: ClassVar[str] = ""

  def __init__(self, cli: CrossBenchCLI) -> None:
    self._cli: Final[CrossBenchCLI] = cli
    self._parser: argparse.ArgumentParser | None = None
    self._parser_populated = False

  def init_cli_parser(self) -> None:
    if not self._parser_populated:
      self.add_cli_arguments(self.parser)
      self._parser_populated = True

  def set_fast_mode_defaults(self, argv: Sequence[str]) -> None:
    pass

  @property
  def cli(self) -> CrossBenchCLI:
    return self._cli

  @property
  def parser(self) -> CBArgumentParser:
    assert self._parser is not None, "Parser not registered"
    assert isinstance(self._parser, CBArgumentParser)
    return self._parser

  @abc.abstractmethod
  def register_subcommand(self,
                          subparsers: Subparsers) -> argparse.ArgumentParser:
    pass

  @abc.abstractmethod
  def add_cli_arguments(self, parser: CBArgumentParser) -> CBArgumentParser:
    pass

  @abc.abstractmethod
  def run(self, args: CBNamespace) -> None:
    pass

  def error(self, message: str) -> None:
    self.cli.error(message)

  def fail(self, message: str) -> None:
    self.parser.error(message)
