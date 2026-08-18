# Repair brief — company adoption stream

## Who this is for

An agent picking up the repair work for the findings raised while publishing AART inside a company.
You did not do the discovery. You do not need to redo it. Everything below points at a written record
with measurements attached.

## The goal

Close all 27 findings in the adoption stream, `AD-01` through `AD-27`, so that a colleague who has
never run `aart` can install a company registry's artifacts, run their setup, and iterate on a setup
recipe without hand-editing files AART owns.

That last clause is the one to hold on to. Six of these findings only appear on the **second** attempt
at something. The stream was found by using the tool for two days, not by reading it.

## Where everything is

Branch: `stream/company-adoption`.

| File | What it holds |
|---|---|
| [`residue-register.md`](residue-register.md) | one row per finding: id, severity, when it was raised, **state**, and the full measured account. This is the single place that says what is open. |
| [`residue-stream-2026-08-16-adoption.md`](residue-stream-2026-08-16-adoption.md) | where each finding came from: the session, the commands run, the outputs, and a Notes section per id with the reproduction |
| [`../tutorials/mcp-servers-into-the-registry.md`](../tutorials/mcp-servers-into-the-registry.md) | the porting procedure written during the stream; several findings are carried in it as caveats that should come out when they are fixed |

Every finding row names the file and line it was measured at. Trust the line numbers less than the
symbol names — read for the function, not the number.

## Rules that carry over

- **Never renumber an id.** `AD-nn` is permanent. If a finding turns out to be wrong, say so in its
  row and change its state; do not reuse the number.
- **The register is the state.** When you fix something, change its state there. The stream file is a
  historical record and does not change.
- **One live revision of any protocol.** Where a fix renames a published key or bumps a schema, reject
  the superseded form with a migration error. Do not read both.
- **Prose in these documents is plain English.** Short sentences, plain words. These are documents
  someone decides from.
- `make quality` runs nine gates and all nine must pass. `python3 scripts/docs_check.py` alone is a
  fast check while editing documentation.

## Suggested order

The clusters are ordered by what unblocks a real user soonest, not by severity.

### 1. The setup lifecycle is one-shot — `AD-27`, `AD-25`, `AD-23`

Start here. `AD-27` is the worst finding in the stream and everything else in setup was harder to
diagnose because of it.

**`AD-27` (high)** — an artifact's setup succeeds exactly once. Change the package bytes at all and
setup can never persist again, on that machine, by any command. `marketplace update` moves the
`installed` object reference and leaves the `setup` one pointing at the superseded digest;
`persist_setup` requires them to match. The version is not part of the check, so re-vendoring at the
same version trips it just as surely as a bump. No command recovers it. Reproduced on a one-step
probe artifact needing neither Docker nor Keychain.

**`AD-25` (medium)** — when persistence fails, the specific cause is computed and discarded, and no
receipt is written, so both routes to the cause close at the same moment. Fixing this is what makes
`AD-27` findable by the next person instead of requiring a debugger.

**`AD-23` (high)** — `marketplace install` and `marketplace update` fold the setup queue's verdict
into their own exit code, while declaring none of the flags that could authorize that queue. A
correct install exits `1`. This breaks every adoption script, whose only permitted dependencies are
`aart` and `git`.

Do these three together. They are one story.

### 2. A setup recipe cannot describe a real machine — `AD-26`, `AD-24`, `AD-17`

**`AD-26` (high)** — a symlinked `~/.zshrc`, which is what a dotfiles repository produces, makes the
managed-block step impossible. The refusal is right; the timing is not. Planning is a pure function
with no filesystem access, by design, so nothing stats the target until the sixth step of seven —
after the image build and after the credentials are typed. Wants a preflight between the reviewed
plan and the first effect, outside the plan hash.

**`AD-24` (high)** — the Keychain steps hand the terminal to `security`, which prints
`password data for new item:` twice, identically, for two different values. AART has the service, the
account and a human-readable summary in hand and shows them in the review, not at the prompt. Typing
the two values in the wrong order succeeds silently and surfaces much later as an authentication
error.

