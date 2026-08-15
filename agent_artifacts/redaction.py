"""The one redactor for the package.

There used to be two, with different rules, and the weaker one was the one `dump_setup_state` used
— so a credentialed clone URL was hidden in a diagnostic and written to disk in full (`LAF-72`).
Two implementations of a safety property is one implementation and one liability.

This module lives at the leaf because both `setup.py` and `configuration.policy` need it and
`setup.py` cannot import from `configuration`: the path
`configuration -> protocol -> native_tree -> setup` closes the cycle.  It therefore imports nothing
from the package, and must keep importing nothing, or the cycle comes back through this file.

See `docs/design/DESIGN-token-containment.md`.
"""

from __future__ import annotations

import re

# 1. Credentials embedded in a URL: the GitHub Enterprise clone shape.
_URL_CREDENTIALS_RE = re.compile(r"(?P<prefix>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)

# 2. Credentials in a query string.
_QUERY_SECRET_RE = re.compile(
    r"(?P<prefix>[?&](?:token|access_token|api_key|key|secret|password)=)[^&#\s]+",
    re.IGNORECASE,
)

# 3. `NAME=value`, where the name *contains* a sensitive word rather than starting with one.
#
# The previous pattern anchored on `\b(token|password|...)`.  In a vendor-prefixed name such as
# `<VENDOR>_TOKEN` the position before `TOKEN` sits between two word characters, so no boundary
# exists and no match is made: a bare `TOKEN=` redacted and every prefixed form did not.  The
# prefixed forms are the ones real recipes use, so the boundary excluded exactly the cases that
# mattered (`LAF-63`).
#
# The names are written generically on purpose.  `scripts/validate.py` fails any module under
# `agent_artifacts/` that contains a real credential variable name, because AART holds no
# credentials of its own and must not look like it does.  That guard is a blunt substring check,
# which is what makes it unbypassable, so this file works around it rather than weakening it.
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?P<prefix>[A-Za-z0-9_.-]*"
    r"(?:token|password|passwd|secret|api[_-]?key|apikey|credential|auth)"
    r"[A-Za-z0-9_.-]*\s*[:=]\s*)[^\s,;&#]+",
    re.IGNORECASE,
)

# 4. The value's own shape, for when it appears with no name beside it.
#
# Rules 1-3 all require the credential to sit next to its name.  A transcript that prints the value
# alone on a line defeats every one of them.  Deliberately *not* entropy-based: a high-entropy
# matcher would redact `sha256:` digests, image ids and plan hashes, which are the fields a receipt
# exists to carry.  The cost of that choice is that an unrecognised credential format is not caught,
# and `DESIGN-token-containment.md` §4.4 states the limit rather than hiding it.
_CREDENTIAL_SHAPE_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[bpsar]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|sk-[A-Za-z0-9]{20,})"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----.*?-----END(?: [A-Z]+)? PRIVATE KEY-----",
    re.DOTALL,
)


def redact_text(text: str) -> str:
    """Hide credentials in free text without interpreting the message.

    Idempotent: ``redact_text(redact_text(x)) == redact_text(x)``, because the boundaries in
    `DESIGN-token-containment.md` §4.2 apply it more than once on purpose.
    """

    redacted = _PRIVATE_KEY_RE.sub("[redacted private key]", text)
    redacted = _URL_CREDENTIALS_RE.sub(r"\g<prefix>[redacted]@", redacted)
    redacted = _QUERY_SECRET_RE.sub(r"\g<prefix>[redacted]", redacted)
    redacted = _ASSIGNMENT_SECRET_RE.sub(r"\g<prefix>[redacted]", redacted)
    return _CREDENTIAL_SHAPE_RE.sub("[redacted]", redacted)


def contains_credential_shape(text: str) -> bool:
    """Whether the text carries something shaped like a bare credential.

    Used by `receipt verify` to report a record that already holds one.  It reports and never
    repairs: a persisted record is evidence of what a run did, and rewriting it destroys the thing
    receipts exist to be.
    """

    return bool(_CREDENTIAL_SHAPE_RE.search(text) or _PRIVATE_KEY_RE.search(text))
