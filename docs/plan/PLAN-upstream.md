# agent-artifacts - Implementation Plan: upstream tracking for vendored artifacts

Companion to [../design/DESIGN-upstream.md](../design/DESIGN-upstream.md), continuing the base plan and the memory
extension plan. This plan adds `aart upstream check/update` as a maintainer workflow. It keeps
the existing ground rules: functional core / imperative shell, immutable data, stdlib only,
`unittest`, no ambient network calls, disjoint file ownership for parallel work, and **TDD:
tests first, then implementation**.

Read order: TDD rules -> contract delta -> target file map -> waves -> dependency graph ->
work packages -> critical path -> tests.

---

## 0. TDD execution rules

Every implementation work package follows the same red-green-refactor loop:

1. **Red:** add or update the focused `unittest` module first. Run that test and confirm it
   fails for the expected missing behavior, not because of syntax/import mistakes.
2. **Green:** implement the smallest production change that makes the focused test pass.
3. **Refactor:** clean up names, pure helpers, and duplication while keeping the focused test
   green.
4. **Guardrail:** run the relevant neighboring tests for that slice.
5. **Gate:** before the WP is done, run the full suite or the documented full-suite subset for
   that wave.

Sub-agents assigned implementation work must include the exact first failing test command in
their final report, followed by the passing command after implementation. They must not land
implementation-only patches.

For contract WPs, the first tests are import/shape tests: assert new fields, dataclass records,
stubs, and parser dispatch exist. For command WPs, the first tests are CLI/command behavior
tests with fakes or fixtures. For IO WPs, the first tests use fake openers or temp directories,
never live network.

---

## 1. Contract delta

The change adds a repo-level upstream tracking model and one nested CLI command family. It
does **not** change the trust boundary of consumer commands.

New source file:

```text
upstreams.json
```

New command:

```sh
aart upstream check ...
aart upstream update ...
```

New data records, names illustrative:

```python
UpstreamKey       # type/name
UpstreamSource    # kind=github, repo, ref, path
UpstreamSync      # sha, content_hash, synced_at
UpstreamEntry     # key, source, last_synced
UpstreamCatalog   # version, entries
UpstreamStatus    # key, state, base/head sha+hash, diagnostics
```

`Request` gains only the fields needed for nested dispatch:

```python
upstream_action: Optional[str] = None   # "check" | "update"
```

The existing selector fields (`names`, `bundles`, `all`, `type_filter`, `dry_run`, `force`,
`json`, `source_dir`) are reused.

No new `Action` is required for the MVP. Upstream updates can be expressed with existing
`WriteFile`, `CopyTree`, `RemovePath`, and `Warn` actions plus the existing executor. If tests
show tree replacement cannot be expressed safely with the current executor, add a narrowly
scoped action only after a failing planner/executor test demonstrates the missing primitive.

---

## 2. Target file map

```
agent-artifacts/
├── upstreams.json                         # WP-43 seed/example, optional in MVP fixtures
├── agent_artifacts/
│   ├── model.py                           # WP-33 Request.upstream_action
│   ├── upstreams.py                       # WP-33/WP-34 pure metadata model, parser, selectors
│   ├── upstream_source.py                 # WP-35 remote upstream resolution/materialization
│   ├── upstream_planner.py                # WP-36 status + update planning
│   ├── commands/upstream.py               # WP-38 command orchestration
│   ├── commands/__init__.py               # WP-38 if needed
│   ├── cli.py                             # WP-39 nested argparse + dispatch
│   ├── io/net.py                          # WP-35 small token fallback if needed
│   └── executor.py                        # untouched unless WP-36 finds a missing primitive
├── tests/
│   ├── upstreams_test.py                  # WP-34
│   ├── upstream_source_test.py            # WP-35
│   ├── upstream_planner_test.py           # WP-36
│   ├── upstream_command_test.py           # WP-38
│   ├── upstream_cli_test.py               # WP-39
│   └── upstream_e2e_test.py               # WP-44
├── tests/fixtures/upstreams/              # WP-43 local/fake upstream fixtures
├── ../design/DESIGN-upstream.md                     # this design
├── PLAN-upstream.md                       # this plan
└── README.md                              # WP-44 docs
```

