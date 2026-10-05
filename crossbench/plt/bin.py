# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import functools
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self, TypeAlias, cast

from typing_extensions import override

from crossbench import path as pth
from crossbench.helper.path_finder_base import ChromiumCheckoutFinder

if TYPE_CHECKING:
  from crossbench.plt.base import Platform
  BinaryLookup: TypeAlias = pth.AnyPathLike | tuple[pth.AnyPathLike, ...]


def validate_win_binary(binary_name: str) -> None:
  if not binary_name.lower().endswith((".exe", ".bat")):
    raise ValueError(
        f"Windows binary {binary_name} should have '.exe' or '.bat' suffix")


class BinaryPath(abc.ABC):
  """Abstract base class to look up different kinds of binaries."""

  @property
  def path(self) -> pth.AnyPath | None:
    """Return the candidate path."""
    return None

  @abc.abstractmethod
  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    """Main entry point to resolve a binary."""

  def validate_win(self) -> None:
    """Specialized windows validation (e.g. check for .exe suffix)"""
    if path := self.path:
      validate_win_binary(path.name)

  def for_windows(self) -> Self:
    """Return a windows compatible version of this lookup."""
    if not (path := self.path):
      return self
    if path.suffix.lower() in (".exe", ".bat"):
      return self
    cls: Any = type(self)
    return cast(Self, cls(f"{path}.exe"))


class SystemPath(BinaryPath):
  """Lookup a binary using in the current PATH using platform.search."""

  def __init__(self, binary: pth.AnyPathLike):
    if not binary:
      raise ValueError("SystemPath requires a non-empty string for binary name")
    self.binary: Final[pth.AnyPath] = pth.AnyPath(binary)

  @property
  @override
  def path(self) -> pth.AnyPath:
    return self.binary

  @override
  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    return platform.search_binary(self.binary)


class EnvVarPath(BinaryPath):
  """Look up a binary with an ENV variable."""

  def __init__(self, env_var: str):
    assert env_var, "ENV_VAR must be a non-empty string"
    self.env_var: Final[str] = env_var

  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    if env_path_str := platform.environ.get(self.env_var):
      return platform.search_binary(env_path_str)
    return None


@functools.cache
def _find_chromium_checkout(platform: Platform) -> pth.AnyPath | None:
  return ChromiumCheckoutFinder(platform).path


class ChromePath(BinaryPath):

  def __init__(self, relative_path: pth.AnyPathLike):
    # Enforce standard AnyPath wrapping
    self.relative_path: Final[pth.AnyPath] = pth.AnyPath(relative_path)
    assert self.relative_path.parts, (
        "ChromiumLookup requires a non-empty relative_path")

  @property
  @override
  def path(self) -> pth.AnyPath:
    return self.relative_path

  @override
  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    if maybe_chrome := _find_chromium_checkout(platform):
      candidate = maybe_chrome / self.relative_path
      if platform.exists(candidate):
        return candidate
    return None


class PerfettoChromePath(ChromePath):
  """Lookup a Perfetto binary in Chrome's third_party/perfetto/tools."""

  PERFETTO_TOOLS_PATH: ClassVar[pth.AnyPath] = pth.AnyPath(
      "third_party/perfetto/tools")

  def __init__(self, binary: pth.AnyPathLike):
    self.binary: Final[pth.AnyPath] = pth.AnyPath(binary)
    if len(self.binary.parts) != 1:
      raise ValueError(f"binary '{binary}' must not contain path separators")
    super().__init__(self.PERFETTO_TOOLS_PATH / self.binary)

  @property
  @override
  def path(self) -> pth.AnyPath:
    return self.binary


