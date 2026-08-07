# TODO

Backup implementation tracker. GitHub issues remain the source of truth for discussion and status;
keep this file aligned with them.

## [#27 — AART 1.0: federated artifact compiler and optional registries](https://github.com/M1F1/agent-artifacts/issues/27)

Product requirements:
[`docs/product/PRD-aart-1.0.md`](docs/product/PRD-aart-1.0.md). Technical contract:
[`docs/design/SPEC-aart-1.0.md`](docs/design/SPEC-aart-1.0.md). Task sequencing and quality gates:
[`PLAN.md`](PLAN.md). Durable execution state: [`PROGRESS.md`](PROGRESS.md).

### Architecture and release

- [x] Separate the AART compiler/tool repository from operational artifact registries.
- [x] Define a federated marketplace with zero or more direct sources/registries and an optional
      default registry.
- [x] Define native references, materialized foreign imports, and direct source subscriptions.
- [x] Treat importers as deterministic Maintainer-time migration/curation tools, never consumer
      runtime conversion.
- [x] Write the AART 1.0 PRD and technical specification.
- [x] Start implementation versions at `1.0.0a1`; do not tag `1.0.0` before the release gates pass.

### Protocol and compiler

- [x] Implement strict JSON schemas for native sources, artifacts, provenance, and collections.
- [x] Implement strict registry, native entry, committed lock, and compiled index schemas.
- [x] Implement strict JSON schemas and canonical writers for user configuration and organization
      policy.
- [ ] Implement remaining strict JSON schemas for outcomes and manifest v2 documents.
- [x] Implement SemVer bounds, protocol/capability negotiation, and canonical JSON/tree digests.
- [ ] Complete qualified-coordinate parsing and ambiguity handling in compiler/marketplace tasks.
- [x] Implement deterministic registry-input hashing, graph validation, index generation, and
      frozen registry lock resolution.
- [x] Implement typed deterministic compiler phases, accumulated diagnostics, immutable candidate
      planning, injected effect ports, and publication gating.
- [x] Supply the concrete source/compatibility/effects graph compiler on the phase framework.
- [ ] Implement built-in deterministic importers, provenance, loss/ambiguity checks, stale-output
      validation, and promotion of native direct sources into registries.
- [ ] Add registry quality gates for format, validate, lock, build, audit, diff, and profile tests.

### Federated sources and managed store

- [x] Add user configuration for zero or more local/Git source and registry aliases, with at most
      one optional default registry.
- [x] Add organization policy for recommended/required sources, allowed Git hosts/prefixes, setup
      capabilities, minimum user-scope trust, custom setup, and reporting destinations.
- [ ] Extend policy consumption with exact company-reviewed source identity and operation-specific
      scope/trust/setup gates in the marketplace, installation, and setup tasks.
- [x] Implement Git mirrors, immutable validated snapshots, atomic current pointers, health/doctor,
      concurrency control, and offline last-known-good behavior.
- [ ] Implement the content-addressed artifact object store with digest verification, safe GC, and
      install/setup references.
- [ ] Merge configured sources deterministically without silent shadowing and display effective
      source/trust for every artifact.

### Consumer and TUI migration

- [ ] Resolve Install/Update from qualified source subscriptions and immutable objects.
- [ ] Keep Copy as default and make managed Symlink target immutable store content; sync alone must
      not retarget installed artifacts.
- [ ] Migrate project/user manifests, scope/profile compatibility, managed merges, uninstall proof,
      setup state, and structured outcomes to manifest v2.
- [ ] Add the Sources/health stage to the persistent TUI while preserving Backspace state, basket,
      Review/Finalize, descriptions, modes, scopes, and explicit outcomes.
- [ ] Bind reviewed macOS setup recipes to source trust and artifact/recipe/plan digests.
- [ ] Keep reporting disabled without an explicit destination and route configured reports only to
      the policy-approved repository.

### Installation-risk assessment

- [ ] Add a zero-runtime-dependency baseline that reports digest-bound installation-risk evidence,
      not a claim that an artifact is safe.
- [ ] Add a versioned out-of-process JSON protocol for independently installed analyzers; never
      auto-install them or import them into the AART process.
- [ ] Add optional adapters/suites for applicable open-source analyzers while preserving the
      stdlib-only AART runtime.
- [ ] Add signed/digest-bound evidence indexes, freshness handling, deterministic bundle
      aggregation, and policy gates based on worst/unknown status rather than average alone.
- [ ] Show provider, rules version, evidence age, coverage, risk range, and remediation details in
      CLI/TUI marketplace, review, maintainer, and outcome views.
- [ ] Test malicious provider output, timeout, crash, stale/mismatched evidence, partial bundle
      coverage, offline behavior, and policy enforcement.

### Repositories, migration, and verification

- [ ] Create the public `M1F1/agent-artifacts-registry` reference marketplace during SEP01, only
      after the deterministic export and public-content preflight pass.
- [ ] Provide a confidential-content-free bootstrap/template for a company registry.
- [ ] Migrate the current top-level 0.1.x catalog into canonical source/registry layout with a
      reviewable built-in importer.
