#!/usr/bin/env python3
"""Validate one installer using the same strict parser as catalog discovery."""

from __future__ import annotations

import argparse
import pathlib
import sys

from agent_artifacts.model import Err
from agent_artifacts.setup import custom_entrypoint_name, parse_installer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=pathlib.Path)
    parser.add_argument("artifact", help="containing TYPE/NAME")
    args = parser.parse_args(argv)
    raw = args.installer.read_bytes()
    custom_name = custom_entrypoint_name(raw)
    if isinstance(custom_name, Err):
        print(custom_name.reason, file=sys.stderr)
        return custom_name.code
    custom = None
    if custom_name.value is not None:
        custom = args.installer.parent.joinpath(custom_name.value).read_bytes()
    result = parse_installer(
        raw,
        artifact_key=args.artifact,
        descriptor_path=args.installer.as_posix(),
        custom_bytes=custom,
    )
    if isinstance(result, Err):
        print(result.reason, file=sys.stderr)
        return result.code
    print(f"installer OK: {result.value.artifact} sha256:{result.value.descriptor_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
