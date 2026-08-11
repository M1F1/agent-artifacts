# Plan: post-v1 catalog boundary and agent onboarding

- **Status:** active follow-up to `v1.0.0`; not a rewrite of the frozen release evidence
- **Working branch:** `codex/remove-legacy-root-catalog`
- **Primary outcome:** the AART executable is a code/tooling repository, while installable
  artifacts and agent guidance live in versioned registries.

## Guardrails

- Do not alter the immutable `v1.0.0` tag, schema freeze, release receipt, or generated release
  evidence. Decide the next executable version before publishing any of this work.
- Preserve the legacy importer and fixtures: AART still imports compatible foreign legacy
  checkouts, but it no longer ships one at its own repository root.
- Keep the interface split explicit: CLI with structured JSON is the automation/agent surface;
  the TUI is the guided human surface. Do not silently redirect legacy commands to a new lifecycle.
- Every source is parsed, policy-checked, freshly synchronized, and validated before configuration
  is written. Never log credentials or make a browse command publish objects.
- The current read/revalidate/write sequence is not a compare-and-swap transaction. Keep its
  remaining concurrent-writer risk explicit in `CFG02`; do not describe this branch as providing
  full configuration-write isolation.
- Create or link a new post-1.0 GitHub issue before opening the CB01 review PR; the released #27
  remains historical tracking and must not be reopened for this scope.

## Delivery sequence

### CB01.A — remove the embedded operational catalog

**Status:** implemented in the current branch; focused tests and the full local quality matrix pass.

1. Delete only the six root operational trees: `skills/`, `guidelines/`, `mcp/`, `hooks/`,
   `memory/`, and `bundles/`; retain test fixtures and legacy importer code.
2. Retire the one-time exporter that rebuilt a registry from this checkout and its bootstrap-only
   tests. Point documentation at independently maintained canonical registries.
3. Add a repository-boundary validation gate so the six trees cannot return unnoticed.
4. Remove the TUI's implicit `bundled-legacy`/package-checkout fallback. A first run must show the
   real empty Sources stage, while explicit `--source`/`--repo` compatibility paths remain inert.
5. Acceptance tests:
   - a fresh CLI/TUI invocation does not inspect the executable checkout as content;
   - a wheel contains only tool code and approved tool resources, never operational artifact
     content;
   - root catalog restoration is rejected by validation;
   - legacy external-checkout importer fixtures still pass.

### CB01.B — source onboarding that is safe for both agents and people

**Status:** implemented in the current branch; the required-policy edge case is covered and the
full local quality matrix passes after final review corrections.

1. Keep `SourceAdditionRequest` separate from toggle-only source management.
2. Retain strict source input parsing and fresh-sync-before-save semantics for:
   `aart source add`, `aart source list`, and TUI Add.
3. Finish the missing-required-sources policy model:
   - permit a configuration-management/onboarding operation to persist one policy-allowed required
     source at a time;
   - keep all content operations fail-closed until *every* required source is enabled;
   - do not relax Git-host, direct-source, reporting, or other policy checks;
   - make a partially configured policy state reloadable only for source management/recovery, not
     marketplace/install/update/setup operations.
4. Acceptance tests:
   - a policy requiring `a` and `b` lets an agent or person add `a`, then `b`;
   - no content command succeeds after only `a` is configured;
   - invalid/corrupt configuration cannot be overwritten;
   - a policy/configuration change during sync prevents the write.
   - a hand-authored configuration cannot bind one Git origin to two refs while the v1 source
     store remains origin-keyed, including equivalent HTTPS/SSH/SCP spellings;
   - an empty required-policy Sources screen still offers Add, Back, and Quit in curses.
   - a safe `refs/heads/<branch>` source ref resolves from the managed remote-tracking branch.

### CB01.C — explicit read-only agent discovery

**Status:** implemented in the current branch; focused tests and the full local quality matrix pass.

1. Keep `aart marketplace list --json` as the canonical agent browse contract.
2. Build the catalog from durable validated snapshots without Git fetches, config writes, or CAS
   object publication; nevertheless verify every native and registry-owned package digest against
   committed evidence.
