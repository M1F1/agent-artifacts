"""Where the running AART came from, discovered from its own checkout.

`registry init` writes three workflows that have to say where CI should fetch the tool.  The
shipped literal is this project's public repository, which is the right answer exactly once -- for
this project.  A fork on a company GitHub Enterprise Server has to change it, and the tempting
place to change it is the template in the fork.  That is the trap: the line then conflicts on
every later sync from upstream, forever, and the conflict is on the one line nobody wants to
resolve by hand.

So the tool answers the question about itself instead.  It reads its own checkout's origin and
current ref, and `registry init` stamps them into the file it generates.  The fork stays
byte-identical to the repository it tracks, and the difference lives in generated files where it
belongs.

Everything here is best effort.  AART installed from a wheel has no checkout to read, and an
origin that names a directory on someone's laptop is worse than no answer at all -- a runner
cannot clone it.  Both cases return `None`, the templates keep their shipped defaults, and the
review says so.
"""

from __future__ import annotations

import os
import pathlib
import re

from agent_artifacts.domain.result import Err
from agent_artifacts.io.git import GitProcessRequest, run_git_process
from agent_artifacts.registry_commands.model import ToolOrigin

# `scheme://[user@]host/owner/name[.git]` and `[user@]host:owner/name[.git]`.  Both require a
# host, which is the point: an origin without one is a path, and a path is not somewhere CI can
# clone from.
_HTTP_ORIGIN = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^/@]+@)?[^/@:]+(?::\d+)?/(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)
_SSH_ORIGIN = re.compile(r"^(?:[^@/\s]+@)?[^/@:\s]+:(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")
_TIMEOUT_SECONDS = 10.0


def _git(root: str, *arguments: str) -> str | None:
    receipt = run_git_process(
        GitProcessRequest(("git", "-C", root, *arguments), root, _TIMEOUT_SECONDS)
    )
    if isinstance(receipt, Err):
        return None
    value = receipt.value.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def _repository_of(origin: str) -> str | None:
    for pattern in (_HTTP_ORIGIN, _SSH_ORIGIN):
        match = pattern.match(origin)
        if match is not None:
            return f"{match['owner']}/{match['name']}"
    return None


def _current_ref(root: str) -> str | None:
    """What this checkout is *on*, not what it should be pinned to.

    A branch stamps a moving reference, a detached tag stamps that tag, and a detached commit
    stamps the commit.  The tool records the shape it was actually run from and leaves the choice
    between moving and frozen where it can be revisited: the `AART_REF` variable, and the
    registry's own declared compatibility window.
    """

    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is not None and branch != "HEAD":
        return branch
    tag = _git(root, "describe", "--tags", "--exact-match", "HEAD")
    if tag is not None:
        return tag
    return _git(root, "rev-parse", "HEAD")


def package_root() -> str:
    """The directory `PYTHONPATH` would have to name for `-m agent_artifacts` to work."""

    return str(pathlib.Path(__file__).resolve().parents[2])


def discover_tool_origin(root: str | None = None) -> ToolOrigin | None:
    """Read the running AART's own origin and ref, or `None` when there is nothing to read."""

    tree = os.path.abspath(root if root is not None else package_root())
    if not os.path.isdir(tree):
        return None
    if _git(tree, "rev-parse", "--is-inside-work-tree") != "true":
        return None
    origin = _git(tree, "remote", "get-url", "origin")
    repository = None if origin is None else _repository_of(origin)
    ref = _current_ref(tree)
    if repository is None and ref is None:
        return None
    try:
        # Only the repository is stamped, never the raw origin URL: a URL freezes the host, and
        # `github.server_url` already resolves the common case where the registry and the tool
        # live on the same instance.  A cross-host fetch is what `AART_TOOL_URL` is for.
        return ToolOrigin(repository=repository, ref=ref)
    except ValueError:
        return None


__all__ = ["discover_tool_origin", "package_root"]
