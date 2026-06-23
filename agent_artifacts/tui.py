"""Interactive selector — WP-20. The second "skin" over the one command core.

DESIGN.md §13 ("one core, two skins"): a bare ``agent-artifacts`` on a TTY launches this
selector; otherwise the CLI runs in flag mode. This module owns **no** install/update/
uninstall logic — it only gathers a selection (artifact(s), profile(s), action), assembles a
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

from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from .model import Artifact, Bundle, Catalog, Err, Request, Result
from .profiles.loader import load_profiles
from .source import open_source

# The three write actions the selector can drive. ``list`` is implicit (we always show the
# catalog first); these are the verbs that build and dispatch a Request.
ACTIONS: Tuple[str, ...] = ("install", "update", "uninstall")

# Canonical artifact-type display order (matches commands.list / DESIGN.md §4).
_TYPE_ORDER: Tuple[str, ...] = ("skill", "guideline", "mcp", "hook", "memory")

ReadFn = Callable[[str], str]
WriteFn = Callable[[str], None]
SourceFactory = Callable[[Request], Result]


# --------------------------------------------------------------------------- #
# Choice model — a flat, ordered menu derived from the catalog (pure).         #
# --------------------------------------------------------------------------- #
class _Choice:
    """One selectable catalog row: either a single artifact or a whole bundle.

    ``kind`` is ``"artifact"`` or ``"bundle"``. ``label`` is the human row text. ``key`` is
    ``(type, name)`` for an artifact (so we can build ``Request.names`` + ``type_filter``-free
    selection) or the bundle name for a bundle.
    """

    __slots__ = ("kind", "label", "name", "type")

    def __init__(self, kind: str, name: str, type_: Optional[str], label: str) -> None:
        self.kind = kind
        self.name = name
        self.type = type_
        self.label = label


def _build_choices(catalog: Catalog) -> Tuple[_Choice, ...]:
    """Flatten a catalog into an ordered list of selectable rows (artifacts then bundles)."""
    out: List[_Choice] = []
    arts: List[Artifact] = list(catalog.artifacts.values())
    arts.sort(key=lambda a: (_type_rank(a.type), a.name))
    for a in arts:
        out.append(_Choice("artifact", a.name, a.type, f"[{a.type}] {a.name}"))
    for bname in sorted(catalog.bundles):
        b: Bundle = catalog.bundles[bname]
        desc = f" — {b.description}" if b.description else ""
        out.append(_Choice("bundle", bname, None, f"[bundle] {bname}{desc}"))
    return tuple(out)


def _type_rank(t: str) -> int:
    return _TYPE_ORDER.index(t) if t in _TYPE_ORDER else len(_TYPE_ORDER)


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

    Drives three prompts — artifact/bundle row(s), profile(s), action — assembles a `Request`
    and dispatches it through the command core. Blank input or ``q`` at any prompt is a clean
    quit (returns 0 without dispatching). Bad numbers re-prompt rather than crash; EOF on the
    input stream is treated as a quit.

    Injection points (so the flow is testable with no real terminal):

    * ``read`` / ``write`` — the I/O channels (default ``input`` / ``print``).
    * ``source_factory`` — ``(Request) -> Result[Source]`` (default :func:`open_source`); a
      test points this at a fixture-backed source.
    * ``source_dir`` / ``repo`` / ``project`` — threaded into every `Request` so the catalog
      shown and the command dispatched resolve against the **same** source (offline-friendly).
    """
    base = Request(command="list", source_dir=source_dir, repo=repo, project=project)

    src_res = source_factory(base)
    if isinstance(src_res, Err):
        write(f"error: {src_res.reason}")
        return getattr(src_res, "code", 1)
    source = src_res.value

    cat_res = source.catalog()
    if isinstance(cat_res, Err):
        write(f"error: {cat_res.reason}")
        return getattr(cat_res, "code", 1)
    catalog: Catalog = cat_res.value

    choices = _build_choices(catalog)
    if not choices:
        write("No artifacts found in source.")
        return 0

    write(f"Source: {source.label()}")
    write("Select artifact(s)/bundle(s) to act on (blank or 'q' to quit):")
    for i, c in enumerate(choices, start=1):
        write(f"  {i:>2}. {c.label}")

    picked = _prompt_indices(read, write, "Selection (e.g. 1,3): ", choices)
    if not picked:
        return 0  # clean quit / empty selection

    profile_names = sorted(load_profiles(project))
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

    request = _build_request(
        action,
        [choices[i] for i in picked],
        profiles,
        source_dir=source_dir,
        repo=repo,
        project=project,
    )
    return _dispatch(request)


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

    The curses layer only collects the same three selections; once gathered it leaves curses
    and calls the shared `_build_request` / `_dispatch` (so the install/update/uninstall logic
    and its stdout summary are identical to flag mode). Any curses error -> the text flow.
    """
    import curses  # stdlib; imported lazily so the text path needs no terminal at all.

    # Resolve the catalog up front (outside curses) so an open/catalog error degrades cleanly.
    base = Request(command="list", source_dir=source_dir, repo=repo, project=project)
    src_res = open_source(base)
    if isinstance(src_res, Err):
        return _run_text(source_dir=source_dir, repo=repo, project=project)
    source = src_res.value
    cat_res = source.catalog()
    if isinstance(cat_res, Err):
        print(f"error: {cat_res.reason}")
        return getattr(cat_res, "code", 1)
    catalog: Catalog = cat_res.value

    choices = _build_choices(catalog)
    if not choices:
        print("No artifacts found in source.")
        return 0
    profile_names = sorted(load_profiles(project))

    selection: dict = {}

    def _ui(stdscr) -> None:
        curses.curs_set(0)
        picked_arts = _curses_multiselect(
            curses,
            stdscr,
            "Select artifact(s)/bundle(s)  (space=toggle, enter=confirm, q=quit)",
            [c.label for c in choices],
        )
        if picked_arts is None:
            return
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
        selection["arts"] = picked_arts
        selection["profs"] = picked_profs
        selection["action"] = action_idx

    try:
        curses.wrapper(_ui)
    except Exception:
        # Terminal too small, no color, init failure, etc. — degrade gracefully.
        return _run_text(source_dir=source_dir, repo=repo, project=project)

    if "action" not in selection:
        return 0  # user quit before completing the flow

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
