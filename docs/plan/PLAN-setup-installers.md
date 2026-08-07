# Plan: issue #20 — reviewed queued macOS setup installers

Status: completed

Design: `docs/design/DESIGN-setup-installers.md`

## 1. Delivery strategy

Deliver test-first vertical slices. Each work package starts with failing domain/security or
lifecycle tests, implements the smallest coherent behavior, and refactors only while its focused
suite remains green. The functional core produces immutable installer/plan/result/state values;
terminal, subprocess, Keychain, Docker, clock, platform, and filesystem effects remain injected
adapters.

## 2. Work packages

### WP-1 — Static installer domain and catalog validation (TDD)

Red:

- Parse the canonical version-1 recipe into frozen records.
- Reject unknown schema/protocol/module versions, fields, platforms, capabilities, identifiers,
  non-HTTPS URLs, missing secret inputs, unpinned Docker images, secret interpolation, path
  traversal, and custom entrypoints outside `setup/`.
- Discover setup for skill/hook/directory-MCP packages and reject it for flat artifacts.
- Bind recipe/custom hashes and the exact artifact `TYPE/NAME`.
- Validate the representative Atlassian recipe and optional custom template.

Green:

- Add immutable setup records to `model.py` and optional `Artifact.setup`.
- Add pure parser/schema/module validation in `setup.py`.
- Attach validated recipes in `Source` without executing custom code.
- Extend catalog/content validation and packaging fixtures.

Refactor gate:

- Catalog/source/content/setup parser tests, Ruff, mypy, `make validate`.

### WP-2 — Pure planning, review, queue, and state (TDD)

Red:

- Derive ordered artifact/profile/scope queue items from selected choices with stable de-duplication.
- Resolve exact fake-home/profile effects without environment reads.
- Require declared capabilities and prerequisites; compute deterministic plan hashes.
- Render artifact, source, path, hash, URLs, effects, commands, and reversibility without secrets.
- Fold configured/failed/cancelled/skipped/unsupported states and mark unstarted items skipped on
  Stop.
- Round-trip separate scope-specific state with multi-harness keys and reject any secret-shaped
  field/output.

Green:

- Add pure queue/planner/hash/review/redaction functions.
- Add `setup-state.json` parser/dumper and scope-root routing.
- Add setup outcome projections and retry/rollback command builders.

Refactor gate:

- Planner/state/outcome tests plus issue #19 scope/manifest regressions.

### WP-3 — Transactional shared module runtime (TDD)

Red:

- `macos-keychain.store`: no secret argv/env/output/state; existence verification; new-item
  rollback; explicit replacement consent.
- managed shell/file blocks: exact marker ownership, atomic/idempotent updates, symlink rejection,
  mode preservation, later unrelated edit preservation, safe rollback.
- managed JSON: preserve foreign keys, no duplicate, collision consent, ownership-safe rollback.
- directory: created/no-op and empty-owned rollback.
- Docker: digest required, inspect-before-pull, exact command review, missing prerequisite,
  consent, no pre-existing-image removal, manual recovery.
- command verification: argv only, minimal environment, controlled cwd, timeout, capped/redacted
  output.
- failure/cancellation after each mutation boundary rolls back only the current item; incomplete
  rollback is explicit.

Green:

- Add adapter protocols and production stdlib performers in `setup_runtime.py`.
- Keep transforms and rollback decisions pure; centralize the imperative transaction loop.
- Use `/usr/bin/security ... -w` with value-less final `-w` in production.

Refactor gate:

- Fake Keychain/Docker/process/filesystem unit tests and synthetic-secret scan of every observable
  channel.

### WP-4 — Custom entrypoint protocol (TDD)

Red:

- Validate and hash a script inside the reviewed package.
- Run `plan/apply/verify/rollback` as argv with `shell=False`, controlled `0700` run directory,
  minimal allowlisted environment, and capped/redacted output.
- Reject hash drift, malformed/non-secret result JSON, plan mutation of the controlled directory,
  missing terminal status, timeout, and unapproved capabilities.
- Demonstrate foreground success, failure, cancellation, retry, idempotency, and rollback using
  fake installers.

Green:

- Add the custom adapter and protocol-result parser.
- Bind apply to source/script/plan hashes and store only the validated receipt.

Refactor gate:

- Custom protocol/security tests plus no-shell/no-broad-env source inspection.

### WP-5 — CLI runner and recovery (TDD)

Red:

- Parse `setup run|retry|status|rollback` with profile/scope/source selectors.
- Reject ambiguous user/project and invalid selection before I/O.
- Resolve only installed manifest entries and their recorded subscriptions.
- Run sequentially; continue after normal failure/cancel; Stop marks remaining items skipped.
- Persist after every terminal item; status remains local-only.
- Return retry commands and distinct configured/already/incomplete outcomes in human and JSON.
- Non-Darwin records unsupported and never touches Keychain/process/files.

Green:

- Add `commands/setup.py`, CLI parser/dispatch, application service, state persistence, and
  structured setup outcomes.

Refactor gate:

- CLI rules/parser/command/state tests with fake platform/home/source/adapters.

### WP-6 — TUI queue and #21 review seam (TDD)

Red:

- Install confirmation lists ordered setup-capable artifact/profile rows before Finalize.
- No setup runs if core install fails/cancels or confirmation is declined.
- After core success, text and curses (after wrapper teardown) call the same queue runner once.
- Every entry becomes terminal; continue/stop behavior is visible.
- Final summary separates installed/configured/incomplete and prints safe retry commands.
- Retry prompt is preselected and reruns only incomplete entries.

Green:

