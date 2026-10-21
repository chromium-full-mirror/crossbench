# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Final, Mapping

from typing_extensions import override

from crossbench.plt.linux import RemoteLinuxPlatform
from crossbench.plt.ssh import SshPlatformMixin
from crossbench.plt.ssh_port_manager import SshPortManager

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.plt.port_manager import PortManager
  from crossbench.plt.types import CmdArg, CmdArgs, ListCmdArgs, ProcessInfo, \
      TupleCmdArgs


class LinuxSshPlatform(SshPlatformMixin, RemoteLinuxPlatform):
  SSH_OPTIONS: Final[TupleCmdArgs] = (
      "-o",
      "ControlMaster=auto",
      "-o",
      "ControlPath=/tmp/crossbench-ssh-%C",
      "-o",
      "ControlPersist=600",
      "-o",
      "CanonicalizeHostname=no",
  )

  def _create_port_manager(self) -> PortManager:
    return SshPortManager(self)

  @property
  @override
  def os_name(self) -> str:
    return "linux"

  @override
  def build_ssh_cmd(self,
                    *args: CmdArg,
                    shell: bool = False,
                    env: Mapping[str, str] | None = None,
                    cwd: pth.AnyPath | None = None) -> ListCmdArgs:
    self.validate_shell_args(args, shell)
    ssh_cmd = self.build_shell_cmd(*args, shell=False, env=env, cwd=cwd)
    if not shell:
      return ssh_cmd
    return [" ".join(map(str, ssh_cmd))]

  @override
  def build_shell_cmd(
      self,
      *args: CmdArg,
      shell: bool = False,
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
  ) -> ListCmdArgs:
    if env:
      # TODO: support env with "export FOO=bar;" prefixes
      raise ValueError(f"{self} platform only supports an empty env for now.")
    if cwd:
      # TODO: support env with "cd foo/bar &&" prefix
      raise ValueError(f"{self} platform does not support custom cwd")
    self.validate_shell_args(args, shell)
    remote_cmd = str(args[0]) if shell else shlex.join(map(str, args))
    return [
        "ssh",
        *self.SSH_OPTIONS,
        "-p",
        f"{self._ssh_port}",
        f"{self._ssh_user}@{self._host}",
        remote_cmd,
    ]

  def processes(self, attrs: list[str] | None = None) -> list[ProcessInfo]:
    del attrs
    # TODO: Define a more generic method in PosixPlatform, possibly with
    # an overridable function to generate ps command line.
    lines = self.sh_stdout("ps", "-A", "-o", "pid,cmd").splitlines()
    if len(lines) == 1:
      return []

    res: list[ProcessInfo] = []
    for line in lines[1:]:
      pid, name = line.split(maxsplit=1)
      res.append({"pid": int(pid), "name": name})
    return res

  def push(self, from_path: pth.LocalPath, to_path: pth.AnyPath) -> pth.AnyPath:
    self.mkdir(to_path.parent, parents=True, exist_ok=True)

    scp_cmd: ListCmdArgs = [
        "scp",
        *self.SSH_OPTIONS,
        "-P",
        f"{self._ssh_port}",
    ]
    if from_path.is_dir():
      scp_cmd.append("-r")
    scp_cmd += [f"{from_path}", f"{self._ssh_user}@{self._host}:{to_path}"]
    self._host_platform.sh_stdout(*scp_cmd)
    return to_path

  def pull(self, from_path: pth.AnyPath,
           to_path: pth.LocalPath) -> pth.LocalPath:
    self._host_platform.mkdir(to_path.parent, parents=True, exist_ok=True)

    scp_cmd: CmdArgs = [
        "scp",
        *self.SSH_OPTIONS,
        "-P",
        f"{self._ssh_port}",
        f"{self._ssh_user}@{self._host}:{from_path}",
        to_path,
    ]
    self._host_platform.sh_stdout(*scp_cmd)
    return to_path
