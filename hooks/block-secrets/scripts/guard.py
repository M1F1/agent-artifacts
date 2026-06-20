#!/usr/bin/env python3
"""Guard script: scans tool input for obvious secret patterns.

Reads the tool-use JSON from stdin (the harness pipes it), checks the
content fields for high-confidence secret patterns (AWS keys, private keys,
password assignments).  Exits 0 (allow) or 2 (block) with a reason on
stdout.

Stdlib only — no external dependencies.
"""

import json
import re
import sys

# High-confidence patterns that almost certainly indicate real secrets.
_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"), "Private key block"),
    (re.compile(r"""(?:password|secret|token)\s*[=:]\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
     "Hardcoded credential assignment"),
]


def _extract_content(payload: dict) -> str:
    """Pull text content from the tool-use payload, best-effort."""
    parts = []
    for key in ("content", "new_string", "command", "code"):
        val = payload.get(key)
        if isinstance(val, str):
            parts.append(val)
    return "\n".join(parts)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # If we cannot parse input, allow — do not block on bad data.
        return 0

    content = _extract_content(payload)
    if not content:
        return 0

    for pattern, label in _PATTERNS:
        match = pattern.search(content)
        if match:
            print(f"BLOCKED: {label} detected (matched: {match.group()[:40]}...)")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
