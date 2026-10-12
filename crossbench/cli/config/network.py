# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import enum
import functools
from typing import TYPE_CHECKING, ClassVar, Self

from typing_extensions import override

from crossbench import exception
from crossbench.cli.config.network_speed import NetworkSpeedConfig, \
    NetworkSpeedPreset
from crossbench.config import ConfigEnum, ConfigObject, ConfigParser
from crossbench.network.live import LiveNetwork
from crossbench.network.local_file_server import LocalFileNetwork
from crossbench.network.replay.wpr import LocalWprReplayNetwork, \
    RemoteWprReplayNetwork
from crossbench.network.traffic_shaping import ts_proxy
from crossbench.network.traffic_shaping.live import NoTrafficShaper
from crossbench.parse import NumberParser, ObjectParser, PathParser

if TYPE_CHECKING:
  import urllib.parse as urlparse

  from crossbench import path as pth
  from crossbench.network.base import Network
  from crossbench.network.traffic_shaping.base import TrafficShaper
  from crossbench.plt.base import Platform

# We're using 'type' here a lot, let's skip the warnings from pylint.


def _parse_existing_file_path_and_resolve(value: str) -> pth.LocalPath:
  # During config parsing, a ChangePWD call ensures that config paths can be
  # specified as relative to the config directory. But the PWD is later reverted
  # to the original one. Resolving to an absolute path upfront ensures we're
  # always looking at the correct file.
  # It would be best to implement this in PathParser, e.g. crrev.com/c/6713595.
  return PathParser.json_file_path(value).resolve()


@enum.unique
class NetworkType(ConfigEnum):
  LIVE = ("live", "Live network.")
  WPR = ("wpr", "Replayed network from a webpagereplay archive.")
  LOCAL = ("local", "Serve content from a local http file server.")


