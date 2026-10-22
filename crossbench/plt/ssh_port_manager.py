# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from crossbench.plt.port_manager import SubprocessPortManager
from crossbench.plt.ssh import SshPlatformMixin

if TYPE_CHECKING:
  import subprocess

  from crossbench.plt.base import Platform
  from crossbench.plt.types import CmdArg, ListCmdArgs


class SshPortManager(SubprocessPortManager):

  def __init__(self, platform: Platform) -> None:
    assert isinstance(platform, SshPlatformMixin)
    super().__init__(platform)

  def _build_ssh_cmd(self, *args: CmdArg, shell: bool = False) -> ListCmdArgs:
    assert isinstance(self.platform, SshPlatformMixin)
    return self.platform.build_ssh_cmd(*args, shell=shell)

  @override
  def _popen_forward(self, local_port: int,
                     remote_port: int) -> subprocess.Popen:
    return self.host_platform.popen(
        *self._build_ssh_cmd("-NL", f"{local_port}:localhost:{remote_port}"))

  @override
  def _popen_reverse_forward(self, remote_port: int,
                             local_port: int) -> subprocess.Popen:
    # TODO: this should likely match with adb, where we support 0
    # for auto-allocating a remote_port
    return self.host_platform.popen(
        *self._build_ssh_cmd("-NR", f"{remote_port}:localhost:{local_port}"))
