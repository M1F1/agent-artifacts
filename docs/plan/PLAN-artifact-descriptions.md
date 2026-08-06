# Plan: issue #16 — first-class artifact descriptions

Status: completed

Design: `docs/design/DESIGN-artifact-descriptions.md`

## 1. Delivery strategy

Implement in vertical, test-first slices. Each slice starts red, adds the smallest domain/core
change that turns it green, and refactors only while the relevant tests remain green. Catalog
parsing and presentation logic stay pure; filesystem and terminal operations remain at the shell
edge.

The dependency direction is:

```text
descriptor text -> pure parser/validation -> immutable Catalog
                                      |-> list projection -> text/JSON shell
                                      `-> pure Choice projection -> text/curses shell
```

No TUI or command code may reread artifact descriptors.

## 2. Work packages

### WP-1 — Domain invariant and parser contract (TDD)

Red:

- Extend parser tests for all five artifact types and bundles to assert the normalized
  description stored in the returned value.
- Add table-style tests for missing, blank, non-string, CR/LF, Markdown block scalar, and Markdown
  continuation descriptions.
- Assert error messages contain the artifact name and canonical descriptor path.
- Change guideline/memory tests to require description-bearing frontmatter.

Green:

- Add `Artifact.description` without disturbing unrelated manual domain fixtures.
- Add pure description normalization/validation helpers.
- Compose the helpers into skill, guideline, memory, MCP, hook, and bundle parsers.
- Keep compatibility parsing and existing name/mode validation behavior intact.

Refactor gate:

- Run catalog, memory-catalog, compatibility-catalog, and source unit tests.
- Ensure no parser duplicates structural description rules.

### WP-2 — Catalog and fixture migration

Red:

- Add/extend source tests proving all five parsed types and bundles have descriptions.
- Run catalog validation to enumerate missing metadata.

Green:

- Add concise, value-oriented, single-line descriptions to every shipped descriptor and reusable
  catalog fixture, including upstream test catalogs.
- Keep intentionally broken fixtures focused on their documented failure.

Refactor gate:

- Run `make validate`.
- Search catalog-shaped paths for descriptors missing a description.

### WP-3 — Human and JSON list parity (TDD)

Red:

- Assert every human artifact row contains its description.
- Assert every JSON artifact object has the same description as the parsed catalog value.
- Retain bundle JSON/text assertions and cover filtered output.

Green:

- Add the normalized value to the list text row and `_artifact_to_dict` projection.
- Do not add source-file reads in the list command.

Refactor gate:

- Run list command unit tests and a local `aart list --source . --json` smoke check.

### WP-4 — Structured TUI choices and compatibility preservation (TDD)

Red:

- Assert install choices for artifacts and bundles expose `description` separately and render it.
- Assert compatibility-filtered rows retain their descriptions.
- Assert update/uninstall rows show source metadata when the catalog contains it and remain
  selectable without it.

Green:

- Extend immutable `_Choice` with description data.
- Add pure row formatting used by install and manifest choice builders.
- Perform best-effort catalog loading for uninstall while preserving offline manifest behavior.

Refactor gate:

- Run pure TUI choice and text-flow tests.
- Confirm request assembly and dispatch are unchanged.

### WP-5 — One-line curses rendering and full detail (TDD)

Red:

- Add pure boundary tests for ellipsis at width 0, 1, exact fit, and narrow fit.
- Add fake-screen tests proving selector lines never exceed the drawable width and truncation ends
  with `…`.
- Add key-flow coverage for `?` in curses and `?N` in text, verifying full description visibility
  and unchanged selection.

Green:

- Centralize width-aware ellipsis and use it for titles and selector rows.
- Add a wrapped curses detail view for the current choice.
- Add text detail lookup and update prompt help.

Refactor gate:

- Run TUI unit and integration tests, including the existing curses-wrapper mocks.

### WP-6 — Contributor documentation and tracker

- Document required description locations for all artifact shapes.
- Give wording rules: one line, concise, user benefit first, no implementation-only tautology.
- Update JSON/list examples and TUI detail controls.
- Mark issue #16 items complete in `TODO.md` only after their tests and validation pass.

## 3. DDD and functional-programming constraints

- `Artifact`, `Bundle`, `Catalog`, and `_Choice` remain frozen value objects.
- Catalog parsing is the anti-corruption boundary: invalid external text becomes `Err`, never a
  partially valid domain object.
- Pure functions return new values and do not mutate catalog, manifest, selection, or input data.
- Expected validation failures remain values (`Result`); exceptions are reserved for shell-level
  unexpected failures.
- Rendering consumes structured choice fields. Later #18-#21 work must not parse presentation
  strings to recover domain facts.
- I/O stays in `Source`, command printing, and terminal adapters.

## 4. Quality gates

Run gates from narrowest to broadest after implementation:

1. Focused unit tests:

   ```sh
   python -m unittest tests.catalog_test tests.memory_catalog_test \
     tests.compatibility_catalog_test tests.source_test tests.list_test tests.tui_test
   ```

2. Formatting and lint:

   ```sh
   make format
   make format-check
   make lint
   ```

3. Static types:

   ```sh
   make typecheck
   ```

4. Catalog and dependency validation:

   ```sh
   make validate
   ```

5. Full unit suite and end-to-end tests:

   ```sh
   make test
   ```

6. CLI smoke checks:

   ```sh
   python -m agent_artifacts list --source .
   python -m agent_artifacts list --source . --json
   ```

7. Final diff audit:

- No unrelated user files changed.
- No manifest schema or command mutation semantics changed.
- Every issue #16 acceptance criterion maps to a passing test or documentation section.
- The design remains compatible with the structured wizard state planned by #21 and does not
  preimplement unrelated #17-#20 behavior.

## 5. Stop conditions

- Do not weaken description validation to make legacy fixtures pass; migrate valid fixtures.
- Do not make uninstall depend on successful source/network access.
- Do not add a runtime dependency for YAML, wrapping, or terminal rendering.
- Do not mark the tracker complete while any quality gate is red.

## 6. Execution record

Completed on 2026-08-06 on branch `codex/issue-16-artifact-descriptions`.

- TDD slices completed for parser/domain invariants, catalog migration, list text/JSON parity,
  structured TUI choices, narrow-terminal rendering, and full-detail navigation.
- DDD boundary retained: parsed catalog values are immutable and invalid external metadata becomes
  `Err` before a `Catalog` is built.
- Functional core retained: normalization, choice projection, label construction, and ellipsis are
  pure; filesystem, printing, and terminal input remain in the shell.
- `make format-check`: 106 files already formatted.
- `make lint`: Ruff passed with no findings.
- `make typecheck`: mypy passed with no issues in 44 source files.
- `make validate`: catalog integrity and standard-library-only import gate passed.
- `make test`: 660 unit tests and the complete 11-step bash end-to-end flow passed.
- CLI smoke checks for human and JSON `list --source .` passed and exposed matching descriptions.
- Final `git diff --check` and code-review audit found no unresolved correctness, style, security,
  performance, or test-coverage findings.
