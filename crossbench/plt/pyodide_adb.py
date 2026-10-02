# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import shlex
import subprocess
import time
from typing import TYPE_CHECKING, Any, Mapping, cast

from typing_extensions import override

from crossbench.plt import android_adb
from crossbench.plt.pyodide import PyodideGcsBlob, PyodidePlatform, \
    is_pyodide_env

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.flags.base import FlagsData
  from crossbench.plt.base import Platform
  from crossbench.plt.signals import Signals
  from crossbench.plt.types import CmdArg, ProcessIo

try:
  import js
except ImportError:
  js = None


class PyodideAdb(android_adb.Adb):
  """ADB implementation that delegates to JavaScript js.webadb via Pyodide."""

  def __init__(
      self,
      host_platform: Platform | None = None,
      device_identifier: str | None = None,
      webadb: Any | None = None,
  ) -> None:
    if webadb is None and js is not None:
      webadb = js.webadb
    if webadb is None:
      raise ValueError("PyodideAdb requires a valid webadb JavaScript object.")
    self._webadb: Any = webadb
    if host_platform is None:
      host_platform = PyodidePlatform(webadb=webadb)
    # Skip native binary discovery by manually initializing superclass state
    self._host_platform = host_platform  # type: ignore[misc]
    self._adb_bin = host_platform.path("webadb")  # type: ignore[misc]
    self._bundletool = None  # type: ignore[misc]
    serial_id, device_info = self._start(device_identifier)
    self._serial_id = serial_id  # type: ignore[misc]
    self._device_info = device_info  # type: ignore[misc]

  @property
  def webadb(self) -> Any:
    return self._webadb

  @override
  def _start(
      self,
      device_identifier: str | None = None,
  ) -> tuple[str, android_adb.AndroidDeviceInfo]:
    serial_id = device_identifier or str(self._webadb.serial)
    device_info = android_adb.AndroidDeviceInfo(
        device_id=serial_id, name="device")
    return serial_id, device_info

  @override
  def devices(self) -> dict[str, android_adb.AndroidDeviceInfo]:
    return {self._serial_id: self._device_info}

  @override
  def start_server(self) -> None:
    pass

  @override
  def kill_server(self) -> None:
    pass

  @override
  def root(self) -> None:
    self._webadb.root()

  @override
  def unroot(self) -> None:
    self._webadb.unroot()

  @override
  def push(
      self,
      local_src_path: pth.LocalPath,
      device_dest_path: pth.AnyPath,
  ) -> None:
    self._check_interrupted()
    local_src = self._host_platform.local_path(local_src_path)
    remote_dest = str(device_dest_path)
    try:
      self._webadb.push(str(local_src), remote_dest)
    except Exception as e:
      if "BenchmarkExecutionInterrupted" in str(e) or "Stopped by user" in str(
          e):
        self._webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt(
            "Benchmark execution interrupted by user") from None
      raise

  @override
  def pull(
      self,
      device_src_path: pth.AnyPath,
      local_dest_path: pth.LocalPath,
  ) -> None:
    self._check_interrupted()
    remote_src = str(device_src_path)
    local_dest = self._host_platform.local_path(local_dest_path)
    try:
      self._webadb.pull(remote_src, str(local_dest))
    except Exception as e:
      if "BenchmarkExecutionInterrupted" in str(e) or "Stopped by user" in str(
          e):
        self._webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt(
            "Benchmark execution interrupted by user") from None
      raise

  @override
  def forward(
      self,
      local: int,
      remote: int | str,
      local_protocol: str = "tcp",
      remote_protocol: str = "tcp",
      flags_data: FlagsData = None,
  ) -> int:
    del local, remote, local_protocol, remote_protocol, flags_data
    raise NotImplementedError("Port forwarding is not supported on Pyodide.")

  @override
  def forward_remove(self, local: int, protocol: str = "tcp") -> None:
    del local, protocol
    raise NotImplementedError("Port forwarding is not supported on Pyodide.")

  @override
  def reverse(self, remote: int, local: int, protocol: str = "tcp") -> int:
    del remote, local, protocol
    raise NotImplementedError(
        "Reverse port forwarding is not supported on Pyodide.")

  @override
  def reverse_remove(self, remote: int, protocol: str = "tcp") -> None:
    del remote, protocol
    raise NotImplementedError(
        "Reverse port forwarding is not supported on Pyodide.")

  def _check_interrupted(self) -> None:
    if self._webadb and self._webadb.isInterrupted():
      self._webadb.acknowledgeInterrupt()
      raise KeyboardInterrupt("Benchmark execution interrupted by user")

  def _run_shell(self, cmd_str: str) -> bytes:
    self._check_interrupted()
    try:
      return self._to_bytes(self._webadb.shell(cmd_str))
    except Exception as e:
      if "BenchmarkExecutionInterrupted" in str(e) or "Stopped by user" in str(
          e):
        self._webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt(
            "Benchmark execution interrupted by user") from None
      raise

  # Required to overcome the "emscripten does not support processes" error.
  @override
  def _adb(
      self,
      *args: CmdArg,
      shell: bool = False,
      capture_output: bool = False,
      stdout: ProcessIo = None,
      stderr: ProcessIo = None,
      stdin: ProcessIo = None,
      input: bytes | None = None,  # pylint: disable=redefined-builtin
      quiet: bool = False,
      check: bool = True,
      use_serial_id: bool = True,
  ) -> subprocess.CompletedProcess:
    del shell, capture_output, stdout, stderr, stdin, input, quiet, check
    del use_serial_id
    self._check_interrupted()
    if not args:
      raise ValueError("No arguments provided to _adb")
    cmd = str(args[0])
    sub_args = args[1:]
    if cmd != "shell":
      raise NotImplementedError(
          f"ADB command '{cmd}' is not supported on Pyodide.")
    return self.shell(*sub_args)

  @override
  def _adb_stdout_bytes(
      self,
      *args: CmdArg,
      quiet: bool = False,
      stdin: ProcessIo = None,
      input: bytes | None = None,  # pylint: disable=redefined-builtin
      use_serial_id: bool = True,
      check: bool = True,
  ) -> bytes:
    del quiet, stdin, input, use_serial_id, check
    res = self._adb(*args)
    stdout = res.stdout
    if isinstance(stdout, bytes):
      return stdout
    return str(stdout).encode("utf-8")

  def _build_shell_cmd_str(self, *args: CmdArg, shell: bool = False) -> str:
    if not shell:
      return shlex.join(map(str, args))
    if len(args) == 1:
      return str(args[0])
    raise ValueError(f"Expected single sh arg with shell=True, but got: {args}")

  def _to_bytes(self, raw: Any) -> bytes:
    if isinstance(raw, bytes):
      return raw
    if isinstance(raw, str):
      return raw.encode("utf-8")
    return bytes(raw)

  @override
  def shell(
      self,
      *args: CmdArg,
      shell: bool = False,
      capture_output: bool = False,
      stdout: ProcessIo = None,
      stderr: ProcessIo = None,
      stdin: ProcessIo = None,
      input: bytes | None = None,  # pylint: disable=redefined-builtin
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
      quiet: bool = False,
      check: bool = True,
  ) -> subprocess.CompletedProcess:
    del capture_output, stdout, stderr, stdin, input, env, cwd, quiet
    del check
    cmd_str = self._build_shell_cmd_str(*args, shell=shell)
    out = self._run_shell(cmd_str)
    return subprocess.CompletedProcess(
        args=args, returncode=0, stdout=out, stderr=b"")

  @override
  def shell_stdout_bytes(
      self,
      *args: CmdArg,
      shell: bool = False,
      quiet: bool = False,
      stdin: ProcessIo = None,
      input: bytes | None = None,  # pylint: disable=redefined-builtin
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
      check: bool = True,
  ) -> bytes:
    del quiet, stdin, input, env, cwd, check
    cmd_str = self._build_shell_cmd_str(*args, shell=shell)
    return self._run_shell(cmd_str)