- [ ] Add dry-run/apply/backup/rollback migration for existing 0.1.x installation state.
- [ ] Test direct-source-only, multi-registry, company-plus-team, native-reference, foreign-import,
      collision, trust, offline, concurrency, Copy/Symlink, setup, and reporting fixtures.
- [ ] Test local editable and local-wheel installation without an embedded operational registry or
      checkout-relative runtime data.
- [ ] Prove deleting/recreating the Python environment does not break managed artifact symlinks.
- [ ] Run registry CI with the minimum supported and latest compatible AART versions.

## Completed 0.1.x TUI and installation UX

## [#15 — TUI: add User/Maintainer entry paths and maintainer workflows](https://github.com/M1F1/agent-artifacts/issues/15)

- [x] Make User/Maintainer selection the first screen in both curses and text TUI modes.
- [x] Explain each path in one line:
  - User installs, updates, and removes artifacts from subscribed/recorded catalog sources.
  - Maintainer can do the same and also curate the catalog and its upstreams.
- [x] Keep the existing profile-aware install/update/uninstall flow in User mode.
- [x] Record enough source/subscription identity for updates without asking for the repository
      again.
- [x] Add guided Maintainer workflows for:
  - adding one upstream from a GitHub URL;
  - scanning a repository/path and selecting detected artifacts to import;
  - optionally adding imported artifacts to a bundle;
  - checking all or selected tracked upstreams;
  - previewing and applying upstream updates;
  - validating the catalog before and after mutations;
  - showing artifact counts, tracked/untracked state, validation failures, and upstreams needing
    attention.
- [x] Make the active catalog checkout/source explicit and reject ambiguous catalog mutations.
- [x] End maintainer mutations with next steps such as reviewing the diff and running validation;
      never commit automatically.
- [x] Reuse Request objects and existing command/core logic instead of duplicating it in the TUI.
- [x] Cover role selection, clean quit, invalid catalog context, and upstream workflows in tests.
- [x] Document the distinction between reviewed consumer updates and maintainer catalog updates.

## [#16 — TUI: show a one-line description for every installable artifact](https://github.com/M1F1/agent-artifacts/issues/16)

- [x] Add a normalized description field to Artifact and populate it in every catalog parser.
- [x] Read descriptions from:
  - Markdown frontmatter for skills, guidelines, and memory;
  - JSON descriptors for MCP servers and hooks;
  - the existing bundle description field.
- [x] Require a non-empty, single-line, user-facing description during catalog validation.
- [x] Add concise, value-oriented descriptions to every shipped artifact and fixture.
- [x] Show descriptions for artifact and bundle rows in both TUI frontends.
- [x] Keep each selector row to one visual line, truncate with an ellipsis on narrow terminals,
      and provide a way to view the full text.
- [x] Expose the same description in human and JSON list output.
- [x] Retain descriptions after compatibility filtering and in update/uninstall views when source
      metadata is available.
- [x] Test all artifact types, bundles, invalid descriptions, narrow terminals, and JSON output.
- [x] Document description authoring conventions for catalog maintainers.

## [#17 — TUI: provide explicit outcome summaries for every action](https://github.com/M1F1/agent-artifacts/issues/17)

- [x] Introduce a shared structured action-result/summary contract; do not parse command stdout in
      the TUI.
- [x] Always leave a visible final summary after curses exits and in the text fallback.
- [x] Report, at minimum:
  - install: installed/reinstalled, copied, symlinked, skipped, and failed targets;
  - update: selected, changed, already current, skipped, conflicted, and failed targets;
  - uninstall: removed, already absent/not matched, preserved user content, and failures;
  - maintainer actions: scanned/imported/checked/updated upstream counts;
  - cancellation or empty selection: explicitly state that no changes were made.
- [x] Make a successful no-op explicit, for example: “Updated 0 artifacts; all 5 selected
      artifacts are already up to date.”
- [x] Distinguish an empty selection from an already-up-to-date selection.
- [x] Preserve appropriate non-zero exit codes for conflicts, partial failures, and errors.
- [x] Keep warnings and recovery instructions visible alongside the summary.
- [x] Provide equivalent counts and item lists in human and JSON output.
- [x] Test successful, no-op, empty, conflict, partial-success, and failure paths in both TUI modes.

## [#18 — TUI: let users choose copy or symlink install mode](https://github.com/M1F1/agent-artifacts/issues/18)

- [x] Add an Install-only mode screen to curses and text TUI:
  - Copy (recommended): install an independent snapshot;
  - Symlink: live-link supported directory artifacts to a local catalog.
- [x] Keep Copy as the default.
- [x] Pass the choice through Request.install_mode/the existing CLI link behavior.
- [x] Explain that Symlink is local-source-only and currently applies to linkable skills/hooks;
      merged and file artifacts still use copy semantics.
- [x] Reject remote-only symlink sources before mutation and explain how to select a local source.
- [x] Disable/hide individual non-linkable rows with a reason instead of failing late.
- [x] Disclose mixed bundle behavior before confirmation, including linked/copied counts.
- [x] Show source, destination scope/path, harness, and mode on the confirmation screen.
- [x] Report the actual mode used for each artifact in the completion summary.
- [x] Preserve recorded modes during update and remove only managed links during uninstall.
- [x] Test default Copy, Symlink, navigation, source validation, non-linkable artifacts, mixed
      bundles, manifest metadata, update, and uninstall.

