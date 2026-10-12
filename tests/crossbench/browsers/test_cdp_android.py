# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import contextlib
import datetime as dt
from typing import Any, Iterator
from unittest import mock

import websocket

from crossbench.action_runner.action.enums import WindowTarget
from crossbench.browsers.attributes import BrowserAttributes
from crossbench.browsers.cdp_android import CdpAndroidBrowser
from crossbench.browsers.chromium.devtools import DevToolsCommandResult, \
    DevToolsRemoteClient
from crossbench.browsers.chromium.version import ChromiumVersion
from crossbench.browsers.settings import Settings
from crossbench.flags.base import Flags
from crossbench.plt.android_adb import AndroidAdbPlatform
from crossbench.plt.pyodide_adb import PyodideAndroidAdbPlatform
from crossbench.runner.groups.session import BrowserSessionRunGroup
from tests import test_helper
from tests.crossbench.base import CrossbenchFakeFsTestCase
from tests.crossbench.mock_helper import LinuxMockPlatform


class MockDevToolsRemoteClient:

  def __init__(self) -> None:
    self.connected = False
    self.commands: list[dict[str, Any]] = []
    self.next_response: tuple[bool, dict[str, Any]] | None = None
    self._next_id: int = 0

  def get_next_id(self) -> int:
    self._next_id += 1
    return self._next_id

  def _get_next_id(self) -> int:
    return self.get_next_id()

  def connect(self, timeout: dt.timedelta = dt.timedelta(seconds=10)) -> None:
    del timeout
    self.connected = True

  def disconnect(self) -> None:
    self.connected = False

  def send_command(self,
                   command_payload: dict[str, object]) -> DevToolsCommandResult:
    self.commands.append(command_payload)
    if self.next_response is not None:
      return DevToolsCommandResult(*self.next_response)
    cmd_id = command_payload.get("id", 1)
    return DevToolsCommandResult(True, {"id": cmd_id, "result": {}})

  def switch_to_new_tab(self, url: str = "about:blank") -> str:
    self.commands.append({
        "method": "Target.createTarget",
        "params": {
            "url": url,
        },
    })
    return "mock_session_id"


