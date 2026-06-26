"""Interactive selector — WP-20. The second "skin" over the one command core.

docs/design/DESIGN.md §13 ("one core, two skins"): a bare ``agent-artifacts`` on a TTY launches this
selector; otherwise the CLI runs in flag mode. This module owns **no** install/update/
uninstall logic — it only gathers a selection (profile(s), action, artifact(s)), assembles a
:class:`~agent_artifacts.model.Request`, and dispatches it through the exact same command
handlers the flag-mode CLI uses. The decision logic stays in the pure core / commands.

Two front-ends, one body:

* ``run()`` — the entry point ``cli._run_bare`` calls on a TTY. It prefers a ``curses``
  full-screen selector and **degrades to a plain ``input()``/``print()`` flow** when curses
  is unavailable or fails to initialise (no TTY, dumb terminal, ``curses`` import/`setupterm`
  error). Either way the *same* selection→Request→dispatch path runs.
* ``_run_text(read, write, ...)`` — the fallback flow, factored so the I/O channels and the
  source factory are injectable. This makes the whole interaction unit-testable headless: a
  test scripts ``read`` with a list of answers, points ``source_factory`` at
  ``tests/fixtures`` and ``project`` at a tmp dir, and asserts the resulting exit code /
  filesystem effects — no real terminal, no curses.

Dispatch is resilient to integration order: it prefers ``cli.DISPATCH`` (WP-19) when present
and otherwise imports the command modules directly. Both routes call the *same* ``run``
functions, so no command logic is ever duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Literal, Mapping, Optional, Sequence, Tuple

from .catalog import resolve_bundle
from .compatibility import check_profile_compatibility
from .model import Artifact, ArtifactType, Catalog, Err, Manifest, Profile, Request, Result
from .profiles.loader import load_profiles
from .source import open_source

# The three write actions the selector can drive; these are the verbs that build and dispatch a
# Request.
ACTIONS: Tuple[str, ...] = ("install", "update", "uninstall")

# Canonical artifact-type display order (matches commands.list / docs/design/DESIGN.md §4).
_TYPE_ORDER: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")
_TYPE_ATTR = {
    "skill": "skills",
    "guideline": "guidelines",
    "mcp": "mcp",
    "hook": "hooks",
    "memory": "memory",
}

ReadFn = Callable[[str], str]
WriteFn = Callable[[str], None]
SourceFactory = Callable[[Request], Result]


# --------------------------------------------------------------------------- #
# Choice model — a flat, ordered menu derived from the catalog (pure).         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Choice:
    """One selectable catalog row: either a single artifact or a whole bundle.

    ``kind`` is ``"artifact"`` or ``"bundle"``. ``label`` is the human row text. ``key`` is
    ``(type, name)`` for an artifact (so we can build ``Request.names`` + ``type_filter``-free
    selection) or the bundle name for a bundle.
    """

    kind: Literal["artifact", "bundle", "profile"]
    name: str
    type: Optional[ArtifactType]
    label: str
    hidden_count: int = 0
    complete: bool = True


def _type_rank(t: ArtifactType) -> int:
    return _TYPE_ORDER.index(t) if t in _TYPE_ORDER else len(_TYPE_ORDER)


def _profile_supports(profile: Profile, art_type: ArtifactType) -> bool:
    """True when a profile has a target for ``art_type``."""
    return getattr(profile, _TYPE_ATTR[art_type], None) is not None


def artifact_visible_for_profiles(
    artifact: Artifact,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> bool:
    """Whether ``artifact`` is installable for every selected profile.

    This is intentionally an intersection check: selecting ``claude,vibe`` hides MCP/hooks
    because ``vibe`` cannot install them.
    """
    if not profile_names:
        return False
    for profile_name in profile_names:
        profile = profiles.get(profile_name)
        if profile is None:
            return False
        if not _profile_supports(profile, artifact.type):
            return False
        if not check_profile_compatibility(artifact, profile_name).ok:
            return False
    return True


def build_install_choices(
    catalog: Catalog,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> Tuple[_Choice, ...]:
    """Build installable artifact/bundle choices for selected profiles."""
    out: List[_Choice] = []
    arts: List[Artifact] = list(catalog.artifacts.values())
    arts.sort(key=lambda a: (_type_rank(a.type), a.name))
    for artifact in arts:
        if artifact_visible_for_profiles(artifact, profile_names, profiles):
            out.append(
                _Choice("artifact", artifact.name, artifact.type, f"[{artifact.type}] {artifact.name}")
            )

    for bundle_name in sorted(catalog.bundles):
        resolved = resolve_bundle(catalog, bundle_name)
        if isinstance(resolved, Err):
            continue

        visible_count = 0
        hidden_count = 0
        for artifact_type, artifact_name in resolved.value.artifacts:
            bundle_artifact = catalog.artifacts.get((artifact_type, artifact_name))
            if bundle_artifact is None:
                continue
            if artifact_visible_for_profiles(bundle_artifact, profile_names, profiles):
                visible_count += 1
            else:
                hidden_count += 1

        if visible_count == 0:
            continue

        bundle = catalog.bundles[bundle_name]
        desc = f" — {bundle.description}" if bundle.description else ""
        if hidden_count:
            label = (
                f"[bundle] {bundle_name}{desc} - "
                f"{visible_count} installable, {hidden_count} hidden for selected profile(s)"
            )
        else:
            label = f"[bundle] {bundle_name}{desc}"
        out.append(
            _Choice(
                "bundle",
                bundle_name,
                None,
                label,
                hidden_count=hidden_count,
                complete=hidden_count == 0,
            )
        )

    return tuple(out)


def build_action_choices(
    action: str,
    catalog: Catalog,
    manifest: Optional[Manifest],
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> Tuple[_Choice, ...]:
    """Build the selectable rows for an action after profile selection."""
    if action == "install":
        return build_install_choices(catalog, profile_names, profiles)
    if action in ("update", "uninstall"):
        if manifest is None:
            return ()
        return _build_manifest_choices(action, catalog, manifest, profile_names, profiles)
    return ()


def _build_manifest_choices(
    action: str,
    catalog: Catalog,
    manifest: Manifest,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> Tuple[_Choice, ...]:
    """Build update/uninstall choices from installed manifest entries."""
    profile_set = set(profile_names)
    entries = [entry for entry in manifest.installed if entry.profile in profile_set]
    out: List[_Choice] = []
    seen_names = set()
    bundle_names = set()

    for entry in entries:
        if action == "update":
            artifact = catalog.artifacts.get((entry.type, entry.artifact))
            if artifact is None:
                continue
            if not artifact_visible_for_profiles(artifact, (entry.profile,), profiles):
                continue

        if entry.artifact not in seen_names:
            seen_names.add(entry.artifact)
            out.append(
                _Choice("artifact", entry.artifact, entry.type, f"[{entry.type}] {entry.artifact}")
            )
        if entry.bundle:
            bundle_names.add(entry.bundle)

    for bundle_name in sorted(bundle_names):
        out.append(_Choice("bundle", bundle_name, None, f"[bundle] {bundle_name} - installed"))
    return tuple(out)


# --------------------------------------------------------------------------- #
# Request assembly + dispatch (the single bridge into the command core).        #
# --------------------------------------------------------------------------- #
def _build_request(
    action: str,
    chosen: Sequence[_Choice],
    profiles: Sequence[str],
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
) -> Request:
    """Assemble the `Request` for *action* from the picked rows + profiles.

    Bundle rows populate ``Request.bundles``; artifact rows populate ``Request.names``. The
    selection is left untyped (no ``type_filter``) so a bare name resolves across types via
    ``_common.resolve_artifacts`` exactly as flag-mode does. ``yes=True`` because the user
    already confirmed interactively; we never re-prompt at the command layer.
    """
    names = tuple(c.name for c in chosen if c.kind == "artifact")
    bundles = tuple(c.name for c in chosen if c.kind == "bundle")
    return Request(
        command=action,
        names=names,
        bundles=bundles,
        profiles=tuple(profiles),
        source_dir=source_dir,
        repo=repo,
        project=project,
        yes=True,
    )


def _dispatch(request: Request) -> int:
    """Route *request* through the same handlers the flag-mode CLI uses.

    Prefers ``cli.DISPATCH`` (WP-19) when it exists; otherwise imports the command module
    for ``request.command`` directly. Both paths call the identical ``run`` function — this
    module duplicates **no** command logic.
    """
    try:
        from . import cli

        dispatch = getattr(cli, "DISPATCH", None)
    except Exception:  # pragma: no cover - cli import is trivial
        dispatch = None

    if isinstance(dispatch, Mapping) and request.command in dispatch:
        return int(dispatch[request.command](request))

    # Fallback: import the specific command module on demand (avoids importing all of them
    # and keeps this independent of WP-19's merge state).
    from importlib import import_module

    module = import_module(f".commands.{request.command}", package=__package__)
    return int(module.run(request))


# --------------------------------------------------------------------------- #
# Text / fallback flow — fully injectable, headless-testable.                   #
# --------------------------------------------------------------------------- #
def _run_text(
    read: ReadFn = input,
    write: WriteFn = print,
    *,
    source_factory: SourceFactory = open_source,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """Plain prompt-driven selector. Returns a process exit code.

    Drives profile -> action -> filtered artifact/bundle prompts, assembles a `Request`, and
    dispatches it through the command core. Blank input or ``q`` at any prompt is a clean quit
    (returns 0 without dispatching). Bad numbers re-prompt rather than crash; EOF on the input
    stream is treated as a quit.

    Injection points (so the flow is testable with no real terminal):

    * ``read`` / ``write`` — the I/O channels (default ``input`` / ``print``).
    * ``source_factory`` — ``(Request) -> Result[Source]`` (default :func:`open_source`); a
      test points this at a fixture-backed source.
    * ``source_dir`` / ``repo`` / ``project`` — threaded into every `Request` so the catalog
      shown and the command dispatched resolve against the **same** source (offline-friendly).
    """
    profiles_map = load_profiles(project)
    profile_names = sorted(profiles_map)
    if not profile_names:  # pragma: no cover - built-ins always present
        write("No profiles available.")
        return 0

    write("Select profile(s):")
    for i, pname in enumerate(profile_names, start=1):
        write(f"  {i:>2}. {pname}")
    prof_choices = tuple(_Choice("profile", p, None, p) for p in profile_names)
    picked_profiles = _prompt_indices(read, write, "Profile (e.g. 1): ", prof_choices)
    if not picked_profiles:
        return 0
    profiles = [profile_names[idx] for idx in picked_profiles]

    write("Action:")
    for i, act in enumerate(ACTIONS, start=1):
        write(f"  {i:>2}. {act}")
    action = _prompt_action(read, write)
    if action is None:
        return 0

    catalog = Catalog(artifacts={}, bundles={})
    if action in ("install", "update"):
        base = Request(command=action, source_dir=source_dir, repo=repo, project=project)
        src_res = source_factory(base)
        if isinstance(src_res, Err):
            write(f"error: {src_res.reason}")
            return getattr(src_res, "code", 1)
        source = src_res.value

        cat_res = source.catalog()
        if isinstance(cat_res, Err):
            write(f"error: {cat_res.reason}")
            return getattr(cat_res, "code", 1)
        catalog = cat_res.value
        write(f"Source: {source.label()}")

    manifest: Optional[Manifest] = None
    if action in ("update", "uninstall"):
        manifest_res = _load_manifest_for_action(
            action,
            source_dir=source_dir,
            repo=repo,
            project=project,
        )
        if isinstance(manifest_res, Err):
            write(f"error: {manifest_res.reason}")
            return getattr(manifest_res, "code", 1)
        manifest = manifest_res.value

    choices = build_action_choices(action, catalog, manifest, profiles, profiles_map)
    if not choices:
        write(_empty_choices_message(action, profiles))
        return 0

    write(f"Select artifact(s)/bundle(s) for {_profiles_label(profiles)}:")
    for i, c in enumerate(choices, start=1):
        write(f"  {i:>2}. {c.label}")

    picked = _prompt_indices(read, write, "Selection (e.g. 1,3): ", choices)
    if not picked:
        return 0  # clean quit / empty selection

    request = _build_request(
        action,
        [choices[i] for i in picked],
        profiles,
        source_dir=source_dir,
        repo=repo,
        project=project,
    )
    return _dispatch(request)


def _load_manifest_for_action(
    action: str,
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
) -> Result:
    """Load the consumer manifest for update/uninstall choice building."""
    from .commands import _common

    return _common.load_manifest(
        Request(command=action, source_dir=source_dir, repo=repo, project=project)
    )


def _profiles_label(profile_names: Sequence[str]) -> str:
    return ", ".join(profile_names)


def _empty_choices_message(action: str, profile_names: Sequence[str]) -> str:
    profiles = _profiles_label(profile_names)
    if action == "install":
        return f"No installable artifacts or bundles for profile(s): {profiles}."
    if action == "update":
        return f"No installed artifacts to update for profile(s): {profiles}."
    if action == "uninstall":
        return f"No installed artifacts to uninstall for profile(s): {profiles}."
    return f"No choices for profile(s): {profiles}."


def _read_line(read: ReadFn, prompt: str) -> Optional[str]:
    """Read one line; map EOF (``input`` raising ``EOFError``) to ``None`` (= quit)."""
    try:
        return read(prompt)
    except EOFError:
        return None


def _prompt_indices(
    read: ReadFn, write: WriteFn, prompt: str, choices: Sequence[_Choice]
) -> Tuple[int, ...]:
    """Prompt for a comma/space-separated 1-based selection; return 0-based indices.

    Blank or ``q`` -> empty tuple (quit). Out-of-range / non-numeric tokens re-prompt with a
    short message rather than crashing. Duplicates are de-duplicated, original order kept.
    """
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return ()
        line = line.strip()
        if line == "" or line.lower() == "q":
            return ()
        tokens = [t for t in line.replace(",", " ").split() if t]
        out: List[int] = []
        seen = set()
        ok = True
        for tok in tokens:
            if not tok.isdigit():
                ok = False
                break
            n = int(tok)
            if not (1 <= n <= len(choices)):
                ok = False
                break
            zero = n - 1
            if zero not in seen:
                seen.add(zero)
                out.append(zero)
        if ok and out:
            return tuple(out)
        write(f"Please enter number(s) between 1 and {len(choices)} (or 'q' to quit).")


def _prompt_action(read: ReadFn, write: WriteFn) -> Optional[str]:
    """Prompt for one action by number or name. Blank/``q`` -> ``None`` (quit)."""
    while True:
        line = _read_line(read, "Action (e.g. 1): ")
        if line is None:
            return None
        line = line.strip()
        if line == "" or line.lower() == "q":
            return None
        low = line.lower()
        if low in ACTIONS:
            return low
        if line.isdigit():
            n = int(line)
            if 1 <= n <= len(ACTIONS):
                return ACTIONS[n - 1]
        write(f"Please enter 1-{len(ACTIONS)} or one of: {', '.join(ACTIONS)}.")


# --------------------------------------------------------------------------- #
# curses front-end — thin: gather selection, then reuse the same dispatch.      #
# --------------------------------------------------------------------------- #
def _run_curses(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """Full-screen selector via stdlib ``curses``; falls back to text on any failure.

    The curses layer only collects the same profile -> action -> filtered choice selections;
    once gathered it leaves curses and calls the shared `_build_request` / `_dispatch` (so the
    install/update/uninstall logic and its stdout summary are identical to flag mode). Any
    curses error -> the text flow.
    """
    import curses  # stdlib; imported lazily so the text path needs no terminal at all.

    profiles_map = load_profiles(project)
    profile_names = sorted(profiles_map)
    if not profile_names:  # pragma: no cover - built-ins always present
        print("No profiles available.")
        return 0

    selection: dict = {}

    def _ui(stdscr) -> None:
        curses.curs_set(0)
        picked_profs = _curses_multiselect(
            curses,
            stdscr,
            "Select profile(s)  (space=toggle, enter=confirm, q=quit)",
            profile_names,
        )
        if picked_profs is None:
            return
        action_idx = _curses_singleselect(
            curses, stdscr, "Action  (enter=confirm, q=quit)", list(ACTIONS)
        )
        if action_idx is None:
            return
        action = ACTIONS[action_idx]
        catalog = Catalog(artifacts={}, bundles={})
        if action in ("install", "update"):
            src_res = open_source(
                Request(command=action, source_dir=source_dir, repo=repo, project=project)
            )
            if isinstance(src_res, Err):
                selection["error"] = (src_res.reason, getattr(src_res, "code", 1))
                return
            cat_res = src_res.value.catalog()
            if isinstance(cat_res, Err):
                selection["error"] = (cat_res.reason, getattr(cat_res, "code", 1))
                return
            catalog = cat_res.value

        manifest: Optional[Manifest] = None
        if action in ("update", "uninstall"):
            manifest_res = _load_manifest_for_action(
                action,
                source_dir=source_dir,
                repo=repo,
                project=project,
            )
            if isinstance(manifest_res, Err):
                selection["error"] = (manifest_res.reason, getattr(manifest_res, "code", 1))
                return
            manifest = manifest_res.value

        selected_profiles = [profile_names[i] for i in picked_profs]
        choices = build_action_choices(action, catalog, manifest, selected_profiles, profiles_map)
        if not choices:
            selection["empty"] = (action, selected_profiles)
            return

        picked_arts = _curses_multiselect(
            curses,
            stdscr,
            "Select artifact(s)/bundle(s)  (space=toggle, enter=confirm, q=quit)",
            [c.label for c in choices],
        )
        if picked_arts is None:
            return
        selection["arts"] = picked_arts
        selection["profs"] = picked_profs
        selection["action"] = action_idx
        selection["choices"] = choices

    try:
        curses.wrapper(_ui)
    except Exception:
        # Terminal too small, no color, init failure, etc. — degrade gracefully.
        return _run_text(source_dir=source_dir, repo=repo, project=project)

    if "error" in selection:
        reason, code = selection["error"]
        print(f"error: {reason}")
        return code
    if "empty" in selection:
        action, profiles = selection["empty"]
        print(_empty_choices_message(action, profiles))
        return 0
    if "action" not in selection:
        return 0  # user quit before completing the flow

    choices = selection["choices"]
    chosen = [choices[i] for i in selection["arts"]]
    profiles = [profile_names[i] for i in selection["profs"]]
    if not chosen or not profiles:
        return 0
    request = _build_request(
        ACTIONS[selection["action"]],
        chosen,
        profiles,
        source_dir=source_dir,
        repo=repo,
        project=project,
    )
    return _dispatch(request)


def _curses_multiselect(curses, stdscr, title: str, labels: Sequence[str]):
    """A checkbox list. Returns a tuple of selected indices, or ``None`` on quit."""
    if not labels:
        return ()
    cursor = 0
    checked = [False] * len(labels)
    while True:
        _draw_list(curses, stdscr, title, labels, cursor, checked)
        ch = stdscr.getch()
        if ch in (ord("q"), 27):  # q / ESC
            return None
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch == ord(" "):
            checked[cursor] = not checked[cursor]
        elif ch in (curses.KEY_ENTER, 10, 13):
            return tuple(i for i, on in enumerate(checked) if on)


def _curses_singleselect(curses, stdscr, title: str, labels: Sequence[str]):
    """A single-choice list. Returns the chosen index, or ``None`` on quit."""
    cursor = 0
    while True:
        _draw_list(curses, stdscr, title, labels, cursor, None)
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return None
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return cursor


def _draw_list(curses, stdscr, title: str, labels, cursor: int, checked) -> None:
    """Render *title* + the labels, marking the cursor row and any checked rows."""
    stdscr.clear()
    stdscr.addstr(0, 0, title[: _width(stdscr) - 1])
    for i, label in enumerate(labels):
        prefix = "> " if i == cursor else "  "
        box = ""
        if checked is not None:
            box = "[x] " if checked[i] else "[ ] "
        line = f"{prefix}{box}{label}"
        row = i + 2
        if row < _height(stdscr):
            stdscr.addstr(row, 0, line[: _width(stdscr) - 1])
    stdscr.refresh()


def _height(stdscr) -> int:
    return stdscr.getmaxyx()[0]


def _width(stdscr) -> int:
    return stdscr.getmaxyx()[1]


# --------------------------------------------------------------------------- #
# Entry point — chooses curses vs text and delegates.                           #
# --------------------------------------------------------------------------- #
def run(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """Launch the interactive selector; return a process exit code.

    Called by ``cli._run_bare`` on a bare TTY invocation. Tries the ``curses`` selector and
    **degrades to the ``input()`` flow** if curses cannot be imported or initialised. A clean
    quit (no selection) returns 0. ``source_dir`` / ``repo`` / ``project`` default to ``None``
    so the standard source resolution (default repo, or env/flags handled upstream) applies.
    """
    try:
        import curses  # noqa: F401  (presence check only)
        import sys

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("not a tty")
    except Exception:
        return _run_text(source_dir=source_dir, repo=repo, project=project)

    try:
        return _run_curses(source_dir=source_dir, repo=repo, project=project)
    except Exception:  # pragma: no cover - last-resort guard around the curses path
        return _run_text(source_dir=source_dir, repo=repo, project=project)
