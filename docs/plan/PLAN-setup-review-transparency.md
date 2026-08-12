# Plan: Track-3 follow-up — transparent setup review and manual fallback

Status: proposed; execute as ERR09 of
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

Every package is tests first. No code may make an existing v1 artifact invalid merely because it
lacks `SETUP.md`; a new protocol/schema revision is the compatibility boundary.

## ERR09-A — setup contract and manual reference

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

## ERR09-B — pure bounded review and effect projections

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

## ERR09-C — review, consent and typed outcomes

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

## ERR09-D — authoring guidance, documentation and final gate

**Owns:** authoring templates/skills, README/design references, fixtures and release handoff notes.

1. Update the installer-authoring material so new setup artifacts start with `SETUP.md`, explain
   the required manual content and add the custom-script header template.
2. Update README trust/review guidance with a concise example of declining automation and following
   the manual route. State v1 compatibility precisely; do not promise retroactive validation.
3. Add representative MCP and non-MCP fixtures covering static, custom and local-source fallback
   routes.
4. Run the focused setup/TUI/typed-error suites, then every command in Track 3's full quality gate.
   Keep untracked workspace artifacts out of the change set.

## Stop conditions

- Do not change an existing v1 artifact's validity or add a schema requirement without a versioned
  boundary.
- Do not show secrets, values typed for setup, raw script content, raw subprocess output or an
  unpinned repository link.
- Do not use a terminal-width-dependent free-form effect line.
- Do not use the bottom pane when the surrounding stage/list failed to load.
- Do not treat a setup failure as a payload rollback, and do not let a manual route apply an effect.
