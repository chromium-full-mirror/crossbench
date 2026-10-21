# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Final, Mapping

from typing_extensions import override

if TYPE_CHECKING:
  import datetime as dt

  from crossbench import path as pth
  from crossbench.plt.base import Platform
  from crossbench.plt.signals import Signals
  from crossbench.plt.types import CmdArg, ListCmdArgs, ProcessIo


class RemotePlatformMixin:

  def __init__(self, host_platform: Platform) -> None:
    self._host_platform: Final[Platform] = host_platform
    super().__init__()

  @property
  def is_remote(self) -> bool:
    return True

  @property
  def host_platform(self) -> Platform:
    return self._host_platform

  def host_path(self, path: pth.AnyPathLike) -> pth.LocalPath:
    return self._host_platform.local_path(path)

  def sleep(self, seconds: float | dt.timedelta) -> None:
    self._host_platform.sleep(seconds)

  def build_shell_cmd(self,
                      *args: CmdArg,
                      shell: bool = False,
                      env: Mapping[str, str] | None = None,
                      cwd: pth.AnyPath | None = None) -> ListCmdArgs:
    raise NotImplementedError


class RemotePopen(subprocess.Popen):
  """
  A wrapper class to represent a process running on a remote platform.

  Allows to send signals to the remote process and gracefully wait for its
  termination.
  """

  def __init__(self,
               platform: Platform,
               args: ListCmdArgs,
               bufsize: int = -1,
               stdout: ProcessIo = None,
               stderr: ProcessIo = None,
               stdin: ProcessIo = None) -> None:
    self._platform: Final[Platform] = platform
    assert self._platform.is_remote, (
        f"Cannot create remote process on local platform {self._platform}")
    self._remote_pid: int | None = None
    super().__init__(
        args, bufsize=bufsize, stdout=stdout, stderr=stderr, stdin=stdin)

  def set_remote_pid(self, pid: int) -> None:
    assert self._remote_pid is None, "Should not set remote PID twice"
    self._remote_pid = pid

  @property
  def remote_pid(self) -> int:
    assert self._remote_pid, "remote process has no PID"
    return self._remote_pid

  @override
  def send_signal(self, sig: int | Signals) -> None:
    sig = self._platform.signals(sig)
    self._platform.send_signal(self.remote_pid, sig)

  @override
  def terminate(self) -> None:
    self._platform.terminate(self.remote_pid)

  @override
  def kill(self) -> None:
    self._platform.kill(self.remote_pid)
