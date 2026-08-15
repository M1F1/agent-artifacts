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

## 2. Two mechanisms, not one — and the correction that found the second

The first version of this design claimed all six C1/C2/C3 findings were one absence: no reader over
the persisted record. Checking each against the code refuted it for three of them, and the refutation
is what makes the design correct rather than tidy.

**`LAF-52` and `LAF-54` are not about the record at all.** Both findings say so in their own words:
for `LAF-52`, *the detail, the artifact key, and the offered manual route are all present in the
`--json` payload and none of them reach the human-readable output*; for `LAF-54`, *the complete review
is in the `--json` payload only*. Nothing is missing and nothing is unreachable. The text renderer
prints counts over a payload that already holds the answer, at the moment the operator is standing
there deciding whether to approve.

**`LAF-59` is not about the record either.** `_docker_build_apply` truncates at the point of failure:
`raise RuntimeError(detail[:512])` (`setup_runtime.py:436`). The tail — the failing instruction and
its exit code, which BuildKit prints last — is discarded before anything is persisted. There is no
whole transcript anywhere to render. The same head-truncation is applied at `setup_runtime.py:496`
and `:535`.

So this design carries two mechanisms:

| Mechanism | Findings | What it is |
|---|---|---|
| The text renderer must not summarise what `--json` carries | `LAF-52`, `LAF-54`, and the rule that keeps `LAF-45` from recurring | A rendering rule, applied where the operator is standing |
| The persisted record gets a reader | `LAF-53`, `LAF-58`, `LAF-55` | `marketplace receipt show`, `verify`, `undo` over `RR-1`'s read path |

And one repair that belongs to neither: `LAF-59` is fixed where the bytes are captured, by keeping
the end of a transcript rather than its beginning.

Splitting them this way is not a concession. Collapsing them would have produced a design whose
central claim — *the data is already there, expose it* — is true of three findings and false of
three, and the false half would have been discovered during implementation instead of during review.

## 3. What is added

One command family, `aart marketplace receipt`, with three actions. All three are read paths over
existing state except where stated.

**Named `marketplace receipt`, not `setup receipt`.** The first draft of this design wrote the
latter, and wiring it refuted the name: `setup` is already a `marketplace` lifecycle action, so a
top-level `aart setup` would make two different operations share one word. A receipt is a read over
one installation, which is what the `marketplace` family is for.

### 3.1 `marketplace receipt show`

Prints the persisted record for an installation: plan hash, timings, exit status, every step with its
module, target and disposition, and the recorded detail.

New logic: none beyond rendering — the data is in the setup state file today. What `show` does **not**
do is close `LAF-52` or `LAF-54`. Those are failures of the live path at the moment of consent, and a
second command the operator would have to know to run afterwards is not consent. They are closed by
§3.4, and `show` is what makes the same account readable again a week later.

`show` also cannot recover a transcript that was truncated before it was written; after `LAF-59` is
fixed at the capture site, `show` renders what capture kept.

### 3.2 `receipt verify`

Re-reads what each receipt claims and reports whether it is still true: does the tag still exist and
still point at the recorded image id; is the managed block still in the file, unchanged; does
the Keychain item exist **and hold a non-empty value**.

Two rows of this section's first draft did not survive contact with the receipts. `file.managed-block@1`
records no digest — it records `installed_block`, the literal text — so the check is a text comparison,
which is stronger than a digest and distinguishes *edited* from *removed*. And
`trust-store.export-certificates@1` records `output`, `subject_contains` and the certificate names,
and no digest at all, so existence is the only claim it licenses. A verifier must ask what the
receipt actually wrote down, and say `unknown` rather than `true` for anything it could not ask —
implemented as a third status, because a verifier that quietly passes what it cannot see is worse
than no verifier.

New logic: yes, and this is the only genuinely new mechanism in the design. It is also the answer to
`LAF-55` — the receipt faithfully records a Keychain step that exited 0, and the only way to learn it
stored nothing is to ask the Keychain. `verify` asks.

`verify` reports; it never repairs. A finding is a finding, exactly as `registry audit` treats one.

### 3.3 `receipt undo`

Calls `rollback_record` against the persisted record instead of the in-process one.

New logic: the wiring, the record lookup, and the review gate. Not the rollback — that function, its
ownership checks and its `receipt_matches_plan` binding are used unchanged.

**`LAF-58` is not closed here, and the reason is a premise of this design that was false.** The
draft said the receipt records the image id the tag pointed at *before* the run, so restoring the
binding would be a matter of reading a field already written. It does not. `_docker_build_apply`
inspects the tag before building only to learn **whether it exists** (`preexisting = inspect.returncode
== 0`, `setup_runtime.py:458`) and reads the id **after** the build (`setup_runtime.py:465`), so
`image_id` is the id the tag points at *afterwards*. The earlier binding is never recorded and cannot
be restored from the record.

Closing it needs the capture site to record the prior id — the same shape of change `RR-2B` made, and
outside `RR-4`, whose whole claim is that it adds no new field. So `RR-4` does the one thing it can do
honestly: **the undo review says so out loud**, naming the tag, saying it will not be removed, and
saying that the original binding cannot be restored. An operator who reads that before approving is
not surprised by it afterwards, which is the difference between a known limit and a defect.

### 3.4 The text renderer stops summarising what `--json` carries

A rule, not a feature: **where the JSON payload holds a detail, an artifact key, a remediation or a
manual alternative, the text renderer prints it.** Counts may accompany that content and may not
replace it.

This is `LAF-52` and `LAF-54`, and it is applied at `commands/marketplace` where the operator is
standing when they decide. `render_setup_review` already composes the effect list, the capabilities
and the `Manual alternative` pointing at `SETUP.md`; the change is that a CLI path emits it, so that
`--approve-setup-effects` approves a list the human has seen.

The rule generalises the lesson of `LAF-45` — success that prints nothing is indistinguishable from a
flag that was dropped — so a path that has nothing to report says that it checked.

### 3.5 A transcript keeps the end that explains it

`LAF-59`, fixed where the bytes are captured: `docker build` prints progress first and the error last,
so a head-truncated 512 characters is exactly the half that cannot explain the failure. Capture keeps
the tail, and where both ends carry meaning it keeps both with the middle elided.

The same three call sites share the defect (`setup_runtime.py:436`, `:496`, `:535`) and the fix is one
helper used by all three, because a rule applied at two of three sites is how this recurs.

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

1. `marketplace setup` at the terminal — no `--json`, no second command — prints the effect list, the
   capabilities and the manual alternative before asking for approval, and prints a planning failure
   as the failure rather than as a count. `marketplace receipt show` prints the same account afterwards.
2. On a setup whose Keychain step ran without a terminal, `receipt verify` reports the item as
   present and empty — the condition `LAF-55` says is reported as success.
3. `receipt undo` on a completed setup removes the image tag, the Keychain item and the shell block,
   and restores a `preexisting` tag's original binding.
4. `receipt undo` without `--yes` changes nothing and prints the effects it would reverse.
5. `receipt verify` reports an orphaned run directory and does not remove it.
6. A build that fails on its last instruction reports that instruction and its exit code, not the
   dockerfile-transfer line that BuildKit printed first.
7. Every one of the above is reachable with no flag that patches the executable, and is walked on a
   real machine in the live acceptance run for this release.
