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
| `LAF-61` | medium | `2.5.0` live acceptance | `visible` | `RR-3`; `receipt verify` names an orphaned run directory and does not remove it |
| `LAF-62` | medium | `2.5.0` publication | `deferred` | — cluster C4; needs the index-version boundary stream |
| `LAF-63` | high | implementing `RR-2A` | `open` | — `tests/setup_render_test.py::test_laf63_a_prefixed_credential_name_is_not_redacted_today` holds the gap visible |
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