@dataclasses.dataclass(frozen=True)
class NetworkConfig(ConfigObject):
  ARCHIVE_EXTENSIONS: ClassVar[tuple[str, ...]] = (".archive", ".wprgo")
  VALID_EXTENSIONS: ClassVar[tuple[str, ...]] = (
      ConfigObject.VALID_EXTENSIONS + ARCHIVE_EXTENSIONS)
  VALID_SCHEMES: ClassVar[tuple[str, ...]] = ("gs",)

  type: NetworkType = NetworkType.LIVE
  speed: NetworkSpeedConfig = NetworkSpeedConfig.default()
  path: pth.LocalPath | None = None
  url: str | None = None
  persist_server: bool = False
  run_on_device: bool = False
  skip_deterministic_script_injection: bool = False
  no_archive_certificates: bool = False
  response_transformations_file: pth.LocalPath | None = None
  cross_platform_mode: bool = False
  host: str | None = None
  http_port: int | None = None
  https_port: int | None = None
  expected_md5_hash: bytes = b""

  @classmethod
  @functools.cache
  def default(cls) -> Self:
    return cls(type=NetworkType.LIVE)

  @classmethod
  @override
  def config_parser(cls) -> ConfigParser[Self]:
    parser = ConfigParser(cls, default=cls.default())
    parser.add_argument("type", type=NetworkType, default=NetworkType.LIVE)
    preset_choices = tuple(str(preset) for preset in NetworkSpeedPreset)
    parser.add_argument(
        "speed",
        type=NetworkSpeedConfig,
        default=NetworkSpeedConfig.default(),
        help=("Enable traffic shaping using ts_proxy, disabled by default. "
              f"Either full NetworkSpeedConfig or one of {preset_choices}."))
    parser.add_argument(
        "path",
        type=PathParser.existing_path,
        help=("Path to a local directory for 'local' file server network, "
              "or path to a archive.wprgo for a 'wpr' replay network"))
    parser.add_argument("url", type=str)
    parser.add_argument("persist_server", type=ObjectParser.bool, default=False)
    parser.add_argument(
        "run_on_device",
        type=ObjectParser.bool,
        default=False,
        help=("For 'wpr' network only: switch to enable running on-device "
              "to reduce delays caused by traffic forwarding over adb."))
    parser.add_argument(
        "skip_deterministic_script_injection",
        type=ObjectParser.bool,
        default=False,
        help=("Don't inject the deterministic.js script into every response "
              "in WPR replay mode. See crbug.com/428945380"))
    parser.add_argument(
        "no_archive_certificates",
        type=ObjectParser.bool,
        default=False,
        help=(
            "For 'wpr' network only. By default, WPR stores certificates in "
            "the archive during recording (minted from the root ones) and "
            "reads them during replay. Such certificates will expire "
            "eventually, so this setup is only suitable when the client "
            "ignores TLS errors (e.g. due to "
            "--ignore-certificate-errors-spki-list in a Chromium browser), or "
            "for short-lived experiments. Otherwise, use this flag to prevent "
            "WPR from reading/writing archive certificates. New certificates "
            "will be generated on replay time, with caching by host."))
    parser.add_argument(
        "response_transformations_file",
        type=_parse_existing_file_path_and_resolve,
        help=("Path to a JSON file specifying transformation rules to apply to "
              "specific responses, e.g. inject a script in google.com. See "
              "WebPageReplay docs for more info on the expected file format."))
    parser.add_argument(
        "cross_platform_mode",
        type=ObjectParser.bool,
        default=False,
        help=("A special mode when WPR doesn't use ADB port forwarding or any "
              "Chromium-specific flags to setup network. Instead WPR serves "
              "requests on standard http/https ports and delegates network "
              "setup to the user. Requires root privileges on the host. "
              "Incompatible with 'run_on_device' setting."))
    parser.add_argument(
        "host", type=str, help=("A host for WPR server to bind to."))
    parser.add_argument(
        "http_port", type=NumberParser.port_number, help="HTTP port for WPR.")
    parser.add_argument(
        "https_port", type=NumberParser.port_number, help="HTTPS port for WPR.")
    parser.add_argument(
        "expected_md5_hash",
        type=ObjectParser.md5_hash,
        default=b"",
        help=("Expected archive MD5 hash for WPR replay network verification."))
    return parser

  @classmethod
  def help(cls) -> str:
    return cls.config_parser().help

  @classmethod
  def parse_args(cls, args: argparse.Namespace) -> Self:
    if network_config := args.network_config:
      return cls.parse(network_config)
    return cls.default()

  @classmethod
  def parse_wpr(cls, value: object) -> Self:
    config = cls.parse(value)
    if config.type != NetworkType.WPR:
      raise argparse.ArgumentTypeError(f"Expected wpr, but got {config.type}")
    return config

  @classmethod
  def parse_local(cls, value: object) -> Self:
    config: Self = cls.parse(value, type=NetworkType.LOCAL)
    if config.type != NetworkType.LOCAL:
      raise argparse.ArgumentTypeError(
          f"Expected local file server, but got {config.type}. ")
    return config

  @classmethod
  @override
  def parse_str(cls, value: str, type: NetworkType | None = None) -> Self:
    if not value:
      raise argparse.ArgumentTypeError("Network: Cannot parse empty string")
    if value == "default":
      default_network = cls.default()
      if type and type != default_network.type:
        raise argparse.ArgumentTypeError(
            f"No default NetworkConfig for type={type}")
      return default_network
    if type and type is not NetworkType.LIVE:
      raise argparse.ArgumentTypeError(
          f"Network type mismatch expected LIVE, got {type}")
    return cls.parse_live(value)

  @classmethod
  def parse_live(cls, value: object) -> Self:
    with exception.annotate_argparsing("Live network with speed config"):
      speed = NetworkSpeedConfig.parse(value)
      return cls(NetworkType.LIVE, speed)
    raise exception.UnreachableError

  @classmethod
  def parse_url(cls,
                url: urlparse.ParseResult,
                type: NetworkType | None = None,
                **kwargs) -> Self:
    cls.expect_no_extra_kwargs(kwargs)
    if type and type is not NetworkType.WPR:
      raise argparse.ArgumentTypeError(
          f"Network type mismatch, expected WPR, got {type}")
    assert url.scheme == "gs", f"Only support gs url, but got {url.scheme}"
    return cls.parse_wpr_archive_url(url.geturl())

  @classmethod
  @override
  def maybe_valid_path(cls, path: pth.LocalPath) -> pth.LocalPath | None:
    if valid_path := super().maybe_valid_path(path):
      return valid_path
    # for local file server
    if path.is_dir():
      return path
    return None

  @classmethod
  def parse_path(cls, path: pth.LocalPath, **kwargs) -> Self:
    if path.suffix in cls.ARCHIVE_EXTENSIONS:
      return cls.parse_wpr_archive_path(path)
    if path.is_dir():
      return cls(NetworkType.LOCAL, path=path)
    return super().parse_path(path, **kwargs)

  @classmethod
  def parse_path_like(cls, original_value: str, path: pth.LocalPath,
                      **kwargs) -> Self:
    del original_value
    return cls.parse_any_path(path, **kwargs)

  @classmethod
  def parse_wpr_archive_path(cls, path: pth.LocalPath) -> Self:
    path = PathParser.non_empty_file_path(path, "webpagereplay archive")
    return cls(type=NetworkType.WPR, path=path)

  @classmethod
  def parse_wpr_archive_url(cls, url: str) -> Self:
    return cls(type=NetworkType.WPR, url=url)

  @override
  def validate(self) -> None:
    if not self.type:
      raise argparse.ArgumentTypeError("Missing NetworkConfig.type.")
    if not self.speed and isinstance(self.speed, NetworkSpeedConfig):
      raise argparse.ArgumentTypeError("Missing NetworkConfig.speed.")
    if self.type == NetworkType.LIVE:
      if self.path:
        raise argparse.ArgumentTypeError(
            "NetworkConfig path cannot be used with type=live")
    elif self.type is NetworkType.WPR:
      if not self.path and not self.url:
        raise argparse.ArgumentTypeError(
            "NetworkConfig with type=replay requires "
            "a valid webpagereplay archive path or download url.")
      if self.path and self.url:
        raise argparse.ArgumentTypeError(
            "NetworkConfig with type=replay requires "
            "either archive path or download url but not both.")
    elif self.type is NetworkType.LOCAL:
      if not self.path:
        raise argparse.ArgumentTypeError(
            "NetworkConfig with type=local requires "
            "a valid local dir path to serve files.")
      PathParser.non_empty_dir_path(self.path, "local-serve dir")

    wpr_only_options = ("persist_server", "run_on_device",
                        "skip_deterministic_script_injection", "host",
                        "no_archive_certificates",
                        "response_transformations_file", "cross_platform_mode",
                        "http_port", "https_port", "expected_md5_hash")
    for option in wpr_only_options:
      if getattr(self, option) and self.type is not NetworkType.WPR:
        raise argparse.ArgumentTypeError(
            f"{option} can only be used for the WPR replay network")

    if self.cross_platform_mode and self.run_on_device:
      raise argparse.ArgumentTypeError(
          "cross_platform_mode is incompatible with run_on_device")

    if self.cross_platform_mode and (self.http_port or self.https_port):
      raise argparse.ArgumentTypeError(
          "http_port and https_port cannot be set in cross_platform_mode")

  def create_network(self, browser_platform: Platform) -> Network:
    with exception.annotate_argparsing(
        f"Setting up {self.type} network for {browser_platform}"):
      traffic_shaper = self._create_traffic_shaper(browser_platform)
      if self.type is NetworkType.LIVE:
        return LiveNetwork(traffic_shaper, browser_platform)
      if self.type is NetworkType.LOCAL:
        assert self.path, "Missing local network path"
        return LocalFileNetwork(self.path, self.url, traffic_shaper,
                                browser_platform)
      if self.type is NetworkType.WPR:
        if self.run_on_device and browser_platform.is_remote:
          if not RemoteWprReplayNetwork.is_compatible(browser_platform):
            raise ValueError(
                f"run_on_device is unsupported on {browser_platform}")
          return RemoteWprReplayNetwork(
              self.url or str(self.path),
              traffic_shaper,
              browser_platform,
              self.persist_server,
              no_archive_certificates=self.no_archive_certificates,
              response_transformations_file=self.response_transformations_file,
              inject_deterministic_script=not self
              .skip_deterministic_script_injection,
              host=self.host,
              http_port=self.http_port,
              https_port=self.https_port,
              expected_md5_hash=self.expected_md5_hash)
        return LocalWprReplayNetwork(
            self.url or str(self.path),
            traffic_shaper,
            browser_platform,
            self.persist_server,
            no_archive_certificates=self.no_archive_certificates,
            response_transformations_file=self.response_transformations_file,
            inject_deterministic_script=not self
            .skip_deterministic_script_injection,
            cross_platform_mode=self.cross_platform_mode,
            host=self.host,
            http_port=self.http_port,
            https_port=self.https_port,
            expected_md5_hash=self.expected_md5_hash)
    raise ValueError(f"Unknown network type {self.type}")

  def is_default(self) -> bool:
    return self is NetworkConfig.default()

  def _create_traffic_shaper(self, browser_platform: Platform) -> TrafficShaper:
    if self.speed.is_live:
      return NoTrafficShaper(browser_platform)
    return ts_proxy.TsProxyTrafficShaper(browser_platform, self.speed.ts_proxy,
                                         self.speed.rtt_ms, self.speed.in_kbps,
                                         self.speed.out_kbps, self.speed.window)
