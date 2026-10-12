# Copyright 2025 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import cache, partial
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

import google.cloud.storage as gcloud_storage  # type: ignore

from crossbench import path as pth
from crossbench import plt
from crossbench.cli.ui import ui
from crossbench.parse import ObjectParser
from crossbench.pinpoint.helper import annotate
from crossbench.pinpoint.job_config import fetch_job_config

if TYPE_CHECKING:
  from crossbench.helper.spinner import Spinner
  from crossbench.types import JsonDict


class PinpointJobResults:

  def __init__(
      self,
      job_id: str,
  ) -> None:
    self.job_id: str = job_id
    self.data: JsonDict = fetch_job_config(job_id, full=True)
    with annotate("Parsing job results"):
      if self.status.lower() != "completed":
        raise ValueError(f"Job is not completed. Status: {self.status}")

      self.name: str = f"pinpoint_{self.benchmark}_{self.bot}"
      self.results_url: str | None = ObjectParser.optional_str(
          self.data.get("results_url"), "results_url")
      state = ObjectParser.sequence(self.data.get("state", ()), "state")
      self.variants: list[PinpointVariantResults] = [
          PinpointVariantResults(ObjectParser.dict(v, f"state[{i}]"), i)
          for i, v in enumerate(state)
      ]

      self.download_index = 0
      self.download_count = 1 if self.results_url else 0
      self.download_count += sum(v.download_count for v in self.variants)

  @property
  def arguments(self) -> JsonDict:
    return ObjectParser.dict(self.data.get("arguments", {}), "arguments")

  @property
  def benchmark(self) -> str:
    return ObjectParser.any_str(
        self.arguments.get("benchmark", ""), "benchmark")

  @property
  def bot(self) -> str:
    return ObjectParser.any_str(
        self.arguments.get("configuration", ""), "configuration")

  @property
  def status(self) -> str:
    return ObjectParser.non_empty_str(self.data["status"], "status")

  @property
  @cache
  def created_date(self) -> str:
    time_str = ObjectParser.any_str(self.data.get("created", ""), "created")
    try:
      dt_object = dt.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
      return dt_object.strftime("%Y-%m-%d_%H%M%S")
    except ValueError:
      logging.warning("Invalid created time: %s", time_str)
      return time_str

  def download(self, out_dir: pth.LocalPath) -> None:
    self.cas_path = self._find_or_install_cas()

    self.download_index = 0
    with ui.spinner(title="Downloading") as spinner:
      tasks = self._prepare_tasks(spinner, out_dir)
      with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(lambda f: f(), tasks)

  def _find_or_install_cas(self) -> pth.LocalPath:
    if installed_cas_path := plt.PLATFORM.which("cas"):
      return pth.LocalPath(installed_cas_path)

    cache_dir = plt.PLATFORM.local_cache_dir("cipd") / "cas"
    cache_dir_cas = cache_dir / "cas"
    if cache_dir_cas.exists():
      return cache_dir_cas

    if plt.PLATFORM.which("cipd"):
      with annotate("Installing cas via cipd"):
        plt.PLATFORM.sh("cipd", "init", "-force", cache_dir)
        plt.PLATFORM.sh("cipd", "install", "infra/tools/luci/cas/${platform}",
                        "latest", "-root", cache_dir)
        return cache_dir_cas

    raise FileNotFoundError(
        "Missing binaries `cas`. Install `cas` from "
        "https://chrome-infra-packages.appspot.com/p/infra/tools/luci/cas and "
        "add it to your PATH.")

  def _prepare_tasks(self, spinner: Spinner,
                     out_dir: pth.LocalPath) -> list[Callable[[], None]]:
    tasks: list[Callable[[], None]] = []
    if self.results_url:
      tasks.append(
          partial(self._download_from_storage, spinner, self.results_url,
                  out_dir / f"{self.job_id}.html"))

    for variant in self.variants:
      variant_dir = out_dir / variant.name
      for attempt in variant.attempts:
        attempt_dir = variant_dir / str(attempt.index + 1)
        attempt_dir.mkdir(parents=True, exist_ok=True)

        if attempt.cas_isolate:
          tasks.append(
              partial(self._download_cas_isolate, spinner, attempt.cas_isolate,
                      attempt_dir))

        for trace_name, trace_url in attempt.perfetto_trace_url_by_name.items():
          tasks.append(
              partial(self._download_from_storage, spinner, trace_url,
                      attempt_dir / trace_name))
    return tasks

  def _next_progress_message(self) -> str:
    self.download_index += 1
    return f" {self.download_index}/{self.download_count}"

  def _download_cas_isolate(self, spinner: Spinner, isolate: str,
                            out_dir: pth.LocalPath) -> None:
    spinner.write(self._next_progress_message())
    cmd: list[pth.AnyPathLike] = [
        self.cas_path,
        "download",
        "-cas-instance",
        "projects/chrome-swarming/instances/default_instance",
        "-digest",
        isolate,
        "-dir",
        out_dir,
    ]
    plt.PLATFORM.sh(*cmd)

  def _download_from_storage(self, spinner: Spinner, url: str,
                             output_file: pth.LocalPath) -> None:
    spinner.write(self._next_progress_message())
    parsed_url = urlparse(url)
    path_segments = parsed_url.path.strip("/").split("/", 1)
    if len(path_segments) < 2:
      raise ValueError(f"Invalid GCS URL: {url}")

    bucket_name = path_segments[0]
    blob_name = path_segments[1]

    client = gcloud_storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    blob.download_to_filename(str(output_file))