Shared-file rule: only WP-39 owns `cli.py`; only WP-33 owns the `Request` model change; only
WP-38 owns `commands/upstream.py`. Tests are added as new modules instead of broad edits to
existing test files.

---

## 3. Wave schedule

| Wave | WPs | Parallelism | Gate to exit |
| --- | --- | --- | --- |
| **A - contract** | WP-33 | 1 blocking | data stubs import; existing suite still green |
| **B - pure core and IO** | WP-34, WP-35, WP-36, WP-37 | up to 4 | unit tests green for each slice |
| **C - command surface** | WP-38, WP-39, WP-43 | up to 3 | `aart upstream ...` works against fixtures |
| **D - integration** | WP-44 | 1 final | e2e green; docs updated; full suite green |

WP-36 can start after WP-33 with fake upstream snapshots, then integrate with WP-35. WP-38
requires WP-34, WP-35, and WP-36. WP-39 can parse and dispatch against a stub command as soon
as WP-33 lands.

---

## 4. Dependency graph

```
                    WP-33 contract/data stubs
                       |        |        |
                     WP-34    WP-35    WP-39
                   metadata   source   cli surface
                       |        |
                       +--- WP-36 planner/status
                                |
                              WP-37 validation helpers
                                |
                              WP-38 command
                                |
                    WP-43 fixtures/seed metadata
                                |
                              WP-44 e2e/docs
```

`WP-37` is separated so validation can be delegated or folded into WP-34 if staffing is small.
If running with fewer agents, combine WP-34 + WP-37.

---

## 5. Work packages

### WP-33 - Contract and stubs *(A, blocking, small)*

**Owns:** `agent_artifacts/model.py`, initial `agent_artifacts/upstreams.py`,
`agent_artifacts/upstream_source.py`, `agent_artifacts/upstream_planner.py`.

**TDD first**
- Add `tests/upstream_contract_test.py` asserting `Request.upstream_action` exists, upstream
  record types import, and stub functions are callable.
- Run that test and confirm it fails before touching production code.

**Implement**
- Add `Request.upstream_action: Optional[str] = None`.
- Add frozen data records for upstream keys, source specs, sync state, entries, catalogs, and
  status results. These may live in `upstreams.py` to avoid overloading `model.py`.
- Add typed stubs for:
  - `parse_upstreams(text) -> Result[UpstreamCatalog]`
  - `dump_upstreams(catalog) -> str`
  - `select_upstreams(...)`
  - `resolve_upstream_source(...)`
  - `hash_upstream_path(...)`
  - `plan_upstream_check(...)`
  - `plan_upstream_update(...)`

**Done when**
- `tests/upstream_contract_test.py` passes.
- Existing tests still pass.
- No behavior is wired yet.

### WP-34 - Metadata parser, serializer, and selectors *(B, parallel, medium)*

**Owns:** `agent_artifacts/upstreams.py`, `tests/upstreams_test.py`.

**Depends:** WP-33.

**TDD first**
- Add parser round-trip, invalid-schema, key parsing, and selector tests in
  `tests/upstreams_test.py`.
- Include one test for `--bundle` selection that skips untracked bundle members with a warning.
- Run the new test module and confirm the expected failures.

**Implement**
- Parse and dump `upstreams.json` deterministically.
- Validate schema version, artifact keys, source kind, repo/ref/path strings, and last-sync
  fields.
- Implement `type/name` key parsing and formatting.
- Resolve selections against the existing `Catalog`:
  - names;
  - `--type`;
  - `--bundle`;
  - `--all`;
  - `type/name` explicit keys.
- Distinguish explicit untracked selection (usage error) from bundle-selected untracked
  members (warning/skip).

