---
name: implementation-workflow
description: >-
  Step-by-step workflow for implementing, typing, formatting, testing, and
  validating Python code in Crossbench.
---

# Crossbench Python Implementation Workflow

This skill defines a structured, step-by-step workflow for implementing new
features, fixing bugs, writing tests, and validating Python code in the
Crossbench codebase.

## Implementation Workflow Orchestration

- Use separate parallel subagents in parallel to speed up.
- Run each sub-step as separate agent.

## Step 1: Research and Design Phase

- Research code for bugs.
- Analyze class hierarchies to understand high-level code patterns.
- Summarize findings into a concrete implementation plan.
- Look for existing code and related behavior in parent classes and sibling
  classes.
- Solve the high-level problem first before looking for simple workarounds.

## Step 2: Implementation

- Implement tests adhering to the python-style skill.
- Implement features / fix bugs adhering to python-style skill.
- Regularly run `poetry run ruff` to validate the code.

## Step 3: Validation and Testing Phase

Use parallel subagents to validate and improve a working implementation.

- Use `python-style` skill to validate code changes.
- Iterate until ruff shows no errors.
- Iterate until mypy shows no errors.
- Iterate until all tests pass.