class PyodideAndroidAdbPlatform(android_adb.AndroidAdbPlatform):
  """Android ADB Platform running in a Pyodide WebAssembly environment."""

  def __init__(
      self,
      host_platform: Platform | None = None,
      device_identifier: str | None = None,
      adb: android_adb.Adb | None = None,
      webadb: Any | None = None,
  ) -> None:
    if host_platform is None:
      host_platform = PyodidePlatform(webadb=webadb)
    adb = adb or PyodideAdb(
        host_platform=host_platform,
        device_identifier=device_identifier,
        webadb=webadb,
    )
    super().__init__(
        host_platform=host_platform,
        device_identifier=device_identifier,
        adb=adb,
    )

  @property
  def is_pyodide(self) -> bool:
    return True

  @property
  def webadb(self) -> Any:
    return cast(PyodideAdb, self.adb).webadb

  @override
  def get_gcs_blob(self, gcs_url: str) -> PyodideGcsBlob:
    return self.host_platform.get_gcs_blob(gcs_url)

  def _check_interrupted(self) -> None:
    if self.webadb and self.webadb.isInterrupted():
      self.webadb.acknowledgeInterrupt()
      raise KeyboardInterrupt("Benchmark execution interrupted by user")

  @override
  def sleep(self, seconds: float | dt.timedelta) -> None:
    total_secs = (
        seconds.total_seconds()
        if isinstance(seconds, dt.timedelta) else float(seconds))
    if total_secs <= 0:
      return
    start = time.time()
    while time.time() - start < total_secs:
      self._check_interrupted()
      step = min(0.05, total_secs - (time.time() - start))
      if step <= 0:
        break
      time.sleep(step)

  @override
  def start_devtools(self) -> None:
    self._check_interrupted()
    res = self.webadb.startDevTools()
    if not res:
      raise RuntimeError("Failed to start DevTools connection in Pyodide")

  @override
  def stop_devtools(self) -> None:
    self.webadb.stopDevTools()

  @override
  def switch_to_new_tab(self, url: str = "about:blank") -> None:
    self._check_interrupted()
    self.webadb.switchTab(url)

  @override
  def send_cdp_command(self,
                       method: str,
                       params: dict[str, Any] | None = None) -> dict[str, Any]:
    self._check_interrupted()
    try:
      res_str = self.webadb.sendCdpCommand(method, json.dumps(params or {}))
    except Exception as e:
      if "BenchmarkExecutionInterrupted" in str(e) or "Stopped by user" in str(
          e):
        self.webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt(
            "Benchmark execution interrupted by user") from None
      raise
    if not res_str:
      raise RuntimeError(
          f"Pyodide sendCdpCommand('{method}') returned empty response")
    res = json.loads(str(res_str))
    if "error" in res:
      raise RuntimeError(f"CDP command '{method}' failed: {res['error']}")
    return {"id": 1, "result": res}

  def _check_path(self, flag: str, path: pth.AnyPathLike) -> bool:
    quoted_path = shlex.quote(str(self.path(path)))
    out = self.sh_stdout(  # noqa: S604
        f"[ {flag} {quoted_path} ] && echo 1", shell=True)
    return out.strip() == "1"

  @override
  def exists(self, path: pth.AnyPathLike) -> bool:
    return self._check_path("-e", path)

  @override
  def is_file(self, path: pth.AnyPathLike) -> bool:
    return self._check_path("-f", path)

  @override
  def is_dir(self, path: pth.AnyPathLike) -> bool:
    return self._check_path("-d", path)

  @override
  def write_text(
      self,
      file: pth.AnyPathLike,
      data: str,
      encoding: str = "utf-8",
  ) -> None:
    del encoding
    self._check_interrupted()
    dest_file = shlex.quote(str(self.path(file)))
    content = shlex.quote(data)
    self.adb.shell(  # noqa: S604
        f"echo -n {content} > {dest_file}", shell=True)

  @override
  def _popen(
      self,
      *args: CmdArg,
      bufsize: int = -1,
      shell: bool = False,
      stdout: ProcessIo = None,
      stderr: ProcessIo = None,
      stdin: ProcessIo = None,
      env: Mapping[str, str] | None = None,
      cwd: pth.AnyPath | None = None,
      encoding: str | None = None,
      quiet: bool = False,
      auto_terminate: bool = True,
  ) -> subprocess.Popen:
    del shell, bufsize, stdin, quiet, encoding, auto_terminate
    assert not env, "ADB does not support env vars"
    self._check_interrupted()

    cmd_str = shlex.join(map(str, args))
    if cwd:
      cmd_str = f"cd {shlex.quote(str(cwd))} && {cmd_str}"

    logging.info("Starting background process via WebADB spawn: %s", cmd_str)
    proc_id = int(self.webadb.spawnProcess(cmd_str))
    popen_obj = PyodideStreamingPopen(
        self,
        proc_id=proc_id,
        cmd=cmd_str,
        stdout=stdout,
        stderr=stderr,
        local_log_file=stdout if isinstance(stdout, io.IOBase) else None,
    )
    popen_obj.poll()
    return popen_obj