class ChromeBuildPath(BinaryPath):
  """Lookup a binary in Chrome build directories."""

  BUILD_DIR_NAMES: Final[tuple[str, ...]] = (
      "Default",
      "Release",
      "release",
      "rel",
      "Optdebug",
      "optdebug",
      "opt",
  )

  def __init__(self, binary: pth.AnyPathLike):
    self.binary: Final[pth.AnyPath] = pth.AnyPath(binary)
    if len(self.binary.parts) != 1:
      raise ValueError(f"binary '{binary}' must not contain path separators")

  @property
  @override
  def path(self) -> pth.AnyPath:
    return self.binary

  @override
  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    if not (maybe_chrome := _find_chromium_checkout(platform)):
      return None
    candidate_out = maybe_chrome / "out"
    if not platform.is_dir(candidate_out):
      return None
    for build in self.BUILD_DIR_NAMES:
      candidate = candidate_out / build / self.binary
      if platform.is_file(candidate):
        return candidate
    for candidate in sorted(platform.glob(candidate_out, f"*/{self.binary}")):
      if platform.is_file(candidate):
        return candidate
    return None


BinaryPathElement: TypeAlias = pth.AnyPathLike | BinaryPath
BinaryPathArg: TypeAlias = BinaryPathElement | tuple[BinaryPathElement, ...]


class AndroidBuildToolPath(BinaryPath):
  """Lookup Android Build Tools by resolving the highest version number
  in a build-tools directory."""

  CHROME_SDK_PATH: ClassVar[pth.AnyPath] = pth.AnyPath(
      "third_party/android_sdk/public")

  def __init__(self,
               tool_name: str,
               fallback_sdk_path: pth.AnyPathLike | None = None):
    assert len(pth.AnyPath(tool_name).parts) == 1, (
        f"tool_name '{tool_name}' must not contain path separators")
    self.fallback_sdk_path: Final[pth.AnyPath | None] = (
        pth.AnyPath(fallback_sdk_path) if fallback_sdk_path else None)
    self.tool_name: Final[str] = str(tool_name)

  @property
  @override
  def path(self) -> pth.AnyPath:
    return pth.AnyPath(self.tool_name)

  @override
  def for_windows(self) -> Self:
    if self.path.suffix.lower() in (".exe", ".bat"):
      return self
    return type(self)(f"{self.tool_name}.exe", self.fallback_sdk_path)

  def _sort_key(self, path: pth.AnyPath) -> tuple[int, ...]:
    try:
      return tuple(int(x) for x in path.name.split("."))
    except ValueError:
      return (0,)

  def _find_tool_in_sdk(self, platform: Platform,
                        base_sdk_path: pth.AnyPath) -> pth.AnyPath | None:
    build_tools_dir = base_sdk_path / "build-tools"
    if not platform.exists(build_tools_dir):
      return None

    valid_dirs = []
    for child in platform.iterdir(build_tools_dir):
      if platform.is_dir(child):
        valid_dirs.append(child)

    if not valid_dirs:
      return None

    valid_dirs.sort(key=self._sort_key)

    candidate = valid_dirs[-1] / self.tool_name
    if platform.exists(candidate):
      return candidate
    return None

  def resolve(self, platform: Platform) -> pth.AnyPath | None:
    if maybe_chrome := _find_chromium_checkout(platform):
      if candidate := self._find_tool_in_sdk(
          platform, maybe_chrome / self.CHROME_SDK_PATH):
        return candidate

    if not self.fallback_sdk_path:
      return None

    parts = list(self.fallback_sdk_path.parts)
    if parts and parts[0] == "~":
      base_dir = platform.home() / pth.AnyPath(*parts[1:])
    else:
      base_dir = self.fallback_sdk_path

    return self._find_tool_in_sdk(platform, base_dir)

class BinaryNotFoundError(RuntimeError):

  def __init__(self, binary: Binary, platform: Platform) -> None:
    self.binary: Final[Binary] = binary
    self.platform: Final[Platform] = platform
    super().__init__(self._create_message())

  def _create_message(self) -> str:
    return (f"Could not find binary '{self.binary}' on {self.platform}. "
            f"Please install {self.binary.name} or use the "
            f"--bin-{self.binary.name} "
            "command line flag to manually specify a path.")


class UnsupportedPlatformError(BinaryNotFoundError):

  def __init__(self, binary: Binary, platform: Platform, expected: str) -> None:
    self.expected_platform_name: str = expected
    super().__init__(binary, platform)

  @override
  def _create_message(self) -> str:
    return (f"Could not find binary '{self.binary}' on {self.platform}. "
            f"Only supported on {self.expected_platform_name}")


