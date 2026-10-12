# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import dataclasses
import secrets
from typing import TYPE_CHECKING, Self, TypeVar

from typing_extensions import override

from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import NumberParser, ObjectParser

if TYPE_CHECKING:
  from crossbench.types import JsonDict

  SecretT = TypeVar("SecretT", bound="Secret")


class SecretsMergeError(ValueError):

  def __init__(self, name: str, primary: Secret, fallback: Secret) -> None:
    super().__init__(f"Conflicting {name} secrets: {primary} vs {fallback}")
    self.name = name
    self.primary = primary
    self.fallback = fallback


@dataclasses.dataclass(frozen=True)
class Secrets(ConfigObject):
  """A set of predefined secrets for common logins.
  """
  google: UsernamePassword | None = None
  bond: ServiceAccount | None = None
  google_workspace: GoogleWorkspaceSecrets | None = None

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("google", type=GoogleUsernamePassword)
    parser.add_argument("bond", type=ServiceAccount)
    parser.add_argument("google_workspace", type=GoogleWorkspaceSecrets)
    return parser

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise NotImplementedError("Cannot create secrets from string")

  def merge(self, fallback: Secrets, strict: bool = False) -> Self:
    return type(self)(
        self._merge_secret("Google", self.google, fallback.google, strict),
        self._merge_secret("Bond", self.bond, fallback.bond, strict),
        self._merge_secret("Google Workspace", self.google_workspace,
                           fallback.google_workspace, strict),
    )

  def _merge_secret(self, name: str, primary: SecretT | None,
                    fallback: SecretT | None, strict: bool) -> SecretT | None:
    if strict and primary and fallback and primary != fallback:
      raise SecretsMergeError(name, primary, fallback)
    return primary or fallback


class Secret(ConfigObject):
  """A single username / password combination. """

  @property
  def is_interactive(self) -> bool:
    return False


@dataclasses.dataclass(frozen=True)
class GoogleWorkspaceSecrets(Secret):
  service_account_key: ServiceAccount
  shared_drive_id: str

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "service_account_key", type=ServiceAccount, required=True)
    parser.add_argument(
        "shared_drive_id", type=ObjectParser.non_empty_str, required=True)
    return parser

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    raise NotImplementedError(
        "GoogleWorkspaceSecrets from string not supported")


@dataclasses.dataclass(frozen=True)
class UsernamePassword(Secret):
  username: str
  password: str

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "username",
        aliases=("user", "usr", "account", "account-name"),
        type=ObjectParser.non_empty_str,
        required=True)
    parser.add_argument(
        "password",
        aliases=("pass", "pw", "account-password"),
        type=ObjectParser.any_str,
        required=True)
    return parser

  @classmethod
  @override
  def parse_str(cls, value: str) -> UsernamePassword:
    if value == "interactive":
      return InteractiveUsernamePassword()
    # TODO: maybe support passwd style string format
    raise NotImplementedError("Cannot support")


@dataclasses.dataclass(frozen=True)
class InteractiveUsernamePassword(UsernamePassword):
  """Interactive secret that defers the input to the user so we can
  live test the login process. """
  username: str = dataclasses.field(default="", init=False)
  password: str = dataclasses.field(default="", init=False)

  @property
  @override
  def is_interactive(self) -> bool:
    return True


@dataclasses.dataclass(frozen=True)
class CycledUsernamePassword(UsernamePassword):
  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = super().config_parser()
    parser.add_argument(
        "use_range",
        aliases=("use-account-range", "enable-range"),
        type=ObjectParser.bool,
        default=False)
    parser.add_argument(
        "start",
        aliases=("account-range-start", "range-start"),
        type=NumberParser.positive_zero_int,
        default=0)
    parser.add_argument(
        "end",
        aliases=("account-range-end", "range-end"),
        type=NumberParser.positive_zero_int,
        default=0)
    return parser

  @classmethod
  @override
  def create(
      cls,
      username: str,
      password: str,
      use_range: bool = False,
      start: int = 0,
      end: int = 0,
  ) -> Self:
    if use_range:
      if end <= start:
        raise ValueError(
            f"CycledUsernamePassword 'end' boundary ({end}) must be "
            f"strictly greater than 'start' ({start}) when 'use_range' "
            "is enabled.")

      account_selection = secrets.randbelow(end - start) + start
      username = username % account_selection

    return cls(username=username, password=password)


@dataclasses.dataclass(frozen=True)
class GoogleUsernamePassword(CycledUsernamePassword):
  pass


@dataclasses.dataclass(frozen=True)
class ServiceAccount(Secret):
  type: str
  project_id: str
  private_key_id: str
  private_key: str
  client_email: str
  client_id: str
  auth_uri: str
  token_uri: str
  auth_provider_x509_cert_url: str
  client_x509_cert_url: str
  universe_domain: str

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls)
    parser.add_argument("type", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "project_id", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "private_key_id", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "private_key", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "client_email", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "client_id", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "auth_uri", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "token_uri", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "auth_provider_x509_cert_url",
        type=ObjectParser.non_empty_str,
        required=True)
    parser.add_argument(
        "client_x509_cert_url", type=ObjectParser.non_empty_str, required=True)
    parser.add_argument(
        "universe_domain", type=ObjectParser.non_empty_str, required=True)
    return parser

  @classmethod
  @override
  def parse_str(cls, value: str) -> Self:
    del value
    raise NotImplementedError("ServiceAccount from string not supported")

  def to_json(self) -> JsonDict:
    return {
        "type": self.type,
        "project_id": self.project_id,
        "private_key_id": self.private_key_id,
        "private_key": self.private_key,
        "client_email": self.client_email,
        "client_id": self.client_id,
        "auth_uri": self.auth_uri,
        "token_uri": self.token_uri,
        "auth_provider_x509_cert_url": self.auth_provider_x509_cert_url,
        "client_x509_cert_url": self.client_x509_cert_url,
        "universe_domain": self.universe_domain,
    }
