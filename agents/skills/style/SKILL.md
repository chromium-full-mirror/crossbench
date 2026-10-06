---
name: style
description: Generic crossbench python coding style guide
---

# Crossbench Python Style & Best Practices

This skill provides guidelines and patterns for writing Python code in the
Crossbench codebase. These rules cover architectural patterns, hygiene, and
design guidelines that are **not** automatically enforced by Ruff.

## Linting with ruff:

For standard linting always rely on `vpython3 -m ruff check` and use
`vpython3 -m ruff check --fix`.

Avoid adding skip rules like `# noqa: BLE001` but rather fix the surrounding
code and look for better approaches.

## Formatting:

- Do not use `ruff format`
- Use `git cl format` to format all sources
- Observe an 80 characters per line limit in Python files.

## Strict Import Discipline

- Imports must only happen at top-level unless it's inside a TYPE_CHECKING block
  or in PRESUBMIT.py. You can rely 100% on ruff checking here.

Importing modules locally inside classes or methods is **strictly forbidden**.
All imports must reside at the top level of the file. (Conditional imports based
on a simple if statement referring to TYPE_CHECKING are an exception.)

```python
# BAD: Forbidden local import
class MyProbe(Probe):
  def setup(self) -> None:
    import subprocess  # FORBIDDEN

# GOOD: Clean top-level import
import subprocess
```

## Type Annotations

- You can skip type checking in test methods to reduce friction
- Add type annotations for all instance variables inside `__init__`
- All methods, method arguments, and return values
- Avoid using the `Any` type if possible as it degrades type checking, as backup
  you can use `object` but prefer specific types

## Design Patterns and style

- **Short Methods**: Keep methods short and break them into well-named helper
  functions. Typical candidates are large inner loop blocks or long blocks
  inside multiple if-statements

- **Reusability**: Check surrounding code and class hierarchies before
  implementing new functionality; reuse existing methods.

- **Code Duplication**: Add reusable methods for repeated code snippets.

- **Method vs Classes:** Prefer instance methods over class methods and avoid
  free-floating functions.

- **Enums:** Use `StrEnum` or `StrEnumWithHelp` to avoid magic string constants.

- **Walrus Operator**: Use the walrus operator for simple statements

  ```
  # BAD:
  log_path = browser.log_path
  if log_path:
    self.do_stuff(log_path)

  # BAD:
  if (log_path := browser.log_path) is not DEFAULT_PATH:
     self.do_stuff(log_path)

  # GOOD: compact use of walrus operator
  if log_path := browser.log_path:
    self.do_stuff(log_path)

  ```

- **Early Returns**: Use early returns, early continue and early breaks to
  reduce nesting levels. It's ok to duplicate simple return statements. Prefer
  separate early bailout checks.

  ```
  # BAD: nested long blocks
  def foo(value):
    if value:
      if value == "error":
        return "error"
      # large block here
      ...
    return "done"

  # GOOD: shallow nesting with early returns
  def foo(value):
    if not value:
      return "done"
    if value == "error":
      return "error"
    # large block here
    ...
    return "done"
  ```

- **Reduce Code Comments**: Avoid inline code comments and prefer using
  well-named constants and helper methods and helper classes. Code comments
  bit-rod, it's better to have executable documentation like tests. Comments on
  classes are good.

- **Avoid defensive programming**: Fail early and explicitly for stricter code
  and better tests. defensive programming is not good for code health.

- **Avoid getattr and hasattr**: The methods are generally an antipattern and
  can hide errors. For accessing args, fix the tests first and add mock values
  to the test Namespaces.

  ```
  # BAD: getattr on args
  if browser_type := getattr(args, "browser_type"):
    ...

  # GOOD: directly accessing args attributes
  if browser_type := args.browser_type:
    ...
  ```

- **Avoid complex inline if-else assignments**: Only use simple inline if
  expressions that fit on one line and are easy to read. For complex or nested
  expressions, use a default value + if or an explicit if-else statement.

  ```python
  # BAD: Hard to read, multi-line or complex ternary assignment
  arguments = (
      self._parse_dict(raw_data.get("args"))
      if isinstance(raw_data.get("args"), dict) and self._is_valid(raw_data)
      else self._default_fallback(source))

  # GOOD: Short and simple inline if-else on a single line
  arguments = raw_arguments if isinstance(raw_arguments, dict) else {}

  # GOOD: Default value + if for multi-step logic
  arguments = {}
  raw_arguments = data.get("arguments")
  if isinstance(raw_arguments, dict):
    arguments = raw_arguments

  # GOOD: Explicit if-else assignment
  if isinstance(raw_arguments, dict):
    arguments = raw_arguments
  else:
    arguments = {}
  ```

- **Match Statement:** Use `match` for repeated checks and if statements.

______________________________________________________________________

## Sanity Checks & Verification

Before committing or uploading changes, always run the validation suite:

1. **Mypy Type Checker:** `poetry run mypy crossbench`
2. **Unit Tests:** `poetry run pytest tests/crossbench -x -n 7`
3. **Crossbench Invocation:** Use `poetry run cb` instead of executing `./cb.py`
   directly.
