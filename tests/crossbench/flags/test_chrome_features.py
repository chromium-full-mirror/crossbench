# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import abc
import unittest

from crossbench.flags.base import FrozenFlagsError
from crossbench.flags.chrome_features import ChromeBaseFeatures, \
    ChromeBlinkFeatures, ChromeFeatures
from tests import test_helper


class _ChromeBaseFeaturesTestCase(unittest.TestCase, metaclass=abc.ABCMeta):

  @abc.abstractmethod
  def instance(self) -> ChromeBaseFeatures:
    pass

  def test_empty(self):
    features = self.instance()
    self.assertEqual(str(features), "")
    features_list = list(features)
    self.assertEqual(len(features_list), 0)
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())

  def test_enable_simple(self):
    features = self.instance()
    features.enable("feature1")
    features.enable("feature2")
    features_list = list(features)
    self.assertEqual(len(features_list), 1)
    features_str = str(features)
    self.assertIn("=feature1,feature2", features_str)

  def test_disable_simple(self):
    features = self.instance()
    features.disable("feature1")
    features.disable("feature2")
    features_list = list(features)
    self.assertEqual(len(features_list), 1)
    features_str = str(features)
    self.assertIn("=feature1,feature2", features_str)

  def test_enable_disable(self):
    features = self.instance()
    features.enable("feature1")
    features.disable("feature2")
    features_list = list(features)
    self.assertEqual(len(features_list), 2)
    features_str = str(features)
    self.assertIn("feature1", features_str)
    self.assertIn("feature2", features_str)
    self.assertDictEqual(features.enabled, {"feature1": None})
    self.assertSetEqual(features.disabled, {"feature2"})

  def test_try_set(self):
    features = self.instance()
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())
    self.assertFalse(features.try_set("--unknown", "val"))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())
    self.assertTrue(features.try_set(features.ENABLE_FLAG, "f1,f2"))
    self.assertDictEqual(features.enabled, {"f1": None, "f2": None})
    self.assertSetEqual(features.disabled, set())
    self.assertTrue(features.try_set(features.ENABLE_FLAG, None))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())
    self.assertTrue(features.try_set(features.DISABLE_FLAG, "f3,f4"))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, {"f3", "f4"})
    self.assertTrue(features.try_set(features.DISABLE_FLAG, None))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())
    self.assertTrue(features.try_set(features.ENABLE_FLAG, "f1"))
    self.assertTrue(features.try_set(features.DISABLE_FLAG, "f2"))
    self.assertDictEqual(features.enabled, {"f1": None})
    self.assertSetEqual(features.disabled, {"f2"})
    self.assertTrue(features.try_set(features.ENABLE_FLAG, None))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, {"f2"})
    self.assertTrue(features.try_set(features.DISABLE_FLAG, None))
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())

  def test_update_same(self):
    features_1 = self.instance()
    features_1.disable("feature1")
    features_2 = self.instance()
    features_2.disable("feature1")
    features_1.update(features_2)
    self.assertEqual(str(features_1), str(features_2))

  def test_update_add(self):
    features_1 = self.instance()
    features_1.disable("feature1")
    features_1.enable("feature2")
    features_2 = self.instance()
    features_2.disable("featureX")
    features_2.enable("featureY")
    features_1.update(features_2)
    self.assertSetEqual(features_1.disabled, {"feature1", "featureX"})
    self.assertSetEqual(
        set(features_1.enabled.keys()), {"feature2", "featureY"})

  def test_update_conflict(self):
    features_1 = self.instance()
    features_1.enable("feature1")
    features_2 = self.instance()
    features_2.disable("feature1")
    with self.assertRaises(ValueError):
      features_1.update(features_2)

  def test_enable_disable_frozen(self):
    features = self.instance()
    features.freeze()
    with self.assertRaises(FrozenFlagsError):
      features.disable("feature1")
    with self.assertRaises(FrozenFlagsError):
      features.enable("feature2")


