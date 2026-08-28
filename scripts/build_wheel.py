#!/usr/bin/env python3
"""Build a pure-Python wheel using only the standard library (WP-21).

A wheel (PEP 427) is just a zip with a ``.dist-info/`` directory. Because agent-artifacts
has zero dependencies and is pure Python, we don't need setuptools or the `wheel` package to
produce one — which means the project builds **and** installs with no external index at all
(docs/design/DESIGN.md §15). The resulting ``dist/aart_cli-<v>-py3-none-any.whl`` installs via:

    pip install --no-index dist/aart_cli-<v>-py3-none-any.whl

Requires Python 3.11+ to build (uses stdlib ``tomllib`` to read pyproject.toml); the built
wheel itself runs on Python 3.10+.

The archive is byte-reproducible (SI-8, design §7.1): every member is dated from the commit
stamped into ``agent_artifacts/_commit.py``, and member order, compression, permissions and
create-system are pinned, so rebuilding the same commit anywhere produces the same digest rather
than merely the same contents.  Nothing here reads the clock, the environment, or the platform.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_RESOURCE_ROOTS = frozenset({"schemas", "profiles", "importers", "templates"})
_COMMIT_EPOCH_RE = re.compile(r"^COMMIT_EPOCH = (\d+)$", re.MULTILINE)
# Zip stores DOS timestamps, which begin in 1980.  A source with no commit date — an editable
# checkout, or a copy taken outside git — builds at that floor rather than at "now".
_DOS_EPOCH_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_DOS_EPOCH = 315532800  # 1980-01-01T00:00:00Z, the earliest a zip member can be dated
# Pinned so the archive cannot drift with a future zipfile default: mode 0o600 is what
# ``ZipFile.writestr`` has always written, and create-system 3 (Unix) is what a build on Windows
# would otherwise change.
_MEMBER_EXTERNAL_ATTR = 0o600 << 16
_UNIX_CREATE_SYSTEM = 3
_COMPRESS_LEVEL = 9


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


def _allowed_package_member(arcname: str) -> bool:
    parts = tuple(Path(arcname).parts)
    if len(parts) < 2 or parts[0] != "agent_artifacts":
        return False
    if arcname.endswith(".py"):
        return True
    return len(parts) >= 3 and parts[1] in _RESOURCE_ROOTS


def source_epoch() -> int:
    """Return the commit date stamped into the source, or ``0`` when none was stamped.

    The stamp is read rather than imported: the package being packaged must not have to import
    cleanly for its own build, and no environment variable may steer the result — a wheel that
    dates differently on two machines is exactly what this build refuses to produce.
    """

    try:
        text = (ROOT / "agent_artifacts" / "_commit.py").read_text(encoding="utf-8")
    except OSError:
        return 0
    match = _COMMIT_EPOCH_RE.search(text)
    return int(match.group(1)) if match else 0


def member_date_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    """Date a zip member in UTC, never in the build host's local time."""

    if epoch < _DOS_EPOCH:
        return _DOS_EPOCH_DATE_TIME
    return time.gmtime(epoch)[:6]


def member_info(arcname: str, date_time: tuple[int, int, int, int, int, int]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = _UNIX_CREATE_SYSTEM
    info.external_attr = _MEMBER_EXTERNAL_ATTR
    return info


def collect_package_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted((ROOT / "agent_artifacts").rglob("*")):
        arc = str(path.relative_to(ROOT)).replace(os.sep, "/")
        if path.is_symlink():
            raise ValueError(f"wheel resource allowlist rejects: {arc}")
        if path.is_dir() or path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        if not path.is_file() or not _allowed_package_member(arc):
            raise ValueError(f"wheel resource allowlist rejects: {arc}")
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

    # Sorted, so the archive's member order comes from the names rather than from the order a
    # directory walk happened to return them in.
    ordered = tuple(sorted(files.items()))
    record = "".join(record_line(arc, data) + "\n" for arc, data in ordered)
    record += f"{info}/RECORD,,\n"

    date_time = member_date_time(source_epoch())
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    wheel_path = dist_dir / f"{dist_name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data in ordered:
            z.writestr(member_info(arc, date_time), data, compresslevel=_COMPRESS_LEVEL)
        z.writestr(member_info(f"{info}/RECORD", date_time), record, compresslevel=_COMPRESS_LEVEL)

    print(f"built {wheel_path.relative_to(ROOT)}  ({wheel_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
