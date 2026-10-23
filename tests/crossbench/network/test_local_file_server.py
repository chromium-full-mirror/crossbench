# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import argparse
from unittest import mock

from typing_extensions import override

from crossbench import path as pth
from crossbench.network.local_file_server import CustomHeadersRequestHandler, \
    LocalFileNetwork, LocalThreadingHTTPServer
from crossbench.plt.port_manager import PortForwardException
from crossbench.runner.groups.session import BrowserSessionRunGroup
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase


class LocalFileNetworkTestCase(BaseCrossbenchTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.server_dir = pth.LocalPath("/foo/bar")
    self.fs.create_dir(self.server_dir)

  def create_session(self,
                     is_remote: bool = False,
                     supports_reverse_port_forwarding: bool = True):
    browser_platform = mock.Mock()
    browser_platform.is_remote = is_remote
    browser_platform.supports_reverse_port_forwarding = (
        supports_reverse_port_forwarding)
    return mock.Mock(
        spec=BrowserSessionRunGroup, browser_platform=browser_platform)

  def test_defaults(self):
    network = LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    self.assertTrue(network.is_local_file_server)
    self.assertFalse(network.is_live)
    self.assertFalse(network.is_wpr)
    self.assertFalse(network.is_running)
    self.assertEqual(network.path, self.server_dir)
    self.assertEqual(network.host, "localhost")
    self.assertEqual(network.http_port, 8000)
    self.assertIsNone(network.https_port)
    self.assertIn("LOCAL(path=/foo/bar", str(network))
    self.assertIn("Cross-Origin-Opener-Policy", str(network))
    self.assertIn("Cross-Origin-Embedder-Policy", str(network))

  def test_custom_url(self):
    network = LocalFileNetwork(
        self.server_dir,
        "http://127.0.0.1:9090",
        browser_platform=self.platform)
    self.assertEqual(network.host, "127.0.0.1")
    self.assertEqual(network.http_port, 9090)

    network_default_port = LocalFileNetwork(
        self.server_dir, "http://myhost.local", browser_platform=self.platform)
    self.assertEqual(network_default_port.host, "myhost.local")
    self.assertEqual(network_default_port.http_port, 8000)

  def test_invalid_url(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      LocalFileNetwork(
          self.server_dir, "://invalid-url", browser_platform=self.platform)

  def test_server_and_handler_defaults(self):
    self.assertEqual(CustomHeadersRequestHandler.protocol_version, "HTTP/1.1")
    bound_cls = CustomHeadersRequestHandler.bind(self.server_dir,
                                                 {"X-Test": "1"})
    self.assertEqual(bound_cls.protocol_version, "HTTP/1.1")
    with mock.patch("http.server.SimpleHTTPRequestHandler.__init__") as (
        mock_super_init):
      handler = bound_cls("req", ("127.0.0.1", 8000), mock.Mock())
    self.assertEqual(dict(handler.extra_headers), {"X-Test": "1"})
    mock_super_init.assert_called_once_with(
        "req", ("127.0.0.1", 8000), mock.ANY, directory=str(self.server_dir))
    self.assertEqual(LocalThreadingHTTPServer.request_queue_size, 128)
    self.assertTrue(LocalThreadingHTTPServer.daemon_threads)
    self.assertFalse(LocalThreadingHTTPServer.block_on_close)

  @mock.patch("crossbench.network.local_file_server."
              "LocalFileNetwork._validate_extra_headers")
  def test_init_validates_headers(self, mock_val):
    LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    mock_val.assert_called_once_with()

  def test_custom_headers_file(self):
    headers_file = self.server_dir / "HEADERS"
    self.fs.create_file(
        headers_file,
        contents="X-Custom-One: value1\nCache-Control: max-age=3600\n")
    self.fs.create_file(
        self.server_dir / "HEADERS.txt", contents="X-Ignored: value2\n")
    network = LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    self.assertEqual(
        dict(network.extra_headers), {
            "X-Custom-One": "value1",
            "Cache-Control": "max-age=3600",
        })
    self.assertIn("X-Custom-One", str(network))
    self.assertNotIn("Cross-Origin-Opener-Policy", str(network))

  def test_custom_headers_txt_file(self):
    headers_file = self.server_dir / "HEADERS.txt"
    self.fs.create_file(headers_file, contents="X-Custom-Two: value2\n")
    network = LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    self.assertEqual(dict(network.extra_headers), {"X-Custom-Two": "value2"})

  def test_empty_headers_file(self):
    headers_file = self.server_dir / "HEADERS"
    self.fs.create_file(headers_file, contents="")
    network = LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    self.assertEqual(dict(network.extra_headers), {})
    self.assertNotIn("extra_headers=", str(network))

  def test_conflicting_headers_logs_error(self):
    headers_file = self.server_dir / "HEADERS"
    self.fs.create_file(
        headers_file, contents="Content-Type: text/plain\nX-Safe: ok\n")
    with self.assertLogs(level="ERROR") as cm:
      LocalFileNetwork(self.server_dir, browser_platform=self.platform)
    self.assertTrue(
        any("Content-Type: text/plain" in output for output in cm.output))

  def test_request_handler_empty_custom_headers(self):
    with mock.patch("http.server.SimpleHTTPRequestHandler.__init__"):
      empty_handler = CustomHeadersRequestHandler("req", ("127.0.0.1", 8000),
                                                  mock.Mock())
    self.assertEqual(dict(empty_handler.extra_headers), {})
    with (mock.patch("http.server.SimpleHTTPRequestHandler.end_headers"),
          mock.patch.object(empty_handler, "send_header") as mock_send_empty):
      empty_handler.end_headers()
    mock_send_empty.assert_not_called()

  def test_request_handler_send_custom_headers(self):
    with mock.patch("http.server.SimpleHTTPRequestHandler.__init__"):
      custom_handler = CustomHeadersRequestHandler(
          "req", ("127.0.0.1", 8000),
          mock.Mock(),
          extra_headers={
              "X-Foo": "bar",
              "X-Baz": "qux",
          })
    with (mock.patch("http.server.SimpleHTTPRequestHandler.end_headers"),
          mock.patch.object(custom_handler, "send_header") as mock_send_custom):
      custom_handler.end_headers()
    mock_send_custom.assert_has_calls([
        mock.call("X-Foo", "bar"),
        mock.call("X-Baz", "qux"),
    ])

  @mock.patch("crossbench.network.local_file_server.LocalThreadingHTTPServer")
  def test_open_local(self, mock_server_cls):
    mock_server = mock_server_cls.return_value
    mock_server.__enter__.return_value = mock_server
    mock_server.server_port = 54321
    network = LocalFileNetwork(
        self.server_dir, "http://127.0.0.1:0", browser_platform=self.platform)
    session = self.create_session(is_remote=False)

    with network.open(session):
      self.assertTrue(network.is_running)
      self.assertEqual(network.http_port, 54321)
      with self.assertRaises(AssertionError):
        with network.open(session):
          pass
    self.assertFalse(network.is_running)
    mock_server.shutdown.assert_called_once_with()
    session.browser_platform.ports.reverse_forward.assert_not_called()

  @mock.patch("crossbench.network.local_file_server.LocalThreadingHTTPServer")
  def test_open_remote_port_forwarding(self, mock_server_cls):
    mock_server = mock_server_cls.return_value
    mock_server.__enter__.return_value = mock_server
    mock_server.server_port = 8123
    network = LocalFileNetwork(
        self.server_dir,
        "http://localhost:8123",
        browser_platform=self.platform)
    session = self.create_session(is_remote=True)

    with network.open(session):
      self.assertTrue(network.is_running)
      session.browser_platform.ports.reverse_forward.assert_called_once_with(
          8123, 8123)
      session.browser_platform.ports.stop_reverse_forward.assert_not_called()
    self.assertFalse(network.is_running)
    session.browser_platform.ports.stop_reverse_forward.assert_called_once_with(
        8123)

  @mock.patch("crossbench.network.local_file_server.LocalThreadingHTTPServer")
  def test_open_remote_without_port_forwarding(self, mock_server_cls):
    mock_server = mock_server_cls.return_value
    mock_server.__enter__.return_value = mock_server
    mock_server.server_port = 8123
    network = LocalFileNetwork(
        self.server_dir,
        "http://localhost:8123",
        browser_platform=self.platform)
    session = self.create_session(
        is_remote=True, supports_reverse_port_forwarding=False)

    with self.assertRaisesRegex(PortForwardException,
                                "reverse port forwarding"):
      with network.open(session):
        pass
    self.assertFalse(network.is_running)
    session.browser_platform.ports.reverse_forward.assert_not_called()
    mock_server.shutdown.assert_called_once_with()


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