class ChromeFeaturesTestCase(_ChromeBaseFeaturesTestCase):

  def instance(self) -> ChromeFeatures:
    return ChromeFeatures()

  def test_enable_complex_features(self):
    features = self.instance()
    features.enable("feature1")
    features.enable("feature2:k1")
    features.enable("feature3:k1/v1/k2/v2")
    features.enable("feature4<Trial1:k1/v1/k2/v2")
    features.enable("feature5<Trial1.Group1:k1/v1/k2/v2")
    features_list = list(features)
    self.assertEqual(len(features_list), 1)

  def test_disable_complex_features(self):
    features = self.instance()
    features.disable("feature1")
    features.disable("feature2:k1")
    features.disable("feature3:k1/v1/k2/v2")
    features.disable("feature4<Trial1:k1/v1/k2/v2")
    features.disable("feature5<Trial1.Group1:k1/v1/k2/v2")
    features_list = list(features)
    self.assertEqual(len(features_list), 1)
    features_str = str(features)
    self.assertIn("feature1", features_str)
    self.assertIn("feature2", features_str)
    self.assertIn("feature3", features_str)
    self.assertIn("feature4", features_str)

  def test_enable_simple_chrome(self):
    features = self.instance()
    features.enable("feature1")
    features.enable("feature2")
    self.assertEqual(str(features), "--enable-features=feature1,feature2")

  def test_disable_simple_chrome(self):
    features = self.instance()
    features.disable("feature1")
    features.disable("feature2")
    self.assertEqual(str(features), "--disable-features=feature1,feature2")

  def test_enable_disable_chrome(self):
    features = self.instance()
    features.enable("feature1")
    features.disable("feature2")
    self.assertEqual(
        str(features), "--enable-features=feature1 --disable-features=feature2")

  def test_enable_disable_complex(self):
    features = self.instance()
    features.enable("feature0")
    features.enable("feature1:k1/v1")
    features.enable("feature2<Trial.Group:k2/v2")
    features.disable("feature3:k3/v3")
    self.assertDictEqual(features.enabled, {
        "feature0": None,
        "feature1": ":k1/v1",
        "feature2": "<Trial.Group:k2/v2",
    })
    self.assertSetEqual(features.disabled, {"feature3"})

  def test_conflicting_values_enabled(self):
    features = self.instance()
    features.enable("feature1")
    features.enable("feature1")
    with self.assertRaises(ValueError):
      features.disable("feature1")
    with self.assertRaises(ValueError):
      features.enable("feature1:k1/v1")
    features_str = str(features)
    self.assertEqual(features_str, "--enable-features=feature1")

  def test_conflicting_values_disabled(self):
    features = self.instance()
    features.disable("feature1")
    features.disable("feature1")
    with self.assertRaises(ValueError):
      features.enable("feature1")
    features.disable("feature1:k1/v1")
    features_str = str(features)
    self.assertEqual(features_str, "--disable-features=feature1")

  def test_contains(self):
    features = self.instance()
    self.assertFalse("feature1" in features)
    self.assertFalse("feature2" in features)

    features.enable("feature1")
    self.assertTrue("feature1" in features)
    self.assertFalse("feature2" in features)

    features.disable("feature2")
    self.assertTrue("feature1" in features)
    self.assertTrue("feature2" in features)


class ChromeBlinkFeaturesTestCase(_ChromeBaseFeaturesTestCase):

  def instance(self) -> ChromeBlinkFeatures:
    return ChromeBlinkFeatures()

  def test_empty(self):
    features = self.instance()
    self.assertEqual(str(features), "")
    features_list = list(features)
    self.assertEqual(len(features_list), 0)
    self.assertDictEqual(features.enabled, {})
    self.assertSetEqual(features.disabled, set())

  def test_enable_basic_features(self):
    features = self.instance()
    features.enable("feature1")

  def test_enable_invalid(self):
    features = self.instance()
    for invalid in ("feature2:k1", "feature3:k1/v1/k2/v2",
                    "feature4<Trial1:k1/v1/k2/v2",
                    "feature5<Trial1.Group1:k1/v1/k2/v2"):
      with self.assertRaises(ValueError):
        features.enable(invalid)
    self.assertTrue(features.is_empty)

  def test_enable_simple_chrome_blink(self):
    features = self.instance()
    features.enable("feature1")
    features.enable("feature2")
    self.assertEqual(str(features), "--enable-blink-features=feature1,feature2")

  def test_disable_simple_chrome_blink(self):
    features = self.instance()
    features.disable("feature1")
    features.disable("feature2")
    self.assertEqual(
        str(features), "--disable-blink-features=feature1,feature2")

  def test_enable_disable_chrome_blink(self):
    features = self.instance()
    features.enable("feature1")
    features.disable("feature2")
    self.assertEqual(
        str(features),
        "--enable-blink-features=feature1 --disable-blink-features=feature2")


del _ChromeBaseFeaturesTestCase

if __name__ == "__main__":
  test_helper.run_pytest(__file__)
