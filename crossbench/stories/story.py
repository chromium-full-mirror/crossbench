# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import datetime as dt
import logging
from typing import TYPE_CHECKING, Final, Iterable

from crossbench import path as pth
from crossbench.cli.config.secrets import Secrets

if TYPE_CHECKING:
  from crossbench.runner.run import Run
  from crossbench.types import JsonDict, StoryTagLookupT


class Story(abc.ABC):

  @classmethod
  @abc.abstractmethod
  def all_story_names(cls) -> tuple[str, ...]:
    pass

  @classmethod
  def default_story_names(cls) -> tuple[str, ...]:
    """Override this method to use a subset of all_story_names as default
    selection if no story names are provided."""
    return tuple(cls.all_story_names())

  @classmethod
  def all_tags_lookup(cls) -> StoryTagLookupT:
    return {}

  @classmethod
  def all_tags(cls) -> tuple[str, ...]:
    tags: set[str] = set()
    for story_tags in cls.all_tags_lookup().values():
      tags.update(story_tags)
    return tuple(sorted(tags))

  @classmethod
  def verify_story_name(cls, name: str) -> None:
    if not name:
      raise ValueError("Invalid story name: story name cannot be empty.")
    if name.startswith(("-", "#")):
      raise ValueError(
          f"Invalid story name: cannot start with '-' or '#': {name!r}")

  def __init__(
      self,
      name: str,
      duration: dt.timedelta = dt.timedelta(seconds=15),
      secrets: Secrets | None = None,
      tags: Iterable[str] = (),
  ) -> None:
    self.verify_story_name(name)
    self._name: str = pth.safe_filename(name)
    self._duration: Final[dt.timedelta] = duration
    self._secrets: Final[Secrets] = secrets or Secrets()
    self._tags: Final[frozenset[str]] = frozenset(tags)
    if self._duration:
      assert self._duration.total_seconds() > 0, (
          f"Duration must be non-empty, but got: {duration}")

  @property
  def name(self) -> str:
    return self._name

  @property
  def tags(self) -> frozenset[str]:
    return self._tags

  @property
  def substories(self) -> tuple[str, ...]:
    return (self.name,)

  @property
  def duration(self) -> dt.timedelta:
    return self._duration

  @property
  def secrets(self) -> Secrets:
    return self._secrets

  def details_json(self) -> JsonDict:
    return {
        "name": self.name,
        "tags": tuple(self.tags),
        "duration": self.duration.total_seconds(),
    }

  def log_run_details(self, run: Run) -> None:
    logging.info("📚 STORY:                    %s", self)
    timing = run.timing
    logging.info("⏳ STORY DURATION:           expected=%s timeout=%s",
                 timing.timedelta(self.duration),
                 timing.timeout_timedelta(self.duration))

  def setup(self, run: Run) -> None:
    """Setup work for a story that is not part of the main workload should
    be put in this method. Probes can skip measuring this section.
    i.e selecting substories to run.
    """

  @abc.abstractmethod
  def run(self, run: Run) -> None:
    """The main workload of a story that is measured by all Probes.
    """

  def teardown(self, run: Run) -> None:
    """Cleanup work for a story that is not part of the main workload should
    be put in this method. Probes can skip measuring this section.
    """

  def __str__(self) -> str:
    return f"Story(name={self.name})"

  def help(self) -> str:
    return self.name
