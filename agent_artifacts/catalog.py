"""Catalog parsing & bundle resolution — pure (WP-1).

Parses artifacts/bundles from already-read text into the `model` records and resolves a
bundle (expand `extends` with cycle detection, merge `pins`, validate references).
Reading files from disk is the shell's job (source.py / io.fs); this module is pure.
"""

from __future__ import annotations

from typing import Tuple

from .model import Catalog, Result

_TODO = "WP-1: not implemented"


def parse_skill(text: str, name: str) -> Result:
    raise NotImplementedError(_TODO)


def parse_guideline(text: str, name: str) -> Result:
    raise NotImplementedError(_TODO)


def parse_mcp(text: str, name: str) -> Result:
    raise NotImplementedError(_TODO)


def parse_hook(text: str, name: str) -> Result:
    raise NotImplementedError(_TODO)


def parse_bundle(text: str, name: str) -> Result:
    raise NotImplementedError(_TODO)


def resolve_bundle(catalog: Catalog, name: str) -> Result:
    """Expand `extends` (union, cycle detection), merge `pins`, validate -> Ok[ResolvedBundle]."""
    raise NotImplementedError(_TODO)


def validate_catalog(catalog: Catalog) -> Tuple:
    """Return a tuple of `Err` for every dangling bundle reference (empty == valid)."""
    raise NotImplementedError(_TODO)
