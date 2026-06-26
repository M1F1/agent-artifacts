"""check command (WP-16). REMOTE, opt-in: installed/CLI commit vs main + what changed (docs/design/DESIGN.md §8).

Fail-soft: any network error prints one line, exits non-zero (NETWORK=3), changes nothing.

The logic lives in ``_check(request, opener=None)`` so tests can inject a fake ``opener``
(an ``(urllib.request.Request) -> file-like`` callable) and never touch the live network.
``run`` is the thin entry point the dispatcher calls.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from typing import List, Optional

from .. import _commit
from ..io import net
from ..model import Err, Manifest, Request
from . import _common

# Top-level directories that hold installable artifacts in the source repo. A changed file
# under one of these maps to an artifact root (its first two path segments, e.g.
# "skills/code-review"); a changed file under "agent_artifacts/" means the CLI code moved.
_ARTIFACT_DIRS = ("skills", "guidelines", "mcp", "hooks", "memory")
_CLI_DIR = "agent_artifacts"


def run(request: Request) -> int:
    return _check(request)


def _check(request: Request, opener=None) -> int:
    """Remote freshness check. Returns OK (0) on a successful check, NETWORK (3) on failure."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = _common.repo_of(request)
    ref = request.version or "main"

    head_res = net.resolve_ref(repo, ref, token, opener)
    if isinstance(head_res, Err):
        print(f"check: cannot reach {repo} ({head_res.reason})", file=sys.stderr)
        return _common.NETWORK
    head_sha = head_res.value

    manifest_res = _common.load_manifest(request)
    if isinstance(manifest_res, Err):
        # A corrupt manifest is not a network failure; surface it with its own code.
        print(f"check: {manifest_res.reason}", file=sys.stderr)
        return _common.exit_code(manifest_res)
    manifest = manifest_res.value

    installed_shas = _installed_shas(manifest)
    base = _pick_base(installed_shas)

    artifacts_changed: List[str] = []
    cli_changed = _commit.COMMIT != head_sha

    # If everything installed is already at head, nothing on the artifact axis can have moved.
    if base is not None and base != head_sha:
        cmp_res = net.compare(repo, base, head_sha, token, opener)
        if isinstance(cmp_res, Err):
            print(f"check: cannot reach {repo} ({cmp_res.reason})", file=sys.stderr)
            return _common.NETWORK
        changed_paths = _changed_paths(cmp_res.value)
        artifacts_changed = _match_artifacts(changed_paths, manifest)
        if _cli_paths_changed(changed_paths):
            cli_changed = True

    suggestion = _suggestion(bool(artifacts_changed), cli_changed)

    if request.json:
        _common.print_json(
            {
                "repo": repo,
                "head": head_sha,
                "artifacts_changed": artifacts_changed,
                "cli_changed": cli_changed,
                "suggestion": suggestion,
            }
        )
    else:
        _print_summary(
            repo,
            head_sha,
            artifacts_changed,
            cli_changed,
            suggestion,
            has_remote_artifacts=bool(base),
        )

    return _common.OK


# --------------------------------------------------------------------------- #
# Pure helpers.                                                                #
# --------------------------------------------------------------------------- #
def _parse_sha(source: str) -> Optional[str]:
    """Pull the SHA out of a manifest ``source`` like ``"main:<sha>"`` / ``"pin:<sha>"``."""
    if not source or source.startswith("local:"):
        return None
    _, _, sha = source.partition(":")
    sha = sha or source
    return sha or None


def _installed_shas(manifest: Manifest) -> List[str]:
    """The installed source SHAs, in install order (duplicates kept for base selection)."""
    out: List[str] = []
    for entry in manifest.installed:
        sha = _parse_sha(entry.source)
        if sha:
            out.append(sha)
    return out


def _pick_base(shas: List[str]) -> Optional[str]:
    """The most common installed SHA (ties broken by first appearance), or None if empty."""
    if not shas:
        return None
    counts = Counter(shas)
    best = max(counts.values())
    for sha in shas:  # first-seen order among the most common
        if counts[sha] == best:
            return sha
    return None  # pragma: no cover - unreachable when shas is non-empty


def _changed_paths(compare_data: dict) -> List[str]:
    """Extract the changed file paths from a GitHub compare payload (``files[].filename``)."""
    files = compare_data.get("files") or []
    paths: List[str] = []
    for f in files:
        if isinstance(f, dict):
            name = f.get("filename")
            if isinstance(name, str) and name:
                paths.append(name)
    return paths


def _artifact_root(path: str) -> Optional[str]:
    """Map a changed path under an artifact dir to its root (first two segments), else None."""
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in _ARTIFACT_DIRS:
        return f"{parts[0]}/{parts[1]}"
    return None


def _match_artifacts(changed_paths: List[str], manifest: Manifest) -> List[str]:
    """Installed artifact roots whose source tree saw a changed file. Sorted, de-duplicated."""
    installed_roots = set()
    for entry in manifest.installed:
        # An entry's type pluralizes to its source dir; root is "<dir>/<artifact-name>".
        installed_roots.add(_entry_root(entry.type, entry.artifact))
    changed_roots = set()
    for path in changed_paths:
        root = _artifact_root(path)
        if root is not None and root in installed_roots:
            changed_roots.add(root)
    return sorted(changed_roots)


def _entry_root(artifact_type: str, name: str) -> str:
    """The source-tree root for an installed entry, e.g. ("skill", "code-review") -> "skills/code-review"."""
    # ArtifactType is singular ("skill"); the source dir is its plural.
    plural = {
        "skill": "skills",
        "guideline": "guidelines",
        "mcp": "mcp",
        "hook": "hooks",
    }.get(artifact_type, artifact_type)
    return f"{plural}/{name}"


def _cli_paths_changed(changed_paths: List[str]) -> bool:
    """True if any changed path lives under the CLI package directory."""
    prefix = _CLI_DIR + "/"
    return any(p == _CLI_DIR or p.startswith(prefix) for p in changed_paths)


def _suggestion(artifacts_changed: bool, cli_changed: bool) -> Optional[str]:
    """The recommended next command (artifacts -> update, CLI -> upgrade), or None."""
    parts: List[str] = []
    if artifacts_changed:
        parts.append("agent-artifacts update")
    if cli_changed:
        parts.append("agent-artifacts upgrade")
    if not parts:
        return None
    return "; ".join(parts)


def _print_summary(
    repo: str,
    head: str,
    artifacts_changed: List[str],
    cli_changed: bool,
    suggestion: Optional[str],
    has_remote_artifacts: bool = True,
) -> None:
    print(f"check: {repo} main is at {head}")
    if artifacts_changed:
        print(f"  artifacts behind main: {', '.join(artifacts_changed)}")
    elif not has_remote_artifacts:
        print("  artifacts: skipped (installed locally)")
    else:
        print("  artifacts: up to date")
    print(f"  cli: {'behind main' if cli_changed else 'up to date'}")
    if suggestion:
        print(f"  next: {suggestion}")
    else:
        print("  everything is up to date")
