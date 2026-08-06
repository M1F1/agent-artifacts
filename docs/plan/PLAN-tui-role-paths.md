# agent-artifacts - Implementation plan: User and Maintainer TUI paths

Execution plan for [DESIGN-tui-role-paths.md](../design/DESIGN-tui-role-paths.md) and issue #15.
Each production slice starts with a failing test and finishes with focused green tests before the
next slice begins.

## 1. Establish the baseline and protect scope

- Run the existing unit suite and record a clean baseline.
- Keep the current branch and preserve unrelated user changes.
- Treat #16-#21 as explicit extension points; do not introduce descriptions, result DTOs, scope,
  setup execution, or a partial navigation state machine in this issue.

Quality gate: existing suite is green before production edits.

## 2. Persist catalog subscriptions (TDD, consumer domain)

1. Add failing model/manifest tests for package, local, and GitHub subscription round-trips and
   legacy manifests without the new field.
2. Add failing pure tests for deriving a subscription from a request/source and rebuilding a
   request from a recorded subscription.
3. Implement the frozen `CatalogSubscription` value and pure transformation functions.
4. Add failing update tests for implicit recorded local/GitHub sources, mixed subscription groups,
   explicit source override, and plan-before-mutate failure safety.
5. Refactor update orchestration to group selected entries by subscription and persist refreshed
   source identity without changing planner policy.

DDD boundary: manifest/source identity belongs to the consumer domain; network and filesystem work
remain in the update command shell.

Functional approach: immutable subscription/group values, deterministic partitioning, `Result`
errors, and pure request transformations.

Focused gates: manifest, source, install, update, status, and compatibility tests; Ruff and mypy on
touched modules.

## 3. Add maintainer context, validation, and health (TDD, maintainer domain)

1. Add failing pure tests for catalog-root recognition, empty upstream tracking, artifact counts,
   tracked/untracked partitioning, validation errors, and attention statuses.
2. Implement frozen `MaintainerContext`/`CatalogHealth` values and pure health derivation.
3. Add failing command tests for `upstream validate` and `upstream health`, including human/JSON
   output, absolute root reporting, missing/invalid catalog contexts, and upstream attention.
4. Extend the upstream command shell and CLI parser with the two read-only actions.

DDD boundary: the maintainer domain owns catalog/upstream invariants; GitHub resolution remains
infrastructure supplied to the health query.

Functional approach: parsing produces `Ok`/`Err`; health is a pure projection over catalog,
tracking metadata, validation errors, and immutable statuses.

Focused gates: catalog/upstream command, JSON contract, CLI mapping, planner, and validation tests.

## 4. Add role and maintainer request builders (TDD, application layer)

1. Add failing pure tests for role/action metadata and for add/import/check/update Request builders.
2. Add failing tests for the common mutation protocol: pre-validation, dry-run, confirmation,
   apply, post-validation, and cancellation.
3. Implement small immutable choice values and request transformations in the TUI/application
   layer.
4. Expose a request-based import scan query from the upstream command core so selectors never
   duplicate URL parsing or scanning.

Functional approach: input values transform into new frozen Requests via `dataclasses.replace`;
the protocol accepts injected dispatch/query functions and returns exit codes as values.

Focused gates: pure TUI/request tests and upstream scan/import tests.

## 5. Implement the text frontend test-first

1. Add failing headless tests proving role is the first prompt, role explanations are present,
   and blank/`q`/EOF quit without dispatch.
2. Update existing User tests to include the User role choice and confirm compatibility filtering
   and real command dispatch still work.
3. Add failing Maintainer tests for invalid context, health, validate, add preview/apply, import
   selection plus optional bundle, check all/selected, update preview cancellation/apply, and User
   workflow entry.
4. Implement the text maintainer loop over the shared request builders/protocol.

Quality gate: all headless TUI tests and a real fixture-backed User install are green.

## 6. Implement the curses frontend test-first

1. Add failing tests proving role selection is the first curses screen.
2. Add routing tests for User and Maintainer roles.
3. Implement thin curses input/rendering adapters and reuse the same builders/protocol.
4. Ensure curses exits before command output where necessary and errors remain recoverable inside
   the maintainer menu.

Quality gate: curses integration tests run headlessly with patched stdlib curses boundaries.

## 7. Documentation and acceptance coverage

- Update README/help with the User/Maintainer distinction and consumer-vs-maintainer update source
  semantics.
- Mark only completed #15 items in TODO.md.
- Add/extend an end-to-end maintainer test covering import, check, and update through Request
  dispatch with fake remote resolution.
- Review every issue #15 acceptance criterion against an automated test or a documented manual
  terminal check.

## 8. Final quality gates

Run and require all of the following to pass:

```sh
python -m ruff format agent_artifacts tests scripts
python -m ruff check agent_artifacts tests scripts
python -m ruff format --check agent_artifacts tests scripts
python -m mypy
python -m unittest discover -s tests -p "*_test.py"
bash tests/e2e_test.sh
make validate
git diff --check
```

If a formatter changes files, rerun lint, mypy, unit, E2E, validation, and diff checks on the final
tree. No commit, push, or PR is part of this plan unless requested separately.
