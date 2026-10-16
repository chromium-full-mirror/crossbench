# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import pathlib
from typing import Any

from typing_extensions import override

from crossbench.action_runner.action_runner import ActionRunner
from crossbench.probes.probe import Probe
from crossbench.probes.results import BrowserProbeResult, \
    DuplicateProbeResult, EmptyProbeResult, LocalProbeResult, \
    ProbeResultDict
from tests import test_helper
from tests.crossbench.base import BaseCrossbenchTestCase, \
    CrossbenchFakeFsTestCase


class ProbeResultTestCase(CrossbenchFakeFsTestCase):

  def test_is_empty(self):
    empty = EmptyProbeResult()
    self.assertTrue(empty.is_empty)
    self.assertFalse(empty)
    combined = empty.merge(EmptyProbeResult())
    self.assertTrue(combined.is_empty)
    url = LocalProbeResult(url=("http://test.com",))
    self.assertFalse(url.is_empty)
    self.assertTrue(url)
    combined = empty.merge(url)
    self.assertFalse(combined.is_empty)
    self.assertTrue(combined)

  def test_equal_empty(self):
    empty = EmptyProbeResult()
    self.assertEqual(empty, empty)
    self.assertEqual(EmptyProbeResult(), EmptyProbeResult())
    local_empty = LocalProbeResult()
    self.assertEqual(local_empty, EmptyProbeResult())
    self.assertEqual(local_empty, local_empty)
    self.assertNotEqual(LocalProbeResult(), None)
    self.assertNotEqual(None, LocalProbeResult())

  def test_is_remote(self):
    empty = EmptyProbeResult()
    self.assertFalse(empty.is_remote)
    local_empty = LocalProbeResult()
    self.assertFalse(local_empty.is_remote)

  def test_equal_single(self):
    url = "http://test.com"
    self.assertEqual(LocalProbeResult(url=(url,)), LocalProbeResult(url=(url,)))
    url_b = "http://foo.test.com"
    self.assertNotEqual(
        LocalProbeResult(url=(url,)), LocalProbeResult(url=(url_b,)))

  def test_invalid_files(self):
    with self.assertRaises(ValueError):
      LocalProbeResult(file=[pathlib.Path("foo.json")])
    with self.assertRaises(ValueError):
      LocalProbeResult(file=[pathlib.Path("foo.csv")])
    with self.assertRaises(ValueError):
      LocalProbeResult(json=[pathlib.Path("foo.csv")])
    with self.assertRaises(ValueError):
      LocalProbeResult(csv=[pathlib.Path("foo.json")])

  def test_inexistent_files(self):
    with self.assertRaises(ValueError):
      LocalProbeResult(file=[pathlib.Path("not_there.txt")])
    with self.assertRaises(ValueError):
      LocalProbeResult(csv=[pathlib.Path("not_there.csv")])
    with self.assertRaises(ValueError):
      LocalProbeResult(json=[pathlib.Path("not_there.json")])

  def test_result_url(self):
    url = "http://foo.bar.com"
    with self.assertRaises(DuplicateProbeResult):
      _ = LocalProbeResult(url=[url, url])
    result = LocalProbeResult(url=[url])
    self.assertFalse(result.is_empty)
    self.assertEqual(result.url, url)
    self.assertSequenceEqual(result.url_list, [url])
    self.assertSequenceEqual(list(result.all_files()), [])
    failed: Any = None
    with self.assertRaises(ValueError):
      failed = result.file
    with self.assertRaises(ValueError):
      failed = result.json
    with self.assertRaises(ValueError):
      failed = result.csv
    self.assertIsNone(failed)
    json_data = result.to_json()
    self.assertDictEqual(json_data, {"url": (url,)})

  def test_result_any_file(self):
    path = self.create_file("result.txt")
    with self.assertRaises(DuplicateProbeResult):
      _ = LocalProbeResult(file=[path, path])
    result = LocalProbeResult(file=[path])
    self.assertFalse(result.is_empty)
    self.assertNotEqual(
        result, LocalProbeResult(file=[
            self.create_file("result2.txt"),
        ]))
    self.assertEqual(result.file, path)
    self.assertSequenceEqual(result.file_list, [path])
    self.assertSequenceEqual(list(result.all_files()), [path])
    failed: Any = None
    with self.assertRaises(ValueError):
      failed = result.url
    with self.assertRaises(ValueError):
      failed = result.json
    with self.assertRaises(ValueError):
      failed = result.csv
    self.assertIsNone(failed)

  def test_result_csv(self):
    path = self.create_file("result.csv")
    with self.assertRaises(DuplicateProbeResult):
      _ = LocalProbeResult(csv=[path, path])
    result = LocalProbeResult(csv=[path])
    self.assertFalse(result.is_empty)
    self.assertNotEqual(
        result, LocalProbeResult(csv=[
            self.create_file("result2.csv"),
        ]))
    self.assertEqual(result.csv, path)
    self.assertEqual(result.get("csv"), path)
    self.assertSequenceEqual(result.csv_list, [path])
    self.assertSequenceEqual(result.get_all("csv"), [path])
    self.assertSequenceEqual(list(result.all_files()), [path])
    self.assertEqual(result.file, path)
    failed: Any = None
    with self.assertRaises(ValueError):
      failed = result.url
    with self.assertRaises(ValueError):
      failed = result.json
    self.assertIsNone(failed)

  def test_result_json(self):
    path = self.create_file("result.json")
    with self.assertRaises(DuplicateProbeResult):
      _ = LocalProbeResult(json=[path, path])
    with self.assertRaises(DuplicateProbeResult):
      _ = LocalProbeResult(file=[path, path])
    result = LocalProbeResult(json=[path])
    self.assertFalse(result.is_empty)
    self.assertNotEqual(
        result, LocalProbeResult(json=[
            self.create_file("result2.json"),
        ]))
    self.assertEqual(result.json, path)
    self.assertEqual(result.get("json"), path)
    self.assertSequenceEqual(result.json_list, [path])
    self.assertSequenceEqual(result.get_all("json"), [path])
    self.assertSequenceEqual(list(result.all_files()), [path])
    self.assertEqual(result.file, path)
    failed: Any = None
    with self.assertRaises(ValueError):
      failed = result.url
    with self.assertRaises(ValueError):
      failed = result.csv
    self.assertIsNone(failed)

  def test_multiple_urls(self):
    url1 = "http://one.com"
    url2 = "http://two.com"
    result = LocalProbeResult(url=(url1, url2))
    self.assertFalse(result.is_empty)
    self.assertFalse(result.has_files)
    with self.assertRaises(ValueError):
      _ = result.file
    with self.assertRaises(ValueError):
      _ = result.url
    self.assertSequenceEqual(result.url_list, (url1, url2))

  def test_multiple_files(self):
    json1 = self.create_file("result_1.json")
    json2 = self.create_file("result_2.json")
    zip1 = self.create_file("result.zip")
    result = LocalProbeResult(file=(json1, json2, zip1))
    self.assertFalse(result.is_empty)
    self.assertTrue(result.has_files)
    with self.assertRaises(ValueError):
      _ = result.file
    with self.assertRaises(ValueError):
      _ = result.json
    self.assertSequenceEqual(result.file_list, (json1, json2, zip1))
    self.assertSequenceEqual(result.json_list, (json1, json2))
    self.assertSequenceEqual(result.get_all("json"), (json1, json2))
    self.assertEqual(result.get("zip"), zip1)
    self.assertSequenceEqual(result.get_all("zip"), [zip1])
    with self.assertRaises(ValueError):
      _ = result.get("other")

  def test_merge(self):
    file = self.create_file("result.custom")
    json = self.create_file("result.json")
    csv = self.create_file("result.csv")
    url = "http://foo.bar.com"
    trace = self.create_file("trace.pb")

    result = LocalProbeResult(
        url=(url,), file=(file,), json=(json,), csv=(csv,), perfetto=(trace,))
    self.assertFalse(result.is_empty)
    self.assertSequenceEqual(list(result.all_files()), [file, json, csv, trace])
    self.assertSequenceEqual(result.url_list, [url])
    self.assertSequenceEqual(result.perfetto_list, [trace])

    merged = result.merge(EmptyProbeResult())
    self.assertFalse(merged.is_empty)
    self.assertSequenceEqual(list(merged.all_files()), [file, json, csv, trace])
    self.assertSequenceEqual(merged.url_list, [url])
    self.assertSequenceEqual(merged.perfetto_list, [trace])

    file_2 = self.create_file("result.2.custom")
    json_2 = self.create_file("result.2.json")
    csv_2 = self.create_file("result.2.csv")
    url_2 = "http://foo.bar.com/2"
    trace_2 = self.create_file("trace.2.pb")
    other = LocalProbeResult(
        url=(url_2,),
        file=(file_2,),
        json=(json_2,),
        csv=(csv_2,),
        perfetto=(trace_2,))
    merged = result.merge(other)
    self.assertFalse(merged.is_empty)
    self.assertSequenceEqual(
        list(merged.all_files()),
        [file, file_2, json, json_2, csv, csv_2, trace, trace_2])
    self.assertSequenceEqual(merged.url_list, [url, url_2])
    # result is unchanged:
    self.assertFalse(result.is_empty)
    self.assertSequenceEqual(list(result.all_files()), [file, json, csv, trace])
    self.assertSequenceEqual(result.url_list, [url])
    self.assertSequenceEqual(result.perfetto_list, [trace])
    # other is unchanged:
    self.assertFalse(other.is_empty)
    self.assertSequenceEqual(
        list(other.all_files()), [file_2, json_2, csv_2, trace_2])
    self.assertSequenceEqual(other.url_list, [url_2])
    self.assertSequenceEqual(other.perfetto_list, [trace_2])

  def test_merge_duplicate_files(self):
    path = self.create_file("result.custom")
    result_1 = LocalProbeResult(file=(path,))
    result_2 = LocalProbeResult(file=(path,))
    with self.assertRaises(DuplicateProbeResult):
      result_1.merge(result_1)
    with self.assertRaises(DuplicateProbeResult):
      result_1.merge(result_2)
    with self.assertRaises(DuplicateProbeResult):
      result_2.merge(result_1)

  def test_merge_multiple(self):
    path_1 = self.create_file("result_1.custom")
    result_1 = LocalProbeResult(file=(path_1,))
    path_2 = self.create_file("result_2.custom")
    result_2 = LocalProbeResult(file=(path_2,))
    path_3 = self.create_file("result_3.custom")
    result_3 = LocalProbeResult(file=(path_3,))

    merged = result_1.merge(result_2, result_3)
    self.assertFalse(merged.is_empty)
    self.assertSequenceEqual(list(merged.all_files()), [path_1, path_2, path_3])

    merged = result_1.merge(result_3, result_2)
    self.assertFalse(merged.is_empty)
    self.assertSequenceEqual(list(merged.all_files()), [path_1, path_3, path_2])

    # Test with empty
    merged_with_empty = result_1.merge(EmptyProbeResult(), result_2)
    self.assertSequenceEqual(
        list(merged_with_empty.all_files()), [path_1, path_2])

  def test_perfetto_list_are_files(self):
    trace = self.create_file("trace.pb")

    result = LocalProbeResult(perfetto=(trace,))
    self.assertFalse(result.is_empty)
    self.assertSequenceEqual(list(result.all_files()), [trace])
    self.assertSequenceEqual(list(result.perfetto_list), [trace])

  def test_perfetto_list_can_be_duplicate(self):
    trace = self.create_file("trace.pb")

    result = LocalProbeResult(perfetto=(trace,), file=(trace,))
    self.assertFalse(result.is_empty)
    self.assertSequenceEqual(list(result.all_files()), [trace])
    self.assertSequenceEqual(list(result.perfetto_list), [trace])


