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

Two places answer.  A checkout answers directly.  An install done by `pip`, `pipx` or `uv` from
a Git URL answers through `direct_url.json`, the record PEP 610 requires every installer to leave
beside the package: it carries the URL, the revision that was asked for, and the commit it
resolved to.  That is the same pair a checkout gives, so `pipx install
git+https://.../agent-artifacts.git@main` stamps what a clone of that branch would.

Everything here is best effort.  A wheel from a package index carries no Git origin at all, and an
origin naming a directory on somebody's laptop is worse than no answer -- a runner cannot clone
it.  Both return `None`, the templates keep their shipped defaults, and the review says so.
"""

from __future__ import annotations

import importlib.metadata
import json
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
DISTRIBUTION = "agent-artifacts"


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


def _origin_from_checkout(tree: str) -> ToolOrigin | None:
    if not os.path.isdir(tree):
        return None
    # Being *inside* a checkout is not the same as being one.  AART unpacked under a home
    # directory that is itself a Git repository would otherwise answer with that repository --
    # someone's dotfiles -- and every registry created there would send its CI to clone a tree
    # with no `agent_artifacts` package in it.  The tool has to be the repository, not a file in
    # one, so the top level must be exactly where the package lives.
    toplevel = _git(tree, "rev-parse", "--show-toplevel")
    if toplevel is None or os.path.realpath(toplevel) != os.path.realpath(tree):
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


def origin_from_direct_url(text: str | None) -> ToolOrigin | None:
    """Read an install done from a Git URL, the way `pipx install git+https://...@main` is.

    A wheel pulled from a package index has no `vcs_info` and is not stamped: an index states a
    version, not a place to clone from, and inventing one would send CI somewhere nobody asked
    for.  That gap is `LAF-122`.
    """

    if text is None:
        return None
    try:
        record = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    vcs = record.get("vcs_info")
    url = record.get("url")
    if not isinstance(vcs, dict) or vcs.get("vcs") != "git" or not isinstance(url, str):
        return None
    repository = _repository_of(url[4:] if url.startswith("git+") else url)
    # What was asked for, not what it resolved to: a branch stays a branch, exactly as a checkout
    # on a branch stamps that branch.  The commit answers only when nothing was asked.
    ref = vcs.get("requested_revision") or vcs.get("commit_id")
    if repository is None or not isinstance(ref, str):
        return None
    try:
        return ToolOrigin(repository=repository, ref=ref)
    except ValueError:
        return None


def _installed_direct_url() -> str | None:
    """The PEP 610 record `pip`, `pipx` and `uv` all leave beside an installed distribution."""

    try:
        return importlib.metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
    except (importlib.metadata.PackageNotFoundError, OSError):
        return None


def discover_tool_origin(root: str | None = None) -> ToolOrigin | None:
    """Read the running AART's own origin and ref, or `None` when there is nothing to read.

    The checkout is asked first because it is the truth about the tree that will actually run --
    an editable install points back at it, and a working copy may sit on a branch the installer
    never heard of.  The installer's record answers for every ordinary install.
    """

    tree = os.path.abspath(root if root is not None else package_root())
    return _origin_from_checkout(tree) or origin_from_direct_url(_installed_direct_url())


__all__ = ["DISTRIBUTION", "discover_tool_origin", "origin_from_direct_url", "package_root"]
