# Design: the receipt has a reader

An operator can read what a setup run actually did, ask whether it is still true, and undo it — from
the record AART already writes.

Composed response to [`residue-stream-2026-08-15.md`](../testing/residue-stream-2026-08-15.md), which
gathered twenty-eight deferred items from `2.2.0`..`2.5.0` into six clusters. This design answers
three of them (C1, C2, C3) and deliberately leaves two alone.

## 1. The barrier this removes

AART writes a complete account of every setup run and offers no way to look at it.

The account is not a sketch. `SetupStateRecord` carries the plan hash, the installer hash, start and
finish timestamps, exit status, a retry command, a rollback command, and a per-step `receipt`
(`model.py:204`). `_record_to_dict` serialises all of it, with secrets redacted, into the setup state
file (`setup.py:1400`), and `LocalSetupAdapter.persist_setup` writes that file atomically with the
install-state pointer and the CAS reference, under a lock, with compensation on failure
(`setup_engine/io.py:89`). Each receipt is bound to one exact reviewed effect by
`receipt_matches_plan`, which checks module, step id, target path, and — for the Keychain module —
service and account (`setup.py:1276`). `rollback_record` replays a record's receipts in reverse
order with ownership checks (`setup_runtime.py:1331`).

Every part of an undo therefore exists, is tested, and runs. It runs exactly once, on the failure
path inside a run: `recovery = rollback_record(applied, runtime) if applied.receipt else applied`
(`setup_engine/application.py:692`).

**`agent_artifacts/cli.py` contains no occurrence of `receipt` and none of `rollback`.** Nothing
outside a run ever reads what a run wrote.

That single gap is what six shipped findings describe from six directions:

- `LAF-54` — the setup review is composed and never printed by any CLI path.
- `LAF-52` — a setup planning failure is reported as a count.
- `LAF-59` — a failing build's transcript is truncated from the front, losing the failing instruction.
- `LAF-53` — nothing reverses a setup that succeeded, though the review line promises it does. Its
  remediation says *undo them from the receipt* and names no command, because there is none.
- `LAF-58` — a pre-existing tag keeps its name and loses its binding; rollback restores neither.
- `LAF-55` — an unattended Keychain step stores an empty secret and reports success, and nothing ever
  re-reads the record to ask whether the success was real.

## 2. Why this is one change and not six

The six are not six defects in six components. They are one absence — no reader — seen from whichever
component the operator happened to be standing in.

Fixing them individually produces six surfaces: a printer for the review, a different printer for the
failure, a transcript window, an undo verb for setup, a tag-specific repair, and a Keychain probe.
Each would re-derive from the record what the record already states, and each would be free to
disagree with the others about what happened. The design claim is that **one reader over one
persisted record is both smaller and more honest than six projections of it.**

## 3. What is added

One command family, `aart setup receipt`, with three actions. All three are read paths over existing
state except where stated.

### 3.1 `receipt show`

Prints the persisted record for an installation: plan hash, timings, exit status, every step with its
module, target and disposition, and the failure detail in full when there is one.

New logic: none beyond rendering. The data is in the setup state file today. This is `LAF-54`,
`LAF-52` and `LAF-59` at once — the transcript is not truncated in the record, only in the one line
that currently reports it.

### 3.2 `receipt verify`

Re-reads what each receipt claims and reports whether it is still true: does the tag still exist and
still point at the recorded image id; does the managed block still carry the recorded digest; does
the Keychain item exist **and hold a non-empty value**.

New logic: yes, and this is the only genuinely new mechanism in the design. It is also the answer to
`LAF-55` — the receipt faithfully records a Keychain step that exited 0, and the only way to learn it
stored nothing is to ask the Keychain. `verify` asks.

`verify` reports; it never repairs. A finding is a finding, exactly as `registry audit` treats one.

### 3.3 `receipt undo`

Calls `rollback_record` against the persisted record instead of the in-process one.

New logic: the wiring, the record lookup, and the review gate. Not the rollback — that function, its
ownership checks and its `receipt_matches_plan` binding are used unchanged. `LAF-58` is closed inside
it: a `preexisting` tag currently keeps its name and loses its binding, and the receipt records the
image id the tag pointed at before the run, so restoring the binding is a matter of reading a field
that is already written.

## 4. Review-first applies unchanged

`undo` mutates, so it is an action, so it stops after Review and changes nothing without `--yes`, and
its review states every effect it will reverse. `--expect <digest>` binds the decision, as `SI-1`
established. `show` and `verify` are read commands and never mutate — including never sweeping the
orphaned run directories `LAF-61` describes, which `verify` reports and leaves alone.

## 5. What this does not do

- **It does not make the receipt durable.** It already is. A design that claimed otherwise would be
  describing the first, wrong reading of the stream.
- **It does not touch the index-version boundary** (`LAF-62`, C4) or the rehearsal refusals
  (`LAF-43`, `RS-03`, C5). Those need their own stream.
- **It does not delete anything the operator may own.** `RS-10` and `LAF-47` — the emptied merge file
  — become *visible* to `verify` and are still not removed, because deciding when AART may delete a
  file that predates it is the separate question `PLAN-subscription-identity-binding` recorded.
- **It adds no protocol version.** The setup state file's schema is unchanged; this design only reads
  fields that `_record_to_dict` already writes.

## 6. Acceptance criteria

1. On a project with a completed setup, `receipt show` prints the review that `LAF-54` says is never
   printed, including a failing step's full transcript.
2. On a setup whose Keychain step ran without a terminal, `receipt verify` reports the item as
   present and empty — the condition `LAF-55` says is reported as success.
3. `receipt undo` on a completed setup removes the image tag, the Keychain item and the shell block,
   and restores a `preexisting` tag's original binding.
4. `receipt undo` without `--yes` changes nothing and prints the effects it would reverse.
5. `receipt verify` reports an orphaned run directory and does not remove it.
6. Every one of the above is reachable with no flag that patches the executable, and is walked on a
   real machine in the live acceptance run for this release.
