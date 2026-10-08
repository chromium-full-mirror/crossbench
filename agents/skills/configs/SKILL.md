---
name: configs
description: Guidelines for crossbench ConfigObjects
---

# Crossbench ConfigObjects & Input Parsing

This skill enforces input validation patterns and immutable configuration object
structures across Crossbench.

## Review Scope

- **Only** report findings about input validation and `ConfigObject` patterns
  covered by this skill.
- **Do not** comment on general Python style or formatting (imports, line
  continuations, line length, naming, comments, etc.). These are owned by the
  separate `cb-style` review agent, and crossbench conventions intentionally
  differ from PEP 8 and the Google Python Style Guide in places.

## Early Input Validation

- All user input and CLI/HJSON arguments must pass through validation helpers in
  `crossbench.parse` or directly with a `ConfigObject`.
- config parser or argparse input choices values can be enums as well
- Perform input validation early at the parsing boundary (config parser or
  argument parsing) to give good CLI experience.
- Any new parser helper method in `crossbench.parse` **must** have a dedicated
  unit test.

## Dedicated `ConfigObject` Pattern

- Any complex or structured input parameter must be modelled as a dedicated,
  immutable / frozen `ConfigObject` (inheriting from
  `crossbench.config.ConfigObject`).
- Provide comprehensive docstrings and example configuration files in
  `config/doc/` or under `config/*`.
- Every new `ConfigObject` requires dedicated unit tests covering:
  1. Short-form string parsing (e.g. `--probe=v8.log:all`).
  2. Full dictionary/HJSON parsing (e.g.
     `--probe=v8.log:{categories: ['all']}`).
  3. An example config.hjson file if it's has a dedicated command line flag
- Every `ConfigObject` that is directly used in a config must be public as it is
  exposed through the `cb.py describe configs` for documentation.

## ConfigParser & `add_default_argument`

When implementing config parsing for a probe, browser, or benchmark component
via `config_parser()`:

- Use `parser.add_default_argument(...)` to expose compact CLI shorthand syntax.
- The default argument is automatically parsed by `parse_str`.
