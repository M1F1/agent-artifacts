"""Source resolver — shell (WP-11). Unifies local ``--source DIR`` and remote ``repo@ref``.

Returns a `Source` handle exposing ``read(rel) -> bytes``, ``catalog() -> Result[Catalog]``,
a ``root`` attribute, and ``label() -> str`` so the rest of the system is agnostic to where
artifacts come from (DESIGN.md §4 repo layout, §7 versioning, §8 fetch mechanics).

Public API
----------
``open_source(request) -> Result[Source]`` resolves a :class:`~agent_artifacts.model.Request`
into a `Source`:

* **Local** — when ``request.source_dir`` is set, ``root`` is that directory (made absolute);
  no network is touched. ``label()`` returns ``"local:<abspath>"`` — there is no commit to
  record, so the install command stores this sentinel verbatim.
* **Remote** — otherwise ``request.repo`` (``"org/repo"``) is resolved at ``request.version``
  (default ``"main"``) via :func:`agent_artifacts.io.net.resolve_ref` → SHA, then materialised
  once through :func:`agent_artifacts.io.cache.ensure_snapshot`; ``root`` is that snapshot dir.
  ``label()`` returns ``"main:<sha>"`` (default branch) or ``"pin:<sha>"`` (explicit ref) via
  :func:`agent_artifacts.model.source_label`.

Both backends produce **identical** catalogs from identical content (the whole point of the
abstraction): downstream commands never branch on local-vs-remote.

Remote testing
--------------
``open_source`` accepts an optional ``opener`` callable ``(urllib.request.Request) ->
file-like`` (same contract as :mod:`agent_artifacts.io.net`). It is threaded through both
``resolve_ref`` and ``fetch_tarball`` so the remote path is exercisable without live network
(point it at a local ``http.server`` or a fake). ``token`` defaults to ``$GITHUB_TOKEN``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from . import catalog as catalog_mod
from . import fp
from .fp import Err, Ok
from .io import cache, fs, net
from .model import Catalog, Request, Resolved, Result, source_label

# Reader signature: given an absolute path, return its bytes. Injectable for testing,
# defaults to the real filesystem performer.
Reader = Callable[[str], bytes]

# Each artifact type maps to (subdir, how-to-locate-the-file, parser). The "locate"
# closure turns an entry name into the path (relative to root) that holds the artifact's
# definition. Skills/hooks live in a per-name directory; guidelines/mcp are flat files.
_SKILL_DIR = "skills"
_GUIDELINE_DIR = "guidelines"
_MCP_DIR = "mcp"
_HOOK_DIR = "hooks"
_BUNDLE_DIR = "bundles"


@dataclass(frozen=True, slots=True)
class Source:
    """A resolved source root — local dir or extracted remote snapshot, uniformly.

    Attributes
    ----------
    root : str
        Absolute filesystem path whose immediate children are ``skills/ guidelines/ mcp/
        hooks/ bundles/`` (DESIGN.md §4).
    _label : str
        The manifest source string: ``"local:<abspath>"`` | ``"main:<sha>"`` | ``"pin:<sha>"``.
    _read : Reader
        Bytes reader keyed on an absolute path (injectable; defaults to ``fs.read_bytes``).
    """

    root: str
    _label: str
    _read: Reader = fs.read_bytes

    def read(self, rel: str) -> bytes:
        """Read ``rel`` (a path relative to :attr:`root`) and return its bytes."""
        return self._read(os.path.join(self.root, rel))

    def label(self) -> str:
        """Manifest source string recorded verbatim by the install command.

        ``"local:<abspath>"`` for a local ``--source DIR`` (no commit exists), or
        ``"main:<sha>"`` / ``"pin:<sha>"`` for a remote snapshot.
        """
        return self._label

    def catalog(self) -> Result:
        """Scan the standard directories, parse every entry, build a `Catalog`.

        Returns ``Ok(Catalog)`` when everything parses, or an ``Err`` accumulating **all**
        malformed artifacts/bundles (via :func:`fp.partition`). Layout (DESIGN.md §4):

        * skill     — ``skills/<name>/SKILL.md``
        * guideline — ``guidelines/<name>.md``
        * mcp       — ``mcp/<name>.json``
        * hook      — ``hooks/<name>/hook.json``
        * bundle    — ``bundles/<name>.json``
        """
        results: List[Result] = []
        results.extend(self._scan_skills())
        results.extend(self._scan_guidelines())
        results.extend(self._scan_mcp())
        results.extend(self._scan_hooks())
        artifact_results = results  # all yield Ok[Artifact]
        bundle_results = self._scan_bundles()

        arts_ok, arts_err = fp.partition(artifact_results)
        bundles_ok, bundles_err = fp.partition(bundle_results)
        errs = arts_err + bundles_err
        if errs:
            return Err("; ".join(e.reason for e in errs))

        artifacts = {(a.type, a.name): a for a in arts_ok}
        bundles = {b.name: b for b in bundles_ok}
        return Ok(Catalog(artifacts=artifacts, bundles=bundles))

    # ---- per-type scanners (each returns a list of Result) --------------- #
    def _names_in(self, subdir: str) -> tuple:
        """Sorted entry names directly under ``<root>/<subdir>`` (empty if absent)."""
        return fs.listdir(os.path.join(self.root, subdir))

    def _scan_skills(self) -> List[Result]:
        out: List[Result] = []
        for name in self._names_in(_SKILL_DIR):
            rel = os.path.join(_SKILL_DIR, name, "SKILL.md")
            if not fs.exists(os.path.join(self.root, rel)):
                continue  # not a skill dir (no SKILL.md) — skip silently
            text = self._read_text(rel)
            out.append(catalog_mod.parse_skill(text, name))
        return out

    def _scan_guidelines(self) -> List[Result]:
        out: List[Result] = []
        for entry in self._names_in(_GUIDELINE_DIR):
            if not entry.endswith(".md"):
                continue
            name = entry[: -len(".md")]
            text = self._read_text(os.path.join(_GUIDELINE_DIR, entry))
            out.append(catalog_mod.parse_guideline(text, name))
        return out

    def _scan_mcp(self) -> List[Result]:
        out: List[Result] = []
        for entry in self._names_in(_MCP_DIR):
            if not entry.endswith(".json"):
                continue
            name = entry[: -len(".json")]
            text = self._read_text(os.path.join(_MCP_DIR, entry))
            out.append(catalog_mod.parse_mcp(text, name))
        return out

    def _scan_hooks(self) -> List[Result]:
        out: List[Result] = []
        for name in self._names_in(_HOOK_DIR):
            rel = os.path.join(_HOOK_DIR, name, "hook.json")
            if not fs.exists(os.path.join(self.root, rel)):
                continue  # not a hook dir (no hook.json) — skip silently
            text = self._read_text(rel)
            out.append(catalog_mod.parse_hook(text, name))
        return out

    def _scan_bundles(self) -> List[Result]:
        out: List[Result] = []
        for entry in self._names_in(_BUNDLE_DIR):
            if not entry.endswith(".json"):
                continue
            name = entry[: -len(".json")]
            text = self._read_text(os.path.join(_BUNDLE_DIR, entry))
            out.append(catalog_mod.parse_bundle(text, name))
        return out

    def _read_text(self, rel: str) -> str:
        """Read ``rel`` as UTF-8 text via :meth:`read` (keeps the injected reader honoured)."""
        return self.read(rel).decode("utf-8")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def open_source(
    request: Request,
    *,
    opener=None,
    token: Optional[str] = None,
    reader: Optional[Reader] = None,
) -> Result:
    """Resolve a `Request` into a `Source` (local dir or remote snapshot).

    Local (``request.source_dir`` set): offline; ``root`` is that dir (absolute), label
    ``"local:<abspath>"``. Remote: ``resolve_ref`` (bind — propagate ``Err`` fail-soft) →
    ``ensure_snapshot``; label ``"pin:<sha>"`` for an explicit ``request.version`` else
    ``"main:<sha>"``.

    ``opener`` / ``token`` are forwarded to the network layer (testability without live
    network; ``token`` falls back to ``$GITHUB_TOKEN``). ``reader`` overrides the bytes
    reader baked into the returned `Source` (defaults to ``fs.read_bytes``).
    """
    read_fn: Reader = reader if reader is not None else fs.read_bytes

    if request.source_dir is not None:
        root = os.path.abspath(request.source_dir)
        return Ok(Source(root=root, _label=f"local:{root}", _read=read_fn))

    if not request.repo:
        return Err("open_source: no source_dir and no repo specified")

    repo = request.repo
    auth = token if token is not None else os.environ.get("GITHUB_TOKEN")

    # An explicit version is a pin; the default ("main" / None) tracks the branch tip.
    explicit = request.version is not None
    ref = request.version if explicit else "main"

    resolved = net.resolve_ref(repo, ref, token=auth, opener=opener)
    if isinstance(resolved, Err):
        return resolved  # fail-soft: propagate the network error verbatim
    sha = resolved.value

    try:
        root = cache.ensure_snapshot(
            repo,
            sha,
            fetch=lambda: net.fetch_tarball(repo, sha, token=auth, opener=opener),
        )
    except Exception as exc:  # snapshot/extract failure — surface as a value
        return Err(f"failed to materialise snapshot {repo}@{sha}: {exc}", code=3)

    kind = "pin" if explicit else "main"
    label = source_label(Resolved(kind=kind, sha=sha))
    return Ok(Source(root=os.path.abspath(root), _label=label, _read=read_fn))
