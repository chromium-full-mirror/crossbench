# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
from typing import Iterator
from unittest import mock

from typing_extensions import override

from crossbench import path as pth
from crossbench import plt
from crossbench.plt.port_manager import PortForwardException
from tests import test_helper
from tests.crossbench.plt.helper import BasePosixMockPlatformTestCase


class LinuxSshMockPlatformTestCase(BasePosixMockPlatformTestCase):
  __test__ = True
  HOST = "host"
  PORT = 9515
  SSH_PORT = 22
  SSH_USER = "user"

  platform: plt.LinuxSshPlatform

  @override
  def setup_platform(self) -> plt.LinuxSshPlatform:
    self.mock_platform_default_tmp_dir(plt.LinuxSshPlatform)
    platform = plt.LinuxSshPlatform(
        self.host_platform,
        host=self.HOST,
        port=self.PORT,
        ssh_port=self.SSH_PORT,
        ssh_user=self.SSH_USER)
    self.mock_platform_str(platform, "linux_ssh_mock_platform")
    return platform

  def _expect_sh_ssh(self, *args, result="", returncode: int = 0):
    self.host_platform.expect_sh(
        "ssh",
        "-p",
        str(self.SSH_PORT),
        f"{self.SSH_USER}@{self.HOST}",
        *args,
        result=result,
        returncode=returncode)

  def _expect_sh_ssh_shell(self, *args, result=""):
    cmd_string = f"ssh -p {self.SSH_PORT!s} {self.SSH_USER}@{self.HOST} "
    cmd_string += " ".join(map(str, args))
    self.host_platform.expect_sh(cmd_string, result=result)

  def expect_sh(self, *args, result="", returncode: int = 0) -> None:
    self._expect_sh_ssh(*args, result=result, returncode=returncode)

  def test_is_linux(self):
    self.assertTrue(self.platform.is_linux)

  def test_is_remote_ssh(self):
    self.assertTrue(self.platform.is_remote_ssh)

  def test_basic_properties(self):
    self.assertTrue(self.platform.is_remote)
    self.assertEqual(self.platform.host, self.HOST)
    self.assertEqual(self.platform.port, self.PORT)
    self.assertIs(self.platform.host_platform, self.host_platform)
    self.assertTrue(self.platform.is_posix)

  def test_name(self):
    self.assertEqual(self.platform.name, "linux_ssh")

  def test_os_name(self):
    self.assertEqual(self.platform.os_name, "linux")

  def test_version(self):
    self._expect_sh_ssh("uname -r", result="999")
    self.assertEqual(self.platform.version_str, "999")
    # Subsequent calls are cached.
    self.assertEqual(self.platform.version_str, "999")

  def test_iterdir(self):
    self._expect_sh_ssh("'[' -d parent_dir/child_dir ']'")
    self._expect_sh_ssh("ls -1 parent_dir/child_dir", result="file1\nfile2\n")

    self.assertSetEqual(
        set(self.platform.iterdir(pth.AnyWindowsPath("parent_dir\\child_dir"))),
        {
            pth.AnyPosixPath("parent_dir/child_dir/file1"),
            pth.AnyPosixPath("parent_dir/child_dir/file2"),
        })

  def test_cat_file(self):
    self._expect_sh_ssh("cat path/to/a/file")
    self.platform.cat(self.platform.path("path/to/a/file"))
    self._expect_sh_ssh("cat 'path/with a space/to/a/file'")
    self.platform.cat(self.platform.path("path/with a space/to/a/file"))

  def test_sh_input(self):
    self.expect_sh("cat", result="hello world")
    hello_world = self.platform.sh_stdout("cat", input=b"hello world")
    self.assertEqual(hello_world, "hello world")

    self.expect_sh("cat", result=b"hello world bytes")
    hello_world_bytes = self.platform.sh_stdout_bytes(
        "cat", input=b"hello world bytes")
    self.assertEqual(hello_world_bytes, b"hello world bytes")

  def test_sh_shell_invalid(self):
    with self.assertRaisesRegex(ValueError, "shell=True"):
      self.platform.sh_stdout("ls", "folder with space", shell=True)

  def test_sh_shell(self):
    self._expect_sh_ssh("ls sdcard", result="FILE1\nFILE2\n")
    self.assertEqual(self.platform.sh_stdout("ls", "sdcard"), "FILE1\nFILE2\n")

    self._expect_sh_ssh("ls 'folder with space'", result="FOLDER\n")
    self.assertEqual(
        self.platform.sh_stdout("ls", "folder with space"), "FOLDER\n")

    self._expect_sh_ssh("'ls foo && ls bar'", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls foo && ls bar"), "FILE1\nFILE2\n")

    self._expect_sh_ssh_shell("'ls foo && ls bar'", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls foo && ls bar", shell=True),
        "FILE1\nFILE2\n")

    self._expect_sh_ssh("ls foo '&&' ls bar", result="FILE1\nFILE2\n")
    self.assertEqual(
        self.platform.sh_stdout("ls", "foo", "&&", "ls", "bar"),
        "FILE1\nFILE2\n")

  @contextlib.contextmanager
  def mock_popen(self, platform) -> Iterator[mock.MagicMock]:
    with mock.patch.object(type(platform), "popen") as patcher:
      yield patcher

  @contextlib.contextmanager
  def mock_get_free_port(self, platform, port) -> Iterator[mock.MagicMock]:
    with mock.patch.object(
        type(platform), "get_free_port", return_value=port) as patcher:
      yield patcher

  @contextlib.contextmanager
  def mock_wait_for_port(self, platform) -> Iterator[mock.MagicMock]:
    with mock.patch.object(type(platform), "wait_for_port") as patcher:
      yield patcher

  def test_port_forward(self):
    with self.platform.ports.nested() as ports:
      with self.mock_popen(
          self.host_platform) as mock_popen, self.mock_wait_for_port(
              self.host_platform) as mock_wait_for_port:
        port = ports.forward(666, 33221)
      mock_popen.assert_called_once()
      mock_wait_for_port.assert_called_once()
      self.assertEqual(port, 666)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        port = ports.forward(666, 33221)
      ports.stop_forward(port)

  def test_port_forward_auto_port(self):
    with self.platform.ports.nested() as ports:
      with self.mock_get_free_port(self.host_platform, 666) as mock_free_port:
        with self.mock_popen(self.host_platform) as mock_popen:
          with self.mock_wait_for_port(
              self.host_platform) as mock_wait_for_port:
            port = ports.forward(0, 33221)
        mock_popen.assert_called_once()
        mock_wait_for_port.assert_called_once()
      mock_free_port.assert_called_once()
      self.assertEqual(port, 666)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        port = ports.forward(666, 33221)
      ports.stop_forward(port)

  def test_reverse_port_forward(self):
    with self.platform.ports.nested() as ports:
      self._expect_sh_ssh("ss -HOlnt sport = 666", result="666")
      with self.mock_popen(self.host_platform) as mock_popen:
        port = ports.reverse_forward(666, 33221)
      mock_popen.assert_called_once()
      with self.assertRaisesRegex(PortForwardException, "twice"):
        ports.reverse_forward(666, 33221)
      self.assertEqual(port, 666)
      ports.stop_reverse_forward(port)

  def test_push_creates_dest_dir(self):
    self._expect_sh_ssh("mkdir -p remote/dest/path")
    self.host_platform.expect_sh(
        "scp", "-P", self.SSH_PORT, "source/path/file",
        f"{self.SSH_USER}@{self.HOST}:remote/dest/path/file")
    self.platform.push(
        self.host_platform.path("source/path/file"),
        self.platform.path("remote/dest/path/file"))

  def test_push_dir(self):
    self._expect_sh_ssh("mkdir -p remote/dest/path")
    self.host_platform.expect_sh(
        "scp", "-P", self.SSH_PORT, "-r", "source/path/dir",
        f"{self.SSH_USER}@{self.HOST}:remote/dest/path/dir")
    source_dir = self.host_platform.path("source/path/dir")
    self.fs.create_dir(source_dir)
    self.platform.push(source_dir, self.platform.path("remote/dest/path/dir"))

  def test_pull_creates_dest_dir(self):
    self.host_platform.expect_sh(
        "scp", "-P", self.SSH_PORT,
        f"{self.SSH_USER}@{self.HOST}:remote/source/path/file",
        "local/dest/path/file")
    self.platform.pull(
        self.platform.path("remote/source/path/file"),
        self.platform.path("local/dest/path/file"))

    self.assertEqual(self.host_platform.mkdir_calls, 1)
    self.assertTrue(pth.LocalPath("local/dest/path").exists())

  def _expect_remote_popen_pid(self, pid: int = 4242) -> None:
    tmp_dir = self.platform.default_tmp_dir
    self._expect_sh_ssh(
        f"mktemp {tmp_dir}/XXXXXXXXXXXpopen_pid_", result="/tmp/pid1")
    self._expect_sh_ssh("cat /tmp/pid1", result=f"{pid}\n")
    self._expect_sh_ssh("'[' -e /tmp/pid1 ']'")
    self._expect_sh_ssh("rm /tmp/pid1")

  def test_popen_kill_all_sends_remote_ssh_kill(self):
    self._expect_remote_popen_pid(4242)
    self._expect_sh_ssh("kill -9 4242")
    with (mock.patch("subprocess.Popen.__init__", return_value=None)
          as mock_popen_init,
          mock.patch("subprocess.Popen.poll", return_value=None),
          mock.patch("subprocess.Popen.send_signal") as mock_local_send_signal):
      proc = self.platform.popen("sleep", "5")
      self.assertIsInstance(proc, plt.remote.RemotePopen)
      self.assertEqual(proc.remote_pid, 4242)
      # The local Popen on host_platform is the SSH transport command waiting
      # on the remote background PID ($PID).
      mock_popen_init.assert_called_once_with([
          "ssh",
          "-p",
          str(self.SSH_PORT),
          f"{self.SSH_USER}@{self.HOST}",
          "set -m; sleep 5 & PID=$! && echo $PID >/tmp/pid1 && wait $PID",
      ],
                                              bufsize=-1,
                                              stdout=None,
                                              stderr=None,
                                              stdin=None)
      # RemotePopen is tracked only on the remote platform, not host_platform.
      self.assertEqual(self.platform.active_popens, (proc,))
      self.assertEqual(self.host_platform.active_popens, ())

      self.platform.kill_all_popens()
      # Killing RemotePopen sends "kill -9 4242" over SSH to the remote host
      # (which lets remote `wait $PID` finish and exit the SSH session),
      # rather than sending a local signal on host_platform.
      mock_local_send_signal.assert_not_called()
      self.assertEqual(self.host_platform.sh_cmds[-1],
                       ("ssh", "-p", str(self.SSH_PORT),
                        f"{self.SSH_USER}@{self.HOST}", "kill -9 4242"))

  def test_build_shell_cmd(self):
    ssh_prefix = [
        "ssh",
        "-p",
        str(self.SSH_PORT),
        f"{self.SSH_USER}@{self.HOST}",
    ]
    self.assertEqual(
        self.platform.build_shell_cmd("echo", "hello world", shell=False),
        [*ssh_prefix, "echo 'hello world'"])
    self.assertEqual(
        self.platform.build_shell_cmd("echo 'hello world' | cat", shell=True),
        [*ssh_prefix, "echo 'hello world' | cat"])
    with self.assertRaisesRegex(ValueError, "shell=True"):
      self.platform.build_shell_cmd("echo", "hello", shell=True)

  def test_popen_terminate_and_send_signal(self):
    self._expect_remote_popen_pid(4242)
    self._expect_sh_ssh("kill -2 4242")
    self._expect_sh_ssh("kill -15 4242")
    with (mock.patch("subprocess.Popen.__init__", return_value=None),
          mock.patch("subprocess.Popen.poll", return_value=None)):
      proc = self.platform.popen("sleep", "5")
      proc.send_signal(self.platform.signals.SIGINT)
      proc.terminate()

  def test_popen_auto_terminate_false(self):
    self._expect_remote_popen_pid(4242)
    self._expect_sh_ssh("kill -9 4242")
    with (mock.patch("subprocess.Popen.__init__", return_value=None),
          mock.patch("subprocess.Popen.poll", return_value=None)):
      proc = self.platform.popen("sleep", "5", auto_terminate=False)
      self.assertIsInstance(proc, plt.remote.RemotePopen)
      self.assertEqual(self.platform.active_popens, ())
      self.assertEqual(self.host_platform.active_popens, ())
      # kill_all_popens() does not touch untracked processes:
      self.platform.kill_all_popens()
      # Explicit kill() still sends kill -9 4242 to the remote SSH device:
      proc.kill()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
