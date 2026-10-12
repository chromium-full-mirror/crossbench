# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

import platformdirs

from crossbench import path as pth
from crossbench.config import ConfigObject, ConfigParser
from crossbench.parse import ObjectParser
from crossbench.pinpoint.helper import annotate

if TYPE_CHECKING:
  from crossbench.types import JsonDict


class Settings:
  """Manages user settings for Pinpoint CLI."""

  _instance: Settings | None = None

  def __new__(cls) -> Settings:  # noqa: PYI034
    if cls._instance is None:
      cls._instance = super().__new__(cls)
      cls._instance._private_init()  # noqa: SLF001
    return cls._instance

  def _private_init(self) -> None:
    if self.path().exists():
      self._config = _SettingsConfig.parse(self.path())
    else:
      self._config = _SettingsConfig()
    self._dirty = False

  @property
  def user_id(self) -> str | None:
    return self._config.user_id

  @user_id.setter
  def user_id(self, value: str | None) -> None:
    self._update_dirty(self._config.user_id, value)
    self._config = replace(self._config, user_id=value)

  @property
  def collect_metrics(self) -> bool | None:
    return self._config.collect_metrics

  @collect_metrics.setter
  def collect_metrics(self, value: bool | None) -> None:
    self._update_dirty(self._config.collect_metrics, value)
    self._config = replace(self._config, collect_metrics=value)

  def _update_dirty(self, before: object, after: object) -> None:
    self._dirty = before != after or self._dirty

  def to_dict(self) -> JsonDict:
    return self._config.to_dict()

  def save(self) -> None:
    if not self._dirty:
      return
    with annotate("Saving settings"):
      self.path().parent.mkdir(parents=True, exist_ok=True)
      with self.path().open("w") as f:
        json.dump(self.to_dict(), f, indent=2)
    self._dirty = False

  @classmethod
  def path(cls) -> pth.LocalPath:
    config_dir = pth.LocalPath(platformdirs.user_config_dir("pinpointcli"))
    return config_dir / "settings.json"


@dataclass(frozen=True)
class _SettingsConfig(ConfigObject):
  """Configuration of user settings for Pinpoint CLI."""

  user_id: str | None = None
  collect_metrics: bool | None = None

  @classmethod
  def config_parser(cls) -> ConfigParser[_SettingsConfig]:
    parser = ConfigParser(cls)
    parser.add_argument(
        "user_id",
        type=str,
        required=False,
        help="Random user ID used to collect metrics.")
    parser.add_argument(
        "collect_metrics",
        type=ObjectParser.bool,
        required=False,
        help=(
            "Boolean flag indicating whether user metrics should be collected."
        ),
    )
    return parser

  @classmethod
  def parse_str(cls, value: str) -> _SettingsConfig:
    raise NotImplementedError

  def to_dict(self) -> JsonDict:
    return asdict(self)
