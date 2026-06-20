#!/usr/bin/env python3
"""Build a pure-Python wheel using only the standard library (WP-21).

A wheel (PEP 427) is just a zip with a ``.dist-info/`` directory. Because agent-artifacts
has zero dependencies and is pure Python, we don't need setuptools or the `wheel` package to
produce one — which means the project builds **and** installs with no external index at all
(DESIGN.md §15). The resulting ``dist/agent_artifacts-<v>-py3-none-any.whl`` installs via:

    pip install --no-index dist/agent_artifacts-<v>-py3-none-any.whl

Requires Python 3.11+ to build (uses stdlib ``tomllib`` to read pyproject.toml); the built
wheel itself runs on Python 3.10+.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_project() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - build host is 3.11+
        sys.exit("build_wheel.py needs Python 3.11+ (stdlib tomllib).")
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]


def normalize(name: str) -> str:
    return name.replace("-", "_")


def record_line(arcname: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{arcname},sha256={digest},{len(data)}"


def metadata_text(proj: dict) -> str:
    lines = ["Metadata-Version: 2.1", f"Name: {proj['name']}", f"Version: {proj['version']}"]
    if proj.get("description"):
        lines.append(f"Summary: {proj['description']}")
    if proj.get("requires-python"):
        lines.append(f"Requires-Python: {proj['requires-python']}")
    for author in proj.get("authors", []):
        if author.get("name"):
            lines.append(f"Author: {author['name']}")
    lic = proj.get("license")
    if isinstance(lic, dict) and lic.get("text"):
        lines.append(f"License: {lic['text']}")
    if proj.get("keywords"):
        lines.append(f"Keywords: {','.join(proj['keywords'])}")
    body = ""
    readme = proj.get("readme")
    if isinstance(readme, str) and (ROOT / readme).exists():
        lines.append("Description-Content-Type: text/markdown")
        body = (ROOT / readme).read_text(encoding="utf-8")
    text = "\n".join(lines) + "\n"
    return text + ("\n" + body if body else "")


def entry_points_text(scripts: dict) -> str:
    if not scripts:
        return ""
    return "[console_scripts]\n" + "".join(f"{k} = {v}\n" for k, v in scripts.items())


def collect_package_files() -> dict:
    files: dict[str, bytes] = {}
    for path in sorted((ROOT / "agent_artifacts").rglob("*")):
        if path.is_dir() or path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        arc = str(path.relative_to(ROOT)).replace(os.sep, "/")
        files[arc] = path.read_bytes()
    return files


def main() -> int:
    proj = load_project()
    name, version = proj["name"], proj["version"]
    dist_name = normalize(name)
    info = f"{dist_name}-{version}.dist-info"

    files = collect_package_files()
    files[f"{info}/METADATA"] = metadata_text(proj).encode("utf-8")
    files[f"{info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: agent-artifacts build_wheel.py\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    eps = entry_points_text(proj.get("scripts", {}))
    if eps:
        files[f"{info}/entry_points.txt"] = eps.encode("utf-8")

    record = "".join(record_line(arc, data) + "\n" for arc, data in files.items())
    record += f"{info}/RECORD,,\n"

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    wheel_path = dist_dir / f"{dist_name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data in files.items():
            z.writestr(arc, data)
        z.writestr(f"{info}/RECORD", record)

    print(f"built {wheel_path.relative_to(ROOT)}  ({wheel_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
