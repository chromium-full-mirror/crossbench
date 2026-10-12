# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

from crossbench.browsers.webkit.version import WebKitVersion
from tests import test_helper
from tests.crossbench.helper.test_version import VersionTestCase


class WebKitVersionTestCase(VersionTestCase):
  VERSION_CLS = WebKitVersion

  def test_parse_webkit_nightly(self):
    version = WebKitVersion.parse("webkit-nightly-299105@main")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit-nightly 299105@main")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit-nightly-299105")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit-nightly 299105")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

  def test_parse_webkit(self):
    version = WebKitVersion.parse("webkit-299105@main")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit 299105@main")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit-299105")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

    version = WebKitVersion.parse("webkit 299105")
    self.assertSequenceEqual(version.parts, (299105,))
    self.assertEqual(version.version_str, "WebKit Nightly 299105")

  def test_parse_invalid(self):
    with self.assertRaises(ValueError):
      WebKitVersion.parse("webkit-nightly@main")
    with self.assertRaises(ValueError):
      WebKitVersion.parse("webkit-nightly")
    with self.assertRaises(ValueError):
      WebKitVersion.parse("299105@main")
    with self.assertRaises(ValueError):
      WebKitVersion.parse("webkit main")


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
