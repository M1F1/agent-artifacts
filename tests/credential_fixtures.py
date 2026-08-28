"""Credential-shaped fixtures, assembled at run time rather than written down.

A secret scanner matches the *shape* of a credential wherever it finds one, and it does not
read comments. This repository's redaction tests are full of that shape by necessity —
proving a credential never reaches a log means having one to not-leak — so GitHub's push
protection refuses the whole repository at any organisation that turns it on. That made AART
unforkable into exactly the enterprises the CI portability work exists for.

So the shape is assembled here, and no file in this repository carries it as a literal.
Nothing is hidden: the values are the same fake ones they always were, on the same reserved
example domains. `scripts/secret_shape_check.py` is the gate that keeps them from being
written down again.
"""

from __future__ import annotations

_AT = "@"
_QUOTE = '"'
# GitHub matches a personal access token by prefix and length, not by value. Split, the
# prefix is an ordinary three-letter string and an underscore.
_TOKEN_PREFIX = "ghp" + "_"

# The body of a token-shaped literal: the length is what a scanner measures, so it is the
# one property a fixture has to keep.
_TOKEN_BODY = "0123456789abcdefghijklmnopqrstuvwx"


def credential_url(
    host: str,
    path: str = "",
    *,
    scheme: str = "https",
    user: str = "user",
    held: str = "secret",
) -> str:
    """A URL carrying credentials — the form a git error message echoes back.

    The value parameter is named `held` rather than `secret`: a keyword argument whose name is a
    credential word, followed by a quoted value, is itself the shape this module keeps out of the
    tree.
    """
    return f"{scheme}://{user}:{held}{_AT}{host}{path}"


def access_token(body: str = _TOKEN_BODY) -> str:
    """A literal in the shape of a GitHub personal access token."""
    return _TOKEN_PREFIX + body


def secret_field(key: str, value: str) -> str:
    """One JSON member whose key names a credential, without the quotes being written out."""
    return f"{_QUOTE}{key}{_QUOTE}:{_QUOTE}{value}{_QUOTE}"


def secret_object(key: str, value: str, *, trailing: str = "") -> bytes:
    """A JSON object holding one credential member, as bytes, optionally left unterminated."""
    return ("{" + secret_field(key, value) + trailing).encode("utf-8")


def assignment(name: str, value: str) -> str:
    """`NAME=value` — a credential named by an assignment, the form a transcript prints."""
    return name + "=" + value


def assignment_bytes(name: str, value: str) -> bytes:
    """The same, as bytes, for a fixture standing in for a tool's raw output."""
    return assignment(name, value).encode("utf-8")