class Binary:
  """A binary abstraction for multiple platforms.
  Use this implementation to define binaries that exist on multiple platforms.
  For platform-specific binaries use subclasses of Binary."""

  def __init__(self,
               name: str,
               default: BinaryPathArg | None = None,
               posix: BinaryPathArg | None = None,
               linux: BinaryPathArg | None = None,
               android: BinaryPathArg | None = None,
               macos: BinaryPathArg | None = None,
               win: BinaryPathArg | None = None,
               chromeos: BinaryPathArg | None = None) -> None:
    self._name = name
    self._default = self._convert(default)
    self._posix = self._convert(posix)
    self._linux = self._convert(linux)
    self._android = self._convert(android)
    self._macos = self._convert(macos)
    self._win = self._convert(win)
    self._validate_win()
    self._chromeos = self._convert(chromeos)
    if not any((chromeos, default, posix, linux, android, macos, win)):
      raise ValueError("At least one platform binary must be provided")

  def _convert(self,
               paths: BinaryPathArg
               | None = None) -> tuple[BinaryPath, ...]:
    if paths is None:
      return ()
    if isinstance(paths, tuple):
      return tuple(self._convert_to_paths(path) for path in paths)
    return (self._convert_to_paths(paths),)

  def _convert_to_paths(self, element: BinaryPathElement) -> BinaryPath:
    if isinstance(element, BinaryPath):
      return element
    return SystemPath(element)

  def _validate_win(self) -> None:
    for bin_path in self._win:
      bin_path.validate_win()

  @property
  def name(self) -> str:
    return self._name

  def __str__(self) -> str:
    return self._name

  def search(self, platform: Platform) -> pth.AnyPath | None:
    self._validate_platform(platform)
    for element in self.platform_path(platform):
      if result := element.resolve(platform):
        return result
    return None

  def exists(self, platform: Platform) -> bool:
    return self.search(platform) is not None

  @functools.cache
  def resolve_cached(self, platform: Platform) -> pth.AnyPath:
    return self.resolve(platform)

  def resolve(self, platform: Platform) -> pth.AnyPath:
    if path := self.search(platform):
      return path
    raise BinaryNotFoundError(self, platform)

  def platform_path(self, platform: Platform) -> tuple[BinaryPath, ...]:
    if self._chromeos and platform.is_chromeos:
      return self._chromeos
    if self._linux and platform.is_linux:
      return self._linux
    if self._android and platform.is_android:
      return self._android
    if self._macos and platform.is_macos:
      return self._macos
    if self._posix and platform.is_posix:
      return self._posix
    if platform.is_win:
      if self._win:
        return self._win
      if self._default:
        return self._win_default()
    return self._default

  def _win_default(self) -> tuple[BinaryPath, ...]:
    return tuple(default.for_windows() for default in self._default)

  def _validate_platform(self, platform: Platform) -> None:
    pass


class PosixBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyPosixPath(name).name, posix=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_posix:
      raise UnsupportedPlatformError(self, platform, "posix")


class MacOsBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyPosixPath(name).name, macos=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_macos:
      raise UnsupportedPlatformError(self, platform, "macos")


class LinuxBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyPosixPath(name).name, linux=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_posix:
      raise UnsupportedPlatformError(self, platform, "linux")


class AndroidBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyPosixPath(name).name, android=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_android:
      raise UnsupportedPlatformError(self, platform, "android")


class WinBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyWindowsPath(name).name, win=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_win:
      raise UnsupportedPlatformError(self, platform, "windows")


class ChromeOSBinary(Binary):

  def __init__(self, name: pth.AnyPathLike) -> None:
    super().__init__(pth.AnyPosixPath(name).name, chromeos=name)

  @override
  def _validate_platform(self, platform: Platform) -> None:
    if not platform.is_chromeos:
      raise UnsupportedPlatformError(self, platform, "chromeos")