class PinpointVariantResults:

  def __init__(self, data: JsonDict, index: int) -> None:
    self.data = data
    self.index = index
    self.name = self.form_variant_name()
    attempts = ObjectParser.sequence(data.get("attempts", ()), "attempts")
    self.attempts = [
        PinpointAttemptResults(
            ObjectParser.dict(attempt, f"attempts[{attempt_index}]"),
            attempt_index) for attempt_index, attempt in enumerate(attempts)
    ]
    self.download_count = sum(a.download_count for a in self.attempts)

  @property
  def change(self) -> JsonDict:
    return ObjectParser.dict(self.data.get("change", {}), "change")

  def form_variant_name(self) -> str:
    if label := ObjectParser.optional_str(self.change.get("label"), "label"):
      return label

    parts = []
    commits = ObjectParser.sequence(self.change.get("commits", ()), "commits")
    for i, raw_commit in enumerate(commits):
      commit = ObjectParser.dict(raw_commit, f"commits[{i}]")
      parts.append(commit.get("repository"))
      parts.append(commit.get("commit_position"))

    str_parts = [str(part) for part in parts if part]
    if str_parts:
      return "_".join(str_parts)

    return f"variant_{self.index}"


class PinpointAttemptResults:

  def __init__(self, data: JsonDict, index: int) -> None:
    self.data = data
    self.index = index
    self.cas_isolate = self.find_results_isolate()
    self.perfetto_trace_url_by_name = self.find_perfetto_traces()

    self.download_count = len(self.perfetto_trace_url_by_name)
    if self.cas_isolate:
      self.download_count += 1

  @property
  def executions(self) -> list[JsonDict]:
    raw_executions = ObjectParser.sequence(
        self.data.get("executions", ()), "executions")
    return [
        ObjectParser.dict(e, f"executions[{i}]")
        for i, e in enumerate(raw_executions)
    ]

  def find_results_isolate(self) -> str | None:
    if len(self.executions) < 2:
      return None

    raw_details = ObjectParser.sequence(self.executions[1].get("details", ()),
                                        "details")
    for i, raw_detail in enumerate(raw_details):
      details = ObjectParser.dict(raw_detail, f"details[{i}]")
      if details.get("key") != "isolate":
        continue
      if value := ObjectParser.optional_str(
          details.get("value"), "isolate value"):
        return value

    return None

  def find_perfetto_traces(self) -> dict[str, str]:
    url_by_name: dict[str, str] = {}
    if len(self.executions) < 3:
      return url_by_name

    raw_details = ObjectParser.sequence(self.executions[2].get("details", ()),
                                        "details")
    for index, raw_detail in enumerate(raw_details):
      details = ObjectParser.dict(raw_detail, f"details[{index}]")
      if details.get("key") != "trace":
        continue
      if url := ObjectParser.optional_str(details.get("url"), "trace url"):
        name = str(details.get("value", index))
        if not name.endswith(".pb"):
          name += ".pb"
        url_by_name[name] = url
    return url_by_name


def download_results(job_id: str,
                     out_dir: pth.LocalPath | None = None,
                     force: bool = False) -> None:
  """Downloads results of a Pinpoint job."""
  job_results = PinpointJobResults(job_id)

  out_dir = out_dir or pth.get_out_dir(pth.LocalPath.cwd(
  )) / ".." / f"{job_results.created_date}_pinpoint_{job_results.job_id}"
  out_dir = out_dir.resolve()
  if out_dir.exists() and not force:
    raise FileExistsError(
        f"Output directory {out_dir} already exists. Use --force to overwrite.")
  out_dir.mkdir(parents=True, exist_ok=True)

  logging.info("RESULT DIR: %s", out_dir)
  job_results.download(out_dir)