**`AD-17` (medium)** — `inputs[].type` accepts `"secret"` and nothing else, so a per-user value that
is not a secret has to be stored as one. The restriction is deliberate and is what lets the parser
refuse interpolation elsewhere, so the ask is a second non-secret input type, not a loosening.

### 3. The TUI cannot install anything with setup — `AD-21` (high)

The TUI's only `MarketplaceTarget` construction omits `setup_capabilities`, so it defaults to empty,
and `_compatibility` evaluates against it with `require_setup=True` hard-coded. Every artifact whose
recipe uses any module except `restart.notice@1` is unselectable, for everyone. The organization field
that would fill it is read as *everything permitted* by the setup engine and as *nothing permitted*
here — one unset field, two opposite readings. The CLI is unaffected.

This is close to a one-line fix and it unblocks the interface newcomers are pointed at.

### 4. Diagnostics that name no fix — `AD-19`, `AD-20`, `AD-22`, plus the discard half of `AD-25`

Three modules on the path from authoring a package to running it have `_error` helpers that take no
remediation, and no call site passes one: `io/registry_workspace.py`,
`registry_maintenance/vendoring.py`, `setup_engine/application.py`. Their neighbours in
`registry_commands/planning.py` all carry theirs.

- **`AD-19`** — the mutation gate refuses without a fix, and enforces a stricter rule than it states:
  `.git` must be at the `--source` path, so a registry inside a monorepo is refused while
  `git rev-parse --is-inside-work-tree` says `true`.
- **`AD-20`** — the vendoring refusal names the missing `payload/mcp.json` and never the path, and the
  correct action inverts on upstream content the maintainer has no reason to have checked.
- **`AD-22`** — the manual-route URL drops the package path and 404s, at the exact moment the
  automated route has declined and the link is all the reader has.

Treat as one repair.

### 5. Freshness is a clock reading — `AD-16` (high)

A source that has fallen behind its origin reports `current`, because nothing compares the snapshot to
the origin: health is `now - published_at`. It fails the other way too — a byte-identical snapshot
reports `stale` once the clock passes. And there is no third state for a check that could not run.
`sync.mode` is validated, persisted, carried into policy, and read by nothing that acts on it.

This one needs design, not a patch. It is the finding that cost the most time during the stream,
because every recipe change silently tested the previous recipe.

### 6. The maintainer's road to publishing — `AD-05`, `AD-07`, `AD-08`, `AD-10`, `AD-11`, `AD-13`, `AD-14`, `AD-15`

Bulk vendoring, collection authoring, candidate discovery, a lock that accepts what build rejects,
single-file vendoring, a missing `.gitignore`, an unautomated publish sequence, and a diagnostic
naming a precondition the code does not have. Independent of each other; pick them off in any order.

`AD-11` was scoped during the stream: the blocker is about twelve lines in `take_subtree`, and the
downstream integrity chain was proved to survive unchanged.

### 7. First contact and naming — `AD-01`, `AD-02`, `AD-03`, `AD-06`, `AD-18`

The README installs one way and it is a developer's way; it never says what vendoring is; it links to
no tutorial. `bundle` is dead vocabulary shipping beside the live `collection`.
`com.m1f1.runtime-requirements` puts a personal account in a namespace whose purpose is to say who
defines the key.

Low severity, high visibility. These are the first thing a colleague meets.

### 8. Reporting and profiles — `AD-09`, `AD-12`, `AD-04`

`AD-09` (high) — usage reporting never fires in either interface and never says why.
`AD-12` (high) — a project can hold only one `memory` artifact though the design was built for
several.
`AD-04` (high) — **partly settled during the stream.** Tabnine listed an installed server as
`disconnected` rather than absent, which proves it reads the file AART writes for project scope. What
remains is `user` scope. Read the row before doing anything here.

## What done looks like

For each finding:

1. the behaviour changes, with a test that fails before and passes after;
2. its row in the register moves out of `open` and says what was done;
3. any caveat carried in the tutorial for it comes out;
4. `make quality` is green.

Do not batch the register updates to the end. A row that still says `open` after the fix has shipped
is worse than no row.

## One warning

Several of these findings were only visible because someone used the tool twice in a row. `AD-27`
looks like nothing until the second setup. `AD-16` looks like nothing until the second sync. When you
believe one is fixed, do the thing twice.
