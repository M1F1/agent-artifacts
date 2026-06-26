# agent-artifacts - Implementation Plan: paste-a-link upstream adoption

Companion to [../design/DESIGN-frictionless-adoption.md](../design/DESIGN-frictionless-adoption.md).

**Status (2026-06-23):** WP-0/1/2/3/4 **done** — parser, `Request`/CLI surface, `_run_add`
command, docs (README + this doc), and verification (513 tests, validate, mypy, ruff all green;
live adoption confirmed). WP-A (optional "no catalog" error) **not done** — Part A stays a
decision per [../design/DESIGN-frictionless-adoption.md §2](../design/DESIGN-frictionless-adoption.md).

One mostly-sequential workstream. Part A (default source) needs no build — it is a recorded
decision (DESIGN §2) plus one *optional* hardening WP. The work is Part B: a deep-link parser and
the `aart upstream add` command. TDD: each work package adds failing tests first, then the
smallest change that passes them.

## 1. Target behavior

```sh
$ aart upstream add skill/domain-modeling \
    https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling
# resolves mattpocock/skills@main, vendors skills/domain-modeling/, writes the upstreams.json entry
$ aart upstream check skill/domain-modeling      # -> unchanged
```

Bare repo URLs and enterprise hosts work with explicit overrides:

```sh
$ aart upstream add guideline/style https://github.my-co.com/platform/skills \
    --ref main --path guidelines/style.md
```

Part A requires no behavior change: under `pip install -e .` the default source already resolves
to the repo (DESIGN §2).

## 2. Workstream shape

Sequential spine: **WP-0 bootstrap → WP-1 parser → WP-2 command → WP-3 docs → WP-4 verify.** The
parser (WP-1) and the optional error-message hardening (WP-A) are independent and may run in
parallel with each other; docs (WP-3) can start early. This is small enough that one or two
workers suffice — no multi-track split is warranted.

## 3. Work packages

### WP-0 - Bootstrap: Request + CLI surface for `add`

**Owns:** `agent_artifacts/model.py`, `agent_artifacts/cli.py`, `tests/upstream_cli_test.py`.

**Tests first**
- `upstream add skill/x <url>` parses into a `Request` with the key, `url`,
  `upstream_action="add"`, and `--ref`/`--path`/`--force`/`--dry-run`/`--json` mapped through.

**Implementation**
- Add `url`/`ref`/`path` to the frozen `Request`; extend `_to_request`.
- Add the `upstream add` subparser routed to the command's `add` branch.
- Land `parse_github_url` as an importable stub so WP-1/WP-2 can build against it.

**Done when:** `python -m unittest discover -s tests -p "upstream_cli_test.py" -v` passes.

### WP-1 - Deep-link URL parser (pure)

**Owns:** `agent_artifacts/github_source.py`, `tests/github_url_test.py` (new).

**Tests first**
- Bare repo URL → `repo` only (parity with `_parse_repo_url`).
- `/tree/main/skills/x` → `ref="main"`, `path="skills/x"`, `is_file=False`.
- `/blob/v1.2.0/guidelines/x.md` → `is_file=True`; nested paths preserved.
- `/tree/main` with no path → `ref="main"`, `path=None`.
- Enterprise host derives `api_url`/`web_url`; `.git` trimmed.
- Query (`?plain=1`) and fragment (`#L10`) stripped, not rejected.
- Errors: non-HTTPS, missing owner/name, credentials, `/tree` or `/blob` with no ref segment.
- Slashed ref: `/tree/feature/login/skills/x` → `ref="feature"`, `path="login/skills/x"`.

**Implementation**
- Add `GitHubUrlParts` + `parse_github_url`, reusing host/`.git`/credential logic; branch on the
  `tree`/`blob` marker. Do not modify `_parse_repo`/`resolve_github_location`/`_normalise_url`.

**Done when:** `github_url_test.py` passes and `upstreams_test.py` (existing `repo` parser) shows
no regression.