**Done when**
- Round-trip tests pass.
- Invalid metadata accumulates errors.
- Bundle selection returns only tracked artifacts and reports untracked bundle members.

### WP-35 - Upstream source resolver and snapshot hashing *(B, parallel, medium)*

**Owns:** `agent_artifacts/upstream_source.py`, `tests/upstream_source_test.py`.

**Depends:** WP-33; reuses `io/net.py` and `io/cache.py`.

**TDD first**
- Add fake-GitHub and temp-cache tests in `tests/upstream_source_test.py` before implementing.
- Cover file hashing, tree hashing, missing path, and cache reuse.
- Run the new tests and confirm they fail for missing behavior.

**Implement**
- Resolve `github` source `repo@ref` to a SHA.
- Fetch/materialize the immutable tarball through the existing cache.
- Read the tracked upstream path from the snapshot.
- Compute deterministic content hashes for files and trees.
- Group work by `(repo, sha)` so one fetched snapshot can serve many tracked artifacts.
- Surface `missing_upstream` when the tracked path is absent.
- Use injected openers in tests; no live network tests.

**Done when**
- Fake GitHub server tests cover resolve, fetch, cache reuse, missing path, file hash, and tree
  hash.

### WP-36 - Upstream check/update planner *(B, parallel, medium)*

**Owns:** `agent_artifacts/upstream_planner.py`, `tests/upstream_planner_test.py`.

**Depends:** WP-33, integrates with WP-34 and WP-35.

**TDD first**
- Add golden planner tests in `tests/upstream_planner_test.py` before implementation.
- Cover no-op, clean update, local drift, conflict, `--force`, missing upstream, invalid staged
  artifact, stale file removal from tree imports, file artifacts, and tree artifacts.
- Run the new tests and confirm they fail for the planned missing behaviors.

**Implement**
- Given selected upstream entries and resolved upstream snapshots, produce status records:
  `up_to_date`, `changed`, `local_drift`, `missing_upstream`, `invalid`, `conflict`.
- Map artifact type to local catalog root:
  - `skill` -> `skills/<name>/`
  - `guideline` -> `guidelines/<name>.md`
  - `mcp` -> `mcp/<name>.json`
  - `hook` -> `hooks/<name>/`
  - `memory` -> `memory/<name>.md`
- Hash local catalog artifacts with the same deterministic file/tree hash function.
- Reuse the existing update policy shape (`disk`, `base`, `new`) for local catalog drift.
- Plan clean updates using existing actions.
- Plan conflict sidecars for file and tree artifacts unless `--force`.
- Plan tree updates as exact replacements so files deleted upstream are removed locally when
  clean or forced.
- Update `upstreams.json` only when an update is applied.
- Validate staged imported content with existing artifact parsers before replacement.

**Done when**
- Golden tests cover no-op, clean update, local drift, conflict, `--force`, missing upstream,
  invalid staged artifact, stale tree-file removal, file artifact, and tree artifact.

### WP-37 - Catalog validation integration *(B, parallel, small)*

**Owns:** validation helpers in `agent_artifacts/upstreams.py` or a small
`agent_artifacts/upstream_validate.py`, `tests/upstream_validate_test.py`.

**Depends:** WP-34.

**TDD first**
- Add `tests/upstream_validate_test.py` before implementation.
- Cover missing local artifact, wrong key syntax, missing last-sync state, and unknown source
  kind.

**Implement**
- Add `validate_upstreams(upstreams, catalog) -> tuple[Err, ...]`.
- Ensure every tracked key resolves to a real catalog artifact.
- Ensure destination shape matches the declared type.
- Provide reusable diagnostics for `aart upstream check` and future `aart validate`.

**Done when**
- Missing local artifact, wrong key syntax, missing last-sync state, and unknown source kind
  are reported clearly.

### WP-38 - `commands/upstream.py` orchestration *(C, parallel after B, large)*

**Owns:** `agent_artifacts/commands/upstream.py`, optional `commands/__init__.py`,
`tests/upstream_command_test.py`.

**Depends:** WP-34, WP-35, WP-36, WP-37.

