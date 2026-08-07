#!/usr/bin/env python3
"""Retired mutating entry point; use the explicit scripts/version.py commands."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "bump_version.py is retired; use `python scripts/version.py next-alpha` and "
        "`python scripts/version.py bump-alpha --write` explicitly.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
