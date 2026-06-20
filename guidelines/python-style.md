---
description: Python coding style conventions for the team.
---

# Python Style Guide

## Formatting

- Use 4 spaces for indentation (no tabs).
- Maximum line length: 100 characters.
- Use trailing commas in multi-line collections.

## Naming

- `snake_case` for functions, variables, and modules.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for module-level constants.
- Prefix private names with a single underscore.

## Imports

- Group imports: stdlib, third-party, local (separated by blank lines).
- Use absolute imports; avoid wildcard imports.
- Sort alphabetically within each group.

## Type hints

- Annotate all public function signatures.
- Use `from __future__ import annotations` for forward references.
- Prefer `X | None` over `Optional[X]` (Python 3.10+).

## Error handling

- Catch specific exceptions, never bare `except:`.
- Use custom exception classes for domain errors.
- Prefer returning result types over raising in pure functions.