**TDD first**
- Add `tests/upstream_command_test.py` first with fake upstream-source/planner functions.
- Cover check JSON, update dry-run, clean update, conflict exit, force update, bundle
  selection, missing upstream metadata, and "update requires explicit selector."
- Confirm failures are behavior failures, then implement orchestration.

**Implement**
- Load the catalog repo from `request.source_dir` or `.`.
- Load and parse `upstreams.json`.
- Resolve selected tracked artifacts.
- `check`:
  - gather statuses;
  - print compact human output or stable JSON;
  - do not write files.
- `update`:
  - require explicit selector (`NAME`, `--bundle`, or `--all`);
  - build update plan;
  - honor `--dry-run`, `--force`, and `--json`;
  - execute planned file actions;
  - persist updated `upstreams.json`.
- Return structured exit codes:
  - `0` OK;
  - `2` usage/schema/selection errors;
  - `3` network/source errors;
  - `4` conflicts;
  - `5` corrupt tracking file if useful, or reuse `2` if keeping exit codes minimal.

**Done when**
- Command tests cover check JSON, update dry-run, clean update, conflict exit, force update,
  bundle selection, and missing upstream metadata.

### WP-39 - CLI nested command surface *(C, parallel, medium)*

**Owns:** `agent_artifacts/cli.py`, `tests/upstream_cli_test.py`.

**Depends:** WP-33; integrates with WP-38.

**TDD first**
- Add `tests/upstream_cli_test.py` first with dispatcher stubs.
- Assert nested parser shape, request mapping, help exit behavior, and dispatch key.
- Run the new CLI tests and confirm they fail before editing `cli.py`.

**Implement**
- Add nested argparse:
  - `agent-artifacts upstream check ...`
  - `agent-artifacts upstream update ...`
- Reuse existing selection flags.
- Add `--all`, `--bundle`, `--type`, `--source`, `--dry-run`, `--force`, `--json` as designed.
- Map parsed args into `Request(command="upstream", upstream_action="check"|"update", ...)`.
- Add `commands.upstream.run` to dispatch.
- Ensure top-level help and upstream help are readable.

**Done when**
- Parser tests confirm all flags map correctly.
- `aart upstream update` without a selector reaches command code with enough information to
  produce the intended usage error.

### WP-40 - Optional maintainer ergonomics *(C, optional, small)*

**Owns:** `agent_artifacts/commands/upstream.py` extensions and tests, if included.

**Depends:** WP-38.

**TDD first**
- If included, add focused tests for `upstream list` or `--allow-dirty` before adding the
  option.

**Implement**
- Add `aart upstream list` if maintainers need an inventory view.
- Consider `--allow-dirty` if the final design chooses broad git worktree protection.
- Keep this package optional; do not block MVP on it.

**Done when**
- Either explicitly deferred or implemented with focused tests.

### WP-41 - JSON output contract and examples *(C, parallel, small)*

**Owns:** `tests/upstream_json_test.py`, docs snippets if useful.

**Depends:** WP-38.

**TDD first**
- Add golden JSON tests before adjusting output.
- Assert exact keys and stable ordering where the command promises it.

**Implement**
- Stabilize JSON shapes for check/update.
- Include states, diagnostics, source info, base/head sha, base/head hash, and planned actions.
- Add golden tests for machine-readable output.

**Done when**
- JSON output can support automation that opens PRs later without parsing human text.

### WP-42 - No-new-dependencies and import hygiene *(C, parallel, small)*

**Owns:** `tests/upstream_import_hygiene_test.py` or extension of existing content/import
tests.

**Depends:** any code WPs.

**TDD first**
- Add import-hygiene tests that fail if upstream modules are imported by consumer-only command
  paths or if non-stdlib imports appear.

**Implement**
- Confirm upstream modules use stdlib only.
- Confirm `commands/status.py` remains network-free; upstream network code must not leak into
  status or normal consumer update paths.
- Confirm consumer `aart update` behavior is unchanged.