### WP-2 - `aart upstream add` command

**Owns:** `agent_artifacts/commands/upstream.py`, `tests/upstream_command_test.py`.

**Tests first** (injected `opener`, temp catalog)
- Happy path writes `skills/x/` + a valid `upstreams.json` entry with `last_synced`; returns OK.
- `--dry-run` prints the plan, writes nothing.
- Type↔shape mismatch (`blob` for a skill; `tree` for a guideline) → USAGE.
- Bare repo URL without `--ref`/`--path` → USAGE naming the missing piece; with both → OK.
- `--ref` overrides a URL-derived ref (slashed-branch case).
- Destination exists → CONFLICT without `--force`, OK with `--force`.
- Existing key → USAGE pointing at `update`, unless `--force`.
- Content failing type validation → nothing written.
- `--json` mirrors the `check`/`update` result shape.

**Implementation**
- Add `_run_add` reusing `_catalog_destination`, `_validate_resolved`, `resolve_upstream_source`,
  `dump_upstreams` + `fs.write_atomic`; order the executor plan so the JSON write is last/atomic.

**Done when:** `python -m unittest discover -s tests -p "upstream_command_test.py" -v` passes.

### WP-3 - Fixtures, end-to-end, docs

**Owns:** `tests/upstream_e2e_test.py`, `tests/fixtures/`, `README.md`, `../design/DESIGN-upstream.md`.

**Tests first**
- E2E: fake-opener repo tarball; `upstream add` a skill by deep-link; assert the vendored tree,
  the entry, and a follow-up `check` reporting `unchanged`. A `blob`-form e2e for a single-file
  type. Round-trip: `add`-written `upstreams.json` re-parses/re-dumps byte-identically.

**Implementation**
- README: document the paste-a-link adoption flow. Mark [../design/DESIGN-upstream.md §11 Q3](../design/DESIGN-upstream.md)
  resolved.

**Done when:** e2e tests pass; README shows the flow.

### WP-4 - Integration and verification

**Owns:** whole-feature integration.

**Tests first**
- Import hygiene holds: consumer read commands must not import upstream network code
  (`tests/upstream_import_hygiene_test.py`).

**Required verification**

```sh
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make test
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make validate
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make lint
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make typecheck
```

### WP-A - (Optional) Clearer "no catalog" error

Independent of WP-0…4; include only if open question DESIGN §5 Q4 is answered "ship it".

**Owns:** `agent_artifacts/source.py` (or the command layer), `tests/source_test.py`.

**Tests first**
- A source whose resolved root has no catalog dirs yields a diagnostic naming the directory and
  suggesting `--source DIR`, rather than a silent empty catalog.

**Implementation**
- After resolving the default root, detect the no-catalog case and return a `USAGE` `Err` with the
  message. No change to the `-e` happy path.

**Done when:** the new test passes; existing source/list/install tests are unaffected.

## 4. Suggested sub-agent dispatch

Small enough for a single implementer. If parallelizing: one worker takes WP-1 (parser) and the
optional WP-A (both independent); the same or a second worker takes WP-2 once WP-0's stub lands.
WP-3 docs/e2e can be drafted early. The integrator runs WP-4.

## 5. Risks and decisions to make during implementation

- **Slashed-ref split & `--force` overload** (DESIGN §5 Q1/Q2). Decide before wiring WP-2 tests.
  Proposal: guess-and-print the `repo@ref:path`; `--force` overwrites the destination only,
  re-adoption stays with `update`.
- **Two-write atomicity (`add`).** Catalog copy then `upstreams.json`; order the JSON write last
  so a failure leaves no tracked-but-untracked drift; document `add --force` recovery.
- **JSON contract.** `add` mirrors the `check`/`update` result dicts rather than a new shape.
- **Part A scope creep.** Resist re-introducing catalog detection / remote fallback under the
  banner of "robustness"; the decision (DESIGN §2) is editable-only. WP-A is the only sanctioned
  Part A change, and it is optional.
