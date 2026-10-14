# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, relationship

__all__ = (
    "Session",
    "relationship",
    "DeclarativeBase",
    "Mapped",
    "mapped_column",
)

if TYPE_CHECKING:
  from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
else:
  # Try importing SQLAlchemy 2.0+ features.
  try:
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
  except ImportError:
    # Fallback for SQLAlchemy 1.4 compatibility (e.g. in Google3).
    from sqlalchemy import Column
    from sqlalchemy.ext.declarative import declarative_base
    DeclarativeBase = declarative_base()
    Mapped = Any

    def mapped_column(*args: Any, **kwargs: Any) -> Any:
      return Column(*args, **kwargs)
