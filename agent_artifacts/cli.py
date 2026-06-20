"""CLI entry point (WP-0 minimal scaffold; full wiring is WP-19).

For the Wave-0 gate this provides a working ``--help`` and dispatches each subcommand to
its (stubbed) ``commands.<name>.run``. Exit-code mapping and full flag plumbing land in WP-19.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from . import __version__

COMMANDS = ("list", "install", "status", "check", "update", "uninstall", "upgrade")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-artifacts", description="Install AI artifacts into agentic harnesses.")
    p.add_argument("--version", action="version", version=f"agent-artifacts {__version__}")
    sub = p.add_subparsers(dest="command")
    for name in COMMANDS:
        sub.add_parser(name, help=f"{name} (not yet implemented — WP-19 wires full flags)")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    # Wave 0: commands are stubs; full dispatch arrives with WP-12..WP-19.
    print(f"agent-artifacts: '{args.command}' is not implemented yet (Wave 0 scaffold).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
