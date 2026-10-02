# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any, Final, Mapping

from crossbench.plt.port_manager import PortManager
from crossbench.plt.remote import RemotePlatformMixin

if TYPE_CHECKING:
  import subprocess

  from crossbench import path as pth
  from crossbench.plt.base import Platform
  from crossbench.plt.types import CmdArg, ListCmdArgs, ProcessIo


class SshPortManager(PortManager):
  pass


class SshPlatformMixin(RemotePlatformMixin, metaclass=abc.ABCMeta):

  def __init__(self, host_platform: Platform, host: str, port: int,
               ssh_port: int, ssh_user: str) -> None:
    self._host: Final[str] = host
    self._port: Final[int] = port
    self._ssh_port: Final[int] = ssh_port
    self._ssh_user: Final[str] = ssh_user
    super().__init__(host_platform)

  @abc.abstractmethod
  def _create_port_manager(self) -> PortManager:
    pass

  @property
  def host(self) -> str:
    return self._host

  @property
  def port(self) -> int:
    return self._port

  @property
  def ssh_user(self) -> str:
    return self._ssh_user

  @property
  def ssh_port(self) -> int:
    return self._ssh_port

  @property
  def is_remote_ssh(self) -> bool:
    return True

  @property
  def key(self) -> tuple[Any, ...]:
    return ("ssh", self.host, str(self.port))

  @abc.abstractmethod
  def build_ssh_cmd(self,
                    *args: CmdArg,
                    shell: bool = False,
                    env: Mapping[str, str] | None = None,
                    cwd: pth.AnyPath | None = None) -> ListCmdArgs:
    pass

  def sh_stdout_bytes(self,
                      *args: CmdArg,
                      shell: bool = False,
                      quiet: bool = False,
                      stdin: ProcessIo = None,
                      input: bytes | None = None,
                      env: Mapping[str, str] | None = None,
                      cwd: pth.AnyPath | None = None,
                      check: bool = True) -> bytes:
    ssh_cmd: ListCmdArgs = self.build_ssh_cmd(
        *args, shell=shell, env=env, cwd=cwd)
    return self._host_platform.sh_stdout_bytes(
        *ssh_cmd,
        shell=False,
        quiet=quiet,
        stdin=stdin,
        input=input,
        check=check)

  def sh(self,
         *args: CmdArg,
         shell: bool = False,
         capture_output: bool = False,
         stdout: ProcessIo = None,
         stderr: ProcessIo = None,
         stdin: ProcessIo = None,
         input: bytes | None = None,
         env: Mapping[str, str] | None = None,
         cwd: pth.AnyPath | None = None,
         quiet: bool = False,
         check: bool = True) -> subprocess.CompletedProcess:
    ssh_cmd: ListCmdArgs = self.build_ssh_cmd(
        *args, shell=shell, env=env, cwd=cwd)
    return self._host_platform.sh(
        *ssh_cmd,
        shell=shell,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        input=input,
        quiet=quiet,
        check=check)