## [#19 — Support project-scoped and user-global installs per harness](https://github.com/M1F1/agent-artifacts/issues/19)

- [x] Add a core/CLI scope option such as `--scope project|user`; keep Project as the default.
- [x] Let the TUI select scope before loading install/status/update/uninstall choices.
- [x] Explain the choices:
  - Project configures only the current repository;
  - User configures the selected harness for the current user.
- [x] Model explicit project and user destinations per harness and artifact type; do not derive
      global paths by blindly prepending the home directory.
- [x] Verify supported user-global paths against current official harness documentation.
- [x] Explicitly mark unsupported harness/type/scope combinations and explain them in the TUI.
- [x] Keep separate project and user manifests/state so update and uninstall never cross scopes.
- [x] Store resolved destinations, harness, source/subscription, install mode, and managed effects,
      but never secrets.
- [x] Reject ambiguous combinations such as `--scope user` with `--project` before mutation.
- [x] Show resolved absolute destinations and ask for confirmation before user-global writes.
- [x] Prevent multi-harness operations from overwriting another harness's state.
- [x] Test with a temporary fake home/state directory; never touch real global harness config.
- [x] Preserve existing project behavior when scope is omitted.
- [x] Document project/user precedence and scoped install/update/uninstall examples.

## [#20 — Support queued per-artifact interactive setup installers on macOS](https://github.com/M1F1/agent-artifacts/issues/20)

- [x] Define and validate a reviewed, per-artifact macOS setup convention, for example an
      `install.sh` plus metadata for OS support, purpose, and credential/help URLs.
- [x] Only run scripts shipped with the reviewed artifact source; never auto-run a script directly
      from an unreviewed network response.
- [x] After core artifact installation, queue setup-capable selected artifacts and run their
      installers sequentially in the foreground.
- [x] Allow each installer to:
  - explain the configuration it will perform;
  - show a direct credential/help URL and wait for the user;
  - read secrets without echoing them;
  - store secrets in macOS Keychain;
  - create only explicit, managed, idempotent configuration/snippets;
  - verify setup and return a meaningful exit status.
- [x] Account for subprocess limitations: scripts cannot export variables into the parent TUI;
      use a durable Keychain plus managed shell/harness lookup and explain restart requirements.
- [x] On failure/cancellation, preserve earlier successes, mark setup incomplete, and continue to
      the next installer unless the user stops the queue.
- [x] Distinguish “installed and configured” from “artifact installed, setup incomplete.”
- [x] List every incomplete installer with a safe retry command and offer a preselected TUI retry.
- [x] Add a first-class CLI setup/retry runner using the same validation and state tracking.
- [x] Never put credentials in argv, manifests, logs, stdout, or JSON output.
- [x] Before execution, show artifact name, reviewed source identity, script path, and requested
      effects, then require explicit consent.
- [x] Use a controlled working directory, documented minimal environment, and safely quoted paths.
- [x] Record only non-secret status, installer version/hash, timestamps, and exit status.
- [x] On non-macOS systems, do not execute the installer and show a clear unsupported message.
- [x] Test with fake installers and a fake Keychain command: success, hidden input, failure,
      cancellation, continue/stop, idempotent retry, and secret redaction.
- [x] Add a representative MCP setup fixture or reviewed example (Atlassian preferred).
- [x] Document the trust model, authoring contract, retry flow, and the role of SETUP.md as
      optional reference rather than the primary guided setup path.

## [#21 — TUI: add onboarding, progress stepper, back navigation, and persistent selections](https://github.com/M1F1/agent-artifacts/issues/21)

- [x] Start text and curses sessions with a concise controls/onboarding screen.
- [x] Derive an accessible, non-color-only progress stepper from the applicable User or Maintainer
      stage graph and keep it usable in narrow terminals.
- [x] Model navigation, confirmations, basket values, notices, and curses cursor/scroll positions
      in one immutable `WizardSession` shared by both frontends.
- [x] Support one-stage Back on every applicable screen (`KEY_BACKSPACE`, `127`, and `8` in
      curses; `b`/`back` in text) without dispatching or losing valid selections.
- [x] Preserve the artifact/bundle/upstream basket across Review/Edit and selectively remove only
      choices invalidated by earlier edits, with a visible reason.
- [x] Show complete Review facts from issues #15–#20, including descriptions, source, scope,
      destinations, projected install modes, warnings, structured outcomes, and setup queue.
- [x] Make Finalize the sole consumer/upstream apply boundary; keep curses teardown before command
      dispatch and setup execution.
- [x] Preserve Maintainer validation/dry-run preview while moving catalog apply behind Finalize.
- [x] Confirm quit when the basket is non-empty and explicitly report that cancellation made no
      changes.
- [x] Cover pure transitions/rendering, text and curses adapters, Maintainer flows, real lifecycle
      E2E, and all repository quality gates.
- [x] Document onboarding, navigation, basket persistence, Review, and Finalize behavior.
