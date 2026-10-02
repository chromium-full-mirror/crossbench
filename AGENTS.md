# Gemini Workspace Configuration

Read `./README.md` for all instructions.

If running `./cb.py` fails, try the following:

1. Look for a local `depot_tools` installation and add it to `$PATH`.

2. If no `depot_tools` found, try running with `poetry`: `poetry run cb`.

# Python Code Style Guide
- You must follow the Google style guide for python coding.
- Observe an 80 characters per line limit in Python files.
- local imports inside classes or methods are strictly **forbidden**.
- Check surrounding code and class hierarchies for reusing functionality.
- Use existing tests and test classes to write platform and mock tests.
- Use early returns / early control flow to reduce nesting levels.
- Keep methods short where possible and use well-named helper methods.
- Type annotate all instance methods inside __init__ methods, method arguments
  and return values.
- Import declarations always go at the top of the file, never nested inside
  of a method or class. (Conditional imports based on a simple if statement
  referring to TYPE_CHECKING are an exception.)
- Disallow `getattr`,  `setattr` and `hasattr`: dynamic attribute access is
  strictly banned by `PRESUBMIT.py`. Only use it when strictly unavoidable.
- Avoid complex or multi-line inline if-else assignments. Only use simple
  inline if expressions that fit on one line and are easy to read; otherwise
  use a default value + if or an explicit if-else assignment.

## Crossbench Platform Code
- Avoid using raw shell-commands if possible and directly use the platform
  helpers for the same functionality.
- Avoid using "shell = True", either use or extend the explicit platform
  helpers or look for simple workarounds.
- New platform methods should be implemented in the most abstract platform
  class if possible.

## Crossbench Paths
- Use pth.AnyPath or pth.LocalPath instead of strings for paths.
- Use pth.AnyPath for paths that can either be local and/or remote.
- Use pth.LocalPath for paths that are exclusively local.

## Crossbench Input Parsing
- All user input should pass through one of the helpers from
  `crossbench.parse`.
- Do early input validation either in the config parser or argument parsing.
- Any new parser helper method needs a dedicated unittest.

## Crossbench ConfigObjects
- Any complex input parameter should be a dedicated immutable / frozen
  ConfigObject with proper documentation.
- Add unittests for each newly added ConfigObject.
- Add example config files to the config/doc or a better suited
  config/* folder.

# Crossbench Sanity Checks
- When producing changes, you should run the following four validations:
  (1) tests, (2) mypy, (3) ruff, (4) git-cl-format-js.
  However, it is extremely important to run such validations at the right time
  only, because the user's time is valuable. Unless there is good reason to do
  otherwise, these steps should run in the order below, with each step only
  running once the previous one passes without errors. Enforce this ordering
  within a single chained command (see "Batch the validations" below) rather
  than by issuing a separate tool call per step.
  1. Tests: Run tests with `vpython3 -m pytest tests/crossbench -x -n 7`.
     Working on CLs is an iterative process. Only run the relevant subset of
     tests during most iterations (e.g. only relevant files), and only run the
     entire suite when it's time to finalise a CL.
  2. mypy: Run `vpython3 -m mypy` only when absolutely necessary (e.g., after a
     larger change). To save time during iterative development, restrict mypy to
     the minimum set of modified files rather than the entire codebase. Infer
     the user's intent and recognize when it's time to finalize the CL;
     when that happens, DO run mypy over the entire codebase.
  3. ruff: Always do `vpython3 -m ruff check` after completing a change to
     validate all results.
  4. Run `git cl format --js`.
- Be judicious after minor iterations. Scale validation to what changed:
  for comment- or docstring-only edits, ruff alone is usually enough (it
  checks line length); for small, local code edits, run only the affected
  test file and mypy on the modified file. Skip steps that cannot be
  affected by the change.
- Batch the validations into a single command. Decide up front which of the
  steps above apply to the current change, then run them all in one shell
  invocation instead of one tool call per step. Chain them with `&&` to
  preserve the ordering and stop-on-first-failure behaviour described above,
  e.g.:
  `vpython3 -m pytest tests/crossbench/test_foo.py -x -n 7 && vpython3 -m mypy
  crossbench/foo.py && vpython3 -m ruff check && git cl format --js`.
  If the checks are cheap and independent (e.g. mypy and ruff), you may chain
  them with `;` instead, so that all failures are reported at once.
  Rationale: every separate tool call adds a full round trip in which the
  user waits for the LLM to read the result and decide on the next command.
  Running all steps together removes that queueing latency, and lets you see
  all the results at once, so you can fix every reported issue in a single
  pass instead of discovering them one at a time.

# Running Performance Investigations
- **Environment Validation**: When running `cb.py` automatically, it might
  block on an interactive prompt for environment validation. Use the
  `--env-validation=warn` flag to prevent blocking while still seeing warning
  outputs.
- **Headless VM Crashes**: If the browser exits immediately with a WebDriver
  error, you are likely on a headless VM. Try passing `--headless` to your
  command.
- **Hanging / Unsupported Probes**: The `downloads` and `screenshot` probes may
  not be fully supported on all local setups (e.g., Linux CloudTop). If you
  encounter errors, omit them using `--no-probe=downloads` /
  `--no-probe=screenshot` or a custom `--probe-config`.
