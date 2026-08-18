# Plan: issue #19 — project and user installation scopes

Status: completed

Design: `docs/design/DESIGN-install-scope.md`

## 1. Delivery strategy

Execute test-first vertical slices. Each work package starts with a failing domain or lifecycle
test, implements the smallest complete behavior, then refactors while focused tests remain green.
Scope decisions remain immutable and pure; filesystem/network/terminal work stays at the shell.

## 2. Work packages

### WP-1 — Scope and profile domain (TDD)

Red:

- Test `Request.scope` defaults to project and accepts user with an injected temporary home.
- Test pure `profile_for_scope` keeps project targets unchanged and expands every user target to
  an absolute path beneath the supplied home.
- Test all built-ins have a target or explicit one-line reason for every user artifact type.
- Assert the target matrix exactly, including Tabnine's company-build `settings.json` MCP file and
  Vibe's JSON/TOML limitations.
- Test custom profile `user` records, malformed unsupported reasons, and the generic fallback for
  intentionally omitted reasons.

Green:

- Add `InstallScope`, `ProfileTargets`, scoped profile data, and pure target/path helpers.
- Populate the four built-ins with the documented user matrix.
- Extend the profile loader without changing existing flat project-profile files.

Refactor gate:

- Run model/profile/loader tests, Ruff, and mypy.

### WP-2 — Scope-specific state and CLI validation (TDD)

Red:

- Test project and user manifest paths are distinct and user state uses only the fake home.
- Test status/check/update/uninstall load only the selected scope.
- Test parser defaults every scoped command to project and maps explicit user scope.
- Test `--scope user --project` returns usage 2 before source open or mutation.

Green:

- Add the shared `--scope` parser option to install/status/check/update/uninstall.
- Add the semantic flag rule.
- Introduce `user_root`, `manifest_root`, and request-based `save_manifest` routing.
- Keep absolute effects intact through rebasing/status/update/uninstall helpers.

Refactor gate:

- Run CLI rules/parser, manifest, status, check, update, and uninstall tests.

### WP-3 — User-scope install lifecycle (TDD)

Red:

- Install supported copy and merge artifacts for every harness into a fake home and inspect exact
  destinations and manifest proofs.
- Test explicit unsupported user combinations return usage 2 with the declared reason.
- Test broad bundle/all selection skips unsupported targets without blocking supported ones.
- Install one artifact for multiple harnesses and prove manifest entries/effects do not overwrite.
- Exercise symlink mode in fake home and prove update/uninstall preserve the source target.
- Assert serialized state includes harness, resolved paths, subscription/mode/effects and excludes
  descriptor secrets.

Green:

- Resolve selected profiles for the request scope before planners run.
- Use the scope effect/state roots in install/update/uninstall orchestration.
- Thread declared unsupported reasons into structured skip/error messages.
- Preserve existing planner and executor action algebra.

Refactor gate:

- Run install, compatibility, symlink, subscription, update, uninstall, and manifest tests.

### WP-4 — Scope-aware TUI and confirmation (TDD)

Red:

- Test text/curses sequence `Harness -> Action -> Scope` for install/update/uninstall and Status.
- Test Project is first/recommended/default and scope reaches the dispatched `Request`.
- Test source/manifest/choice loading happens after scope selection.
- Test unsupported user artifact rows/bundles are hidden or disabled with a reason.
- Test user Install confirmation lists de-duplicated absolute destinations.
- Test decline/quit makes no mutation and accept dispatches once after curses teardown.

Green:

- Add frozen scope choices and text/curses scope selectors.
- Project profiles through the shared scope resolver before choice construction.
- Add Status to the user action menu and dispatch it after scope selection.
- Extend immutable Install confirmation with scope and resolved destinations.
- Thread `scope` and internal `user_home` through all TUI request seams.

Refactor gate:

- Run TUI role, profile, install-mode, input, request, curses, confirmation, and outcome tests.

### WP-5 — Documentation and regression/E2E

- Update README and CLI help with project default, harness-native precedence, supported matrix,
  unsupported behavior, state path, and install/status/update/uninstall examples.
- Update `TODO.md` #19 only after every acceptance test passes.
- Run paired fake project/home E2E: install -> status -> update -> uninstall in each scope, proving
  the other scope remains unchanged.
- Run multi-harness fake-home E2E and a user-scope Symlink lifecycle.
- Record evidence and change design/plan status only after all gates pass.

## 3. DDD and functional-programming constraints

- Scope, target sets, support decisions, confirmation facts, and destination lists are frozen data.
- Profile projection and path/destination transformations are pure, deterministic functions.
- No planner reads environment/home or branches on UI state.
- No TUI code writes a manifest or harness file; it builds a `Request` and dispatches once.
- Expected unsupported/invalid combinations use `Err`/structured skips, not exceptions.
- Preserve stable ordering across profiles, artifacts, effects, destinations, and manifests.
- Keep the runtime zero-dependency; do not add a TOML writer under this issue.

## 4. Quality gates

Run narrowest to broadest:

1. Focused scope tests:

   ```sh
   python -m unittest tests.install_scope_test tests.cli_rules_test tests.tui_scope_test
   ```

2. Related regressions:

   ```sh
   python -m unittest tests.install_test tests.status_test tests.check_test \
     tests.update_test tests.uninstall_test tests.symlink_install_test \
     tests.tui_test tests.tui_install_mode_test tests.memory_profiles_test
   ```

3. Formatting and lint:

   ```sh
   make format
   make format-check
   make lint
   ```

4. Static types and validation:

   ```sh
   make typecheck
   make validate
   ```

5. Full unit and shell E2E:

   ```sh
   make test
   ```

6. Final code-review audit:

- Map every #19 acceptance criterion to a focused or lifecycle test.
- Confirm tests never resolve a user target outside their temporary home.
- Confirm the literal project default remains byte/behavior compatible.
- Confirm user state serializes no descriptor content, environment value, or credential.
- Confirm unrelated untracked user files remain untouched and unstaged.

## 5. Stop conditions

- Do not derive user paths by prefixing current project targets.
- Do not mutate a real user harness path in any test or smoke run.
- Do not accept `--scope user --project` or save user state under a project.
- Do not silently install an unsupported harness/type/scope combination.
- Do not make user scope the default.
- Do not implement TOML merges, setup installers, or full wizard state.
- Do not mark #19 complete while any quality gate is red.

## 6. Execution record

- Implemented WP-1 through WP-4 test-first with dedicated scope domain/lifecycle and text/curses
  TUI suites. Every user-scope filesystem test injects a temporary home.
- Added project/user state isolation, the exact built-in support matrix, early validation at CLI
  and command boundaries, absolute confirmation destinations, and scope-aware install, status,
  check, update, uninstall, Copy, and Symlink paths.
- Code review found and fixed an unsafe lifecycle gap in list-merge proofs: hook uninstall now
  records the reviewed matcher/command identity, removes only its registration, and preserves
  foreign hooks. The reviewed hook fixture now resolves to the copied `scripts/guard.py` file.
- Focused scope/CLI/TUI tests: 39 passed after the command-boundary audit.
- Related planner/install/uninstall regression slice: 60 passed after the hook proof fix.
- Full unit suite: 728 passed.
- Shell E2E: all 11 onboarding/update/uninstall steps passed, including clean hook merge reversal.
- Ruff format check: all changed implementation/test Python files already formatted.
- Ruff lint: all checks passed (tracked scripts only; the unrelated untracked demo script was
  deliberately excluded).
- Mypy: success across 47 source files.
- Catalog and stdlib-only validation: passed.
- `git diff --check`: passed; unrelated untracked user files were neither edited nor staged.
