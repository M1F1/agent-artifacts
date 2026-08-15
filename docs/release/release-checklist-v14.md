# AART 2.6.0 release checklist and evidence

This minor release gives the persisted setup receipt a reader. `2.5.0` wrote a complete, redacted,
plan-bound account of every setup run — and shipped nothing that could look at it. Three actions now
can: `marketplace receipt show`, `verify`, and `undo`. Two rendering paths stop summarising what they
already held, and a failing build's transcript keeps the end that explains it.

The work was composed from [`residue-stream-2026-08-15.md`](../testing/residue-stream-2026-08-15.md),
which gathered twenty-eight deferred items from `2.2.0`..`2.5.0` into six clusters, against
[`DESIGN-readable-receipt.md`](../design/DESIGN-readable-receipt.md) and
[`PLAN-readable-receipt.md`](../plan/PLAN-readable-receipt.md).

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.6.0
python scripts/build_wheel.py
python scripts/release.py wheel-digest
```

The release check must pass repository/version evidence, schema freeze v14, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit, and
compatibility gates. The GitHub release must attach the wheel produced from the tagged commit, and
the release notes must carry the `sha256:<hex>  <wheel filename>` line
`python scripts/release.py wheel-digest` prints at the tag.

## Registry precondition

**None, in either direction.** This is the first release in three that adds no obligation to a
registry maintainer.

No index field changes, no capability vocabulary changes, and no module is added, so a registry built
on `2.5.0` validates on `2.6.0` and a registry built on `2.6.0` validates on `2.5.0`. Nothing here
publishes into an index at all: every command this release adds reads a file under the **consumer's**
data root. `release-check` is order-independent again — the ordering constraint `v13` introduced was a
consequence of the index-vocabulary fix and does not recur.

A consumer on `2.5.0` reading a `2.6.0` registry sees no difference. A consumer on `2.6.0` reading a
`2.5.0` registry sees no difference. The asymmetry `LAF-62` describes does not arise, because nothing
in this release changes what an index compiles to.

## Acceptance

The three actions read state that already existed, so acceptance is mostly a question of whether the
account is true — which is what `verify` was written to ask, and what the live run puts to a real
daemon and a real keychain.

`marketplace receipt show` reads the record from outside a run:

- resolution is by coordinate, profile and scope, with the `kind/name` tail accepted and ambiguity
  reported rather than resolved by picking the first — a receipt printed for the wrong installation
  reads exactly like a correct one;
- three absences get three sentences: never installed, installed with no setup run recorded, and a
  pointer whose target is gone. The middle one says *no setup run has been recorded for it* and not
  *it declares no setup*, because `InstallationRecord` carries nothing that would support the second
  claim — the first draft said it, and measuring it live refuted it;
- no lock is taken, so a `show` during an unrelated install does not block or fail;
- every value the `--json` payload carries appears in the text, checked structurally rather than
  against a list of field names, so a field added to the receipt and forgotten in the renderer fails
  the test without anyone remembering to extend it.

`marketplace receipt verify` asks, and reports what it could not ask:

- three statuses. A claim it could not put — no daemon, no login session, an unreadable path — is
  `unknown` and never `true`;
- the Keychain claim is *exists **and** holds a non-empty value*, which is `LAF-55`: `security
  add-generic-password -w` with no terminal exits 0 having stored nothing, and every check downstream
  agreed the item existed. The probe measures the length and discards the value; no secret enters
  AART, is printed, or is persisted;
- `file.managed-block@1` is verified by text comparison and not by digest, because the receipt records
  `installed_block` — the literal text — and no digest. That is stronger than a digest and
  distinguishes *edited* from *removed*. `trust-store.export-certificates@1` records no digest either,
  so existence is the only claim it licenses. Both were corrections to this design's first draft;
- the probe inherits the environment a setup run gets rather than a hardcoded `PATH`. Measured on
  `2026-08-15`: hardcoding it made every docker claim report `unknown` on a host whose daemon was
  running, because `docker` is at `/usr/local/bin`;
- exit is non-zero when any claim is false, so it is usable from CI;
- it reports and never repairs, proved by hashing `.zshrc` before and after a verify. That now
  includes a record written before the redactor was corrected: `verify` reports credential-shaped
  text in the record, names neither the value nor a repair, and leaves the file alone;
- the orphaned run directory it was meant to report (`LAF-61`) it now finds. The live run measured
  the probe scanning the project root while runs are created under the data root (`LAF-66`); it takes
  the run root the engine writes into, and answers `unknown` rather than `true` when it has no root
  to read. A test drives `new_run_directory` and `orphan_run_directories` together, and asserts the
  old location finds nothing, so the fix cannot pass by widening the search.

`marketplace receipt undo` is review-first, like every other mutation:

- without `--yes` nothing changes — proved by hashing both `.zshrc` and the persisted record file
  before and after a run without it;
- `--expect <digest>` binds the decision to the exact undo that was read; the interactive front-ends
  recompute the undo from disk after the answer and refuse if the digest moved;
- the review names every effect it will reverse **and every effect it will not, with the reason**.
  `plan_undo` is a projection of `_rollback_receipt`'s decisions, and a test holds the two together by
  running the real rollback against a fake runtime and requiring the prediction to match what actually
  happened, module by module;
- `rollback_record`, its ownership checks and its `receipt_matches_plan` binding are used unchanged. A
  step whose receipt no longer matches the reviewed plan is reported and skipped, never forced;
- on partial success the record is written back as `rollback_incomplete`, which the existing status
  already expresses.

Both front-ends reach all three:

- `receipt` is in the Action menu of the line-oriented and the full-screen skin, and is deliberately
  not a fifth wizard verb — it reads or reverses one artifact that is already installed, so it has no
  basket and no install mode;
- both call one function, and an AST guard fails if either skin names a receipt renderer, a
  projection, or the rollback outside it. Without that guard the second skin drifts, and the drift
  shows up as two different answers to the same question.

The renderer stops summarising:

- `marketplace setup` at a terminal, with no `--json`, prints the effect list, the capabilities and the
  manual alternative before asking for approval, so `--approve-setup-effects` approves a list the
  operator has been shown (`LAF-54`);
- a planning failure prints the detail, the artifact key and the manual route (`LAF-52`). Counts still
  appear — after the content, never instead of it;
- a path with nothing to report says that it checked, which is `LAF-45`'s lesson applied so it does not
  recur in a new command;
- a failing build reports the instruction that failed and its exit code (`LAF-59`), because capture
  keeps the tail. One helper, used at all three capture sites, because a rule applied at two of three
  is how this recurs.

## Evidence

Nine quality gates green. `docs-check` now carries four rules the previous release did not have —
`DOC006`..`DOC009` — which hold [`residue-register.md`](../testing/residue-register.md) and every
current plan, design and compatibility document in agreement about what is open.

The v14 schema freeze differs from v13 in **one input and no protocol version**:
`agent_artifacts/setup.py` — the `_public_text` → `public_text` rename, and the redaction rules
leaving for `agent_artifacts/redaction.py`, which parses nothing and is not a schema input. Verified
rather than asserted, and re-verified after `RR-10`: `protocol_versions` are equal between
`schema-freeze-v13.json` and `schema-freeze-v14.json`, and `setup.py` is still the only
`schema_inputs` entry whose digest moved.

The live acceptance run is recorded below when it has been walked, on a real machine, with a real
daemon and a real keychain, and with **no patched executable** — `2.5.0`'s run needed a patch to
observe anything at all (`LAF-51`), and Design §6 criterion 7 makes not repeating that a criterion
rather than a hope.

## Residues shipped open

Nine findings move out of shipped-open and close, and `LAF-61` becomes visible — five in this
release's first pass and the rest in the second, which the live acceptance run made necessary and
which [`compatibility-v14.md`](compatibility-v14.md) accounts for.
The state of every one of them is in [`residue-register.md`](../testing/residue-register.md), which
`docs-check` enforces, and **not** in this document — a second list is how the first stops being true.

One is worth naming here because it changes what an operator should expect:

- `LAF-58`: an image tag that existed before a run keeps its name through an undo and points at what
  the run built. The earlier binding was never recorded, so nothing can restore it. The undo review
  says so before consent, which is the difference between a known limit and a defect. Closing it is a
  capture-site change tracked as `RR-4A`.
