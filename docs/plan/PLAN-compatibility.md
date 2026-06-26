# agent-artifacts - Implementation Plan: per-artifact profile compatibility

Companion to [../design/DESIGN-compatibility.md](../design/DESIGN-compatibility.md) and GitHub issue
[#6](https://github.com/M1F1/agent-artifacts/issues/6).

This plan is TDD-first and DDD-first. The first work package freezes the domain language and
pure compatibility contract before command code grows behavior around it. After that gate,
work can split across parser/model, install planning, update/list behavior, and docs/fixtures.

## 1. Target behavior

Artifacts may optionally declare an explicit profile allow-list:

```json
{
  "name": "postgres",
  "compatibility": {
    "profiles": ["tabnine"]
  },
  "server": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"]
  }
}
```

Markdown/frontmatter artifacts use the same conceptual field through a flat dotted key:

```markdown
---
name: code-review
description: Review code changes for correctness.
compatibility.profiles: claude, tabnine
---
```

Behavior:

- No metadata means existing behavior.
- Explicit incompatible install/update fails with usage exit code `2`.
- Bundle and `--all` install skip incompatible artifact/profile targets and report why.
- Broad update skips incompatible installed entries and leaves them untouched.
- Dry-run and JSON output include machine-readable skip/rejection reasons.

## 2. Domain contract gate

Land this first, then fan out.

```python
@dataclass(frozen=True, slots=True)
class Compatibility:
    profiles: Tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    ok: bool
    reason: Optional[str] = None
    allowed_profiles: Tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class SkippedTarget:
    artifact: str
    type: ArtifactType
    profile: str
    reason: str
    allowed_profiles: Tuple[str, ...] = ()
```

Extend `Artifact`:

```python
@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType
    name: str
    root: str
    compatibility: Optional[Compatibility] = None
```

Pure helpers should live in a small module such as `agent_artifacts/compatibility.py`:

```python
def parse_profile_allow_list(value: object) -> Result[Tuple[str, ...]]:
    ...

def compatibility_from_json(data: Mapping[str, object], label: str) -> Result[Optional[Compatibility]]:
    ...

def compatibility_from_frontmatter(fields: Mapping[str, str], label: str) -> Result[Optional[Compatibility]]:
    ...

def check_profile_compatibility(artifact: Artifact, profile_name: str) -> CompatibilityDecision:
    ...
```

This keeps parsing and command policy out of the model and makes all compatibility behavior
unit-testable without filesystem or network access.

## 3. Parallelization shape

**Sequential bootstrap**

- Add the model fields and `compatibility.py` helper API with tests.
- Update existing construction sites to pass or default `compatibility=None`.
- Keep the current suite green before delegating.

**Parallel workers after bootstrap**

- Worker A owns artifact parsing and catalog metadata.
- Worker B owns install selection, dry-run, JSON skips, and manifest-safe planning.
- Worker C owns update/list/status visibility and command JSON consistency.
- Worker D owns fixtures, README, and final integration tests.

Workers B and C can write tests early against the helper API, but final green depends on Worker
A producing compatibility metadata on `Artifact`.

## 4. Work packages

### WP-C1 - Domain compatibility contract

**Wave:** blocking bootstrap  
**Owns:**

- `agent_artifacts/model.py`
- new `agent_artifacts/compatibility.py`
- new `tests/compatibility_test.py`

**Tests first**

- `check_profile_compatibility` returns ok for unrestricted artifacts.
- It returns ok when the target profile is in the allow-list.
- It returns `reason == "incompatible-profile"` and allowed profiles when excluded.
- Profile list parsing de-duplicates while preserving order.
- Empty lists, non-string values, and invalid profile names return `Err`.
- Existing `Artifact(...)` call sites continue to work through the default field.

**Implementation**

- Add `Compatibility`, `CompatibilityDecision`, and `SkippedTarget` domain records.
- Extend `Artifact` with `compatibility: Optional[Compatibility] = None`.
- Implement the pure helper functions.
- Keep helper functions free of filesystem, profile loader, or command imports.

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "compatibility_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -v
```

### WP-C2 - Parse compatibility from every artifact package

**Wave:** parallel after WP-C1  
**Owns:**

- `agent_artifacts/catalog.py`
- `agent_artifacts/source.py` only if scanner comments need metadata wording
- `tests/catalog_test.py`
- `tests/content_test.py`
- optional new `tests/compatibility_catalog_test.py`

**Tests first**

- Skill `SKILL.md` frontmatter with `compatibility.profiles` produces
  `Artifact.compatibility`.
- Guideline and memory markdown frontmatter do the same.
- MCP JSON descriptor with nested `compatibility.profiles` produces compatibility.
- Hook `hook.json` descriptor does the same while keeping the artifact root as
  `hooks/<name>`.
- Invalid compatibility metadata is reported with the artifact label.
- Existing artifacts without metadata still parse exactly as before.
- Directory packages remain directory packages: skill and hook roots do not become descriptor
  file paths.

**Implementation**

- Call `compatibility_from_frontmatter` in `parse_skill`, `parse_guideline`, and
  `parse_memory`.
- Call `compatibility_from_json` in `parse_mcp` and `parse_hook`.
- Preserve all current name/required-key validations.
- Add content validation for canonical examples if fixtures include compatibility.

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "catalog_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "compatibility_catalog_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "content_test.py" -v
```

### WP-C3 - Install compatibility filtering and JSON skips

**Wave:** parallel after WP-C1, final integration after WP-C2  
**Owns:**

- `agent_artifacts/commands/install.py`
- `agent_artifacts/executor.py` only if dry-run JSON wrapper helpers belong there
- `tests/install_test.py`
- optional new `tests/compatibility_install_test.py`

**Tests first**

- Explicit incompatible install by name returns exit code `2` and prints a clear error.
- Explicit compatible install succeeds.
- `--bundle` skips incompatible targets, succeeds, and installs compatible targets.
- `--all` skips incompatible targets, succeeds, and installs compatible targets.
- Multi-profile install can install one target and skip another for the same artifact.
- Human dry-run includes skip warnings and writes nothing.
- JSON dry-run includes structured `skipped` entries with:
  - `artifact`
  - `type`
  - `profile`
  - `reason`
  - `allowed_profiles`
- Normal `--json` install output includes `skipped` and keeps existing `installed` fields.
- Artifacts without compatibility metadata preserve the current JSON and install behavior.

**Implementation**

- Add a small target partition step after type-support filtering:
  - kept targets
  - explicit compatibility errors
  - broad compatibility skips
- Use the same explicit-vs-broad distinction as unsupported type handling.
- Add structured skip objects to JSON output.
- For dry-run JSON, return an object with `actions` plus `skipped` if skips exist. Preserve the
  bare action array when there are no skips if practical.
- Keep the pure planners unaware of CLI selection provenance; compatibility selection belongs
  in command orchestration.

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "compatibility_install_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "install_test.py" -v
```

### WP-C4 - Update compatibility behavior

**Wave:** parallel after WP-C1, final integration after WP-C2  
**Owns:**

- `agent_artifacts/commands/update.py`
- `tests/update_test.py`
- optional new `tests/compatibility_update_test.py`

**Tests first**

- `aart update NAME` fails with usage code `2` when the current source makes that installed
  artifact incompatible with its installed profile.
- Broad `aart update` skips incompatible installed entries, reports structured `skipped`, and
  leaves their files and manifest entries unchanged.
- Compatible installed entries still update normally.
- `--dry-run --json` reports skipped entries without touching files.
- `--force` does not override compatibility. It only controls file/merge conflicts.
- `--prune` does not remove incompatible entries automatically.

**Implementation**

- During desired-plan reconstruction, check each selected manifest entry against the current
  source artifact's compatibility before adding it to `targets`.
- Preserve skipped entries in the manifest.
- Return usage only for explicitly named incompatible update targets.
- Add `skipped` to update JSON output and human warnings.

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "compatibility_update_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "update_test.py" -v
```

### WP-C5 - List and catalog visibility

**Wave:** parallel after WP-C2  
**Owns:**

- `agent_artifacts/commands/list.py`
- `tests/list_test.py`
- optional new `tests/compatibility_list_test.py`

**Tests first**

- `aart list --json` includes `compatibility.profiles` for restricted artifacts.
- Unrestricted artifacts either omit `compatibility` or set it to `null`, with one behavior
  chosen and tested.
- `aart list --type mcp --json` preserves compatibility metadata.
- Human list output remains concise and backward-compatible.

**Implementation**

- Serialize `Artifact.compatibility` in JSON list rows.
- Avoid making human output noisy in v1.

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "compatibility_list_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "list_test.py" -v
```

### WP-C6 - Fixtures and documentation

**Wave:** parallel after WP-C2  
**Owns:**

- `tests/fixtures/`
- `tests/fixtures/bundles/`
- `README.md`
- `../design/DESIGN.md` only if adding a short pointer to the focused design
- `../design/DESIGN-compatibility.md`
- `PLAN-compatibility.md`

**Tests first**

- Add fixture assertions that at least one profile-specific MCP or hook parses.
- Add a fixture bundle containing a profile-specific artifact so install skip behavior is
  exercised from a real source tree.

**Implementation**

- Add one canonical compatibility fixture:
  - recommended: `mcp/tabnine-postgres.json` with
    `"compatibility": {"profiles": ["tabnine"]}`, or keep `postgres` unrestricted and add a
    new restricted descriptor to avoid changing broad existing tests too much.
- Optionally add a Claude-only hook fixture if command tests need a directory package example.
- Document:
  - JSON descriptor shape
  - Markdown frontmatter dotted key
  - explicit install failure
  - bundle/`--all` skip behavior
  - update behavior

**Done when**

```sh
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "content_test.py" -v
PYTHONPATH=$(pwd) python -m unittest discover -s tests -p "install_test.py" -v
```

### WP-C7 - End-to-end integration gate

**Wave:** final  
**Owns:**

- `tests/e2e_test.py`
- any final cross-file cleanup

**Tests first**

- End-to-end install from local `--source`:
  - restricted artifact by explicit incompatible profile fails.
  - restricted artifact through bundle skips incompatible target and installs compatible target.
  - JSON and dry-run JSON expose `skipped`.
- End-to-end update:
  - broad update skips a now-incompatible installed entry.
  - explicit update fails.
- Directory package regression:
  - a restricted skill or hook still copies its full tree when compatible.

**Implementation**

- Resolve integration mismatches between worker branches.
- Keep output wording consistent across install and update.
- Confirm docs match the shipped behavior.

**Required verification**

```sh
PYTHONPATH=$(pwd) make test
PYTHONPATH=$(pwd) make validate
PYTHONPATH=$(pwd) make lint
PYTHONPATH=$(pwd) make typecheck
```

## 5. Suggested sub-agent dispatch

After WP-C1 lands, dispatch up to four workers:

- **Worker A - parser and catalog contract**
  - Files: `agent_artifacts/catalog.py`, parser-focused tests.
  - Deliverable: every artifact packaging format can produce `Artifact.compatibility`.

- **Worker B - install policy**
  - Files: `agent_artifacts/commands/install.py`, install compatibility tests.
  - Deliverable: explicit errors, broad skips, dry-run/JSON structured skip output.

- **Worker C - update/list surface**
  - Files: `agent_artifacts/commands/update.py`, `agent_artifacts/commands/list.py`,
    update/list compatibility tests.
  - Deliverable: update validates compatibility and list exposes metadata.

- **Worker D - fixtures/docs/e2e**
  - Files: `tests/fixtures/`, `README.md`, `tests/e2e_test.py`.
  - Deliverable: realistic restricted artifacts and end-to-end proof.

The integrating agent should review all output shapes, normalize reason strings, and run the
full verification suite.

## 6. Critical path

`WP-C1 -> WP-C2 -> WP-C3/WP-C4 -> WP-C7`

WP-C5 and WP-C6 can run beside command work once WP-C2 exposes metadata. If staffing is limited,
do the path above first and fold list/docs afterward.

## 7. Risks and guardrails

- **Dry-run JSON shape.** Existing dry-run JSON is a bare action array. Adding structured skips
  may need a wrapper object. Prefer preserving the array when no skips exist.
- **Custom profiles.** Do not reject unknown-but-valid profile names during catalog validation.
  Compatibility is evaluated against the actual selected profile at command time.
- **Force semantics.** `--force` must not bypass compatibility. It only resolves file and merge
  conflicts.
- **Directory artifacts.** Do not accidentally narrow skills/hooks to descriptor files. The
  compatible unit is the whole directory package.
- **Unsupported type vs incompatible profile.** Keep reason strings distinct:
  - `unsupported-type`
  - `incompatible-profile`
- **Manifest stability.** Existing manifests do not store compatibility and do not need
  migration.

## 8. Definition of done

- All acceptance criteria from issue #6 are covered by tests.
- Existing unrestricted artifacts behave exactly as before.
- JSON output includes machine-readable reasons for compatibility skips/rejections.
- Docs show both JSON descriptor and Markdown frontmatter syntax.
- The full local suite, validation, lint, and typecheck pass.