class PyodideStreamingPopen(subprocess.Popen):
  """A wrapper class to represent a streaming process spawned over WebADB.

  Keeps the ADB stream open and continuously synchronizes stdout/stderr to
  the local file without terminating the remote session.
  """

  def __init__(
      self,
      platform: PyodideAndroidAdbPlatform,
      proc_id: int,
      cmd: str,
      stdout: ProcessIo = None,
      stderr: ProcessIo = None,
      local_log_file: Any | None = None,
  ) -> None:
    self._platform: PyodideAndroidAdbPlatform = platform
    self._proc_id: int = proc_id
    self._cmd: str = cmd
    self._local_log_file: Any | None = local_log_file
    self._last_log_offset: int = 0
    self.returncode: int | None = None
    self.args = cmd
    self.pid = proc_id
    self.stdout = None
    self.stderr = None
    self.stdin = None
    if stdout == subprocess.PIPE or stderr == subprocess.PIPE:
      raise ValueError("PIPE is not supported in PyodideStreamingPopen")

  @property
  def proc_id(self) -> int:
    return self._proc_id

  @override
  def poll(self) -> int | None:
    if self.returncode is not None:
      return self.returncode
    self._sync_logs()
    return self.returncode

  def _sync_logs(self) -> None:
    webadb = self._platform.webadb
    raw_status = webadb.readProcessLog(self._proc_id, self._last_log_offset)
    if not raw_status:
      return
    try:
      status = json.loads(str(raw_status))
    except (ValueError, TypeError) as e:
      logging.warning("Failed to parse readProcessLog JSON: %s", e)
      return

    new_text = status.get("text", "")
    next_offset = status.get("nextOffset", self._last_log_offset)
    is_exited = status.get("isExited", False)
    exit_code = status.get("exitCode")

    if new_text and self._local_log_file:
      self._local_log_file.write(new_text)
      self._local_log_file.flush()

    self._last_log_offset = next_offset
    if is_exited and self.returncode is None:
      self.returncode = exit_code if exit_code is not None else 0

  @override
  def wait(self, timeout: float | None = None) -> int:
    start_time = time.time()
    while self.poll() is None:
      if timeout and (time.time() - start_time) > timeout:
        raise subprocess.TimeoutExpired(self._cmd, timeout)
      time.sleep(0.1)
    assert self.returncode is not None
    return self.returncode

  @override
  def send_signal(self, signal: int | Signals) -> None:
    if self.returncode is not None:
      return
    self._platform.webadb.killProcess(self._proc_id)
    self.returncode = -int(signal)
    self._sync_logs()

  @override
  def terminate(self) -> None:
    self.send_signal(self._platform.signals.SIGTERM)

  @override
  def kill(self) -> None:
    self.send_signal(self._platform.signals.SIGKILL)


__all__ = [
    "PyodideAdb",
    "PyodideAndroidAdbPlatform",
    "PyodideGcsBlob",
    "PyodidePlatform",
    "PyodideStreamingPopen",
    "is_pyodide_env",
]
