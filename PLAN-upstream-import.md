# agent-artifacts - Implementation Plan: batch upstream import

Companion to [DESIGN-upstream-import.md](DESIGN-upstream-import.md). This plan adds
`aart upstream scan` and `aart upstream import` for batch maintainer adoption from GitHub
repos. It follows the repo's existing rules: stdlib only, pure core plus imperative shell,
`unittest`, no live network tests, and tests first for each work package.

Read order: target file map -> shared contract -> mode split -> waves -> work packages ->
verification.

---

## 1. Target file map

Likely production files:

```text
agent_artifacts/
  import_candidates.py          # new pure candidate records, render helpers, selection helpers
  import_manifest.py            # new pure manifest parser/dumper/validator
  import_scanner.py             # new pure-ish scanner over materialized snapshots
  import_planner.py             # new pure import and bundle plan builder
  commands/upstream.py          # extend nested dispatch: scan/import
  cli.py                        # parse new subcommands/options
  upstream_source.py            # small batch materialization helper if needed
  upstreams.py                  # no schema fork; maybe expose destination helpers
  catalog.py/source.py          # only if scanner needs shared descriptor helpers
```

Likely test files:

```text
tests/import_manifest_test.py
tests/import_scanner_test.py
tests/import_planner_test.py
tests/upstream_import_command_test.py
tests/upstream_import_cli_test.py
tests/upstream_import_e2e_test.py
tests/fixtures/imports/
```

Docs:

```text
DESIGN-upstream-import.md
PLAN-upstream-import.md
README.md
```

## 2. Shared contract

The first implementation step should add the neutral data contract used by both modes:

```python
ImportCandidate
ImportScan
ImportSelection
ImportPlan
ImportConflict
```

The contract should carry:

- upstream source fields: repo, ref, path, api_url/web_url;
- candidate key: `type/name`;
- shape: file or tree;
- local destination;
- confidence: explicit/high/medium/ambiguous;
- detected mode: manifest/heuristic;
- validation warnings/errors;
- optional bundle names.

Do not wire CLI behavior until these records have focused tests. This keeps manifest and
heuristic workers independent.

## 3. Mode split

### Manifest mode

Manifest mode owns explicit import definitions from:

```text
agent-artifacts.import.json
.agent-artifacts/import.json
```

It should be deterministic and strict:

- parse JSON;
- validate schema;
- materialize candidates exactly as declared;
- fail on invalid manifest;
- select all valid manifest artifacts by default.

### Heuristic mode

Heuristic mode owns discovery from arbitrary GitHub content:

- walk a materialized snapshot under the requested scan root;
- identify candidate shapes;
- validate through existing parsers;
- mark confidence and ambiguity;
- skip ambiguous candidates by default in non-interactive imports.

The two modes should share candidate records and the import planner, but not share detection
logic. That keeps heuristics from contaminating manifest mode.

## 4. Wave schedule

| Wave | Work packages | Parallelism | Exit gate |
| --- | --- | --- | --- |
| A - contract | WP-I0 | blocking | contract tests green |
| B - discovery modes | WP-I1, WP-I2, WP-I3 | parallel | manifest and heuristic scan tests green |
| C - planning | WP-I4, WP-I5 | parallel after B | import plan and bundle plan tests green |
| D - command shell | WP-I6, WP-I7 | parallel after C | command/CLI tests green |
| E - integration | WP-I8, WP-I9 | final | e2e, docs, full suite green |

Dependency sketch:

```text
WP-I0 contract
  |-- WP-I1 GitHub scan source
  |-- WP-I2 manifest mode
  |-- WP-I3 heuristic mode
          \       /
           WP-I4 import planner
              |
           WP-I5 bundle planner
              |
      WP-I6 command orchestration
              |
      WP-I7 CLI and interactive text flow
              |
      WP-I8 e2e fixtures
              |
      WP-I9 docs and verification
```

## 5. Work packages

### WP-I0 - Shared import contract

**Owns:** `agent_artifacts/import_candidates.py`, tests in
`tests/import_contract_test.py`.

**Tests first**

- candidate dataclass equality and JSON shape;
- key formatting and parsing reuse `UpstreamKey`;
- selection state can represent selected, skipped, ambiguous, and conflicting candidates.

**Implementation**

