# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, ClassVar, cast
from unittest import mock

from crossbench.plt.port_manager import PortForwardException, PortManager, \
    SubprocessPortManager
from tests import test_helper
from tests.crossbench.mock_helper import LinuxMockPlatform, \
    MockRemotePortManager

if TYPE_CHECKING:
  import subprocess

  from crossbench.plt.base import Platform


class FakePortLinuxMockPlatform(LinuxMockPlatform):

  def _create_port_manager(self) -> PortManager:
    return MockRemotePortManager(self)


class PortManagerTestCase(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.platform = FakePortLinuxMockPlatform()
    self.port_scope = self.platform.ports
    self.port_manager: MockRemotePortManager = cast(MockRemotePortManager,
                                                    self.platform.port_manager)
    self.assertIsInstance(self.port_manager, MockRemotePortManager)

  def tearDown(self):
    self.assertFalse(self.port_manager.forwarded_ports)
    self.assertFalse(self.port_manager.reverse_forwarded_ports)
    self.assertTrue(self.port_scope.is_empty)
    super().tearDown()

  def test_default(self):
    self.assertTrue(self.port_scope.is_empty)
    self.assertFalse(self.port_manager.has_nested_scopes)

  def test_nested(self):
    self.assertTrue(self.port_scope.is_empty)
    with self.port_scope.nested() as scope:
      self.assertFalse(self.port_manager.is_empty)
      self.assertTrue(self.port_scope.is_empty)
      self.assertTrue(scope.is_empty)
      self.assertTrue(self.port_manager.has_nested_scopes)
    self.assertTrue(self.port_scope.is_empty)

  def test_stop(self):
    self.port_manager.stop()
    self.assertTrue(self.port_scope.is_empty)
    self.assertFalse(self.port_manager.has_nested_scopes)

  def test_forward_port(self):
    with self.port_scope.nested() as port_scope:
      returned_local_port = port_scope.forward(12345, 8080)
      self.assertEqual(returned_local_port, 12345)
      self.assertIn(12345, self.port_manager.forwarded_ports)
      self.assertEqual(self.port_manager.forwarded_ports[12345], 8080)
      self.assertFalse(port_scope.is_empty)
    self.assertFalse(self.port_manager.forwarded_ports)
    self.assertTrue(port_scope.is_empty)

  def test_forward_port_auto_assign(self):
    with self.port_scope.nested() as port_scope:
      returned_local_port = port_scope.forward(0, 8080)
      self.assertEqual(returned_local_port, 60001)
      self.assertIn(60001, self.port_manager.forwarded_ports)

  def test_stop_forward_port(self):
    with self.port_scope.nested() as port_scope:
      port_scope.forward(12345, 8080)
      port_scope.stop_forward(12345)
      self.assertNotIn(12345, self.port_manager.forwarded_ports)

  def test_forward_port_conflict(self):
    with self.port_scope.nested() as port_scope:
      port_scope.forward(12345, 8080)
      with self.assertRaises(PortForwardException):
        # Try to forward same local port
        port_scope.forward(12345, 8081)

  def test_stop_forward_port_not_forwarded(self):
    with self.port_scope.nested() as port_scope:
      with self.assertRaises(PortForwardException):
        port_scope.stop_forward(12345)

  def test_reverse_forward_port(self):
    with self.port_scope.nested() as port_scope:
      returned_remote_port = port_scope.reverse_forward(54321, 8081)
      self.assertEqual(returned_remote_port, 54321)
      self.assertIn(54321, self.port_manager.reverse_forwarded_ports)
      self.assertEqual(self.port_manager.reverse_forwarded_ports[54321], 8081)
      self.assertFalse(port_scope.is_empty)

  def test_reverse_forward_port_auto_assign(self):
    with self.port_scope.nested() as port_scope:
      returned_remote_port = port_scope.reverse_forward(0, 8081)
      self.assertEqual(returned_remote_port, 60001)
      self.assertIn(60001, self.port_manager.reverse_forwarded_ports)

  def test_stop_reverse_forward_port(self):
    with self.port_scope.nested() as port_scope:
      port_scope.reverse_forward(54321, 8081)
      port_scope.stop_reverse_forward(54321)
      self.assertNotIn(54321, self.port_manager.reverse_forwarded_ports)

  def test_reverse_forward_port_conflict(self):
    with self.port_scope.nested() as port_scope:
      port_scope.reverse_forward(54321, 8081)
      with self.assertRaises(PortForwardException):
        # Try to reverse forward same remote port
        port_scope.reverse_forward(54321, 8082)

  def test_stop_reverse_forward_port_not_forwarded(self):
    with self.port_scope.nested() as port_scope:
      with self.assertRaises(PortForwardException):
        port_scope.stop_reverse_forward(54321)

  def test_nested_cleanup(self):
    self.port_scope.forward(1111, 2222)
    with self.port_scope.nested() as port_scope:
      port_scope.forward(3333, 4444)
    self.assertIn(1111, self.port_manager.forwarded_ports)
    self.assertNotIn(3333, self.port_manager.forwarded_ports)
    self.assertFalse(self.port_manager.has_nested_scopes)
    self.port_manager.stop()
    self.assertTrue(self.port_scope.is_empty)
    self.assertNotIn(1111, self.port_manager.forwarded_ports)
    self.assertNotIn(3333, self.port_manager.forwarded_ports)

  def test_forward_nested_cleanup_stop_outer(self):
    self.port_scope.forward(1111, 2222)
    with self.port_scope.nested() as port_scope:
      port_scope.forward(3333, 4444)
      port_scope.stop_forward(3333)
      with self.assertRaisesRegex(PortForwardException, "1111"):
        port_scope.stop_forward(1111)
    self.port_scope.stop_forward(1111)

  def test_reverse_forward_nested_cleanup_stop_outer(self):
    self.port_scope.reverse_forward(1111, 2222)
    with self.port_scope.nested() as port_scope:
      port_scope.reverse_forward(3333, 4444)
      port_scope.stop_reverse_forward(3333)
      with self.assertRaisesRegex(PortForwardException, "1111"):
        port_scope.stop_reverse_forward(1111)
    self.port_scope.stop_reverse_forward(1111)

  def test_root_scope(self):
    self.assertIs(self.port_scope.root_scope, self.port_scope)
    with self.port_scope.nested() as scope_1:
      self.assertIs(scope_1.root_scope, self.port_scope)
      with scope_1.nested() as scope_2:
        self.assertIs(scope_2.root_scope, self.port_scope)

  def test_root_scope_forward_persists_across_nested_scopes(self):
    with self.port_scope.nested() as scope_1:
      local_port = scope_1.root_scope.forward(1111, 2222)
      self.assertEqual(local_port, 1111)
      self.assertTrue(scope_1.is_forwarded_port_used(1111))
      self.assertFalse(scope_1.is_own_forwarded_port_used(1111))
      self.assertTrue(self.port_scope.is_own_forwarded_port_used(1111))
    self.assertTrue(self.port_scope.is_own_forwarded_port_used(1111))
    self.assertIn(1111, self.port_manager.forwarded_ports)
    self.port_scope.stop_forward(1111)


class ForwardOnlySubprocessPortManager(SubprocessPortManager):
  """Only supports forwarding, like iproxy on iOS."""

  def __init__(self, platform: Platform, throw: bool = False) -> None:
    super().__init__(platform, throw)
    self.forward_procs: dict[int, mock.MagicMock] = {}

  def _popen_forward(self, local_port: int,
                     remote_port: int) -> subprocess.Popen:
    proc = mock.MagicMock(name=f"forward {local_port}:{remote_port}")
    self.forward_procs[local_port] = proc
    return proc


class FakeSubprocessPortManager(ForwardOnlySubprocessPortManager):
  """Supports forwarding and reverse forwarding, like ssh."""

  def __init__(self, platform: Platform, throw: bool = False) -> None:
    super().__init__(platform, throw)
    self.reverse_procs: dict[int, mock.MagicMock] = {}

  def _popen_reverse_forward(self, remote_port: int,
                             local_port: int) -> subprocess.Popen:
    proc = mock.MagicMock(name=f"reverse {remote_port}:{local_port}")
    self.reverse_procs[remote_port] = proc
    return proc


class SubprocessPortPlatform(LinuxMockPlatform):
  PORT_MANAGER_CLS: ClassVar[type[SubprocessPortManager]] = (
      FakeSubprocessPortManager)

  def _create_port_manager(self) -> PortManager:
    return self.PORT_MANAGER_CLS(self)


class ForwardOnlySubprocessPortPlatform(SubprocessPortPlatform):
  PORT_MANAGER_CLS = ForwardOnlySubprocessPortManager


class SubprocessPortManagerTestCase(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.platform = SubprocessPortPlatform()
    self.port_manager = cast(FakeSubprocessPortManager,
                             self.platform.port_manager)
    self.mock_wait_for_port = self.enterContext(
        mock.patch.object(type(self.platform), "wait_for_port"))
    self.mock_get_free_port = self.enterContext(
        mock.patch.object(
            type(self.platform), "get_free_port", return_value=60001))

  def tearDown(self):
    self.assertTrue(self.platform.ports.is_empty)
    super().tearDown()

  def test_forward(self):
    with self.platform.ports.nested() as ports:
      self.assertEqual(ports.forward(12345, 8080), 12345)
      self.mock_wait_for_port.assert_called_once_with(
          12345, SubprocessPortManager.PORT_FORWARDING_TIMEOUT)
      self.mock_get_free_port.assert_not_called()
      proc = self.port_manager.forward_procs[12345]
      proc.terminate.assert_not_called()
      self.assertTrue(ports.is_forwarded_port_used(12345))
    proc.terminate.assert_called_once_with()
    self.assertFalse(self.platform.ports.is_forwarded_port_used(12345))

  def test_forward_auto_assign(self):
    with self.platform.ports.nested() as ports:
      self.assertEqual(ports.forward(0, 8080), 60001)
      self.mock_get_free_port.assert_called_once_with()
      self.mock_wait_for_port.assert_called_once_with(
          60001, SubprocessPortManager.PORT_FORWARDING_TIMEOUT)
      self.assertIn(60001, self.port_manager.forward_procs)

  def test_forward_twice(self):
    with self.platform.ports.nested() as ports:
      ports.forward(12345, 8080)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        ports.forward(12345, 8081)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        self.port_manager.forward(12345, 8081)
      self.assertEqual(len(self.port_manager.forward_procs), 1)

  def test_forward_wait_failure_terminates_process(self):
    self.mock_wait_for_port.side_effect = TimeoutError("not bound")
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(TimeoutError, "not bound"):
        ports.forward(12345, 8080)
      self.port_manager.forward_procs[12345].terminate.assert_called_once()
      self.assertFalse(ports.is_forwarded_port_used(12345))
      # The port can be forwarded again after a failed attempt.
      self.mock_wait_for_port.side_effect = None
      self.assertEqual(ports.forward(12345, 8080), 12345)

  def test_forward_interrupt_terminates_process(self):
    self.mock_wait_for_port.side_effect = KeyboardInterrupt()
    with self.platform.ports.nested() as ports:
      with self.assertRaises(KeyboardInterrupt):
        ports.forward(12345, 8080)
      self.port_manager.forward_procs[12345].terminate.assert_called_once()
      self.assertFalse(ports.is_forwarded_port_used(12345))

  def test_reverse_forward_interrupt_terminates_process(self):
    self.mock_wait_for_port.side_effect = KeyboardInterrupt()
    with self.platform.ports.nested() as ports:
      with self.assertRaises(KeyboardInterrupt):
        ports.reverse_forward(54321, 8081)
      self.port_manager.reverse_procs[54321].terminate.assert_called_once()
      self.assertFalse(ports.is_reverse_forwarded_port_used(54321))

  def test_stop_forward_terminate_failure_propagates(self):
    with self.platform.ports.nested() as ports:
      ports.forward(12345, 8080)
      proc = self.port_manager.forward_procs[12345]
      proc.terminate.side_effect = PermissionError("not ours")
      with self.assertRaisesRegex(PermissionError, "not ours"):
        ports.stop_forward(12345)
      # The port is unregistered even though terminate() failed.
      self.assertFalse(ports.is_forwarded_port_used(12345))

  def test_reverse_forward(self):
    with self.platform.ports.nested() as ports:
      self.assertEqual(ports.reverse_forward(54321, 8081), 54321)
      self.mock_wait_for_port.assert_called_once_with(
          54321, SubprocessPortManager.PORT_FORWARDING_TIMEOUT)
      proc = self.port_manager.reverse_procs[54321]
      proc.terminate.assert_not_called()
      self.assertTrue(ports.is_reverse_forwarded_port_used(54321))
    proc.terminate.assert_called_once_with()
    self.assertFalse(self.platform.ports.is_reverse_forwarded_port_used(54321))

  def test_reverse_forward_auto_assign_local_port(self):
    with self.platform.ports.nested() as ports:
      self.assertEqual(ports.reverse_forward(54321, 0), 54321)
      self.mock_get_free_port.assert_called_once_with()

  def test_reverse_forward_twice(self):
    with self.platform.ports.nested() as ports:
      ports.reverse_forward(54321, 8081)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        ports.reverse_forward(54321, 8082)
      with self.assertRaisesRegex(PortForwardException, "twice"):
        self.port_manager.reverse_forward(54321, 8082)
      self.assertEqual(len(self.port_manager.reverse_procs), 1)

  def test_reverse_forward_wait_failure_terminates_process(self):
    self.mock_wait_for_port.side_effect = TimeoutError("not bound")
    with self.platform.ports.nested() as ports:
      with self.assertRaisesRegex(TimeoutError, "not bound"):
        ports.reverse_forward(54321, 8081)
      self.port_manager.reverse_procs[54321].terminate.assert_called_once()
      self.assertFalse(ports.is_reverse_forwarded_port_used(54321))
      # The port can be reverse forwarded again after a failed attempt.
      self.mock_wait_for_port.side_effect = None
      self.assertEqual(ports.reverse_forward(54321, 8081), 54321)

  def test_reverse_forward_not_supported(self):
    platform = ForwardOnlySubprocessPortPlatform()
    with platform.ports.nested() as ports:
      with self.assertRaisesRegex(NotImplementedError, "reverse_forward"):
        ports.reverse_forward(54321, 8081)
      self.assertFalse(ports.is_reverse_forwarded_port_used(54321))
      self.assertEqual(ports.forward(12345, 8080), 12345)
    self.assertTrue(platform.ports.is_empty)

  def test_reforward_after_stop_forward(self):
    with self.platform.ports.nested() as ports:
      ports.forward(12345, 8080)
      first_proc = self.port_manager.forward_procs[12345]
      ports.stop_forward(12345)
      first_proc.terminate.assert_called_once_with()
      self.assertEqual(ports.forward(12345, 8080), 12345)
      self.assertIsNot(self.port_manager.forward_procs[12345], first_proc)

  def test_stop_terminates_all_processes(self):
    self.platform.ports.forward(1111, 2222)
    self.platform.ports.reverse_forward(3333, 4444)
    self.port_manager.stop()
    self.port_manager.forward_procs[1111].terminate.assert_called_once()
    self.port_manager.reverse_procs[3333].terminate.assert_called_once()
    self.assertTrue(self.platform.ports.is_empty)


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
