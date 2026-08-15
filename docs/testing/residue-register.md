# Residue register

The single place that says what is open.

Cluster `C6` of [`residue-stream-2026-08-15.md`](residue-stream-2026-08-15.md) is that no document
answers that question: closure is recorded in prose — *"`LAF-28` closed"* in a run log, a sentence in
a release paragraph — so a cross-reference over all 58 `LAF-*` findings classifies 50 of them as *no
closure statement found*, which is not the truth. Items are then re-discovered rather than resolved.

This file exists so the answer is a lookup. It is enforced by `scripts/docs_check.py`, which fails
when a document names a finding this file does not carry, and when a document lists as *shipped open*
a finding this file records as `closed`. Documents may describe a finding at any length; they may not
disagree with this table about its state.

## Scope

**Seeded from the twenty-eight items of the `2026-08-15` stream, plus what implementing the response
to it found — not from all 58.** A register that claimed to cover a history it cannot reconstruct
would be the same defect one level up. Findings older than the stream are outside it, and a row is
added here the first time an older id is referred to again.

## Dispositions

| Value | Means |
|---|---|
| `open` | true today, and nothing in the shipped code addresses it |
| `closed` | no longer true, with the reproduction that establishes it in the last column |
| `visible` | still true, and now observable — reported by a command rather than repaired |
| `deferred` | out of scope by an explicit decision recorded in a design, not by neglect |

`visible` and `deferred` are *not* `closed`. A document may list either as shipped open.

## Checked documents

These are the documents `docs_check` requires to agree with the table below — a finding listed under
a *shipped open* heading in one of them must not be `closed` here:

- checked: `docs/plan/*.md`
- checked: `docs/design/*.md`
- checked: `docs/release/compatibility-v14.md`
- checked: `docs/release/release-checklist-v14.md`

**A release note is checked until it is published, and never after.** `github-release-v2.6.0.md` was
in this list while it was still the text about to be pasted into a release — a current document
making current claims. It was published on `2026-08-15` and the entry came out the same day, which is
the rule working rather than the rule being abandoned. `LAF-74` is what putting it here found, and
the next release note joins the list the moment it is written and leaves it the moment it ships.

**Released documents are deliberately absent.** `github-release-v2.5.0.md` and
`release-checklist-v13.md` list `LAF-52`..`LAF-59` as shipped open, and that was true when they
shipped. Editing them to agree with today would destroy the evidence they exist to be. A dated record
does not have to agree with the present; a current document does.

## Register

