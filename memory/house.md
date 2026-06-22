---
description: House rules every repo inherits — build/test/PR conventions for AI agents.
mode: prepend
---
# Engineering house rules

These are the team's baseline expectations for any AI agent working in this repository.

## Build & test
- Run the full test suite before proposing a change; never hand back red.
- Prefer the project's `Makefile` targets (`make test`, `make validate`) over ad-hoc commands.

## Changes
- Keep diffs minimal and match the surrounding style; do not reformat unrelated code.
- One logical change per commit; write why, not just what.

## Pull requests
- Summarize the change, the reasoning, and how it was verified.
- Call out anything you could not test.
