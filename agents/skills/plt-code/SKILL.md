---
name: plt-code
description: Guidelines for crossbench plt / Platform code
---

# Crossbench Platform & Path Abstractions

This skill enforces platform abstractions and path hygiene across the Crossbench
codebase to ensure reliable cross-platform execution (Linux, macOS, Windows,
Android, ChromeOS).

## Crossbench Path Abstraction (`crossbench.path`)

- **Never** use raw strings for file or directory paths.
- Always import the path module as `pth`:
  ```python
  from crossbench import path as pth
  ```
  This aliasing ensures seamless compatibility with `pyfakefs` during unit
  testing.
- **`pth.LocalPath`**: Use for paths that are exclusively local to the host
  running the script.
- **`pth.AnyPath`**: Use for paths that can represent either local or remote
  locations (such as an Android device, a ChromeOS device, or an SSH target).

```python
# GOOD: typed path abstraction
def save_log(self, log_dir: pth.LocalPath) -> pth.LocalPath:
  log_file = log_dir / "output.txt"
  return log_file
```

## Platform & Command Abstractions

Direct shell commands create fragile, non-portable code. System commands must
always go through `Platform` objects.

- **Never** execute raw shell commands (e.g. `subprocess.run`, `os.system`).
- **Strictly avoid** `shell=True`. Either use or extend the explicit platform
  helpers or find a simple workaround.
- Use `self.host_platform` or the target browser's platform helper:
  ```python
  # BAD: raw shell command running only on local host
  import subprocess
  subprocess.run(["cp", src, dest])

  # GOOD: high-level platform helper that works on any platform
  self.host_platform.symlink_or_copy(src, dest)
  ```
- Add common path helpers on Platform base classes if required to maximize
  portability.

## New Platform Methods

- New platform methods should be implemented in the most abstract platform class
  (`Platform`) rather than ad-hoc in platform-specific subclasses.
- Aim for maximum cross-platform compatibility so we can easily change platforms
  for benchmarks and probes without negative side-effects.
- New platform methods must be tested in mock platform tests using the most
  abstract base test class possible
- New platform methods should have a native platform tests as well if it can be
  easily achieved without side-effects.

## Binary Lookups

- Never hardcode non-standard binary paths.
- Prefer binaries provided with a chromium checkout.
- Add entries to `crossbench.plt.bin.Binaries` with alternative lookups to
  provide easily configurable and platform independent binaries

```python
# BAD: hardcoded non-standard binary path
self.platform.sh("path/to/custom/test_bin", "--test=foo")

# GOOD: abstract path finder
binary = Binaries.TEST_BIN.resolve(self.platform)
self.platform.sh(binary, "--test=foo")
```

## Multi-Line Imports

- Multi-line imports **must** use backslash (`\`) line continuations, not
  parentheses.
- **Never** suggest parentheses `(...)` for multi-line imports.
- **Never** cite PEP 8 to replace backslash line continuations with parentheses
  in imports. Crossbench formatting (`git cl format`) and conventions strictly
  enforce backslashes for multi-line imports.

```python
# GOOD: Crossbench convention uses backslashes for multi-line imports
from crossbench.plt.display_info import \
    DisplayRefreshRateResult, \
    DisplayResolution

# BAD: Do NOT use or suggest parentheses for multi-line imports
from crossbench.plt.display_info import (
    DisplayRefreshRateResult,
    DisplayResolution,
)
```