- Add immutable candidate/scan/selection records.
- Add small render helpers for human and JSON output.
- Keep no filesystem or network behavior here.

**Done when**

- Contract tests pass.
- Existing suite still imports cleanly.

### WP-I1 - GitHub scan source materialization

**Owns:** `agent_artifacts/upstream_source.py` or a new helper in `import_scanner.py`,
`tests/upstream_import_source_test.py`.

**Tests first**

- fake GitHub URL resolves once for a scan root;
- `/tree/ref/path` scans only that path;
- path traversal is rejected;
- missing scan root is a usage-shaped error;
- public and enterprise host metadata are preserved.

**Implementation**

- Reuse `parse_github_url` and `resolve_upstream_source` mechanics.
- Materialize the repo snapshot once per command.
- Return a scan root path plus normalized `UpstreamSource` prefix data.

**Done when**

- No live network tests.
- One materialized snapshot can feed both manifest and heuristic scanners.

### WP-I2 - Manifest mode parser

**Owns:** `agent_artifacts/import_manifest.py`, `tests/import_manifest_test.py`.

**Tests first**

- valid manifest with skill, memory, and directory MCP produces explicit candidates;
- duplicate `type/name` fails;
- unknown type fails;
- path outside scan root fails;
- invalid JSON fails;
- manifest bundle declarations parse and validate references.

**Implementation**

- Search fixed manifest locations at scan root.
- Parse versioned schema.
- Convert entries to `ImportCandidate(confidence="explicit")`.
- Preserve declared bundle metadata for later planner work.

**Done when**

- Manifest mode never uses heuristic classification.
- Invalid manifest fails instead of falling back.

### WP-I3 - Heuristic scanner

**Owns:** `agent_artifacts/import_scanner.py`, `tests/import_scanner_test.py`.

**Tests first**

- detects `*/SKILL.md` as skill;
- detects `*/hook.json` as hook;
- detects MCP file and MCP directory with `mcp.json`;
- classifies markdown under `memory/` as memory;
- classifies markdown under `guidelines/` or `rules/` as guideline;
- leaves generic `README.md` unselected/ignored;
- reports ambiguous markdown separately;
- handles descriptor name mismatch warnings.

**Implementation**

- Walk materialized scan root with ignored directories.
- Validate each candidate through existing parsers.
- Mark confidence and selected-by-default status.
- Avoid duplicates when one directory has multiple recognizable files.

**Done when**

- Heuristic mode can produce a stable scan report without writing files.

### WP-I4 - Import planner

**Owns:** `agent_artifacts/import_planner.py`, `tests/import_planner_test.py`.

**Tests first**

- selected skill plans `CopyTree` to `skills/name`;
- selected memory plans `WriteFile` to `memory/name.md`;
- selected directory MCP plans `CopyTree` to `mcp/name`;
- selected file MCP plans `WriteFile` to `mcp/name.json`;
- existing destination conflicts without `--force`;
- existing upstream entry conflicts without `--force`;
- dry-run plan contains actions but command does not execute them;
- tracking metadata is written last.

**Implementation**

- Convert selected candidates into file/tree actions.
- Build new `upstreams.json` content by upserting entries.
- Keep source commit/hash from the materialized candidate.
- Reuse existing destination rules wherever possible.

**Done when**

- Planner tests prove no writes happen in pure code.

### WP-I5 - Bundle planner

**Owns:** `agent_artifacts/import_planner.py` or `agent_artifacts/bundle_writer.py`,
`tests/import_bundle_test.py`.

**Tests first**

- creates new bundle with includes grouped by type;
- append mode preserves existing extends/pins/description and dedups includes;
- replace mode overwrites includes;
- fail mode errors if bundle exists;
- bundle description flag applies only where specified;
- selected artifacts only, not skipped/ambiguous candidates, enter the bundle.

**Implementation**

- Parse existing bundle if present.
- Produce `WriteFile` action for `bundles/name.json`.
- Keep JSON deterministic and compatible with `catalog.parse_bundle`.

**Done when**

- Bundle plan validates through current catalog parser.

### WP-I6 - Command orchestration

**Owns:** `agent_artifacts/commands/upstream.py`, `tests/upstream_import_command_test.py`.

**Tests first**

