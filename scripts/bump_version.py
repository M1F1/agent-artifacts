#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = ROOT / "agent_artifacts" / "__init__.py"
PYPROJECT_FILE = ROOT / "pyproject.toml"

def bump_version():
    init_content = INIT_FILE.read_text(encoding="utf-8")
    
    # Match __version__ = "X.Y.Z"
    match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', init_content)
    if not match:
        print("Could not find version in __init__.py")
        return 1

    major, minor, patch = match.groups()
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{int(patch) + 1}"

    print(f"Bumping version: {old_version} -> {new_version}")

    # Update __init__.py
    INIT_FILE.write_text(init_content.replace(f'"{old_version}"', f'"{new_version}"'), encoding="utf-8")

    # Update pyproject.toml
    pyproject_content = PYPROJECT_FILE.read_text(encoding="utf-8")
    pyproject_content = re.sub(
        r'version\s*=\s*"{}"'.format(re.escape(old_version)),
        f'version = "{new_version}"',
        pyproject_content
    )
    PYPROJECT_FILE.write_text(pyproject_content, encoding="utf-8")

    return 0

if __name__ == "__main__":
    raise SystemExit(bump_version())
