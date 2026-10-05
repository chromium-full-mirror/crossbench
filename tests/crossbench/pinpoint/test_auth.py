# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import google.auth
import google.auth.exceptions
from typing_extensions import override

from crossbench.cli.ui import ui
from crossbench.exception import MultiException
from crossbench.pinpoint import auth
from crossbench.pinpoint.exceptions import AuthenticationError, \
    GCloudNotInstalledError
from crossbench.plt.bin import Binaries, Binary
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase

if TYPE_CHECKING:
  from crossbench import path as pth


class AuthTestCase(BaseCrossbenchTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    auth.get_auth_session.cache_clear()
    self.google_auth_default = self.enterContext(
        mock.patch.object(google.auth, "default"))
    self.google_auth_default.side_effect = (
        google.auth.exceptions.DefaultCredentialsError())
    self.ui_prompt = self.enterContext(mock.patch.object(ui, "prompt"))

  def _install_binary(self, binary: Binary) -> pth.AnyPath:
    binary_path = self.platform.path(f"/usr/bin/{binary.name}")
    self.fs.create_file(binary_path)
    self.platform.set_binary_lookup_override(binary.name, binary_path)
    return binary_path

  def test_get_auth_session_luci_auth_success(self) -> None:
    luci_auth_bin = self._install_binary(Binaries.LUCI_AUTH)
    self.platform.expect_sh(luci_auth_bin, "token", result="test_luci_token\n")

    session = auth.get_auth_session()

    self.assertEqual(session.credentials.token, "test_luci_token")
    self.google_auth_default.assert_not_called()
    self.ui_prompt.assert_not_called()

  def test_get_auth_session_luci_auth_fails_fallback_to_gcloud(self) -> None:
    luci_auth_bin = self._install_binary(Binaries.LUCI_AUTH)
    self._install_binary(Binaries.GCLOUD)
    self.platform.expect_sh(luci_auth_bin, "token", returncode=1)
    mock_credentials = mock.Mock()
    self.google_auth_default.side_effect = None
    self.google_auth_default.return_value = (mock_credentials, "project_id")

    session = auth.get_auth_session()

    self.google_auth_default.assert_called_once()
    self.assertEqual(session.credentials, mock_credentials)

  def test_get_auth_session_luci_auth_empty_token_fallback_to_gcloud(
      self) -> None:
    luci_auth_bin = self._install_binary(Binaries.LUCI_AUTH)
    self._install_binary(Binaries.GCLOUD)
    self.platform.expect_sh(luci_auth_bin, "token", result="  \n")
    mock_credentials = mock.Mock()
    self.google_auth_default.side_effect = None
    self.google_auth_default.return_value = (mock_credentials, "project_id")

    session = auth.get_auth_session()

    self.google_auth_default.assert_called_once()
    self.assertEqual(session.credentials, mock_credentials)

  def test_get_auth_session_luci_auth_fails_gcloud_missing(self) -> None:
    luci_auth_bin = self._install_binary(Binaries.LUCI_AUTH)
    self.platform.expect_sh(luci_auth_bin, "token", returncode=1)

    with self.assertRaises(MultiException) as cm:
      auth.get_auth_session()
    self.assertTrue(cm.exception.matching(GCloudNotInstalledError))

  def test_get_auth_session_gcloud_missing(self) -> None:
    # User says "yes" to running gcloud
    self.ui_prompt.return_value = "y"
    # But gcloud is missing (default state in fake fs)

    with self.assertRaises(MultiException) as cm:
      auth.get_auth_session()
    self.assertTrue(cm.exception.matching(GCloudNotInstalledError))

    self.assertEqual(self.platform.sh_cmds, [])

  def test_get_auth_session_gcloud_present(self) -> None:
    # User says "yes" to running gcloud
    self.ui_prompt.return_value = "y"

    gcloud_bin = self._install_binary(Binaries.GCLOUD)
    self.platform.expect_sh(
        gcloud_bin, "auth", "application-default", "login", result="logged in")

    # Second call needs to succeed otherwise we loop
    self.google_auth_default.side_effect = [
        google.auth.exceptions.DefaultCredentialsError(),
        (mock.Mock(), "project_id"),
    ]

    auth.get_auth_session()

  def test_get_auth_session_prompt_rejected(self) -> None:
    self.ui_prompt.return_value = "n"
    self._install_binary(Binaries.GCLOUD)

    with self.assertRaises(MultiException) as cm:
      auth.get_auth_session()
    self.assertTrue(cm.exception.matching(AuthenticationError))
    errors = cm.exception.matching(AuthenticationError)
    self.assertIn("gcloud auth application-default login", str(errors[0]))

  def test_get_auth_session_refresh_error(self) -> None:
    self.ui_prompt.return_value = "n"
    self._install_binary(Binaries.GCLOUD)
    self.google_auth_default.side_effect = (
        google.auth.exceptions.RefreshError("token expired"))

    with self.assertRaises(MultiException) as cm:
      auth.get_auth_session()
    self.assertTrue(cm.exception.matching(AuthenticationError))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
