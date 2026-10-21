# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import enum
import logging
import re
import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
  from crossbench import plt


class VolumeMode(enum.StrEnum):
  ON = "on"
  OFF = "off"
  UNCHANGED = "unchanged"


# TODO(eladalon): Upstream this volume control helper into core Crossbench
# platform infrastructure.
class AndroidVolumeController:
  """Helper to control and inspect Android music volume streams."""

  def __init__(self, platform: plt.Platform) -> None:
    self._platform: Final[plt.Platform] = platform

  def configure_volume(self, target_volume: VolumeMode) -> None:
    """Configures device music stream volume."""
    if target_volume == VolumeMode.UNCHANGED:
      logging.info("Keeping volume unchanged.")
      return

    target_volume_on = (target_volume == VolumeMode.ON)
    if CmdAudioController(self._platform).set_volume(target_volume_on):
      logging.info("Volume successfully adjusted using adb's cmd audio.")
    elif LegacyAudioController(self._platform).set_volume(target_volume_on):
      logging.info("Volume successfully adjusted using fallback keyevents.")
    else:
      raise RuntimeError("Failed to configure volume.")


class CmdAudioController:
  """Controls Android volume using the modern 'cmd audio' manager."""

  # Android AudioManager stream type documentation:
  # https://developer.android.com/reference/android/media/AudioManager#STREAM_MUSIC
  _STREAM_MUSIC: str = "3"

  def __init__(self, platform: plt.Platform) -> None:
    self._platform: Final[plt.Platform] = platform

  def _cmd_audio(self, *args: str) -> str:
    """Executes 'cmd audio' and returns the decoded stdout."""
    return self._platform.sh(
        "cmd", "audio", *args, capture_output=True).stdout.decode()

  def _get_volume(self) -> int:
    """Retrieves current volume level."""
    output = self._cmd_audio("get-stream-volume", self._STREAM_MUSIC)
    # Expected output format: "AudioManager.getStreamVolume(3) -> 15"
    pattern = (rf"AudioManager\.getStreamVolume\({self._STREAM_MUSIC}\)\s*->\s*"
               r"(?P<volume>\d+)")
    if m := re.search(pattern, output):
      return int(m.group("volume"))
    raise ValueError(f"Unexpected get-stream-volume output format: {output}")

  def _is_muted(self) -> bool:
    """Checks whether the stream is muted."""
    output = self._cmd_audio("is-stream-mute", self._STREAM_MUSIC)
    return "true" in output.lower()

  def _is_music_audible(self) -> bool:
    """Returns True if the stream is currently active and audible."""
    return self._get_volume() > 0 and not self._is_muted()

  def set_volume(self, target_volume_on: bool) -> bool:
    """Configures music stream volume level. Returns True if successful."""
    try:
      if target_volume_on == self._is_music_audible():
        return True

      # Construct target volume level (preserve positive volume if unmuting).
      if not target_volume_on:
        volume_level = "0"
      else:
        current_volume = self._get_volume()
        volume_level = str(current_volume) if current_volume > 0 else "1"

      self._cmd_audio("set-volume", self._STREAM_MUSIC, volume_level)

      return (self._is_music_audible() == target_volume_on)
    except Exception as e:  # noqa: BLE001
      logging.warning("Failed to set volume via 'cmd audio': %s", e)
      return False


class LegacyAudioController:
  """Controls Android volume using legacy dumpsys audio and keyevents."""

  # Android KeyEvent code documentation:
  # https://developer.android.com/reference/android/view/KeyEvent
  KEYCODE_VOLUME_MUTE: str = "164"
  KEYCODE_VOLUME_UP: str = "24"

  def __init__(self, platform: plt.Platform) -> None:
    self._platform: Final[plt.Platform] = platform

  def _input_keyevent(self, keycode: str) -> None:
    """Sends an input keyevent command to the device."""
    self._platform.sh("input", "keyevent", keycode)

  def _is_music_audible(self) -> bool:
    music_info = self._get_music_stream_info()
    return not (re.search(r"Muted:\s*true", music_info, re.IGNORECASE) or
                re.search(r"streamVolume:\s*0(?!\d)", music_info,
                          re.IGNORECASE))

  def _get_music_stream_info(self) -> str:
    """Extracts the STREAM_MUSIC block from dumpsys audio."""
    result = self._platform.sh("dumpsys", "audio", capture_output=True)
    stdout_str = result.stdout.decode()

    # Match STREAM_MUSIC block up to the next STREAM_ block or end of string.
    pattern = r"(?:- )?STREAM_MUSIC:.*?(?=(?:- )?STREAM_|$)"
    if m := re.search(pattern, stdout_str, re.DOTALL):
      return m.group(0)
    raise ValueError("Could not isolate STREAM_MUSIC block from dumpsys audio.")

  def set_volume(self, target_volume_on: bool) -> bool:
    """Configures music stream volume via keyevents. Returns True on success."""
    try:
      if target_volume_on == self._is_music_audible():
        return True

      if not target_volume_on:
        self._input_keyevent(self.KEYCODE_VOLUME_MUTE)
      else:
        # Sending the keyevent twice ensures that the first unmutes the stream
        # and the second actually increases the volume level above 0.
        self._input_keyevent(self.KEYCODE_VOLUME_UP)
        self._input_keyevent(self.KEYCODE_VOLUME_UP)

      # Allow the device a brief moment to dispatch and process the keyevents.
      time.sleep(1.0)

      return target_volume_on == self._is_music_audible()
    except Exception as e:  # noqa: BLE001
      logging.warning("Failed to set volume via keyevents: %s", e)
      return False
