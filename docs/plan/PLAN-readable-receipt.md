# Plan: the receipt has a reader

Execution plan for [DESIGN-readable-receipt.md](../design/DESIGN-readable-receipt.md), composed
against [residue-stream-2026-08-15.md](../testing/residue-stream-2026-08-15.md).

Nine work packages. `RR-1` is the foundation every reader needs; `RR-2`..`RR-4` are the three
actions; `RR-5` gives the text front-end the same actions; `RR-6` makes the documents a test gate;
`RR-7` answers cluster C6; `RR-8` is the release; `RR-9` is the live run on two registries and the
consumer repository.

## Guardrails

These hold for every package and are not restated in each.

- **No protocol version, and no schema change.** Every field this plan reads is already written by
  `_record_to_dict` (`setup.py:1376`). A package that finds itself wanting a new field has found a
  different design and must stop.
- **Review-first for the one action that mutates.** `undo` stops after Review and changes nothing
  without `--yes`; `--expect <digest>` binds the decision, as `SI-1` established. `show` and `verify`
  never mutate anything, including the orphaned run directories they report.
- **AART never deletes what may predate it.** `RS-10` and `LAF-47` become visible and stay
  untouched.
- **No credential is read, written, or printed.** The persisted receipt is already redacted
  (`_redact`, `setup.py:1400`); `verify` asks the Keychain *whether* an item holds a value and never
  for the value.
- **Zero dependencies, functional core, ports at the edge** — as everywhere else in this package.
- **Findings during a run are recorded, not fixed mid-run.** They are clustered at the end, which is
  how `LAF-51`..`LAF-61` were handled.

## `RR-1` — the persisted record can be read from outside a run

Today the only reader of a persisted setup record is the run that is about to replace it
(`setup_engine/application.py:301`, `_previous_record`). This package adds a read path that resolves
a record by installation coordinate, profile and scope, with no run in progress and nothing locked
for writing.

- A port that reads `setup_state_path(scope_root)` (`setup.py:1349`) and parses it with
  `parse_setup_state` (`setup.py:1433`), returning the typed record rather than a snapshot.
- Lookup by coordinate, and a typed refusal when the installation exists with no setup record, which
  is distinct from the installation not existing at all — two different sentences, both with
  remediation, because `RS-09` is in this stream and this package must not add a tenth empty one.
- No locking. A read that blocks on a write lock would make `show` fail during an unrelated install.

**Evidence:** a test that installs a setup-bearing artifact, then reads its record through the new
port in a separate process with no run in flight.

## `RR-2` — `setup receipt show`

Renders the record `RR-1` reads: plan hash, installer hash, start and finish, exit status, and every
step with module, target, disposition and detail.

This package is rendering only, and it closes none of `LAF-52`, `LAF-54` or `LAF-59` — an earlier
draft of this plan said it closed all three, and checking each against the code refuted it. Those
belong to `RR-2A` and `RR-2B`. What `show` gives is the account, readable a week later, which is what
`undo` and `verify` are argued from.

**Evidence:** a completed setup's record rendered in text and in `--json`, with the text carrying
every field the JSON does.

## `RR-2A` — the text renderer stops summarising what `--json` carries

Design §3.4. The defect `LAF-52` and `LAF-54` describe is not distance from the record — both
findings state that the content is present in the `--json` payload and absent from the human output.
It is a lossy renderer at the moment of consent.

- `marketplace setup` without `--yes` prints the **setup** review — effects, capabilities, and the
  `Manual alternative` pointing at `SETUP.md` — which `render_setup_review` already composes and no
  CLI path emits.
- A setup planning failure prints the detail, the artifact key and the manual route, not
  `planned=0, failures=1`.
- Counts may accompany content; they may not replace it.
- A path with nothing to report says it checked, so `LAF-45`'s lesson does not recur in a new command.

**Evidence:** `marketplace setup <coord>` at a terminal with no `--json` shows every field the JSON
payload carries; `--approve-setup-effects` now approves a list the operator has been shown.

## `RR-2B` — a transcript keeps the end that explains it

Design §3.5. `_docker_build_apply` raises `RuntimeError(detail[:512])` at the point of failure
(`setup_runtime.py:436`), so the failing instruction and exit code BuildKit prints last are discarded
before persistence. Nothing downstream can recover them.

- One helper that keeps the tail, and both ends with the middle elided where both carry meaning.
- Used at all three call sites — `:436`, `:496`, `:535` — because a rule applied at two of three is
  how this recurs.