3. Acceptance tests cover native and registry sources, including an assertion that no object path
   appears after a list operation.

### LIFE02 — canonical non-interactive lifecycle

**Status:** planned; do not fold into CB01 without a separate reviewable task.

1. Add qualified, JSON-first `aart marketplace install`, `update`, `uninstall`, `status`, and
   `setup` commands over the existing canonical application services.
2. Require source-qualified coordinates or deterministic ambiguity diagnostics. Preserve
   Copy/Symlink, project/user scope, trust, security, setup, and offline gates from the TUI.
3. Keep `list/install/update/setup --source/--repo` visibly documented as legacy adapters until a
   separately approved deprecation path exists.
4. Add real temporary-home/project E2E coverage for Copy, managed Symlink, update/no-op,
   uninstall, setup retry, and JSON diagnostics.

### SRC02 — source-store identifier migration and maintenance commands

**Status:** planned.

1. The current source store is intentionally origin-keyed for backward compatibility. Keep the
   onboarding UI/CLI from configuring one Git origin at multiple refs until a versioned
   ref-aware store migration/rebind path exists; otherwise two refs could share a pointer.
2. Design and implement that migration before changing the identity algorithm, including recovery
   for existing pointers and an explicit ambiguity diagnostic for legacy multi-ref configurations.
3. Add explicit `aart source sync`, `health`, and `doctor` commands rather than asking users to
   re-add an existing alias. They must never change source identity or policy defaults implicitly.
4. Test old-pointer discovery/migration, multi-ref isolation, stale/offline results, lock recovery,
   and idempotent retry.

### CFG02 — atomic source-management configuration writes

**Status:** planned; keep separate from CB01 rather than weakening its current fail-closed review
checks.

1. Add a configuration-scoped lock and expected-digest compare-and-swap writer for source
   management and source addition. Preserve recoverable atomic-file replacement only after the
   expected on-disk configuration is still current.
2. Wire the source-selection and source-addition finalizers through that writer; a concurrent
   change after Review must return a deterministic retry diagnostic and must never be overwritten.
3. Test interleavings for CLI and TUI finalizers, including absent configuration, valid existing
   configuration, recovery/corrupt state, and a lock-holder crash/retry path.
4. Keep content operations fail-closed throughout; this task improves source-management write
   isolation and does not authorize source identity mutation outside reviewed requests.

### REG02 — registry-owned agent skills

**Status:** separate repository PR, after the next AART executable version is chosen and released.

1. In `M1F1/agent-artifacts-registry`, update (do not duplicate):
   - `artifacts/skill/agent-artifacts` → `2.0.0`;
   - `artifacts/skill/author-aart-installer` → `2.0.0`.
2. Rewrite the skills around explicit configured sources, federated registries, human TUI versus
   agent CLI/JSON, trust/health, Copy/Symlink and project/user scope. Do not claim that the
   executable bundles a catalog.
3. Remove stale `legacy-catalog-v1` provenance once the rewritten payload is registry-owned.
4. Regenerate—not hand-edit—`aart.lock.json` and `aart.index.json`, then run registry format,
   validate, lock, build, audit, and compatibility gates.
5. Do not advertise commands in a registry skill before the corresponding executable version
   actually exposes them in `aart --help`.

### REG03 — Residuality framework bundle in the main registry

**Status:** implemented locally as a new registry import after REG02. The content import does not by
itself require an AART executable bump or a higher registry/artifact compatibility floor. A separate
AART change adds collection selectors as a lifecycle convenience and must follow its own SemVer
release decision.

