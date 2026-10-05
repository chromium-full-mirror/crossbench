# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Iterable, Sequence

from perfetto.batch_trace_processor.api import BatchTraceProcessorConfig
from perfetto.trace_processor.api import TraceProcessorConfig

from crossbench.probes.trace_processor.constants import MODULES_DIR

if TYPE_CHECKING:
  from perfetto.batch_trace_processor.api import FailureHandling
  from perfetto.trace_uri_resolver.registry import ResolverRegistry

  from crossbench import path as pth


def CBTraceProcessorConfig(  # noqa: N802
    bin_path: pth.LocalPath | str | None = None,
    module_paths: Iterable[pth.LocalPath | str] | None = None,
    extra_flags: Sequence[str] | None = None,
    verbose: bool = False,
    enable_dev_features: bool = False,
    resolver_registry: ResolverRegistry | None = None,
    load_timeout: int = 10,
    ingest_ftrace_in_raw: bool = True,
) -> TraceProcessorConfig:
  """TraceProcessorConfig preconfigured with Crossbench SQL modules."""
  packages: list[str] = [os.fspath(MODULES_DIR)]
  for path in module_paths or ():
    fspath = os.fspath(path)
    if fspath not in packages:
      packages.append(fspath)

  return TraceProcessorConfig(
      bin_path=os.fspath(bin_path) if bin_path else None,
      verbose=verbose,
      enable_dev_features=enable_dev_features,
      resolver_registry=resolver_registry,
      load_timeout=load_timeout,
      ingest_ftrace_in_raw=ingest_ftrace_in_raw,
      extra_flags=list(extra_flags) if extra_flags else None,
      add_sql_packages=packages,
  )


def CBBatchTraceProcessorConfig(  # noqa: N802
    tp_config: TraceProcessorConfig | None = None,
    bin_path: pth.LocalPath | str | None = None,
    module_paths: Iterable[pth.LocalPath | str] | None = None,
    extra_flags: Sequence[str] | None = None,
    load_failure_handling: FailureHandling | None = None,
    execute_failure_handling: FailureHandling | None = None,
    **kwargs,
) -> BatchTraceProcessorConfig:
  """BatchTraceProcessorConfig preconfigured with Crossbench SQL modules."""
  if tp_config is not None:
    conflicting = []
    if bin_path is not None:
      conflicting.append("bin_path")
    if module_paths is not None:
      conflicting.append("module_paths")
    if extra_flags is not None:
      conflicting.append("extra_flags")
    if kwargs:
      conflicting.extend(sorted(kwargs.keys()))
    if conflicting:
      names = ", ".join(conflicting)
      raise ValueError(f"Cannot specify {names} when tp_config is provided")
  else:
    tp_config = CBTraceProcessorConfig(
        bin_path=bin_path,
        module_paths=module_paths,
        extra_flags=extra_flags,
        **kwargs)
  btp_kwargs = {}
  if load_failure_handling is not None:
    btp_kwargs["load_failure_handling"] = load_failure_handling
  if execute_failure_handling is not None:
    btp_kwargs["execute_failure_handling"] = execute_failure_handling
  return BatchTraceProcessorConfig(tp_config=tp_config, **btp_kwargs)
