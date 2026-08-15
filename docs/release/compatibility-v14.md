# AART 2.6.0 compatibility matrix

AART `2.6.0` is a minor release over `2.5.0`. It adds one command family — `aart marketplace receipt`
with three actions — over state that `2.5.0` already writes, and makes two rendering paths stop
summarising what they had. Every `2.0.0`…`2.5.0` configuration, source store, object store,
installation record, registry, artifact, and setup state file is read and written exactly as before.

It is minor rather than patch because the CLI surface grows and the text front-end grows with it. No
document gains a field, no schema moves, and no protocol version changes. A `2.5.0` data root is
fully readable by `2.6.0`, and a `2.6.0` data root is fully readable by `2.5.0` — this release writes
nothing `2.5.0` cannot parse.

| Boundary | Supported in 2.6.0 | Change from 2.5.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | unchanged | none | native tree and registry gates |
| Provenance document | v1 with `aart.vendor` | none | vendoring and integrity tests |
| Configuration schema | v1 | none | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | none | setup parser and canonical setup tests |
| Setup receipts | unchanged shape | none — this release **reads** them | setup runtime tests, receipt tests |
| Setup state file | unchanged shape | **a failing step's `detail` now keeps the end of the transcript** | setup runtime tests |
| Index setup evidence | unchanged | none | index and vocabulary tests |
| Registry maintainer gates | unchanged | none | registry validate/build gates |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1, ruleset `baseline-v1.1` | none | security tests |
| Install effects | unchanged | none | installation tests |
| CLI surface | **three commands added** | `marketplace receipt show\|verify\|undo` | CLI and e2e tests |
| Setup review rendering | **printed at the terminal** | was `--json` only | marketplace command tests |
| Consumer text front-end | **`receipt` in the Action menu** | both skins, one shared seam | TUI parity tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is minor and not a protocol move

The v14 schema freeze differs from v13 in **one input and no protocol version**:
`agent_artifacts/setup.py`, and the difference there is a single rename — `_public_text` became
`public_text` so the shared renderer could reach it. No parsed field, no module catalog entry, no
validation rule. `schema-freeze-v14.json` and `schema-freeze-v13.json` carry identical
`protocol_versions`, and every other hashed input is byte-identical.

That is the machine-checked statement that this release moves no boundary. Every part of the work is
above the schema line: reading a file the previous release already wrote, and printing what was
already computed.

## Added

### `aart marketplace receipt show` — the account, readable a week later

Renders the persisted `SetupStateRecord`: plan hash, installer hash, start and finish, exit status,
and every step with its module, target, disposition and detail. Nothing is recomputed and nothing is
locked, so it can be read while an unrelated install is in flight.

Named `marketplace receipt` and not `setup receipt`: `setup` is already a `marketplace` lifecycle
action, and a top-level `aart setup` would make two different operations share one word.

### `receipt verify` — is any of it still true?

For each receipt kind, one question put to this machine:

| Receipt kind | Question |
|---|---|
| `docker.build@1` | does the tag exist, and does it still resolve to the recorded image id |
| `docker.pull@1` | is the image still present |
| `macos-keychain.store@1` | does the item exist, **and does it hold a non-empty value** |
| `file.managed-block@1` | does the file still carry the block text that was installed |
| `shell.env-from-keychain@1` | the same |
| `json.managed-merge@1` | does the file exist |
| `trust-store.export-certificates@1` | does the exported bundle exist |
| any | is there an orphaned run directory under `setup-runs/` for this plan hash |

Three statuses, not two. A claim `verify` **could not ask** — no daemon, no login session, an
unreadable path — is `unknown`, never `true`. A verifier that quietly passes what it cannot see is
worse than no verifier. The exit code is non-zero when any claim is false, so it is usable from CI.

`verify` reports and never repairs, exactly as `registry audit` does.

### `receipt undo` — the rollback, reached from outside a failing run

`rollback_record` already existed, with its ownership checks and its `receipt_matches_plan` binding,
and ran exactly once: on the failure path inside a run. This release lets a consumer invoke it
against the persisted record.

It is a mutation, so it takes the same boundary as every other mutation: without `--yes` it prints
the effects it would reverse and changes nothing, and `--expect <digest>` binds the decision to the
exact undo that was read. The review names every effect it will **not** reverse and why — including
the one limit this release cannot remove, below.

### The same three actions in the text front-end

`receipt` appears in the Action menu of both the line-oriented and the full-screen front-end. Both
call one function; a test fails if either skin names a receipt renderer or the rollback outside it.

## Changed

**A setup review is printed by a CLI path.** It was composed in full and emitted only under `--json`,
which meant `--approve-setup-effects` approved a list the consumer had never been shown. The effect
list, the capabilities and the manual alternative now print at the terminal before approval is asked
for.

**A setup planning failure prints the failure.** It printed `planned=0, failures=1`. It now prints the
detail, the artifact key and the manual route. Counts still appear — after the content, not instead
of it.

**A failing build's transcript keeps its end.** `docker build` prints progress first and the error
last, so a head-truncated 512 characters was exactly the half that could not explain the failure.
Capture now keeps the tail, and where both ends carry meaning it keeps both with the middle elided.
The same helper is used at all three capture sites.

## Residues this release closes

Five of the findings `compatibility-v13` shipped open close, and the register
[`residue-register.md`](../testing/residue-register.md) is where their state now lives — not this
document, and not a release paragraph.

The plan for this work predicted six. The sixth was `LAF-61`, and this release does **not** move it:
`RR-3` shipped a probe for orphaned run directories, the live acceptance run measured it against a
real leftover directory, and it scans the project root while runs are created under the data root
(`LAF-66`). The claim answers `true` without looking. `LAF-61` is open, and so is the probe defect
that briefly made it look otherwise.

| Finding | Now | Established by |
|---|---|---|
| `LAF-52` — a planning failure reported as a number | `closed` | `marketplace setup` at a terminal prints the failure |
| `LAF-53` — nothing reverses a setup that succeeded | `closed` | `aart marketplace receipt undo` |
| `LAF-54` — the review composed and never printed | `closed` | the review prints before approval is asked for |
| `LAF-55` — an unattended Keychain step stores nothing and reports success | `closed` | `receipt verify` asks whether the item holds a value |
| `LAF-59` — a transcript truncated from the wrong end | `closed` | a build failing on its last instruction reports that instruction |

## Known defects shipped open

`LAF-58` is the one this release could have been expected to close and does not. A `preexisting`
image tag keeps its name through an undo and points at what the run built, because
`_docker_build_apply` inspects the tag before building only to learn *whether it exists* and reads the
id *after*. The earlier binding was never written down, so no reader can restore it. What this release
does instead is **say so in the undo review, before consent** — the tag is named, the fact that it is
not removed is stated, and so is the reason. Closing it is a capture-site change tracked as `RR-4A`.

`LAF-63` — credential redaction misses every namespaced name, so `GITHUB_TOKEN=…` is printed *and
persisted* in full — was found while building this release and ships open. It is a defect in
`_SENSITIVE_ASSIGNMENT`, whose pattern anchors on a word boundary that does not exist inside
`GITHUB_TOKEN`. A test holds the gap visible so it cannot be assumed closed.

The rest of what is open is in the register, with a disposition each. This document does not
enumerate it, because a second list is how the first one stops being true.

## Upgrade notes

None. There is no state migration, no re-`build`, and no index recompilation. `2.5.0` and `2.6.0`
read each other's data roots.

A consumer on `2.5.0` who reads a `2.6.0` registry sees no difference: this release publishes nothing
new into an index.