- Extend immutable Install confirmation with setup queue facts.
- Add shared post-dispatch orchestration outside rendering/curses code.
- Preserve a small immutable queue projection for #21's future basket Review.

Refactor gate:

- Text/curses/install-mode/scope/outcome integration tests and exactly-once dispatch assertions.

### WP-7 — Authoring skill, examples, documentation, and E2E

- Add `skills/author-aart-installer/` with `SKILL.md`, canonical assets, contract/module references,
  deterministic schema validator, and fake-adapter test workflow.
- Add a representative Atlassian token-mode test fixture using the current official credential
  URL, Keychain storage, managed shell lookup, verification, and restart notice. Recommend OAuth
  first; do not invent Docker for the official remote service.
- Add a separate pinned-image Docker fixture/test.
- Update README/CLI help with trust model, queue, commands, retry/rollback, Keychain/environment
  limitations, and `SETUP.md`'s reference role.
- Check #20 in `TODO.md` only after every gate passes.

## 3. DDD and functional-programming constraints

- Installer, inputs, steps, capabilities, queue items, effects, plans, receipts, results, and state
  are frozen values.
- Parser/planner/queue/state/managed-content functions are total, deterministic, and side-effect
  free; expected invalid states use `Err` values.
- One item is one transaction aggregate; queue orchestration never rolls back a prior item.
- TUI/CLI use one application service and structured result; neither parses prose output.
- Runtime modules own operations; custom scripts never reimplement shared Keychain/file/JSON/
  Docker helpers in shipped examples.
- Stable ordering applies to selections, profiles, steps, effects, state, receipts, summaries, and
  retry commands.
- Runtime remains Python-stdlib-only.

## 4. Security gates

- Synthetic canary secrets are searched in argv captures, environment snapshots, stdout/stderr,
  exceptions, JSON, state, receipts, backups, plans, and logs.
- No source code path calls subprocess with `shell=True` or a string command.
- Production Keychain argv has value-less final `-w`; verification never requests password output.
- File/JSON adapters reject symlinks/path traversal and preserve unrelated content/edits.
- Docker references are digest-pinned and missing Docker is non-mutating.
- Custom source/script/plan hashes are rechecked immediately before apply.
- Non-Darwin execution is rejected before effect adapters.
- Every test home/state/source/run directory is temporary; real Keychain, Docker, shell config,
  harness config, and user home are never mutated.

## 5. Quality gates

Run narrowest to broadest:

1. Setup parser/planner/state:

   ```sh
   python -m unittest tests.setup_catalog_test tests.setup_plan_test tests.setup_state_test
   ```

2. Runtime/security/custom protocol:

   ```sh
   python -m unittest tests.setup_runtime_test tests.setup_custom_test tests.setup_security_test
   ```

3. CLI/TUI/E2E:

   ```sh
   python -m unittest tests.setup_command_test tests.tui_setup_test tests.setup_e2e_test
   ```

4. Related regressions:

   ```sh
   python -m unittest tests.install_scope_test tests.install_test tests.update_test \
     tests.uninstall_test tests.tui_test tests.tui_scope_test tests.tui_install_mode_test
   ```

5. Formatting/lint/static/catalog:

   ```sh
   make format
   make format-check
   make lint
   make typecheck
   make validate
   ```

6. Complete unit and shell E2E:

   ```sh
   make test
   ```

7. Final code-review audit:

- Map every issue criterion and owner-comment addition to code/test/doc evidence.
- Inspect all secret channels, source trust/hash binding, transaction boundaries, and rollback
  ownership.
- Confirm #21 can consume immutable setup queue facts without reworking the runner.
- Confirm unrelated untracked user files remain untouched and unstaged.

## 6. Stop conditions

- Do not execute custom code during discovery, parsing, list, or flag-mode artifact install.
- Do not pass or serialize a credential.
- Do not mutate before review/consent or outside declared effects.
- Do not leave an unstarted queue item without `skipped` after Stop.
- Do not claim rollback for an effect that cannot be safely compensated.
- Do not use real Keychain/Docker/home in tests.
- Do not implement #21's full wizard/back stack in this issue.
- Do not mark #20 complete while a security or quality gate is red.

## 7. Execution record

Completed on 2026-08-06 on branch `codex/issue-20-macos-setup`.

- Delivered WP-1 through WP-7 as test-first slices: strict static recipes, immutable plans and
  state, shared transactional modules, hash-bound custom protocol, CLI/TUI queue integration,
  recovery commands, authoring skill, Atlassian example, and documentation.
- Preserved the DDD boundary around one setup item as one transaction aggregate. Pure parsing,
  planning, state, redaction, and managed-content transforms remain separate from injected
  filesystem, terminal, platform, Keychain, Docker, and process adapters.
- The final code-review audit fixed source symlink escapes, sparse-retry cross-products, unsafe
  rollback receipt trust, JSON/Keychain replacement reversibility claims, early rollback
  short-circuiting, custom-protocol compensation failures, ownership receipt loss on idempotent
  reruns, and post-apply persistence failures.
- Focused setup parser/planner/runtime/security/CLI/TUI/E2E suite: 44 passed.
- Full unit suite: 772 passed.
- Shell E2E: all 11 onboarding/update/uninstall steps passed.
- Ruff format check: 127 intended Python files already formatted.
- Ruff lint: all checks passed for source, tests, tracked build scripts, and the installer-author
  validator (the unrelated untracked demo script was deliberately excluded).
- Mypy: success across 50 source files.
- Catalog and standard-library-only validation: passed.
- No real Keychain, Docker, home, harness configuration, or credential was used by tests.
