# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json

import requests
from google.auth import exceptions as google_auth_exceptions

from crossbench.pinpoint import auth
from crossbench.pinpoint.exceptions import AuthenticationError


def get(url: str, **kwargs) -> requests.Response:
  return _method("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
  return _method("POST", url, **kwargs)


class ServerError(requests.exceptions.HTTPError):

  def __init__(self, error: requests.exceptions.HTTPError) -> None:
    error_message = ""
    if response := error.response:
      try:
        data = response.json()
        if error_text := data.get("error"):
          error_message = f"\n{error_text}"
        else:
          error_message = f"\n{data}"
      except json.JSONDecodeError:
        pass
    super().__init__(str(error) + error_message, response=response)


def _method(method: str, url: str, **kwargs) -> requests.Response:
  try:
    response = auth.get_auth_session().request(method, url, **kwargs)
  except google_auth_exceptions.RefreshError as e:
    raise AuthenticationError from e
  _raise_for_status(response)
  return response


def _raise_for_status(response: requests.Response) -> None:
  try:
    response.raise_for_status()
  except requests.exceptions.HTTPError as e:
    if response.status_code in (401, 403):
      raise AuthenticationError from e
    raise ServerError(e) from e