- Redaction is applied before truncation, as it is today, and the helper must not be able to reorder
  those two steps.

**Evidence:** an artifact whose Dockerfile ends `RUN … && exit 3` reports that instruction and
`exit code: 3`, which is `LAB-X-04` re-walked.

## `RR-3` — `setup receipt verify`

The one package with genuinely new mechanism. For each receipt kind, ask the world whether what the
receipt claims is still true:

| Receipt kind | Question asked |
|---|---|
| `docker.build@1` | does the tag exist, and does it still resolve to the recorded image id |
| `macos-keychain.store@1` | does the item exist, **and does it hold a non-empty value** |
| `file.managed-block@1` | does the file exist, and does the block still carry the recorded digest |
| `trust-store.export-certificates@1` | does the exported bundle still match the recorded digest |
| any | is there an orphaned run directory under `setup-runs/` for this plan hash |

- **`LAF-55` is closed by the second row.** `security add-generic-password -w` with no terminal exits
  0 having stored nothing; the receipt faithfully records a step that reported success. Only a
  question put to the Keychain can distinguish the two, and nothing asks it today.
- **`verify` reports and never repairs**, exactly as `registry audit` does. An orphaned directory
  (`LAF-61`) is named and left; an emptied merge file (`LAF-47`, `RS-10`) is named and left.
- Exit non-zero when any claim is false, so it is usable from CI.

**Evidence:** an unattended setup run whose Keychain step stores nothing, reported by `verify` as
present-and-empty; a hand-deleted tag reported as missing; a clean install reporting every claim
true, and saying so rather than printing nothing — `LAF-45`'s lesson applied to a new command.

## `RR-4` — `setup receipt undo`

Calls `rollback_record` (`setup_runtime.py:1331`) against the record `RR-1` reads, instead of the
in-process one.

- The rollback function, its ownership checks and its `receipt_matches_plan` binding
  (`setup.py:1276`) are used unchanged. This package is wiring, a review, and a record lookup.
- **`LAF-58` is *not* closed inside it**, and finding out why is what this package produced.
  `_docker_build_apply` records the image id *after* the build (`setup_runtime.py:465`); the
  pre-run inspect only asks whether the tag exists (`:458`). The earlier binding was never written
  down, so no reader can restore it. Closing it is a capture-site change like `RR-2B`'s, tracked as
  `RR-4A`. What `RR-4` does instead is name the limit in the undo review, before consent.
- The review names every effect it will reverse and every effect it will not — a step whose receipt
  no longer matches the reviewed plan is reported and skipped, never forced.
- On partial success the record is written back as `rollback_incomplete`, which the existing
  `SetupStateRecord` status already expresses.

**Evidence:** `LAF-53`'s scenario end to end — install a setup-bearing artifact, `undo`, and observe
the image tag, the Keychain item and the shell block gone, with a `preexisting` tag restored to its
original binding.

## `RR-4A` — the capture site records what a tag pointed at before the run

One line at `setup_runtime.py:458`: the pre-build inspect already runs, and already discards
everything but its exit status. Reading `{{.Id}}` there and recording it as `previous_image_id`
costs nothing extra and is what `LAF-58` needs. The undo then restores the binding with
`docker tag <previous_image_id> <tag>` for a `preexisting` tag, and the review says so.

Kept out of `RR-4` deliberately: `RR-4` claims to add no field, and a package that quietly breaks
its own claim is how a guardrail stops meaning anything.

**Evidence:** a tag that names an image before a run points at that same image again after an undo.

## `RR-5` — the same three actions in the text front-end

`VN-9` established that a maintainer action that exists only in the CLI is half-shipped. The three
actions appear in the text front-end with the same review, the same refusals and the same
remediation.

Two things this package settled that the plan had left implicit:

- **`receipt` is not a fifth wizard verb.** The four in `ACTIONS` select artifacts from a catalog and
  end at the wizard's Review; a receipt reads or reverses one artifact that is already installed, so
  it has no basket and no install mode. Putting it in `ACTIONS` would set a value in the state machine
  that no stage after `action` can interpret. It is offered from the same menu, runs its own three
  questions, and returns to the menu.
- **Parity is enforced by a guard, not by intention.** Both skins call one function; an AST check
  fails if either names a receipt renderer, a projection, or `apply_undo` outside it. Without that,
  the second skin drifts and the drift shows up as two different answers to the same question — which
  is the defect `VN-9` describes, one level up.