class MockRun:

  def __init__(self,
               browser,
               browser_platform,
               action_runner: ActionRunner | None = None):
    self.browser = browser
    self.browser_platform = browser_platform
    self.is_remote = False
    self.action_runner: ActionRunner = action_runner or ActionRunner(self)


class BrowserProbeResultTestCase(BaseCrossbenchTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.run = MockRun(self.browsers[0], self.platform)

  def test_empty(self):
    result = BrowserProbeResult(self.run)
    self.assertTrue(result.is_empty)
    self.assertFalse(result.is_remote)

  def test_remote_empty(self):
    self.run.is_remote = True
    result = BrowserProbeResult(self.run)
    self.assertTrue(result.is_empty)
    self.assertEqual(result, EmptyProbeResult())
    self.assertEqual(result, LocalProbeResult())

  def test_remote_only_urls(self):
    self.run.is_remote = True
    result = BrowserProbeResult(self.run, url=("http://test.com",))
    self.assertFalse(result.is_empty)
    self.assertNotEqual(result, EmptyProbeResult())
    self.assertEqual(result, LocalProbeResult(url=("http://test.com",)))
    self.assertNotEqual(result, LocalProbeResult(url=("http://test.com/bar",)))

  def test_local_browser_equal_local_run(self):
    url = "http://foo.bar.com"
    file = self.create_file("results/file.any")
    json = self.create_file("results/file.json")
    csv = self.create_file("results/file.csv")
    local = LocalProbeResult((url,), (file, json, csv))
    browser = BrowserProbeResult(self.run, (url,), (file, json, csv))
    self.assertEqual(local, browser)
    local_kwargs = LocalProbeResult(
        url=(url,), file=(file,), json=(json,), csv=(csv,))
    browser_kwargs = BrowserProbeResult(
        self.run, url=(url,), file=(file,), json=(json,), csv=(csv,))
    self.assertEqual(local, browser)
    self.assertEqual(local, browser_kwargs)
    self.assertEqual(local_kwargs, browser)
    self.assertEqual(local_kwargs, browser_kwargs)

  def test_copy_remote_files(self):
    out_dir_local = pathlib.Path("local/results")
    out_dir_remote = pathlib.Path("remote/results")
    out_dir_local.mkdir(parents=True)
    out_dir_remote.mkdir(parents=True)
    self.assertTrue(out_dir_local.is_dir())
    self.assertTrue(out_dir_remote.is_dir())
    remote_txt = self.create_file(
        out_dir_remote / "result.txt", contents="a1 b2 c3")
    remote_json = self.create_file(
        out_dir_remote / "result.json", contents="[]")
    self.run.is_remote = True
    self.run.out_dir = out_dir_local
    self.run.browser_tmp_dir = out_dir_remote
    with self.assertRaises(DuplicateProbeResult):
      _ = BrowserProbeResult(self.run, file=(remote_txt, remote_txt))
    with self.assertRaises(DuplicateProbeResult):
      _ = BrowserProbeResult(self.run, json=(remote_json, remote_json))
    result = BrowserProbeResult(
        self.run, file=(remote_txt,), json=(remote_json,))
    self.assertTrue(remote_txt.is_file())
    with self.assertRaises(ValueError):
      _ = result.file
    self.assertTrue(result.has_files)
    self.assertNotEqual(remote_json, result.json)
    self.assertTrue(result.json.is_file())
    self.assertEqual(result.json.read_text(), "[]")
    self.assertNotEqual(remote_txt, result.get("txt"))
    self.assertEqual(result.get("txt").read_text(), "a1 b2 c3")


class MockProbe(Probe):
  """
  Probe DOC Text
  """
  NAME = "mock-probe"

  @override
  def get_context_cls(self):
    pass


class ProbeResultDictTestCase(CrossbenchFakeFsTestCase):

  @override
  def setUp(self) -> None:
    super().setUp()
    self.result_location = pathlib.Path("test/out/results")
    self.result_dict = ProbeResultDict(self.result_location)
    self.local_result = LocalProbeResult()

  def test_create_empty(self):
    self.assertEqual(len(self.result_dict), 0)
    self.assertFalse(self.result_dict)
    self.assertNotIn(MockProbe(), self.result_dict)

  def test_get_item(self):
    probe = MockProbe()
    with self.assertRaises(KeyError):
      _ = self.result_dict[probe]
    self.result_dict[probe] = self.local_result
    self.assertIs(self.result_dict[probe], self.local_result)

  def test_get(self):
    probe = MockProbe()
    self.assertIsNone(self.result_dict.get(probe))
    self.assertEqual(self.result_dict.get(probe, 1234), 1234)
    self.result_dict[probe] = self.local_result
    self.assertIs(self.result_dict.get(probe), self.local_result)

  def test_to_json_empty(self):
    probe = MockProbe()
    self.result_dict[probe] = self.local_result
    json = self.result_dict.to_json()
    self.assertDictEqual(json, {MockProbe.NAME: None})

  def test_to_json_result(self):
    csv = self.create_file("result.csv")
    txt = self.create_file("result.txt")
    self.local_result = LocalProbeResult(csv=(csv,), txt=(txt,))
    probe = MockProbe()
    self.result_dict[probe] = self.local_result
    json = self.result_dict.to_json()
    self.assertDictEqual(
        json, {MockProbe.NAME: {
            "csv": [str(csv)],
            "txt": [str(txt)],
        }})


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