class CdpAndroidBrowserTest(CrossbenchFakeFsTestCase):
  __test__ = True

  def setUp(self) -> None:
    super().setUp()
    self.host_platform = LinuxMockPlatform()
    mock_adb = mock.Mock()
    mock_adb.serial_id = "mock-android"
    mock_adb.dumpsys.return_value = "versionName=130.0.6723.58"
    self.platform = AndroidAdbPlatform(
        self.host_platform,
        device_identifier="mock-android",
        adb=mock_adb,
    )
    self.mock_devtools = MockDevToolsRemoteClient()
    self.platform._devtools_client = (
        self.mock_devtools  # type: ignore[assignment]
    )
    self.platform.app_path_to_package = (  # type: ignore[method-assign]
        mock.Mock(return_value="com.android.chrome"))
    self.browser = CdpAndroidBrowser(
        label="cdp-chrome",
        path=self.platform.path("/system/app/Chrome.apk"),
        settings=Settings(platform=self.platform),
    )

  def test_attributes(self) -> None:
    attrs = CdpAndroidBrowser.attributes()
    self.assertIn(BrowserAttributes.CHROME, attrs)
    self.assertIn(BrowserAttributes.CHROMIUM_BASED, attrs)
    self.assertIn(BrowserAttributes.MOBILE, attrs)
    self.assertEqual(CdpAndroidBrowser.type_name(), "cdp-android")
    self.assertEqual(CdpAndroidBrowser.version_cls(), ChromiumVersion)

  def test_start_flag_filtering_and_single_underscore(self) -> None:
    self.platform.write_text = mock.Mock()  # type: ignore[method-assign]
    self.browser.flags.set("--disable-sync")
    self.browser.flags.set("--window-size", "100,100")
    self.browser.flags.set("--foo", "bar")
    mock_session = mock.MagicMock(spec=BrowserSessionRunGroup)
    mock_session.browser = self.browser
    mock_session.extra_flags = Flags()
    mock_session.browser_flags = ()
    with mock.patch.object(self.browser, "_log_browser_start") as mock_log, \
         self.browser.network.open(mock_session):
      self.browser.start(mock_session)
      mock_log.assert_called_once()
    self.platform.write_text.assert_called()
    content = self.platform.write_text.call_args[0][1]
    self.assertTrue(content.startswith("_ "))
    self.assertNotIn("--disable-sync", content)
    self.assertNotIn("--window-size", content)
    self.assertIn("--foo=bar", content)

  def test_adb_force_clear(self) -> None:
    with mock.patch.object(self.platform, "sh"), \
         mock.patch.object(self.platform.adb, "force_clear") as mock_clear:
      self.browser.adb_force_clear()
      mock_clear.assert_called_once_with("com.android.chrome")

  def test_show_url(self) -> None:
    self.browser.show_url("https://example.com")
    self.assertEqual(len(self.mock_devtools.commands), 1)
    cmd = self.mock_devtools.commands[0]
    self.assertEqual(cmd["method"], "Page.navigate")
    self.assertEqual(cmd["params"]["url"], "https://example.com")

  def test_show_url_new_tab(self) -> None:
    self.browser.show_url("https://example.com", target=WindowTarget.NEW_TAB)
    self.assertEqual(len(self.mock_devtools.commands), 1)
    cmd = self.mock_devtools.commands[0]
    self.assertEqual(cmd["method"], "Target.createTarget")
    self.assertEqual(cmd["params"]["url"], "https://example.com")

  def test_switch_to_new_tab(self) -> None:
    self.browser.switch_to_new_tab()
    self.assertEqual(len(self.mock_devtools.commands), 1)
    cmd = self.mock_devtools.commands[0]
    self.assertEqual(cmd["method"], "Target.createTarget")
    self.assertEqual(cmd["params"]["url"], "about:blank")

  def test_js(self) -> None:
    self.mock_devtools.next_response = (
        True,
        {
            "id": 1,
            "result": {
                "result": {
                    "value": 42,
                },
            },
        },
    )
    res = self.browser.js("return 42;")
    self.assertEqual(res, 42)
    cmd = self.mock_devtools.commands[0]
    self.assertEqual(cmd["method"], "Runtime.evaluate")
    self.assertEqual(
        cmd["params"]["expression"],
        "(function(){return 42;}).apply(window, [])",
    )

  def test_js_with_arguments(self) -> None:
    self.mock_devtools.next_response = (
        True,
        {
            "id": 1,
            "result": {
                "result": {
                    "value": 30,
                },
            },
        },
    )
    res = self.browser.js(
        "return arguments[0] + arguments[1];", arguments=(10, 20))
    self.assertEqual(res, 30)
    cmd = self.mock_devtools.commands[-1]
    self.assertEqual(cmd["method"], "Runtime.evaluate")
    self.assertEqual(
        cmd["params"]["expression"],
        "(function(){return arguments[0] +"
        " arguments[1];}).apply(window, [10, 20])",
    )

  def test_js_exception(self) -> None:
    self.mock_devtools.next_response = (
        True,
        {
            "id": 1,
            "result": {
                "result": {
                    "type": "undefined",
                },
                "exceptionDetails": {
                    "exception": {
                        "description": "SyntaxError: Illegal return statement",
                    },
                },
            },
        },
    )
    with self.assertRaises(ValueError) as cm:
      self.browser.js("return 42;")
    self.assertIn("SyntaxError: Illegal return statement", str(cm.exception))

  def test_current_url(self) -> None:
    self.mock_devtools.next_response = (
        True,
        {
            "id": 1,
            "result": {
                "result": {
                    "value": "https://example.com",
                },
            },
        },
    )
    url = self.browser.current_url
    self.assertEqual(url, "https://example.com")

  def test_webadb_cdp_bridge(self) -> None:
    mock_webadb = mock.Mock()
    mock_webadb.isInterrupted.return_value = False
    mock_webadb.sendCdpCommand.return_value = '{"frameId": "mock_frame"}'
    pyodide_platform = PyodideAndroidAdbPlatform(
        self.host_platform,
        device_identifier="mock-android",
        webadb=mock_webadb,
    )
    pyodide_platform.app_path_to_package = (  # type: ignore[method-assign]
        mock.Mock(return_value="com.android.chrome"))
    pyodide_platform.app_version = (  # type: ignore[method-assign]
        mock.Mock(return_value="130.0.6723.58"))
    browser = CdpAndroidBrowser(
        label="cdp-chrome",
        path=pyodide_platform.path("/system/app/Chrome.apk"),
        settings=Settings(platform=pyodide_platform),
    )
    browser.show_url("https://example.com")
    mock_webadb.sendCdpCommand.assert_called_once_with(
        "Page.navigate", '{"url": "https://example.com"}')


