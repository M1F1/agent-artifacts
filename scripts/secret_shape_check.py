#!/usr/bin/env python3
"""Refuse credential-shaped literals anywhere in the tracked tree.

A secret scanner reads bytes, not intent. Push protection at an organisation that turns it on
rejects a push carrying anything in the shape of a credential — including a redaction test's
fixture, whose entire purpose is to prove the credential never escapes. Two of those fixtures
are what made this repository unpushable to a GitHub Enterprise Server instance, which is to
say unforkable into the enterprises `docs/ci/enterprise-fork-v1.md` is written for.

Fixing the four files that were reported would have left the rest, because the rejection said
`scan incomplete: this push was large and we didn't finish on time`. So this gate holds the
class instead: the shape is assembled at run time by `tests/credential_fixtures.py`, and no
file writes it down.

The patterns below are built from fragments for the same reason the fixtures are — a checker
that trips itself is a checker nobody can run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_AT = "@"
_COLON = ":"
_SLASHES = "/" + "/"

# A scheme, then a userinfo holding two colon-separated halves, then the authority. Both halves
# exclude quotes and whitespace, so a line that merely mentions a scheme and, separately, an
# address does not match.
_URI_RE = re.compile(
    r"[a-z][a-z0-9+.\-]*" + _COLON + _SLASHES + r"[^\s/@:\"']+" + _COLON + r"[^\s/@\"']+" + _AT
)

# A credential-naming key next to a quoted value: `"password":"…"`, `token = '…'`, `secret: "…"`.
_KEY_WORDS = "password|passwd|pwd|secret|token|api[_-]?key|credential"
_KV_RE = re.compile(
    r"(?i)\b(" + _KEY_WORDS + r")\b[\"']?\s*[" + _COLON + r"=]\s*[\"'][^\"']{2,}[\"']"
)

# The prefixes GitHub issues tokens under, matched the way a scanner matches them: by prefix
# and length, never by value.
_TOKEN_PREFIXES = ("ghp", "gho", "ghs", "ghu", "ghr", "github" + "_pat")
_TOKEN_RE = re.compile(r"\b(" + "|".join(_TOKEN_PREFIXES) + r")_[A-Za-z0-9_]{20,}")

_SKIP_SUFFIXES = (".lock.json", ".png", ".ico", ".whl")


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    code: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.text}"


def _tracked_files() -> tuple[str, ...]:
    listing = subprocess.run(
        ("git", "ls-files"), cwd=ROOT, capture_output=True, text=True, check=True
    )
    return tuple(line for line in listing.stdout.splitlines() if line)


def _scan(path: str) -> tuple[Finding, ...]:
    if path.endswith(_SKIP_SUFFIXES):
        return ()
    try:
        text = (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _URI_RE.search(line):
            findings.append(
                Finding(path, number, "credential-url", "a URL carrying user and secret")
            )
        if _KV_RE.search(line):
            findings.append(
                Finding(
                    path,
                    number,
                    "credential-literal",
                    "a credential-naming key with a quoted value",
                )
            )
        if _TOKEN_RE.search(line):
            findings.append(
                Finding(path, number, "token-literal", "a literal in the shape of an issued token")
            )
    return tuple(findings)


def main() -> int:
    findings: list[Finding] = []
    for path in _tracked_files():
        findings.extend(_scan(path))
    if not findings:
        print("secret shape check OK")
        return 0
    for finding in sorted(findings):
        print(finding.render(), file=sys.stderr)
    print(
        f"\n{len(findings)} credential-shaped literal(s). Assemble them through "
        "tests/credential_fixtures.py instead — see that module's docstring for why.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