class Binaries:
  ADB: ClassVar = Binary(
      "adb",
      macos=(
          "adb",
          "~/Library/Android/sdk/platform-tools/adb",
          ChromePath("third_party/android_sdk/public/platform-tools/adb"),
      ),
      linux=(
          "adb",
          ChromePath("third_party/android_sdk/public/platform-tools/adb"),
      ),
      win=(
          "adb.exe",
          "Android/sdk/platform-tools/adb.exe",
          ChromePath("third_party/android_sdk/public/platform-tools/adb.exe"),
      ))
  AAPT: ClassVar = Binary(
      "aapt",
      macos=(
          "aapt",
          AndroidBuildToolPath("aapt", "~/Library/Android/sdk"),
      ),
      linux=(
          "aapt",
          AndroidBuildToolPath("aapt"),
      ),
      win=(
          "aapt.exe",
          AndroidBuildToolPath("aapt.exe", "Android/sdk"),
      ))
  CPIO: ClassVar = LinuxBinary("cpio")
  FFMPEG: ClassVar = Binary("ffmpeg", posix="ffmpeg")
  GCERT: ClassVar = Binary("gcert", posix="gcert")
  GCERTSTATUS: ClassVar = Binary("gcertstatus", posix="gcertstatus")
  GCLOUD: ClassVar = Binary("gcloud", default="gcloud")
  LSCPU: ClassVar = LinuxBinary("lscpu")
  LUCI_AUTH: ClassVar = Binary("luci-auth", default="luci-auth")
  MONTAGE: ClassVar = Binary("montage", posix="montage")
  ON_AC_POWER: ClassVar = LinuxBinary("on_ac_power")
  PERF: ClassVar = LinuxBinary("perf")
  PPROF: ClassVar = LinuxBinary("pprof")
  PYTHON3: ClassVar = Binary("python3", default="python3", win="python3.exe")
  RPM2CPIO: ClassVar = LinuxBinary("rpm2cpio")
  SIMPLEPERF: ClassVar = AndroidBinary("simpleperf")
  XCTRACE: ClassVar = MacOsBinary("xctrace")
  CHROMEDRIVER: ClassVar = Binary(
      "chromedriver",
      chromeos="/usr/local/chromedriver/chromedriver",
      linux="chromedriver")
  LLVM_SYMBOLIZER: ClassVar = Binary(
      "llvm-symbolizer",
      default=(
          ChromePath(
              "third_party/llvm-build/Release+Asserts/bin/llvm-symbolizer"),
          "llvm-symbolizer",
      ))
  TRACECONV: ClassVar = Binary(
      "traceconv", default=(
          PerfettoChromePath("traceconv"),
          "traceconv",
      ))
  TRACEBOX: ClassVar = Binary(
      "tracebox", default=(
          PerfettoChromePath("tracebox"),
          "tracebox",
      ))
  TRACE_PROCESSOR: ClassVar = Binary(
      "trace_processor",
      default=(
          PerfettoChromePath("trace_processor"),
          "trace_processor",
      ))
  TRACE_PROCESSOR_SHELL: ClassVar = Binary(
      "trace_processor_shell",
      default=(
          ChromeBuildPath("trace_processor_shell"),
          PerfettoChromePath("trace_processor"),
          "trace_processor_shell",
          "trace_processor",
      ))


class Browsers:
  SAFARI: ClassVar = MacOsBinary("Safari.app")
  SAFARI_TECH_PREVIEW: ClassVar = MacOsBinary("Safari Technology Preview.app")
  FIREFOX_STABLE: ClassVar = Binary(
      "firefox stable",
      macos="Firefox.app",
      linux="firefox",
      win="Mozilla Firefox/firefox.exe")
  FIREFOX_DEV: ClassVar = Binary(
      "firefox developer edition",
      macos="Firefox Developer Edition.app",
      linux="firefox-developer-edition",
      win="Firefox Developer Edition/firefox.exe")
  FIREFOX_NIGHTLY: ClassVar = Binary(
      "Firefox nightly",
      macos="Firefox Nightly.app",
      linux=("firefox-nightly", "firefox-trunk"),
      win="Firefox Nightly/firefox.exe")
