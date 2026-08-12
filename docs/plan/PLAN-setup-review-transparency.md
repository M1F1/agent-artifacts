# Plan: Track-3 follow-up — transparent setup review and manual fallback

Status: delivered; ERR09-A completed in `819b885`, ERR09-B completed in `0cfee2a`, ERR09-C
completed in `74c22e9`, ERR09-D completed with a maintainer-decided scope change (see below);
tracked by
[issue #75](https://github.com/M1F1/agent-artifacts/issues/75); execute as ERR09 of
[`PLAN-typed-wizard-errors.md`](PLAN-typed-wizard-errors.md), after ERR04 and ERR06.

Design: [`DESIGN-setup-review-transparency.md`](../design/DESIGN-setup-review-transparency.md)

## Delivery shape

The work is intentionally after the typed-error core. ERR04 supplies one record renderer and the
placement rule for recoverable stage failures; ERR06 classifies setup-boundary failures. This
follow-up reuses both rather than adding a parallel setup-only error or layout system.

```
ERR04 shared record + recovery renderer
             |
ERR06 setup-boundary diagnostic audit
             |
ERR09-A protocol and source reference
             |
ERR09-B pure bounded setup projections
             |
ERR09-C review/runtime wiring and outcomes
             |
ERR09-D docs, compatibility and full gate
```

Every package is tests first.

**Superseded during ERR09-D.** Packages A–C were built behind a versioned compatibility boundary,
on the rule that no change may invalidate an existing v1 artifact for lacking `SETUP.md`. The
maintainer replaced that rule mid-delivery: only the newest revision of a protocol is maintained,
so the boundary was collapsed and revision 1 is now rejected outright. The record below is kept as
written; ERR09-D states what it removed.

## ERR09-A — setup contract and manual reference

**Status:** completed in `819b885`.

**Owns:** setup descriptor/schema/parser/catalog validation and their focused tests.

1. Freeze the smallest additive descriptor/protocol revision that can require a package-root,
   regular UTF-8 `SETUP.md` for new/updated setup-capable artifacts. Preserve v1 parser behavior
   exactly.
2. Add an immutable manual-reference value: artifact-relative path plus enough source provenance
   to resolve a commit-pinned web URL or an absolute local source path at rendering time.
3. Reject missing, directory, symlink-escaping, non-UTF-8 or unsafe manual-reference files before
   setup planning. Do not parse prose as commands.
4. Add the standard initial comment header requirement for a custom entrypoint, validated from the
   reviewed source bytes. The runtime preamble remains authoritative even if a legacy custom script
   has no header.

Acceptance: v1 fixtures remain green; v2 fixtures reject an absent or unsafe `SETUP.md`; a parsed
new installer carries a deterministic manual reference without reading environment or terminal
state.

Delivered:

- The parser accepts only matching `schema_version`/`protocol_version` pairs `1/1` and `2/2`.
  Version 1 still has no required manual document; version 2 derives the single package-root
  relative route rather than accepting author-controlled duplicate metadata.
- Catalog discovery checks v2 `SETUP.md` before setup planning: it must be a contained regular
  file, non-empty safe UTF-8 text, and cannot be a symlink. A v2 custom entrypoint must have the
  standard comment header after an optional shebang; v1 custom scripts remain compatible.
- Parser/catalog compatibility, missing/non-UTF-8 documents, custom-header and noncanonical-path
  tests pass. Independent review closed the descriptor-normalization gap. The complete quality
  matrix passed with 1870 tests.

## ERR09-B — pure bounded review and effect projections

**Status:** completed in `0cfee2a`.

**Owns:** setup review projection, `tui_layout`-using helpers and focused renderer tests.

1. Replace flat effect lines with a typed review projection that carries queue identity, manual
   route, effect records, capability/tool context, reversibility/recovery and preflight state.
2. Use `field_block`, `wrap`, `CONTENT_MEASURE` and `READABLE_MEASURE` for every normal line.
   Preserve full immutable paths/URLs only in an explicit scrollable detail route; ellipsize
   bounded summaries visibly.
3. Define exact safe fields per effect module. Redact or omit custom body, input values,
   environment values, raw process output and unsafe argv parts by construction.
4. Use one deterministic ordering: queue item, manual preamble, effects by planned order, then
   preflight/recovery. Test width 40, 80, 120 and 200, empty capabilities, long targets, manual
   recovery and a custom entrypoint.

Acceptance: text and curses consume the same projection; no output contains the old flattened
arrow shape; normal lines remain within their measure and no secret-shaped fixture value appears.

Delivered:

- `SetupReview` and `SetupEffectReview` are immutable pure values shared by the retained setup
  command today and reserved for the TUI/canonical adapters in ERR09-C. They carry the manual
  reference, recipe/plan hashes, required tools, ordered allowlisted effect facts and preflight.
- The renderer uses only `wrap` and `field_block`; at widths 40, 80, 120 and 200 its normal lines
  stay within the shared measure. Effect records replace the former flattened arrow form and keep
  identity, target, capability, recovery and safe details visible.
- Provenance accepts only an HTTPS commit-pinned blob root, with a contained absolute local route
  as the fallback. Credential-shaped author text is redacted; arbitrary argv, custom body,
  managed content, environment lookup and JSON values are withheld. v1 is explicitly labeled
  manual documentation unavailable.
- Static, custom, empty-capability, long-target, recovery, source and legacy setup tests passed.
  Independent review found no critical issue; the complete quality matrix passed with 1876 tests.

## ERR09-C — review, consent and typed outcomes

**Status:** completed in `74c22e9`.

**Owns:** setup queue adapters/runtime presentation, TUI integration and focused tests.

1. Show setup-capable selections and their manual route at the user-facing Review before Finalize;
   keep core payload installation and setup as separate transactions.
2. Immediately before setup consent, render the complete bounded review/preamble again. This is
   required for canonical and retained compatibility queues, text and curses paths, and
   non-interactive review output.
3. On decline, cancellation, planning failure, execution failure or incomplete rollback, render
   the known payload outcome first, then the typed setup outcome and manual route. Preserve safe
   retry/rollback commands where they already exist.
4. Use the lower fixed pane only for an actionable list-local refusal. Route a blocking setup
   review/stage error through `WizardStageFailure`'s full record and a post-curses outcome through
   its equivalent terminal record.
5. Keep `--yes`, `--approve-setup-effects`, trust authorizations and per-effect consent semantics
   unchanged. A manual alternative must never become implicit approval.

Acceptance: declining setup leaves the payload installed and provides the manual path; a failed
effect is recoverable without claiming payload rollback; custom and static paths cannot omit the
preamble; no failure starts a second wizard.

Delivered:

- The Install confirmation lists the manual route for every setup-capable selection, bounded to
  the terminal width the curses confirmation actually has. The complete bounded review is
  re-rendered immediately before consent on the retained, canonical and non-interactive paths;
  the machine-readable plan payload carries the same reviewed effect facts and manual route.
- Planning failure, decline and execution outcomes render the payload statement first and then one
  `render_setup_outcome` record per item, with the `SETUP.md` route whenever the status is not
  complete. A denial after recipe validation keeps the route it proved, through
  `CanonicalSetupAttempt`; a failure before it claims none. The unstarted statuses are named
  explicitly, and `skipped` is excluded because a completed rollback reports it too.
- Item 4 was audited rather than assumed. The fixed lower pane is already list-local only —
  setup runs after the frontend closed, now pinned by a curses test that observes the setup stage
  executing outside `curses.wrapper`. The retained runner's loose `error: <reason>` line was the
  one real gap; it now crosses a single named bridge into `WizardStageFailure`, keeping ERR04's
  record, ERR06's terminal recovery and its legacy exit status, without a second error system.
- Consent semantics are unchanged: `--yes`, `--approve-setup-effects`, trust authorization and
  per-effect approval behave exactly as before, and the manual route never applies an effect.
- Independent review found no critical issue; all ten quality gates passed with 1892 tests and
  85.27% branch coverage.

## ERR09-D — authoring guidance, documentation and final gate

**Status:** completed.

**Owns:** authoring templates/skills, README/design references, fixtures and release handoff notes.

1. Update the installer-authoring material so new setup artifacts start with `SETUP.md`, explain
   the required manual content and add the custom-script header template. — `DESIGN-setup-installers.md`
   §3.1 and SPEC §17.1.
2. Update README trust/review guidance with a concise example of declining automation and following
   the manual route. ~~State v1 compatibility precisely; do not promise retroactive validation.~~
   **Replaced:** state that exactly one revision is supported and that a superseded recipe is
   rejected with its migration named. Recorded setup state is still never migrated or rewritten.
3. Add representative MCP and non-MCP fixtures covering static, custom and local-source fallback
   routes. — `tests/fixtures/setup-routes/` with `tests/setup_manual_routes_test.py`.
4. Run the focused setup/TUI/typed-error suites, then every command in Track 3's full quality gate.
   Keep untracked workspace artifacts out of the change set. — all ten gates green, 1898 unit + 52
   integration tests, 85.28% branch coverage.

**Delivered beyond the written plan:** collapsing the two supported revisions into one. That
deleted `manual_path`'s optionality, the `legacy` marker on `SetupManualReference`, its render
branch, the `legacy` key in both JSON payloads, and the version-conditional `SETUP.md` validation
in `source.py` and the setup engine. `ERR09-D` delivery notes in
[PROGRESS-tui-program.md](PROGRESS-tui-program.md) carry the detail.

## Stop conditions

- ~~Do not change an existing v1 artifact's validity or add a schema requirement without a
  versioned boundary.~~ **Withdrawn by the maintainer during ERR09-D**: only the newest revision
  is maintained, and revision 1 is rejected at parse time. Recorded setup state is still never
  migrated or overwritten automatically.
- Do not show secrets, values typed for setup, raw script content, raw subprocess output or an
  unpinned repository link.
- Do not use a terminal-width-dependent free-form effect line.
- Do not use the bottom pane when the surrounding stage/list failed to load.
- Do not treat a setup failure as a payload rollback, and do not let a manual route apply an effect.
