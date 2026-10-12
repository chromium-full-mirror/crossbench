# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
from contextlib import closing
from typing import TYPE_CHECKING, Any, Callable, Final, Iterator, NamedTuple, \
    Self

import websocket
from websocket import create_connection

from crossbench.helper import wait

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.plt.base import Platform


class DevToolsCommandResult(NamedTuple):
  # True if the command succeeded, False if DevTools replied with a
  # protocol error.
  success: bool
  # The full response message returned by the websocket.
  response: dict[str, object]


class DevToolsInBrowserClient:
  """Manages communication with the Chrome DevTools Protocol from within
     the browser context.
  """

  def open_frontend(self, browser: Browser, panel_name: str) -> None:
    with closing(create_connection(browser.ws_endpoint)) as ws:
      ws.send(
          json.dumps({
              "id": 1,  # short lived connection, id can be anything
              "method": "Target.openDevTools",
              "params": {
                  "targetId": browser.current_window_id(),
                  "panelId": panel_name,
              },
          }))
      result = json.loads(ws.recv())
      if "result" not in result:
        raise RuntimeError(f"Failed to open DevTools. Response: {result}")
      if "targetId" not in result["result"]:
        raise RuntimeError(f"Failed to open DevTools, no targetId: {result}")


# CDP domains that are only implemented by BrowserDevToolsAgentHost and thus
# must never be routed to a page session. Note that Storage is not part of
# this list: frame targets implement it as well.
BROWSER_CDP_PREFIXES: Final[tuple[str, ...]] = (
    "Browser.",
    "NativeProfiling.",
    "SystemInfo.",
    "Target.",
    "Tethering.",
)


