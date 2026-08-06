# TODO

Backup implementation tracker for the open TUI and installation UX work. GitHub issues remain
the source of truth for discussion and status; keep this file aligned with them.

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

- [ ] Add an Install-only mode screen to curses and text TUI:
  - Copy (recommended): install an independent snapshot;
  - Symlink: live-link supported directory artifacts to a local catalog.
- [ ] Keep Copy as the default.
- [ ] Pass the choice through Request.install_mode/the existing CLI link behavior.
- [ ] Explain that Symlink is local-source-only and currently applies to linkable skills/hooks;
      merged and file artifacts still use copy semantics.
- [ ] Reject remote-only symlink sources before mutation and explain how to select a local source.
- [ ] Disable/hide individual non-linkable rows with a reason instead of failing late.
- [ ] Disclose mixed bundle behavior before confirmation, including linked/copied counts.
- [ ] Show source, destination scope/path, harness, and mode on the confirmation screen.
- [ ] Report the actual mode used for each artifact in the completion summary.
- [ ] Preserve recorded modes during update and remove only managed links during uninstall.
- [ ] Test default Copy, Symlink, navigation, source validation, non-linkable artifacts, mixed
      bundles, manifest metadata, update, and uninstall.

## [#19 — Support project-scoped and user-global installs per harness](https://github.com/M1F1/agent-artifacts/issues/19)

- [ ] Add a core/CLI scope option such as `--scope project|user`; keep Project as the default.
- [ ] Let the TUI select scope before loading install/status/update/uninstall choices.
- [ ] Explain the choices:
  - Project configures only the current repository;
  - User configures the selected harness for the current user.
- [ ] Model explicit project and user destinations per harness and artifact type; do not derive
      global paths by blindly prepending the home directory.
- [ ] Verify supported user-global paths against current official harness documentation.
- [ ] Explicitly mark unsupported harness/type/scope combinations and explain them in the TUI.
- [ ] Keep separate project and user manifests/state so update and uninstall never cross scopes.
- [ ] Store resolved destinations, harness, source/subscription, install mode, and managed effects,
      but never secrets.
- [ ] Reject ambiguous combinations such as `--scope user` with `--project` before mutation.
- [ ] Show resolved absolute destinations and ask for confirmation before user-global writes.
- [ ] Prevent multi-harness operations from overwriting another harness's state.
- [ ] Test with a temporary fake home/state directory; never touch real global harness config.
- [ ] Preserve existing project behavior when scope is omitted.
- [ ] Document project/user precedence and scoped install/update/uninstall examples.

## [#20 — Support queued per-artifact interactive setup installers on macOS](https://github.com/M1F1/agent-artifacts/issues/20)

- [ ] Define and validate a reviewed, per-artifact macOS setup convention, for example an
      `install.sh` plus metadata for OS support, purpose, and credential/help URLs.
- [ ] Only run scripts shipped with the reviewed artifact source; never auto-run a script directly
      from an unreviewed network response.
- [ ] After core artifact installation, queue setup-capable selected artifacts and run their
      installers sequentially in the foreground.
- [ ] Allow each installer to:
  - explain the configuration it will perform;
  - show a direct credential/help URL and wait for the user;
  - read secrets without echoing them;
  - store secrets in macOS Keychain;
  - create only explicit, managed, idempotent configuration/snippets;
  - verify setup and return a meaningful exit status.
- [ ] Account for subprocess limitations: scripts cannot export variables into the parent TUI;
      use a durable Keychain plus managed shell/harness lookup and explain restart requirements.
- [ ] On failure/cancellation, preserve earlier successes, mark setup incomplete, and continue to
      the next installer unless the user stops the queue.
- [ ] Distinguish “installed and configured” from “artifact installed, setup incomplete.”
- [ ] List every incomplete installer with a safe retry command and offer a preselected TUI retry.
- [ ] Add a first-class CLI setup/retry runner using the same validation and state tracking.
- [ ] Never put credentials in argv, manifests, logs, stdout, or JSON output.
- [ ] Before execution, show artifact name, reviewed source identity, script path, and requested
      effects, then require explicit consent.
- [ ] Use a controlled working directory, documented minimal environment, and safely quoted paths.
- [ ] Record only non-secret status, installer version/hash, timestamps, and exit status.
- [ ] On non-macOS systems, do not execute the installer and show a clear unsupported message.
- [ ] Test with fake installers and a fake Keychain command: success, hidden input, failure,
      cancellation, continue/stop, idempotent retry, and secret redaction.
- [ ] Add a representative MCP setup fixture or reviewed example (Atlassian preferred).
- [ ] Document the trust model, authoring contract, retry flow, and the role of SETUP.md as
      optional reference rather than the primary guided setup path.
