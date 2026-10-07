# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import Iterable, Mapping, MutableMapping, Sequence, TypeAlias, \
    Union

from immutabledict import immutabledict

Json: TypeAlias = Union["JsonMapping", "JsonSequence", str, int, float, bool,
                        None]
JsonMapping: TypeAlias = Mapping[str, Json]
JsonMutableMapping: TypeAlias = MutableMapping[str, Json]
JsonDict: TypeAlias = dict[str, Json]
ImmutableJsonDict: TypeAlias = immutabledict[str, Json]
JsonSequence: TypeAlias = Sequence[Json]
JsonList: TypeAlias = list[Json]
JsonTuple: TypeAlias = tuple[Json, ...]
StoryTagLookupT: TypeAlias = Mapping[str, Iterable[str]]