class DevToolsRemoteClient:
  """Manages communication with the Chrome DevTools Protocol."""

  def __init__(
      self,
      platform: Platform,
      requested_local_port: int = 0,
      remote_devtools_identifier: str = "chrome_devtools_remote",
  ) -> None:
    self._platform: Final[Platform] = platform
    self._requested_local_port: Final[int] = requested_local_port
    self._remote_devtools_identifier: Final[str] = remote_devtools_identifier
    self._ws: websocket.WebSocket | None = None
    self._devtools_port: int = 0
    self._session_id: str | None = None
    self._next_id: int = 0

  def get_next_id(self) -> int:
    self._next_id += 1
    return self._next_id

  def _get_next_id(self) -> int:
    return self.get_next_id()

  def connect(self, timeout: dt.timedelta = dt.timedelta(seconds=10)) -> None:
    """Establishes a WebSocket connection to the DevTools service."""
    if self._ws and self._ws.connected:
      return
    try:
      if not self._devtools_port:
        self._devtools_port = self._platform.ports.forward_devtools(
            local_port=self._requested_local_port,
            remote_identifier=self._remote_devtools_identifier)
      url = f"ws://localhost:{self._devtools_port}/devtools/browser/"
      last_error: Exception | None = None
      try:
        for _ in wait.wait_with_backoff(timeout):
          try:
            self._ws = websocket.WebSocket()
            self._ws.connect(url)
            logging.debug(
                "DevTools connected: ws://localhost:%s/devtools/browser/",
                self._devtools_port)
            return
          except (websocket.WebSocketException, ConnectionRefusedError,
                  TimeoutError) as e:
            last_error = e
            if self._ws:
              with contextlib.suppress(Exception):
                self._ws.close()
              self._ws = None
      except TimeoutError as e:
        if last_error:
          raise last_error from e
        raise
    except (websocket.WebSocketException, ConnectionRefusedError,
            TimeoutError) as e:
      logging.error("DevTools connection error: %s", e)
      self._disconnect_internal()
      raise
    except Exception as e:
      logging.error("Unexpected error during DevTools connection: %s", e)
      self._disconnect_internal()
      raise

  def _disconnect_internal(self) -> None:
    if self._ws and self._ws.connected:
      try:
        self._ws.close()
      except websocket.WebSocketException as e:
        logging.warning("Error closing DevTools WebSocket: %s", e)
    self._ws = None
    self._session_id = None
    if self._devtools_port:
      try:
        self._platform.ports.stop_forward(self._devtools_port)
      except Exception as e:  # noqa: BLE001
        # Best effort to remove forwarding, log if it fails but don't crash
        logging.warning(
            "Error removing DevTools port forwarding for port %s: %s",
            self._devtools_port, e)
    self._devtools_port = 0

  def disconnect(self) -> None:
    """Closes the WebSocket connection and removes port forwarding."""
    self._disconnect_internal()
    logging.debug("DevTools disconnected")

  def _send_raw_command(
      self, command_payload: dict[str, object]) -> DevToolsCommandResult:
    if not self._ws or not self._ws.connected:
      raise RuntimeError("DevTools is not connected. Cannot send command.")

    expected_id = command_payload.get("id")
    if expected_id is None:
      raise ValueError("DevTools command requires an 'id' in the payload.")

    self._ws.send(json.dumps(command_payload).encode("utf-8"))
    while True:
      data = self._ws.recv()
      response = json.loads(data)
      if response.get("id") == expected_id:
        return DevToolsCommandResult(True, response)

  def _get_page_session_id(self) -> str:
    if self._session_id:
      return self._session_id
    _, response = self._send_raw_command({
        "id": self._get_next_id(),
        "method": "Target.getTargets",
    })
    if not isinstance(result := response.get("result"), dict):
      raise RuntimeError(f"Target.getTargets failed: {response}")
    target_infos = result.get("targetInfos", [])
    page_target_id = None
    for info in target_infos:
      if info.get("type") == "page":
        page_target_id = info.get("targetId")
        break
    if not page_target_id:
      _, response = self._send_raw_command({
          "id": self._get_next_id(),
          "method": "Target.createTarget",
          "params": {
              "url": "about:blank",
          },
      })
      if not isinstance(result := response.get("result"), dict):
        raise RuntimeError(f"Target.createTarget failed: {response}")
      page_target_id = result.get("targetId")
    if not page_target_id:
      raise RuntimeError("Failed to obtain a page targetId")
    _, response = self._send_raw_command({
        "id": self._get_next_id(),
        "method": "Target.attachToTarget",
        "params": {
            "targetId": page_target_id,
            "flatten": True,
        },
    })
    result = response.get("result")
    if not isinstance(result, dict) or "sessionId" not in result:
      raise RuntimeError(f"Target.attachToTarget failed: {response}")
    self._session_id = result["sessionId"]
    return self._session_id

  def switch_to_new_tab(self, url: str = "about:blank") -> str:
    """Creates a new page target and attaches to it as the active session."""
    _, response = self._send_raw_command({
        "id": self._get_next_id(),
        "method": "Target.createTarget",
        "params": {
            "url": url,
        },
    })
    if not isinstance(result := response.get("result"), dict):
      raise RuntimeError(f"Could not create new tab: {response}")
    page_target_id = result.get("targetId")
    if not page_target_id:
      raise RuntimeError(f"Could not get targetId for new tab: {response}")
    _, response = self._send_raw_command({
        "id": self._get_next_id(),
        "method": "Target.attachToTarget",
        "params": {
            "targetId": page_target_id,
            "flatten": True,
        },
    })
    result = response.get("result")
    if not isinstance(result, dict) or "sessionId" not in result:
      raise RuntimeError(
          f"Could not attach to new tab {page_target_id}: {response}")
    self._session_id = result["sessionId"]
    return self._session_id

  def send_command(self,
                   command_payload: dict[str, object]) -> DevToolsCommandResult:
    """Sends a command to DevTools and waits for the matching response.

    Commands are routed to a page session by default. Commands for
    browser-level domains (see BROWSER_CDP_PREFIXES) are sent to the browser
    session instead, since page targets do not implement them. Callers can
    override the routing by setting "sessionId" explicitly: to a session of
    their choice, or to None to target the browser session, in which case the
    key is stripped from the payload instead of being sent as null.

    An "id" is added automatically if the payload does not provide one.

    Args:
      command_payload: The command payload to send.

    Returns:
      DevToolsCommandResult with (success, response).
    """
    command_payload = dict(command_payload)
    command_payload.setdefault("id", self._get_next_id())
    method = str(command_payload.get("method", ""))
    if "sessionId" in command_payload:
      if command_payload["sessionId"] is None:
        del command_payload["sessionId"]
    elif not method.startswith(BROWSER_CDP_PREFIXES):
      if session_id := self._get_page_session_id():
        command_payload["sessionId"] = session_id
    success, response = self._send_raw_command(command_payload)
    return DevToolsCommandResult(success and "error" not in response, response)

  def dispatch_command(self, command_payload: dict[str, Any]) -> bool:
    """Dispatches a command to DevTools. Does not wait for any response.

    Args:
      command_payload: The command payload to send. Must include an 'id'.

    Returns:
      bool: True if the command was sent successfully, False otherwise.
    """
    if not self._ws or not self._ws.connected:
      logging.error("DevTools is not connected. Cannot send command.")
      return False

    expected_id = command_payload.get("id")
    if expected_id is None:
      logging.error("DevTools command requires an 'id' in the payload.")
      return False

    try:
      self._ws.send(json.dumps(command_payload).encode("utf-8"))
      return True
    except (websocket.WebSocketException, ConnectionRefusedError,
            TimeoutError) as e:
      logging.error("DevTools communication error: %s", e)
      return False
    except json.JSONDecodeError as e:
      logging.error("Error decoding JSON response from DevTools: %s", e)
      return False

  def poll_for_response(
      self,
      condition_fn: Callable[[], bool],
      process_fn: Callable[[dict], None],
      timeout: dt.timedelta = dt.timedelta(seconds=1),
  ) -> bool:
    """Polls for DevTools events and processes them until a condition is met or
       a timeout occurs.

    Args:
      condition_fn: A boolean function that determines whether we should
                    continue polling for more events. Polling stops when this
                    function returns False.
      process_fn:   Function that takes each response as input for
                    processing.
      timeout:      Total number of seconds to poll for events before timing
                    out.

    Returns:
      bool: True if the condition was met (condition_fn returned False),
            False if the timeout was reached.
    """
    if not self._ws or not self._ws.connected:
      logging.error("DevTools is not connected. Cannot poll events.")
      return False
    deadline = dt.datetime.now() + timeout
    try:
      self._ws.settimeout(timeout.total_seconds())
      while condition_fn():
        data = self._ws.recv()
        response = json.loads(data)
        process_fn(response)
        if dt.datetime.now() > deadline:
          return False
        self._ws.settimeout((deadline - dt.datetime.now()).total_seconds())
    except (TimeoutError, json.JSONDecodeError):
      return False
    finally:
      self._ws.settimeout(None)
    return True

  @contextlib.contextmanager
  def open(self) -> Iterator[Self]:
    self.connect()
    try:
      yield self
    finally:
      self.disconnect()