**Done when**
- Import hygiene tests pass.

### WP-43 - Fixtures and sample metadata *(C, parallel, small)*

**Owns:** `tests/fixtures/upstreams/`, fixture `upstreams.json`, optional root
`upstreams.json` if we want the repo to dogfood this immediately.

**Depends:** WP-34.

**TDD first**
- Add fixture-shape tests that expect the fake upstream content and metadata to exist.

**Implement**
- Add fake upstream repo fixture content with:
  - one skill tree;
  - one memory file;
  - one changed path outside a tracked artifact;
  - one invalid upstream artifact for validation tests.
- Add fixture tracking metadata with known hashes.
- Optionally add a real but conservative root `upstreams.json` only if the repo has a genuine
  vendored artifact to track at launch. Otherwise keep dogfooding out of MVP.

**Done when**
- Command and e2e tests use fixtures without live network.

### WP-44 - End-to-end gate and docs *(D, final, medium)*

**Owns:** `tests/upstream_e2e_test.py`, `README.md`, any updates to `../design/DESIGN.md` or
`../design/DESIGN-upstream.md` open questions after implementation.

**Depends:** WP-38, WP-39, WP-43.

**TDD first**
- Add `tests/upstream_e2e_test.py` first. It should fail before command wiring and then pass
  after integration.
- Add README example assertions if the repo's existing docs tests support them; otherwise
  verify examples manually in the final WP report.

**Implement**
- E2E:
  - create a temp catalog repo from fixtures;
  - run `aart upstream check --all --json`;
  - run `aart upstream update --all --dry-run`;
  - run clean update and inspect changed artifact + updated `upstreams.json`;
  - simulate local catalog drift and assert conflict/sidecar behavior;
  - run `--bundle` selection.
- README:
  - explain maintainer workflow;
  - show `upstreams.json`;
  - show check/update commands;
  - state clearly that consumers still update from the curated catalog repo.
- Full test suite and no-dependency validation.

**Done when**
- `python -m unittest discover -s tests` is green.
- README examples match real CLI behavior.
- Existing consumer install/check/update tests still pass unchanged.

---

## 6. Critical path

`WP-33 -> WP-34/WP-35/WP-36 -> WP-38 -> WP-39 -> WP-44`.

The shortest staffed path is:

1. One agent lands WP-33.
2. Three agents run WP-34, WP-35, and WP-36 in parallel.
3. One command worker integrates WP-38 while a CLI worker lands WP-39 against a stub.
4. One final worker owns WP-44.

WP-40, WP-41, WP-42, and WP-43 can run in parallel with command work when staffing allows.

---

## 7. Test strategy

Keep all tests stdlib `unittest`.

Unit tests:

- metadata parse/dump and validation;
- selector behavior, especially bundles and untracked artifacts;
- deterministic hashing for files and trees;
- fake GitHub resolver/cache behavior;
- planner decisions for no-op, clean update, drift, conflict, force, and missing upstream;
- nested CLI parsing.

Integration tests:

- no live network;
- fake upstream snapshots served through injected openers or local fixture tarballs;
- command output in human and JSON modes;
- dry-run writes nothing;
- update writes only the artifact roots and `upstreams.json`;
- consumer `status`, `check`, and `update` do not import upstream modules that perform network
  work.

Regression tests:

- an upstream commit that changes only unrelated files reports `up_to_date` for the tracked
  artifact;
- a local catalog edit plus upstream edit produces conflict, not overwrite;
- an invalid upstream `SKILL.md` does not replace a valid local skill;
- upstream path deletion does not delete the local catalog artifact by default.

---

## 8. Rollout

1. Land metadata parser and validation with no commands.
2. Add `aart upstream check` read-only.
3. Add `aart upstream update --dry-run`.
4. Enable mutating update after conflict behavior is tested.
5. Document the maintainer workflow.
6. Optionally dogfood with one low-risk vendored skill after the feature is stable.

This staged rollout keeps the review boundary intact at every step.
