# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum

from crossbench.str_enum_with_help import StrEnumWithHelp


@enum.unique
class CleanupMode(StrEnumWithHelp):

  @classmethod
  def _missing_(cls, value: object) -> CleanupMode | None:
    if value is True:
      return CleanupMode.ALWAYS
    if value is False:
      return CleanupMode.NEVER
    return super()._missing_(value)

  ALWAYS = ("always", "Always clean up temp files")
  AUTO = ("auto", "Best-guess auto-cleanup")
  NEVER = ("never", "Never clean up temp files")


@enum.unique
class TargetMode(StrEnumWithHelp):
  AUTO = ("auto", "Automatically choose the best option based on the platform")
  RENDERER_MAIN_ONLY = ("renderer_main_only",
                        "Profile Renderer Main thread only")
  RENDERER_PROCESS_ONLY = ("renderer_process_only",
                           "Profile Renderer process only")
  BROWSER_APP_ONLY = ("browser_app_only",
                      "Profile all processes of the Browser App only")
  SYSTEM_WIDE = ("system_wide", "Run system-wide profiling")


@enum.unique
class CallGraphMode(StrEnumWithHelp):
  # Refer to the documentation below for more details and comparison
  # between these options:
  # https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/README.md.
  NO_CALL_GRAPH = ("no_call_graph", "Do not record a call graph")
  DWARF = ("dwarf", "Run DWARF-based unwinding")
  FRAME_POINTER = ("fp", "Run frame pointer unwinding")


@enum.unique
class PprofMode(StrEnumWithHelp):
  """Execution mode for corp pprof profile symbolization and upload."""

  @classmethod
  def _missing_(cls, value: object) -> PprofMode | None:
    if value is True:
      return PprofMode.ALWAYS
    if value is False:
      return PprofMode.NEVER
    return super()._missing_(value)

  ALWAYS = ("always", "Always run corp pprof")
  AUTO = ("auto", "Run corp pprof if available")
  NEVER = ("never", "Do not run corp pprof")


@enum.unique
class TraceconvMode(StrEnumWithHelp):
  """Execution mode for local traceconv profile conversion."""

  @classmethod
  def _missing_(cls, value: object) -> TraceconvMode | None:
    if value is True:
      return TraceconvMode.ALWAYS
    if value is False:
      return TraceconvMode.NEVER
    return super()._missing_(value)

  ALWAYS = ("always", "Always run traceconv")
  AUTO = ("auto", "Run traceconv if available")
  NEVER = ("never", "Do not run traceconv")
