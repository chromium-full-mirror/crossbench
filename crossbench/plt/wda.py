# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Client for interacting with WebDriverAgent (WDA) on iOS.

WebDriverAgent (https://github.com/appium/WebDriverAgent) is an iOS HTTP
server that enables UI automation and physical touch/gesture simulation
(swipes, taps, scrolling) on iOS devices and simulators.

Crossbench uses WDA for native physical touch interaction and Safari
automation on iOS. To use WDA:
1. Build WebDriverAgentRunner.xcodeproj in Xcode or with xcodebuild:
   xcodebuild build-for-testing -project WebDriverAgent.xcodeproj \\
     -scheme WebDriverAgentRunner -destination "id=<UDID>"
   This deposits a .xctestrun file in ~/Library/Developer/Xcode/DerivedData,
   which Crossbench automatically discovers.
2. Alternatively, set CROSSBENCH_WDA_XCTESTRUN to the path of your
   built WebDriverAgentRunner*.xctestrun file.
3. Or launch WebDriverAgentRunner on the device beforehand so it listens
   on port 8100.
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import logging
import plistlib
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import IO, TYPE_CHECKING, Any, Final, Sequence

from crossbench.helper.wait import wait_with_backoff
from crossbench.plt.bin import Binaries
from crossbench.plt.display_info import DisplayResolution
from crossbench.plt.port_manager import PortForwardException

if TYPE_CHECKING:
  from crossbench import path as pth
  from crossbench.plt.ios import IOSPlatform


class WDAError(RuntimeError):
  """Exception raised for WebDriverAgent communication or setup errors."""


class WDAClient:
  """Client for interacting with WebDriverAgent running on an iOS device."""

  DEFAULT_PORT: Final[int] = 8100
  STARTUP_TIMEOUT: Final[dt.timedelta] = dt.timedelta(seconds=90)
  REQUEST_TIMEOUT: Final[dt.timedelta] = dt.timedelta(seconds=30)

  def __init__(
      self,
      platform: IOSPlatform,
      port: int = DEFAULT_PORT,
  ) -> None:
    self._platform: Final[IOSPlatform] = platform
    self._port: Final[int] = port
    self._session_id: str | None = None
    self._xcodebuild_proc: subprocess.Popen[Any] | None = None
    self._is_forwarded: bool = False
    atexit.register(self.stop)

  @property
  def platform(self) -> IOSPlatform:
    return self._platform

  @property
  def port(self) -> int:
    return self._port

  @property
  def base_url(self) -> str:
    return f"http://localhost:{self._port}"

  def _request(
      self,
      method: str,
      endpoint: str,
      data: dict[str, Any] | None = None,
      timeout: dt.timedelta = REQUEST_TIMEOUT,
  ) -> dict[str, Any]:
    url = f"{self.base_url}/{endpoint.lstrip('/')}"
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(  # noqa: S310
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
      with urllib.request.urlopen(  # noqa: S310
          req, timeout=timeout.total_seconds()) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
      body = e.read().decode("utf-8", errors="replace")
      raise WDAError(f"{method} {url}: HTTP {e.code}: {body}") from e

  def is_connected(self) -> bool:
    """Check whether WebDriverAgent HTTP server is responsive and ready."""
    try:
      status = self._request("GET", "/status", timeout=dt.timedelta(seconds=2))
      value = status.get("value", {})
      return bool(value.get("ready", False))
    except (WDAError, urllib.error.URLError, TimeoutError, OSError):
      return False

  def start(self) -> None:
    """Ensure WebDriverAgent is forwarded and running."""
    if self.is_connected():
      return

    if not self._platform.is_simulator and not self._is_forwarded:
      self._platform.ports.forward(self._port, self._port)
      self._is_forwarded = True

    if self.is_connected():
      return

    self._start_runner()

  def _start_runner(self) -> None:
    """Launch WebDriverAgent via xcodebuild if available."""
    self._check_devtools_security()
    xctestrun_path = self._find_xctestrun()
    if not xctestrun_path:
      raise WDAError(
          f"WebDriverAgent is not running on {self.base_url} and no "
          ".xctestrun file was found to launch it automatically.\n"
          "To enable iOS touch gestures / Safari automation:\n"
          "1. Build WebDriverAgentRunner "
          "(https://github.com/appium/WebDriverAgent)\n"
          "   in Xcode or with xcodebuild so its .xctestrun file is in\n"
          "   ~/Library/Developer/Xcode/DerivedData, or\n"
          "2. Set the CROSSBENCH_WDA_XCTESTRUN environment variable to the\n"
          "   path of your built .xctestrun file, or\n"
          "3. Start WebDriverAgentRunner on the device beforehand.")

    logging.info("Starting WebDriverAgentRunner on %s...", self._platform.udid)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log_file:
      self._xcodebuild_proc = self._platform.host_platform.popen(
          *self._build_runner_cmd(xctestrun_path),
          stdin=subprocess.DEVNULL,
          stdout=log_file,
          stderr=subprocess.STDOUT)
      if self._wait_for_runner(log_file):
        logging.info("WebDriverAgent is ready.")
        return
      output = self._read_runner_log(log_file)
    self._raise_startup_timeout(output)

  def _build_runner_cmd(
      self, xctestrun_path: pth.AnyPath) -> tuple[pth.AnyPathLike, ...]:
    xcodebuild_bin = Binaries.XCODEBUILD.resolve(self._platform.host_platform)
    return (
        xcodebuild_bin,
        "test-without-building",
        "-collect-test-diagnostics",
        "never",
        "-xctestrun",
        str(xctestrun_path),
        "-destination",
        f"id={self._platform.udid}",
    )

  def _wait_for_runner(self, log_file: IO[str]) -> bool:
    """Poll until WDA is reachable; returns False on timeout."""
    try:
      for _ in wait_with_backoff(self.STARTUP_TIMEOUT):
        if self._poll_runner(log_file):
          return True
    except TimeoutError:
      pass
    return False

  def _poll_runner(self, log_file: IO[str]) -> bool:
    """Check the runner once; raises on known errors or unexpected exit."""
    assert self._xcodebuild_proc is not None
    output = self._read_runner_log(log_file)
    if output:
      self._check_runner_output_for_known_errors(output)
    if self._xcodebuild_proc.poll() is not None:
      self._handle_runner_error(self._xcodebuild_proc.returncode, output)
    return self.is_connected()

  def _raise_startup_timeout(self, output: str) -> None:
    timeout_sec = self.STARTUP_TIMEOUT.total_seconds()
    self.stop()
    message = (f"Timed out after {timeout_sec}s waiting for WebDriverAgent on "
               f"{self.base_url}")
    if not output:
      raise WDAError(f"{message}.")
    self._check_runner_output_for_known_errors(output)
    raise WDAError(f"{message}:\n{self._truncate_log(output)}")

  def _check_devtools_security(self) -> None:
    try:
      status = self._platform.host_platform.sh_stdout("DevToolsSecurity",
                                                      "-status")
    except (subprocess.SubprocessError, OSError) as e:
      logging.warning("Could not check DevToolsSecurity status: %s", e)
      return
    if "disabled" in status.lower():
      raise WDAError("macOS Developer Mode is disabled. "
                     "Please run 'sudo DevToolsSecurity -enable' in a "
                     "Terminal.")

  def _read_runner_log(self, log_file: IO[str]) -> str:
    try:
      log_file.seek(0)
      return log_file.read()
    except OSError:
      return ""

  def _truncate_log(self, output: str, max_lines: int = 20) -> str:
    output_summary = output.strip()
    if not output_summary:
      return ""
    lines = output_summary.splitlines()
    if len(lines) > max_lines:
      return "\n".join(lines[-max_lines:])
    return output_summary

  def _check_runner_output_for_known_errors(self, output: str) -> None:
    combined_output = output
    if match := re.search(r"attach the result bundle at\s+(\S+\.xcresult)",
                          output):
      try:
        xcresult = self._platform.host_platform.path(match.group(1))
        for log_file in self._platform.host_platform.glob(
            xcresult, "**/Session-*.log"):
          combined_output += "\n" + (self._platform.host_platform.cat(log_file))
      except (OSError, subprocess.SubprocessError) as e:
        logging.warning("Could not inspect xcresult log: %s", e)
    # 0xe8008012 (kAMDProvisioningProfileInstallFailedError) is reported when
    # the embedded provisioning profile does not include this device's UDID.
    if ("provisioning profile cannot be installed on this device"
        in combined_output or "0xe8008012" in combined_output):
      self.stop()
      xcodeproj = self._find_xcodeproj_for_hint()
      raise WDAError(
          f"The pre-built WebDriverAgentRunner on this Mac was signed for a "
          f"different iOS device and is not authorized to run on device "
          f"{self._platform.udid}.\n"
          "To authorize and rebuild it for this device:\n"
          "1. Open the project in Xcode by running:\n"
          f"     open {xcodeproj}\n"
          "2. In Xcode's top toolbar, select the 'WebDriverAgentRunner' scheme "
          "and select your connected iPhone/iPad as the target device.\n"
          "3. In the Xcode menu bar, click Product -> Build For -> Testing "
          "(Cmd+Shift+U) so Xcode registers this device and updates the build.")
    if ("Developer App Certificate is not trusted" in combined_output or
        "profile has not been explicitly trusted" in combined_output):
      self.stop()
      raise WDAError(
          f"The Developer App Certificate is not trusted on device "
          f"{self._platform.udid}. "
          "Please open Settings -> General -> VPN & Device Management on the "
          "device and trust your Developer App certificate. Note: The device "
          "requires an internet connection (Wi-Fi or cellular) to verify the "
          "certificate.")
    if "Guided Access active" in combined_output:
      self.stop()
      raise WDAError(
          f"Guided Access is active on device {self._platform.udid}, which "
          "prevents WebDriverAgentRunner from launching. Please end Guided "
          "Access on the device (triple-click the side button, enter your "
          "passcode, and tap 'End', or disable it under "
          "Settings -> Accessibility -> Guided Access).")
    if "agreed to the Xcode license agreements" in combined_output:
      self.stop()
      raise WDAError(
          "Xcode license agreements have not been accepted. "
          "Please run 'sudo xcodebuild -license accept' in a Terminal.")
    if ("Developer Mode is disabled" in combined_output or
        "Developer Mode not enabled" in combined_output):
      self.stop()
      raise WDAError(
          f"Developer Mode is disabled on device {self._platform.udid}. "
          "Please open Settings -> Privacy & Security -> Developer Mode on "
          "the device to enable it.")
    if ("Device is locked" in combined_output or
        "device was locked" in combined_output):
      self.stop()
      raise WDAError(f"Device {self._platform.udid} is locked. "
                     "Please unlock the device.")
    if "password" in combined_output.lower():
      self.stop()
      raise WDAError(
          "xcodebuild is requesting authentication. "
          "macOS Developer Mode may be disabled. "
          "Please run 'sudo DevToolsSecurity -enable' in a Terminal.")

  def _handle_runner_error(self, returncode: int, output: str) -> None:
    self.stop()
    self._check_runner_output_for_known_errors(output)
    output_summary = self._truncate_log(output)
    if output_summary:
      raise WDAError(f"xcodebuild process terminated unexpectedly with code "
                     f"{returncode}:\n{output_summary}")
    raise WDAError(
        f"xcodebuild process terminated unexpectedly with code {returncode}.")

  def _find_xctestrun(self) -> pth.AnyPath | None:
    """Find a candidate .xctestrun file on the host platform."""
    host = self._platform.host_platform
    if env_path := host.environ.get("CROSSBENCH_WDA_XCTESTRUN"):
      candidate = host.path(env_path)
      if not host.is_file(candidate):
        raise WDAError(
            f"CROSSBENCH_WDA_XCTESTRUN points to a missing file: {candidate}")
      return candidate

    home = host.home()
    derived_data = home / "Library/Developer/Xcode/DerivedData"
    if not host.is_dir(derived_data):
      return None

    candidates = list(
        host.glob(derived_data, "WebDriverAgent-*/Build/Products/*.xctestrun"))
    if not candidates:
      return None

    # Xcode names builds e.g. WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun
    # or WebDriverAgentRunner_iphonesimulator26.5-arm64.xctestrun.
    sdk_name = "iphonesimulator" if self._platform.is_simulator else "iphoneos"
    if matching := [c for c in candidates if sdk_name in c.name]:
      candidates = matching
    # Prefer the most recently modified .xctestrun build.
    candidates.sort(key=host.last_modified, reverse=True)
    return candidates[0]

  def _find_xcodeproj_for_hint(self) -> pth.AnyPath:
    """Resolve the path to WebDriverAgent.xcodeproj for error messages."""
    host = self._platform.host_platform
    xctestrun_path = self._find_xctestrun()
    if xctestrun_path and len(xctestrun_path.parents) >= 3:
      info_plist = xctestrun_path.parents[2] / "info.plist"
      if host.is_file(info_plist):
        try:
          workspace = plistlib.loads(
              host.cat_bytes(info_plist)).get("WorkspacePath")
          if workspace and host.exists(host.path(workspace)):
            return host.path(workspace)
        except (plistlib.InvalidFileException, OSError) as e:
          logging.warning("Could not read info.plist at %s: %s", info_plist, e)
    try:
      out = host.sh_stdout(
          "mdfind", "kMDItemFSName == 'WebDriverAgent.xcodeproj'").strip()
      if out:
        return host.path(out.splitlines()[0])
    except (subprocess.SubprocessError, OSError) as e:
      logging.warning("Could not locate WebDriverAgent.xcodeproj: %s", e)
    return host.path("WebDriverAgent.xcodeproj")

  def ensure_session(self) -> str:
    """Return active session ID or create a new session if needed."""
    if self._session_id:
      return self._session_id

    self.start()

    try:
      status = self._request("GET", "/status", timeout=self.REQUEST_TIMEOUT)
      if session_id := (status.get("sessionId") or
                        status.get("value", {}).get("sessionId")):
        self._session_id = session_id
        self._configure_session(session_id)
        return session_id
    except (WDAError, urllib.error.URLError, TimeoutError, OSError) as e:
      raise WDAError("Failed to query WebDriverAgent status") from e

    try:
      resp = self._request(
          "POST",
          "/session", {
              "capabilities": {
                  "waitForIdleTimeout": 0,
              },
          },
          timeout=self.REQUEST_TIMEOUT)
    except (WDAError, urllib.error.URLError, TimeoutError, OSError) as e:
      raise WDAError("Failed to create WebDriverAgent session") from e
    session_id = resp.get("sessionId") or resp.get("value", {}).get("sessionId")
    if not session_id:
      raise WDAError(f"Failed to create WebDriverAgent session: {resp}")
    self._session_id = session_id
    self._configure_session(session_id)
    return self._session_id

  def set_settings(self, settings: dict[str, Any]) -> None:
    """Update WebDriverAgent runtime settings for the active session."""
    session_id = self.ensure_session()
    self._request(
        "POST",
        f"/session/{session_id}/appium/settings",
        {"settings": settings},
        timeout=self.REQUEST_TIMEOUT,
    )

  def _configure_session(self, session_id: str) -> None:
    """Disable quiescence, animation cooldown, and deep DOM snapshots."""
    try:
      self._request(
          "POST",
          f"/session/{session_id}/appium/settings",
          {
              "settings": {
                  "animationCoolOffTimeout": 0,
                  "snapshotMaxChildren": 1,
                  "snapshotMaxDepth": 1,
                  "waitForIdleTimeout": 0,
              },
          },
          timeout=self.REQUEST_TIMEOUT,
      )
    except (WDAError, urllib.error.URLError, TimeoutError, OSError) as e:
      logging.warning("Failed to configure WDA session %s: %s", session_id, e)

  def window_size(self) -> DisplayResolution:
    """Return device window dimensions in points."""
    session_id = self.ensure_session()
    resp = self._request(
        "GET",
        f"/session/{session_id}/window/size",
        timeout=self.REQUEST_TIMEOUT)
    val = resp.get("value", {})
    width = int(val.get("width", 0))
    height = int(val.get("height", 0))
    if width <= 0 or height <= 0:
      raise WDAError(f"Invalid window size received from WDA: {val}")
    return DisplayResolution(width, height)

  def drag(
      self,
      from_x: int,
      from_y: int,
      to_x: int,
      to_y: int,
      duration: dt.timedelta = dt.timedelta(milliseconds=400),
  ) -> None:
    """Perform a coordinate-based drag/swipe gesture in points."""
    session_id = self.ensure_session()
    payload = {
        "fromX": from_x,
        "fromY": from_y,
        "toX": to_x,
        "toY": to_y,
        "duration": duration.total_seconds(),
    }
    self._request(
        "POST",
        f"/session/{session_id}/wda/dragfromtoforduration",
        payload,
        timeout=self.REQUEST_TIMEOUT + duration)

  def swipe(
      self,
      from_x: int,
      from_y: int,
      to_x: int,
      to_y: int,
      duration: dt.timedelta = dt.timedelta(milliseconds=300),
      settle_duration: dt.timedelta = dt.timedelta(),
  ) -> None:
    """Perform a coordinate-based touch swipe gesture in points."""
    session_id = self.ensure_session()
    duration_ms = max(50, int(duration.total_seconds() * 1000))
    settle_ms = max(0, int(settle_duration.total_seconds() * 1000))
    actions: list[dict[str, Any]] = [
        {
            "type": "pointerMove",
            "duration": 0,
            "x": from_x,
            "y": from_y,
        },
        {
            "type": "pointerDown",
            "button": 0,
        },
        {
            "type": "pause",
            "duration": 10,
        },
        {
            "type": "pointerMove",
            "duration": duration_ms,
            "x": to_x,
            "y": to_y,
        },
    ]
    if settle_ms > 0:
      actions.append({
          "type": "pause",
          "duration": settle_ms,
      })
    actions.append({
        "type": "pointerUp",
        "button": 0,
    })
    payload = {
        "actions": [{
            "type": "pointer",
            "id": "finger1",
            "parameters": {
                "pointerType": "touch",
            },
            "actions": actions,
        }],
    }
    self._request(
        "POST",
        f"/session/{session_id}/actions",
        payload,
        timeout=self.REQUEST_TIMEOUT + duration + settle_duration)

  def scroll(self, direction: str = "down") -> None:
    """Perform a native scroll gesture (down, up, left, right)."""
    session_id = self.ensure_session()
    self._request(
        "POST",
        f"/session/{session_id}/wda/scroll",
        {"direction": direction},
        timeout=self.REQUEST_TIMEOUT,
    )

  def launch_app(
      self,
      bundle_id: str,
      arguments: Sequence[str] | None = None,
  ) -> None:
    """Launch an application on the device by bundle identifier."""
    session_id = self.ensure_session()
    payload: dict[str, object] = {"bundleId": bundle_id}
    if arguments:
      payload["arguments"] = list(arguments)
    self._request(
        "POST",
        f"/session/{session_id}/wda/apps/launch",
        payload,
        timeout=self.REQUEST_TIMEOUT,
    )

  def terminate_app(self, bundle_id: str) -> None:
    """Terminate an application on the device by bundle identifier."""
    session_id = self.ensure_session()
    self._request(
        "POST",
        f"/session/{session_id}/wda/apps/terminate",
        {"bundleId": bundle_id},
        timeout=self.REQUEST_TIMEOUT,
    )

  def open_url(self, url: str) -> None:
    """Open a URL in the active browser on device."""
    session_id = self.ensure_session()
    self._request(
        "POST",
        f"/session/{session_id}/url",
        {"url": url},
        timeout=self.REQUEST_TIMEOUT,
    )

  def stop(self) -> None:
    """Tear down any active xcodebuild process."""
    atexit.unregister(self.stop)
    if proc := self._xcodebuild_proc:
      self._xcodebuild_proc = None
      try:
        proc.terminate()
      except OSError as e:
        logging.warning("Failed to terminate xcodebuild process: %s", e)
    if self._is_forwarded:
      if self._platform.ports.is_own_forwarded_port_used(self._port):
        try:
          self._platform.ports.stop_forward(self._port)
        except (PortForwardException, OSError) as e:
          logging.warning("Failed to stop forwarding port %s: %s", self._port,
                          e)
      self._is_forwarded = False