@contextlib.contextmanager
def _mock_transport(
    client: DevToolsRemoteClient,
    response: dict[str, Any] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], mock.Mock]]:
  """Records the payloads reaching the websocket and fakes page sessions.

  Yields the list of sent payloads and the mocked page-session lookup.
  """
  sent_payloads: list[dict[str, Any]] = []

  def mock_send(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    sent_payloads.append(payload)
    return True, {"id": payload["id"], **(response or {"result": {}})}

  patch_send = mock.patch.object(
      client, "_send_raw_command", side_effect=mock_send)
  patch_session_id = mock.patch.object(
      client, "_get_page_session_id", return_value="mock-session")
  with patch_send, patch_session_id as mock_session_id:
    yield sent_payloads, mock_session_id


class DevToolsRemoteClientTest(CrossbenchFakeFsTestCase):
  __test__ = True

  def setUp(self) -> None:
    super().setUp()
    self.host_platform = LinuxMockPlatform()
    mock_adb = mock.Mock()
    mock_adb.serial_id = "mock-android"
    self.platform = AndroidAdbPlatform(
        self.host_platform,
        device_identifier="mock-android",
        adb=mock_adb,
    )
    self.client = DevToolsRemoteClient(platform=self.platform)

  def test_connect_retry_success(self) -> None:
    mock_ws_first = mock.Mock()
    mock_ws_first.connect.side_effect = (
        websocket.WebSocketConnectionClosedException("Lost"))
    mock_ws_second = mock.Mock()
    mock_ws_second.connected = True

    with mock.patch.object(
        self.platform.ports, "forward_devtools", return_value=12345), \
        mock.patch("websocket.WebSocket", side_effect=[
            mock_ws_first, mock_ws_second,
        ]):
      self.client.connect(timeout=dt.timedelta(seconds=1))

    mock_ws_first.close.assert_called_once()
    self.assertIs(self.client._ws, mock_ws_second)
    self.assertEqual(self.client._devtools_port, 12345)

  def test_connect_timeout_failure(self) -> None:
    mock_ws = mock.Mock()
    mock_ws.connect.side_effect = (
        websocket.WebSocketConnectionClosedException("Lost"))

    with mock.patch.object(
        self.platform.ports, "forward_devtools", return_value=12345), \
        mock.patch("websocket.WebSocket", return_value=mock_ws):
      with self.assertRaises(websocket.WebSocketConnectionClosedException):
        self.client.connect(timeout=dt.timedelta(seconds=0.1))

    self.assertIsNone(self.client._ws)
    self.assertEqual(self.client._devtools_port, 0)

  def test_send_command_browser_domains(self) -> None:
    with _mock_transport(self.client) as (payloads, mock_session_id):
      self.client.send_command(
          {"method": "NativeProfiling.dumpProfilingDataOfAllProcesses"})
      self.client.send_command({"method": "Browser.getVersion"})
      self.client.send_command({"method": "Target.getTargets"})

    mock_session_id.assert_not_called()
    self.assertEqual(len(payloads), 3)
    for payload in payloads:
      self.assertNotIn("sessionId", payload)
    self.assertEqual(len({payload["id"] for payload in payloads}), 3)

  def test_send_command_page_domain(self) -> None:
    with _mock_transport(self.client) as (payloads, _):
      self.client.send_command({
          "method": "Page.navigate",
          "params": {
              "url": "https://example.com",
          },
      })
      # Storage is implemented by frame targets as well, so it must keep
      # using the page session.
      self.client.send_command({"method": "Storage.getStorageKeyForFrame"})

    self.assertEqual(len(payloads), 2)
    for payload in payloads:
      self.assertEqual(payload.get("sessionId"), "mock-session")

  def test_send_command_explicit_session(self) -> None:
    with _mock_transport(self.client) as (payloads, mock_session_id):
      self.client.send_command({
          "method": "Page.navigate",
          "sessionId": "custom-session",
      })

    mock_session_id.assert_not_called()
    self.assertEqual(payloads[0]["sessionId"], "custom-session")

  def test_send_command_explicit_no_session(self) -> None:
    with _mock_transport(self.client) as (payloads, mock_session_id):
      self.client.send_command({"method": "Custom.command", "sessionId": None})

    mock_session_id.assert_not_called()
    self.assertNotIn("sessionId", payloads[0])

  def test_send_command_does_not_modify_payload(self) -> None:
    payload: dict[str, Any] = {"method": "Page.navigate"}
    with _mock_transport(self.client):
      self.client.send_command(payload)

    self.assertEqual(payload, {"method": "Page.navigate"})

  def test_send_command_protocol_error(self) -> None:
    error = {"code": -32601, "message": "'Custom.command' wasn't found"}
    with _mock_transport(self.client, response={"error": error}):
      success, response = self.client.send_command({"method": "Custom.command"})

    self.assertFalse(success)
    self.assertEqual(response["error"], error)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