| ID | Severity | Found in | Disposition | Closed or made visible by |
|---|---|---|---|---|
| `LAF-43` | medium | `2.4.0` live acceptance | `deferred` | — cluster C5; `DESIGN-readable-receipt.md` §5 leaves it for its own stream |
| `LAF-45` | medium | `2.4.0` live acceptance | `open` | — the rule it teaches is applied to the new commands; `audit --check-upstream` itself is untouched |
| `LAF-47` | medium | `2.4.0` live acceptance | `open` | — see *Corrections* below |
| `LAF-49` | low | `2.4.0` live acceptance | `open` | — |
| `LAF-52` | high | `2.5.0` live acceptance | `closed` | `RR-2A`; `tests/setup_render_test.py`, and `marketplace setup` at a terminal prints the failure detail, the artifact key and the manual route |
| `LAF-53` | high | `2.5.0` live acceptance | `closed` | `RR-4`; `aart marketplace receipt undo <coordinate>` |
| `LAF-54` | high | `2.5.0` live acceptance | `closed` | `RR-2A`; `marketplace setup` without `--yes` prints the effect list, the capabilities and the manual alternative before asking for approval |
| `LAF-55` | high | `2.5.0` live acceptance | `closed` | `RR-3`; `receipt verify` asks the Keychain whether the item holds a non-empty value, `tests/setup_verify_test.py` |
| `LAF-57` | low | `2.5.0` live acceptance | `open` | — |
| `LAF-58` | medium | `2.5.0` live acceptance | `open` | — `RR-4` names the limit in the undo review before consent; closing it needs `RR-4A` at the capture site |
| `LAF-59` | high | `2.5.0` live acceptance | `closed` | `RR-2B`; a build failing on its last instruction reports that instruction and its exit code |
| `LAF-61` | medium | `2.5.0` live acceptance | `visible` | `RR-10D`; `receipt verify` names an orphaned run directory and removes nothing. Claimed `visible` once already on a probe that read the wrong root (`LAF-66`); the claim is made again on a test that drives the real writer and the real reader together |
| `LAF-62` | medium | `2.5.0` publication | `deferred` | — cluster C4; needs the index-version boundary stream |
| `LAF-63` | high | implementing `RR-2A` | `closed` | `RR-10A`; one redactor in `agent_artifacts/redaction.py`, matching a credential name with any prefix, `tests/setup_render_test.py::test_laf63_a_prefixed_credential_name_is_redacted` |
| `LAF-64` | medium | implementing `RR-5` | `open` | — |
| `RS-01` | medium | `2.3.0` prose | `open` | — |
| `RS-02` | low | `2.3.0` prose | `open` | — |
| `RS-03` | medium | `2.3.0` prose | `deferred` | — cluster C5, with `LAF-43` |
| `RS-04` | low | `2.3.0` prose | `open` | — |
| `RS-05` | low | `2.3.0` prose | `open` | — |
| `RS-06` | low | `2.3.0` prose | `open` | — |
| `RS-07` | medium | `2.2.0` prose | `open` | — |
| `RS-08` | medium | `2.2.0` prose | `open` | — |
| `RS-09` | medium | `2.2.0` prose | `open` | — the three receipt refusals all carry remediation, which is the rule rather than the fix; `registry`'s own refusals are untouched |
| `RS-10` | medium | `2.2.0` prose | `open` | — see *Corrections* below |
| `RS-11` | low | `2.5.0` prose | `open` | — |
| `RS-12` | medium | `2.5.0` prose | `open` | — |
| `RS-13` | low | `2.5.0` prose | `open` | — |
| `RS-14` | low | `2.5.0` prose | `open` | — |
| `RS-15` | low | `2.5.0` prose | `open` | — |
| `LAF-65` | medium | `2.6.0` live acceptance | `closed` | `RR-10E`; `rollback_command` names `receipt undo`, and `tests/setup_custom_test.py::WrittenCommandFieldTests` hands the written field to the shipped CLI parser so it cannot go stale again |
| `LAF-66` | high | `2.6.0` live acceptance | `closed` | `RR-10D`; the probe takes the run root the engine writes into, answers `unknown` when it has no root to read, and `tests/setup_verify_test.py::test_laf66_the_probe_reads_the_root_the_engine_writes_into` drives the real writer and the real reader together |
| `LAF-67` | medium | `2.6.0` live acceptance | `open` | — |
| `LAF-68` | medium | `2.6.0` live acceptance | `closed` | — [#1](https://github.com/M1F1/agent-artifacts-live-acceptance-project/pull/1) merged: the acceptance runner is on `2.6.0` and reconciles eleven installations against the published wheel, so `main` no longer pins a runner three releases behind the tool it exercises |
| `LAF-69` | high | using this register | `open` | — `DOC009` fails a document that calls a `closed` finding open, and not one that calls an `open` finding closed or visible |
| `LAF-70` | medium | triaging for `2.6.0` | `closed` | — the authoring machine runs `2.6.0`, installed from the published release asset after verifying its digest against `wheel-digest`. Registry A's CI gates at `2.5.0` and its pin move is the remaining half, tracked as `LAF-71` |
| `LAF-71` | medium | triaging for `2.6.0` | `closed` | — every pin in the constellation is `2.6.0` and merged: Registry B [#5](https://github.com/M1F1/agent-artifacts-registry-2/pull/5) against the real tag, the acceptance repository [#1](https://github.com/M1F1/agent-artifacts-live-acceptance-project/pull/1) against the published wheel, and Registry A's own three workflows [#10](https://github.com/M1F1/agent-artifacts-registry/pull/10) — the half that had no PR when this row said `visible` |
| `LAF-75` | high | publishing `2.6.0` | `closed` | `wheel-digest` writes the wheel it hashes (`dist/`, or `--output <dir>`) and reads the digest back from the written file, so the printed line describes the file left behind. `tests/release_test.py::WheelDigestArtifactTest`, and live `LA-0-07`..`LA-0-10` in [`PROGRESS-live-acceptance-v5.md`](PROGRESS-live-acceptance-v5.md): on `main` the command printed `8ed1226d…` and left nothing while the wheel a publisher then builds hashed `fcdf95d9…`; on the branch the printed `e552d473…` is the digest of the file in `dist/`, which installs and reports this commit |
| `LAF-80` | medium | fixing `LAF-75` | `open` | — `make wheel` rewrites the tracked `agent_artifacts/_commit.py`, so the verification route `wheel-reproducibility-v1.md` recommends leaves the checkout dirty and no document says to restore it |
| `LAF-81` | medium | fixing `LAF-75` | `open` | — `wheel-digest` builds from the working tree and stamps `HEAD`, so on a dirty checkout it emits a wheel claiming a commit it does not contain; true before the fix, and now durable as a file rather than discarded with the temporary directory |
| `LAF-74` | high | publishing `2.6.0` | `closed` | `docs/release/github-release-v2.6.0.md` added to the checked list while it is unpublished; `DOC009` then failed it for `LAF-63`, which is how the stale claim was found |
| `LAF-73` | medium | `2.6.0` live acceptance, second pass | `open` | — `receipt show` prints the pre-`RR-10E` rollback sentence from an older record while the same executable writes the correct command; `RR-10F` is the pattern for the answer, a claim in `verify` rather than a rewrite |
| `LAF-72` | high | measuring `LAF-63` | `closed` | `RR-10A`, `RR-10C`; there is one `redact_text` and `tests/token_containment_test.py` walks every string of the persisted record, so a field added later is covered without being named |

## Corrections this register forced

Writing the table refuted a claim of the design it records, which is the third time in this stream
that a premise did not survive being checked, and the reason the register is worth having.

`DESIGN-readable-receipt.md` §5 says `RS-10` and `LAF-47` — the merge file left behind, emptied —
*become visible to `verify`*. They do not. Both describe an **install** effect: the `.mcp.json` that
`marketplace uninstall` reduces to `{"mcpServers": {}}` and leaves. `plan_verification` reads a
**setup** record, and the one claim it makes for `json.managed-merge@1` is that the path exists — which
is `true` for an emptied file exactly as it is for a full one. Nothing in the shipped response makes
either finding observable, so both are `open` here and not `visible`.

The design sentence is wrong rather than imprecise, and it is left standing with this correction
beside it, because a design edited until it agrees with the code stops being evidence of what was
believed when it was written.

**`LAF-61` was recorded `visible` and the live run took it back.** `RR-3` shipped a probe for orphaned
run directories and this register recorded the finding as observable on the strength of it. `RR-9`
measured the probe against a real leftover directory and found it scanning
`<project_root>/.agent-artifacts/setup-runs` while runs are created under `<data_root>`
(`setup_engine/application.py:457`), so the claim answers `true` without looking — recorded as
`LAF-66`, and `LAF-61` is `open` again.

That correction is the register earning its place. Under the old regime the `visible` claim would have
lived in a release paragraph, agreed with nothing, and been re-discovered a release later as a new
finding. Here it had one row, the row was wrong, and the row changed.

**The release notes were wrong about the release, and the gate did not cover them.** `LAF-74`.
`github-release-v2.6.0.md` still listed `LAF-63` under *known defects shipped open* after `RR-10`
closed it, and told operators to *prefer recipes whose inputs are named without a namespace prefix
until it is fixed* — advice about a defect that is not there, in the text about to be published.
`docs-check` passed, because this list excluded released documents and a release note was assumed to
be one.

It is not, until it is published. Before that moment it is the most current document in the
repository and the only one an operator outside the project will read. Adding it to the list failed
`DOC009` immediately, which is the whole of the fix and the whole of the evidence.

The exclusion below is still right for what it was written for. What was wrong was the word
*released* doing two jobs: naming a document's genre, and asserting a fact about time. The entry
comes out the moment the release is published, and then the original rule applies to it unchanged.

**`LAF-61` is `visible` again, and this time on a different kind of evidence.** `RR-10D` gave the
probe the run root the engine writes into. The claim being made is the same claim `RR-3` made and
lost, so the thing worth recording is what changed about the *measurement*: the first claim rested
on a test that drove a fake probe, which proved the claim rendered and never proved the probe looked
anywhere real. The second rests on `test_laf66_the_probe_reads_the_root_the_engine_writes_into`,
which calls `new_run_directory` — the function a run actually uses — and then the real
`orphan_run_directories`, and then asserts the old location finds nothing, so the fix cannot pass by
widening the search. A claim is only as good as the thing that would falsify it, and the first one
had nothing.

**And the gate did not notice the row changing.** Moving `LAF-61` back to `open` left
`compatibility-v14.md` and `release-checklist-v14.md` both saying `visible`, and `make docs-check`
passed. `DOC009` is one-directional by construction: it fails a document that lists as *shipped open*
something this table records as `closed`, and says nothing about a document claiming `closed` or
`visible` for something this table records as `open` — the direction that asserts a safety which is
not there. Both documents were corrected by hand. That is `LAF-69`, and until it closes, the sentence
above about this file being *enforced* means enforced against stale pessimism only.
