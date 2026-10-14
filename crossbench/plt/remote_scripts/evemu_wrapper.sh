# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Wrapper script for bootstrapping and playing events into a Linux/ChromeOS
# evemu virtual input device within a single process.
#
# Usage: sh -c "$(cat evemu_wrapper.sh)" -- "<evemu_device_descriptor>"
#
# Lifecycle:
#   1. Writes the EVEMU device descriptor ($1) to a temporary file and launches
#      `evemu-device` in the background to register the uinput kernel device.
#   2. Reads the first output line from `evemu-device` (e.g.
#      "Crossbench Keyboard: /dev/input/event4") via a FIFO, forwards that line
#      to stdout so the host knows the device is ready, and removes the
#      temporary descriptor and FIFO files.
#   3. Runs `evemu-play` in the foreground on the created /dev/input/eventX
#      node, reading E: event lines streamed by the host over stdin until EOF.
#   4. When `evemu-play` exits (e.g. when the host closes stdin on teardown) or
#      the wrapper receives a signal, the EXIT/signal trap kills the background
#      `evemu-device` daemon so the kernel uinput device is immediately
#      destroyed.

for bin in evemu-device evemu-play; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    printf "error: required binary '%s' not found in PATH " "$bin"
    printf "(install evemu-tools)\n"
    exit 1
  fi
done

if [ ! -e /dev/uinput ]; then
  printf "error: /dev/uinput does not exist "
  printf "(load kernel module: sudo modprobe uinput)\n"
  exit 1
fi

if [ ! -r /dev/uinput ] || [ ! -w /dev/uinput ]; then
  if [ ! -d /sys/class/misc/uinput ]; then
    printf "error: /dev/uinput is not accessible and the 'uinput' kernel "
    printf "module is not loaded (run: sudo modprobe uinput)\n"
  else
    printf "error: insufficient permissions for /dev/uinput\n"
  fi
  exit 1
fi

dev_pid=""
tmp=$(mktemp /tmp/evemu_XXXXXX) || exit 1
fifo="$tmp.fifo"

cleanup() {
  trap - EXIT HUP INT TERM
  rm -f "$tmp" "$fifo"
  if [ -n "$dev_pid" ]; then
    kill -9 "$dev_pid" 2>/dev/null
    wait "$dev_pid" 2>/dev/null
  fi
  exit
}
trap cleanup EXIT HUP INT TERM

# Use a named pipe (FIFO) to capture `evemu-device`'s stdout line without
# using a shell pipeline (`evemu-device | ...`), which would replace
# `evemu-play`'s stdin with the pipe instead of the wrapper's stdin stream.
mkfifo "$fifo" || exit 1
printf "%s" "$1" >"$tmp"

# Detach `evemu-device` from the wrapper's stdin (`</dev/null`) so it does not
# compete with `evemu-play` for incoming event lines.
evemu-device "$tmp" </dev/null >"$fifo" 2>&1 &
dev_pid=$!

# Block until `evemu-device` prints the created device node line (or exits on
# error), then clean up the temporary files and report the line to the host.
IFS= read -r line <"$fifo"
rm -f "$tmp" "$fifo"
printf "%s\n" "$line"

# Extract the path after the last ": " (expected: /dev/input/eventX) and start
# `evemu-play` in the foreground, inheriting the wrapper's stdin.
node=${line##*: }
case "$node" in
  /dev/input/*) evemu-play "$node" >/dev/null 2>&1 ;;
  *) exit 1 ;;
esac
