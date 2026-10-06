# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import Final, NamedTuple

from immutabledict import immutabledict


class KeyMapping(NamedTuple):
  key: str
  code: str
  has_shift: bool = False


def _build_us_keyboard_layout() -> immutabledict[str, KeyMapping]:
  layout: dict[str, KeyMapping] = {
      "0": KeyMapping("0", "Digit0"),
      "1": KeyMapping("1", "Digit1"),
      "2": KeyMapping("2", "Digit2"),
      "3": KeyMapping("3", "Digit3"),
      "4": KeyMapping("4", "Digit4"),
      "5": KeyMapping("5", "Digit5"),
      "6": KeyMapping("6", "Digit6"),
      "7": KeyMapping("7", "Digit7"),
      "8": KeyMapping("8", "Digit8"),
      "9": KeyMapping("9", "Digit9"),
      ")": KeyMapping(")", "Digit0", has_shift=True),
      "!": KeyMapping("!", "Digit1", has_shift=True),
      "@": KeyMapping("@", "Digit2", has_shift=True),
      "#": KeyMapping("#", "Digit3", has_shift=True),
      "$": KeyMapping("$", "Digit4", has_shift=True),
      "%": KeyMapping("%", "Digit5", has_shift=True),
      "^": KeyMapping("^", "Digit6", has_shift=True),
      "&": KeyMapping("&", "Digit7", has_shift=True),
      "*": KeyMapping("*", "Digit8", has_shift=True),
      "(": KeyMapping("(", "Digit9", has_shift=True),
      " ": KeyMapping(" ", "Space"),
      "`": KeyMapping("`", "Backquote"),
      "~": KeyMapping("~", "Backquote", has_shift=True),
      "-": KeyMapping("-", "Minus"),
      "_": KeyMapping("_", "Minus", has_shift=True),
      "=": KeyMapping("=", "Equal"),
      "+": KeyMapping("+", "Equal", has_shift=True),
      "[": KeyMapping("[", "BracketLeft"),
      "{": KeyMapping("{", "BracketLeft", has_shift=True),
      "]": KeyMapping("]", "BracketRight"),
      "}": KeyMapping("}", "BracketRight", has_shift=True),
      "\\": KeyMapping("\\", "Backslash"),
      "|": KeyMapping("|", "Backslash", has_shift=True),
      ";": KeyMapping(";", "Semicolon"),
      ":": KeyMapping(":", "Semicolon", has_shift=True),
      "'": KeyMapping("'", "Quote"),
      '"': KeyMapping('"', "Quote", has_shift=True),
      ",": KeyMapping(",", "Comma"),
      "<": KeyMapping("<", "Comma", has_shift=True),
      ".": KeyMapping(".", "Period"),
      ">": KeyMapping(">", "Period", has_shift=True),
      "/": KeyMapping("/", "Slash"),
      "?": KeyMapping("?", "Slash", has_shift=True),
      "\n": KeyMapping("Enter", "Enter"),
      "\r": KeyMapping("Enter", "Enter"),
      "\t": KeyMapping("Tab", "Tab"),
  }
  for char in "abcdefghijklmnopqrstuvwxyz":
    layout[char] = KeyMapping(char, f"Key{char.upper()}")
    layout[char.upper()] = KeyMapping(
        char.upper(), f"Key{char.upper()}", has_shift=True)
  return immutabledict(layout)


# Represents a mapping from standard characters to W3C KeyboardEvent.code
# physical keys. This maps directly to the UI Events KeyboardEvent code values
# specification: https://www.w3.org/TR/uievents-code/
US_KEYBOARD_LAYOUT: Final[immutabledict[str, KeyMapping]] = (
    _build_us_keyboard_layout())


def _build_reverse_us_keyboard_layout() -> immutabledict[tuple[str, bool], str]:
  return immutabledict({
      (mapping.code, mapping.has_shift): char
      for char, mapping in US_KEYBOARD_LAYOUT.items()
      if len(mapping.key) == 1
  })


# Maps (W3C KeyboardEvent.code, has_shift) pairs back to their original
# character. UnifiedInputActionRunner translates text strings into low-level
# KeyEvent sequences (using W3C key codes and ShiftLeft modifier events) before
# passing them to Platform.inject_input_events(). On older Android devices
# (SDK < 37) where uinput EVEMU injection is unsupported, AndroidAdbPlatform
# falls back to `adb shell input keyboard text <str>` and needs this reverse
# mapping to reconstruct the text string from the KeyEvent stream.
REVERSE_US_KEYBOARD_LAYOUT: Final[immutabledict[tuple[str, bool], str]] = (
    _build_reverse_us_keyboard_layout())

# Maps non-character W3C KeyboardEvent.code values to Android keyevent names for
# the legacy `adb shell input keyevent` fallback on Android SDK < 37.
W3C_TO_ANDROID_KEYCODE: Final[immutabledict[str, str]] = immutabledict({
    "Enter": "KEYCODE_ENTER",
    "Tab": "KEYCODE_TAB",
    "Space": "KEYCODE_SPACE",
    "Backspace": "KEYCODE_DEL",
    "Delete": "KEYCODE_FORWARD_DEL",
    "Escape": "KEYCODE_ESCAPE",
    "ArrowUp": "KEYCODE_DPAD_UP",
    "ArrowDown": "KEYCODE_DPAD_DOWN",
    "ArrowLeft": "KEYCODE_DPAD_LEFT",
    "ArrowRight": "KEYCODE_DPAD_RIGHT",
    "Home": "KEYCODE_MOVE_HOME",
    "End": "KEYCODE_MOVE_END",
    "PageUp": "KEYCODE_PAGE_UP",
    "PageDown": "KEYCODE_PAGE_DOWN",
    "ShiftLeft": "KEYCODE_SHIFT_LEFT",
    "ShiftRight": "KEYCODE_SHIFT_RIGHT",
    "ControlLeft": "KEYCODE_CTRL_LEFT",
    "ControlRight": "KEYCODE_CTRL_RIGHT",
    "AltLeft": "KEYCODE_ALT_LEFT",
    "AltRight": "KEYCODE_ALT_RIGHT",
    "MetaLeft": "KEYCODE_META_LEFT",
    "MetaRight": "KEYCODE_META_RIGHT",
})