1. Use
   [`M1F1/residues-architecture-framework`](https://github.com/M1F1/residues-architecture-framework)
   and its `agent-artifacts.import.json` as the reviewed inventory, but resolve and record one
   immutable upstream commit rather than publishing content from a moving `main` branch. The
   declared set is fourteen artifacts: the `residuality-theory` guideline, `using-residues`, nine
   `residual-01-*` through `residual-09-*` stage skills, and the three `residual-run-*` drivers.
2. Publish the reviewed upstream MIT license and managed-Symlink path fixes before the dependent
   registry change, then import from that immutable commit. Record the intentional initial artifact
   version `1.0.0`, supported platforms and profiles, Python 3.11 requirement, install modes/scopes,
   and the review decision for executable Python/shell payloads instead of inferring them from file
   names.
3. Vendor the reviewed payloads as canonical registry-owned packages in
   `M1F1/agent-artifacts-registry`. Preserve per-artifact provenance with the upstream URL, exact
   path, resolved commit, and input digest. Import only the fourteen declared artifacts: examples,
   repository wrappers, conversion utilities, ignored book/PDF material, and unrelated files are
   outside the package boundary.
4. Publish `collections/residuality.json` as the canonical registry representation of the
   upstream `residuality` bundle. It must contain all fourteen artifacts and install
   `using-residues` beside the stage/driver skills so their documented
   `../using-residues/kernel` fallback works from an installed profile layout.
5. Do not add per-artifact `requires_aart` merely because AART imported or distributes the
   package. Add a bound only where the installed payload itself invokes or depends on a specific
   AART executable contract; otherwise compatibility with the registry is governed by the
   registry's own `requires_aart` range.
   The optional collection-selector convenience does not alter this rule: AART `1.1.1` users can
   still discover the collection and install its member artifacts individually.
6. Regenerate—not hand-edit—`aart.lock.json` and `aart.index.json`. Run the registry's pinned AART
   quality gates: format, strict/frozen validate, lock, build, audit, and minimum/latest
   compatibility. CI must exercise the same commands as local review.
7. Acceptance tests must prove that the `residuality` collection and every member stay visible in
   the human marketplace and CLI/JSON discovery, and that collection installation works in
   project/user scope with Copy/Symlink for every declared compatible profile. From the installed
   layout, run the upstream kernel/stage test entry points and at least one pipeline smoke test;
   record unavailable combinations with an explicit reason rather than silently dropping them.
8. Keep the publication chain explicit: first make the exact upstream provenance commit reachable,
   then publish/release the independently reviewable AART collection-selector change if desired,
   and finally publish the registry import. Do not point provenance at an unpublished local commit,
   and do not increase `requires_aart` merely to require the one-coordinate shortcut.

### REL02 — next release contract

**Status:** planned; expected target is at least `1.0.1` because the public CLI/TUI behavior and
repository boundary change after `v1.0.0`.

1. Create a new versioned release checklist/schema contract rather than editing REL01 evidence.
2. Bump the executable version only after the intended CB01 scope is agreed.
3. Rebuild the wheel in a clean environment, validate allowlisted contents, run full quality/CI,
   review a merged `main` commit, then tag/release through the new fail-closed contract.
4. Only then raise registry `requires_aart` minimums and merge REG02.

## Test and quality matrix

For each task: write the failing characterization/negative test first, implement the smallest
functional-core change, then run focused tests before refactoring. Before a PR, run:

```sh
git diff --check
make format-check
make lint
make typecheck
make unit
make integration
make e2e
make validate
make coverage
make packaging-check
make docs-check
```

Additionally inspect the final diff for credential exposure, unintended configuration/object-store
writes, implicit checkout/catalog access, policy bypasses, and stale command examples. A task can
be committed and pushed only after these gates pass; merge/tag/release remain separate authorized
actions.

## Handoff checklist

If the current session stops before CB01 is published:

1. Start from the existing isolated branch/worktree and inspect `git status --short`.
2. Inspect the required-policy and read-only-discovery regressions before touching release/version
   files; they are already covered in the current branch.
3. Re-run the complete matrix above after the last edit; do not rely on earlier partial green runs.
4. Commit only the catalog-boundary/onboarding scope, push the branch, create/link a post-1.0 issue,
   and open a reviewable PR.
5. Leave LIFE02, SRC02, CFG02, REG02, REG03, and REL02 as distinct tasks/PRs; do not bundle them
   merely because they are related.