The interactive undo is bound the way `--expect` binds the flag-mode one: after the answer, the undo
is recomputed from disk and refused if the digest moved.

**Evidence:** both front-ends walked for all three actions against a real record in a temporary data
root, as `SI-9` and `VN-9` were. Found doing it: `LAF-64`.

## `RR-6` — the documents become a test gate

- Command reference for the three actions, and a worked section showing an undo.
- `compatibility-v14` records what became possible and — the part that matters — moves six findings
  from *shipped open*, with the reproduction each moved by.
- The remediation guard already parses every user-visible `aart …` mention with the real CLI parser;
  three new commands means three new mentions that must parse.

**Six move, and five of them close.** This bullet said *six findings from shipped open to closed*.
`LAF-61` does not close: `verify` names the orphaned run directory and leaves it, because
`DESIGN-readable-receipt.md` §4 forbids a read command from sweeping anything. It is `visible` in the
register, and `compatibility-v14` says five closed and one visible rather than rounding up — which is
the whole point of having a register with more than two dispositions.

**And `visible` did not survive either.** `RR-9` measured the probe against a real leftover directory
and found it scanning the project root while runs are created under the data root (`LAF-66`), so
`verify` never names anything: it answers `true` without looking. Five findings move and `LAF-61` is
`open`. The paragraph above is left as it was written, because it is the record of what this plan
believed — the correction goes beside it, not over it. The register is where the state lives, and it
says `open`.

The worked undo in `README.md` is the renderer's real output, captured from `render_undo_payload`, not
prose shaped like it. A hand-written example is a claim about the code that nothing checks.

## `RR-7` — the open-residue register, derived rather than maintained

Cluster C6: no document says what is open now, and a cross-reference over 58 findings misclassifies
50 of them because closure is recorded in prose.

- One register file: id, severity, where it was found, disposition, and — when closed — the
  reproduction that closed it.
- A `docs_check` rule that fails when a finding is referenced as open in a plan or a compatibility
  document and is absent from the register, or is closed in the register and still described as open
  somewhere. The register is the single place; everything else must agree with it.
- Seeded from this stream's twenty-eight items, not from all 58 — the register starts honest about
  what it covers rather than pretending to a history it cannot reconstruct.

**Evidence:** `make docs-check` fails on a deliberately introduced disagreement, and passes when the
register and the documents agree.

## `RR-8` — the release commit

Version, contract `v14`, compatibility and checklist documents, a freeze that differs from `v13` in
the inputs this work actually changed, and `CHANGELOG.md` and `PROGRESS.md` recording what became
possible and what each package's plan did not anticipate.

## `RR-9` — live acceptance: two registries and the consumer repository

The run this whole stream exists to make honest.

- **Registry A** (`agent-artifacts-registry`) — carries the three setup-bearing docker recipes, so it
  is where `show`, `verify` and `undo` have something real to read.
- **Registry B** (`agent-artifacts-registry-2`) — carries no setup-bearing package, so it is where the
  three actions must refuse cleanly rather than crash: an installation with no setup record is
  `RR-1`'s typed refusal, and this is the registry that proves it.
- **The consumer repository** (`agent-artifacts-live-acceptance-project`) — its acceptance workflow
  reconciles eleven installations; after this release it must still report eleven `current` and a
  clean `git diff`, and its AART pin moves with the release.
- Walked on a real machine, with a real daemon and a real keychain, with **no patched executable**.
  Design §6 criterion 6 makes that a criterion rather than a hope, because `2.5.0`'s run needed a
  patch to observe anything at all (`LAF-51`) and that must not recur silently.
- Findings recorded live as `LAF-63`+ and clustered at the end, never fixed mid-run.

## Dependency order

`RR-1` first and alone. Then `RR-2`, `RR-3`, `RR-4` in parallel — they share only the reader.
`RR-2A` and `RR-2B` are independent of the reader and of each other, and may land at any point;
`RR-2B` before `RR-2A` is preferable, so the renderer's first honest output is not a truncated one.
`RR-5` after `RR-2`..`RR-4`. `RR-6` after `RR-5`. `RR-7` is independent of every other package.
`RR-8` after `RR-6` and `RR-7`. `RR-9` last, against the released artifact.

## Release shape

One minor version. No protocol revision, no command removal, no field change: three new read/act
commands over state that `2.5.0` already writes. A `2.5.0` data root is fully readable, and a
`2.6.0` data root is fully readable by `2.5.0` — the asymmetry that `LAF-62` describes does not
arise here, because nothing this plan writes changes what an index compiles to.
