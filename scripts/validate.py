#!/usr/bin/env python3
"""Code-only checkout boundary and zero-runtime-dependency validation gate."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMBEDDED_CATALOG_PATHS = (
    "skills",
    "guidelines",
    "mcp",
    "hooks",
    "memory",
    "bundles",
    "artifacts",
    "collections",
    "aart-source.json",
    "aart-registry.json",
    "aart.lock.json",
    "aart.index.json",
)


def non_stdlib_imports(package_root: Path) -> tuple[str, ...]:
    allowed = set(sys.stdlib_module_names) | {package_root.name}
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = (node.module,)
            else:
                continue
            for module in imported:
                top = module.split(".")[0]
                if top not in allowed:
                    violations.append(f"{path.relative_to(ROOT)}: non-stdlib import {module}")
    return tuple(sorted(set(violations)))


def operational_catalog_diagnostics(root: Path) -> tuple[str, ...]:
    """Reject embedded legacy or canonical catalog content from the tool checkout.

    ``Path.exists`` alone misses dangling symbolic links, which would let a future checkout appear
    code-only locally while turning into a catalog when its target appears.  A tool repository must
    not carry either the legacy roots or the canonical source/registry markers at its own root.
    """

    return tuple(
        f"repository contains embedded operational catalog path: {name}"
        for name in EMBEDDED_CATALOG_PATHS
        if (root / name).exists() or (root / name).is_symlink()
    )


def main() -> int:
    diagnostics = (
        *non_stdlib_imports(ROOT / "agent_artifacts"),
        *operational_catalog_diagnostics(ROOT),
    )
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        print(f"validation FAILED: {len(diagnostics)} diagnostic(s)")
        return 1
    print("validation OK: repository boundary and runtime imports are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
