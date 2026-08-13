"""Pure project/user installation-state path policy."""

from __future__ import annotations

import posixpath

from .model import InstallScope, InstallStatePaths


def _absolute(path: str, label: str) -> str:
    if not posixpath.isabs(path) or posixpath.normpath(path) != path:
        raise ValueError(f"{label} must be a normalized absolute path")
    return path


def install_state_paths(
    scope: InstallScope,
    *,
    project_root: str,
    user_home: str,
    data_root: str,
) -> InstallStatePaths:
    """Resolve state without consulting cwd, HOME, XDG, or the process environment."""

    project_root = _absolute(project_root, "project root")
    user_home = _absolute(user_home, "user home")
    data_root = _absolute(data_root, "data root")
    if scope == "project":
        state_root = posixpath.join(project_root, ".agent-artifacts")
        return InstallStatePaths(
            scope,
            posixpath.join(state_root, "manifest.json"),
            posixpath.join(state_root, "state.lock"),
        )
    if scope == "user":
        state_root = posixpath.join(data_root, "state")
        return InstallStatePaths(
            scope,
            posixpath.join(state_root, "manifest.json"),
            posixpath.join(state_root, "state.lock"),
        )
    raise ValueError("state scope must be 'project' or 'user'")