- `scan` prints candidates and writes nothing;
- `scan --json` is stable JSON;
- `import --dry-run` reports vendor/tracking/bundle plan and writes nothing;
- manifest mode import writes artifacts, upstreams, and bundle;
- heuristic mode import skips ambiguous markdown;
- conflicts return `CONFLICT`;
- `--force` replaces destination and tracking entry.

**Implementation**

- Add nested actions `scan` and `import`.
- Wire source materialization, mode choice, scanning, selection, planning, execution, and output.
- Keep `upstream add/check/update` behavior unchanged.

**Done when**

- Command tests pass with temp dirs and fake resolvers.

### WP-I7 - CLI and interactive text flow

**Owns:** `agent_artifacts/cli.py`, optional small helpers in command module,
`tests/upstream_import_cli_test.py`.

**Tests first**

- argparse accepts `upstream scan URL`;
- argparse accepts `upstream import URL --bundle NAME`;
- `--mode`, `--select`, `--bundle-mode`, `--interactive`, `--dry-run`, `--json`, `--force`
  map to `Request`;
- unsupported combinations fail clearly.

**Implementation**

- Add CLI parser entries.
- Add text interactive picker first:
  - group by type;
  - show confidence and warnings;
  - let maintainer select/skip;
  - require type choice for ambiguous markdown.
- Curses UI can be a follow-up unless time allows.

**Done when**

- Maintainer can complete a batch import without manually editing JSON.

### WP-I8 - End-to-end fixtures

**Owns:** `tests/fixtures/imports/`, `tests/upstream_import_e2e_test.py`.

**Tests first**

- fixture repo with explicit manifest imports skill, memory, MCP, and creates bundle;
- fixture repo without manifest imports high-confidence artifacts heuristically;
- rerun without changes is idempotent or reports no-op/conflict according to `--force`;
- `aart upstream check --bundle imported-bundle` works after import.

**Implementation**

- Add local fake upstream trees and fake GitHub opener where needed.
- Keep tests offline.

**Done when**

- Import integrates with existing check/update tracking flow.

### WP-I9 - Docs and final verification

**Owns:** `README.md`, `DESIGN-upstream-import.md`, `PLAN-upstream-import.md`.

**Tasks**

- Document quick examples for manifest and heuristic modes.
- Document manifest schema.
- Document conflict and bundle modes.
- Run:
  - focused import tests;
  - `python -m unittest discover -s tests -p "*_test.py"`;
  - `make test && make validate`;
  - `make lint && make typecheck`;
  - `git diff --check`.

**Done when**

- Docs match shipped CLI.
- Full verification passes.

## 6. Parallelization guide

Good subagent splits after WP-I0:

- **Manifest worker:** WP-I2 only. Files: `import_manifest.py`, `tests/import_manifest_test.py`.
- **Heuristic worker:** WP-I3 only. Files: `import_scanner.py`, `tests/import_scanner_test.py`.
- **Planner worker:** WP-I4 and WP-I5 after candidate contract is stable. Files:
  `import_planner.py`, planner tests.
- **CLI worker:** WP-I7 after command request fields are known. Files: `cli.py`,
  `tests/upstream_import_cli_test.py`.
- **Command integrator:** WP-I6 owns `commands/upstream.py` and should integrate completed
  pure helpers.

Workers should not edit overlapping files. If command and CLI work run in parallel, define the
`Request` fields in WP-I0 first so both can target the same contract.

## 7. Suggested MVP cut

The smallest useful ship:

1. `upstream scan URL --json`.
2. `upstream import URL --mode manifest --bundle NAME --dry-run`.
3. `upstream import URL --mode manifest --bundle NAME`.
4. Heuristic scan report.
5. Heuristic import for high-confidence candidates only.

Interactive selection can land after the pure import path is stable. That keeps the first PR
reviewable while still proving both modes.

## 8. Risks

- Markdown classification can surprise maintainers. Mitigation: ambiguous markdown is never
  imported by default.
- Bundle updates can accidentally change curated team sets. Mitigation: default append and
  deterministic dry-run output.
- Name mismatches can create broken catalog entries. Mitigation: parser validation remains
  authoritative.
- Batch imports can be large. Mitigation: scan ignore rules and a future `--max-files` limit.
- Existing `upstream add` behavior must not regress. Mitigation: keep focused regression tests
  for add/check/update in the command gate.
