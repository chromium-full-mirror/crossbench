# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import warnings
from functools import cache

from google import auth as google_auth
from google.auth.transport import requests as auth_requests
from google.oauth2 import credentials as oauth2_credentials

from crossbench import plt
from crossbench.cli.ui import ui
from crossbench.pinpoint.exceptions import AuthenticationError, \
    GCloudNotInstalledError
from crossbench.pinpoint.helper import annotate
from crossbench.plt.bin import Binaries


def _get_luci_auth_session() -> auth_requests.AuthorizedSession | None:
  if not (luci_auth_bin := Binaries.LUCI_AUTH.search(plt.PLATFORM)):
    return None
  try:
    token = plt.PLATFORM.sh_stdout(luci_auth_bin, "token").strip()
  except plt.SubprocessError as e:
    logging.debug("luci-auth failed: %s", e)
    return None
  if not token:
    return None
  credentials = oauth2_credentials.Credentials(token)
  return auth_requests.AuthorizedSession(credentials)


def _get_gcloud_auth_session() -> auth_requests.AuthorizedSession:
  if not (gcloud_bin := Binaries.GCLOUD.search(plt.PLATFORM)):
    raise GCloudNotInstalledError(
        "gcloud not found. Please install the Google Cloud SDK: "
        "https://docs.cloud.google.com/sdk/docs/install-sdk")
  try:
    # TODO(b/455510346): Make sure it supports @chromium.org accounts.
    credentials, _ = google_auth.default(
        scopes=["https://www.googleapis.com/auth/userinfo.email"])
  except (
      google_auth.exceptions.DefaultCredentialsError,
      google_auth.exceptions.RefreshError,
  ) as e:
    user_input = ui.prompt(
        "Authentication failed. "
        "Please run 'gcloud auth application-default login' "
        "to configure your credentials.\n"
        "Would you like to run it now?", "[Y/n] ").lower().strip()
    if user_input in ("", "y", "yes"):
      plt.PLATFORM.sh(
          gcloud_bin, "auth", "application-default", "login", check=True)
      return _get_gcloud_auth_session()
    raise AuthenticationError from e
  return auth_requests.AuthorizedSession(credentials)


@cache
def get_auth_session() -> auth_requests.AuthorizedSession:
  # TODO(b/455510346): Figure out how to fix the quota warning properly.
  warnings.filterwarnings("ignore", module="google.auth._default")
  with annotate("Authenticating"):
    if session := _get_luci_auth_session():
      return session
    return _get_gcloud_auth_session()
