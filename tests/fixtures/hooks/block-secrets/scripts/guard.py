#!/usr/bin/env python3
"""Fixture guard script (minimal, for testing)."""
import sys
import json

def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
