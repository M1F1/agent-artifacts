# Design: transparent setup review and manual fallback

Status: in delivery ([issue #75](https://github.com/M1F1/agent-artifacts/issues/75)); ERR09-A/B
completed, ERR09-C/D pending

## 1. Context

The completed legibility work made artifact selection readable: a short, stable list occupies the
top of the screen and the selected artifact's evidence is shown in a bounded pane below it. Setup
is still an older surface. A queue can flatten an effect into one long line such as
`module: summary -> target`; review of a custom installer gives a cautious user no guaranteed
route to inspect and perform the actions manually; and a setup failure can leave them with a
status but no immediate fallback.

This follow-up makes the manual route part of the setup contract. An installer is an optional
convenience, never the only way to finish configuring an artifact. That matters most for MCPs,
but applies equally to every directory-shaped skill, hook or MCP that declares additional setup.

## 2. Decisions

### D1 — `SETUP.md` is the manual contract for new setup artifacts

For a new setup protocol revision, every directory-shaped artifact that declares
`setup/installer.json` contains a regular UTF-8 `SETUP.md` at its package root. The document
explains prerequisites, each intended effect in human terms, how to perform or verify it manually,
and any safe recovery step. It must not contain a secret value or require a user to copy one into
shell history.

Version-1 installers remain accepted unchanged; they cannot be made invalid after publication.
The revised catalog/schema validation applies only to newly authored or explicitly upgraded setup
descriptors. This is a protocol addition, not a silent reinterpretation of old artifacts.

ERR09-A implements the smallest compatible boundary as the matching descriptor pair `1/1` or
`2/2`. A v2 installer deterministically derives its package-root `SETUP.md` path from its recipe
path; catalog discovery requires that file to be regular, contained, non-empty UTF-8 text. A v2
custom entrypoint must start (after an optional shebang) with
`# AART manual setup: see ../SETUP.md`. Version-1 descriptors and custom scripts retain their
published validation unchanged.

The conventional location is intentionally fixed:

```text
artifacts/mcp/example/
├── payload/mcp.json
├── SETUP.md
└── setup/
    ├── installer.json
    └── install.sh              # only when custom-code is declared
```

The runtime derives the relative path; authors do not type a second, drifting copy of it into the
recipe.

### D2 — The manual alternative is presented before automation

Before the user approves a setup queue or any individual effect, AART prints a standard preamble:

```text
Manual alternative
  You may skip this installer and configure the artifact yourself.
  Instructions: artifacts/mcp/example/SETUP.md
  Source: https://host/org/repo/blob/<resolved-commit>/artifacts/mcp/example/SETUP.md
  No setup effect has run.
```

For a local source with no immutable web URL, `Source` is the absolute local path to the same
`SETUP.md`. For a materialized source, the UI still prefers a commit-pinned provenance URL when
available; a moving branch URL is not an adequate substitute. The relative path is always shown,
so an archived checkout remains usable.

The preamble repeats after a declined, cancelled, failed, or rollback-incomplete setup outcome.
If the payload itself has already installed, the outcome says so before it names the setup problem.
It never suggests that declining setup removed the installed payload.

Static recipes and custom entrypoints follow the same rule. The runtime emits the user-facing
preamble before it invokes any effect, so custom code cannot omit or replace it. A custom
`install.sh` begins with the standard non-executing comment header that points readers directly to
`../SETUP.md`; direct inspection of a script therefore reveals the manual route too.

### D3 — Effects are records, not horizontally stretched sentences

One effect is projected as a stable record. It shows only allowlisted, non-secret facts:

```text
1. Store an API token in macOS Keychain
   target        service com.example.mcp, account <selected profile>
   capability    keychain
   rollback      removes only an item created by this run
   details       required tool: /usr/bin/security
```

The record has a numbered identity, purpose, target, required capability/prerequisite,
reversibility or manual recovery, and safe command detail where a command is reviewable. An
opaque script body, input value, environment value, raw subprocess output, and full secret-bearing
argv are never rendered.

ERR09-B implements `SetupReview` and `SetupEffectReview` as the shared pure projection. The
projection keeps recipe and plan hashes, relative/local-or-pinned manual references, ordered
effect identity, target, capability, recovery and an allowlisted detail. It redacts
credential-shaped author text and withholds script bodies, managed values, Keychain lookup content
and arbitrary command arguments by construction. A URL is used only when it is an HTTPS
commit-pinned `/blob/<sha>` root; otherwise the projection uses the contained absolute local path.

`tui_layout.field_block`, `wrap`, `CONTENT_MEASURE` (100) and `READABLE_MEASURE` (80) own the
layout. The renderer is shared by text, curses and canonical setup execution; no caller builds a
separate `module: summary -> target` string. At 40 columns a field may wrap, but it never forces a
horizontal scan. Paths and immutable links may be shown in a scrollable full-detail route when
they do not fit their bounded summary; a truncated value is marked with `…`, never silently cut.

### D4 — Error placement follows whether a list is still actionable

The lower artifact pane is a useful, stable place for an error only while its list remains usable.
For an unavailable row or a rejected local effect, it becomes a `Feedback` record in the same
fixed pane budget. The status bar keeps only recovery keys.

A stage that failed to load its list/review has no valid cursor context. It therefore opens the
typed, scrollable failure record with Retry/Back/Quit, as defined by
[`DESIGN-typed-wizard-errors.md`](DESIGN-typed-wizard-errors.md). Post-payload setup happens after
curses exits and uses the equivalent bounded terminal record. It does not reopen a stale artifact
list merely to place an error at the bottom.

## 3. Boundaries and non-goals

- No setup effect, custom script, or documentation is executed while discovering an artifact or
  rendering its review.
- `SETUP.md` is instructional material, not executable input and not a source of dynamically
  parsed commands.
- The manual route does not grant additional capabilities or bypass policy, source trust, hash
  checks, or explicit consent for automated effects.
- Exactly one recipe revision is supported. A package declaring the superseded revision, with or
  without `SETUP.md`, is refused when the catalog is read; the error names the migration. Because
  every validated installer therefore has a route, no record ever reports a route as unavailable
  and none is fabricated from a URL. (This replaces the original v1-compatibility boundary,
  withdrawn by the maintainer during ERR09-D.)
- This follow-up does not promise an in-curses setup runner. The existing post-curses transaction
  boundary remains intact.
- It does not auto-execute a manual command, write a README, or collect a user's reason for
  declining automation.

## 4. Acceptance criteria

1. A setup-capable artifact is rejected at catalog validation when its package-root `SETUP.md` is
   missing, unsafe or unreadable, and when its version pair is not the single supported revision.
2. Before every setup consent, and after every incomplete setup outcome, a user sees a concrete
   relative route plus a commit-pinned URL or local absolute path.
3. At widths 40, 80, 120 and 200 no normal review/effect/error line exceeds the shared measure;
   effect identity and recovery remain visible.
4. The same facts and ordering render in text, curses review and non-interactive review output.
5. A custom entrypoint cannot suppress the runtime preamble; its source begins with the standard
   `SETUP.md` comment header.
6. No route or record leaks a credential, setup input, environment value, raw subprocess output,
   arbitrary script body, or unpinned source URL.

## 5. Delivery record

D1 landed in `819b885`, D3 in `0cfee2a`, and D2/D4 in `74c22e9`. Two decisions were sharpened by
the implementation and are recorded here rather than left implicit in the code:

- **A proven route survives a denied plan.** D2 promises the manual alternative before automation,
  but trust and policy can deny a plan *after* its recipe and `SETUP.md` have already been
  validated. Planning is therefore split at that seam and returns an attempt value whose invariant
  is that a planned attempt always carries its route. This keeps the promise without ever
  re-reading, guessing or fabricating a route for a failure that occurred before validation.
- **"Incomplete" and "unstarted" are different claims.** After an outcome the record states
  either that no effect has run or that automated setup is incomplete. Only statuses that prove
  nothing was attempted may claim the former; `skipped` is excluded because a *completed* rollback
  also reports it. When the retained runner fails mid-queue it discards the records it completed,
  so its blocking record makes the weaker, provable claim.

D4 was audited, not re-implemented. The lower fixed pane was already list-local by construction —
setup runs only after the frontend closes — and that is now pinned by observing the setup stage
execute outside the curses wrapper. The one violation was a retained blocking run printing a loose
error line; it crosses a single named bridge into the typed stage record instead. No parallel,
setup-only error or layout system exists.
