#!/usr/bin/env python3
"""Canonical catalog and zero-runtime-dependency validation gate."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def catalog_diagnostics(root: Path) -> tuple[str, ...]:
    from agent_artifacts.catalog import validate_catalog
    from agent_artifacts.model import Err, Request
    from agent_artifacts.source import open_source

    source = open_source(Request(command="list", source_dir=str(root)))
    if isinstance(source, Err):
        return (f"source error: {source.reason}",)
    catalog = source.value.catalog()
    if isinstance(catalog, Err):
        return (f"catalog error: {catalog.reason}",)
    return tuple(f"catalog: {error.reason}" for error in validate_catalog(catalog.value))


def main() -> int:
    diagnostics = (*non_stdlib_imports(ROOT / "agent_artifacts"), *catalog_diagnostics(ROOT))
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        print(f"validation FAILED: {len(diagnostics)} diagnostic(s)")
        return 1
    print("validation OK: catalog valid and runtime imports are stdlib-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
