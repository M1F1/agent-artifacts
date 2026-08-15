# AART 2.6.0

A setup run has always written down exactly what it did. The plan hash, the installer hash, when it
started and finished, how it exited, and one receipt per step — module, target, disposition, and the
detail — redacted, bound to the reviewed plan, written atomically under a lock. It has been there
since `2.2.0`.

Nothing could look at it.

`aart marketplace uninstall` reported `setup skipped` and left the image tag, the keychain item and
the shell block where they were, while every effect's review line promised `removes only changes
created by this run`. The remediation for that finding said *undo them from the receipt, which
records exactly what was done*. The receipt did. There was no command.

This release adds the reader.

## `receipt show` — what the run actually did

```sh
aart marketplace receipt show company/mcp/github --profile claude
```

The persisted record, rendered: plan hash, installer hash, timings, exit status, and every step with
its module, target, disposition and detail. Nothing is recomputed and no lock is taken, so it can be
read while an unrelated install is in flight.

Three absences get three sentences, because an operator holding a refusal needs to know which one they
are in: the artifact was never installed, it is installed and no setup run was recorded for it, or the
record it points at is gone.

## `receipt verify` — whether any of it is still true

```sh
aart marketplace receipt verify company/mcp/github --profile claude
```

For each receipt, one question put to this machine. Does the tag exist and still resolve to the
recorded image id. Does the file still carry the block that was installed. Does the Keychain item
exist — **and hold a non-empty value**.

That last one is the reason this command exists. `security add-generic-password -w` with no terminal
attached exits 0 having stored nothing, and every check downstream agrees the item is there. The
receipt faithfully records a step that reported success. The only way to learn the truth is to ask the
Keychain, and nothing asked. Now something does; the probe measures the length and discards the value.

**Three statuses, not two.** A claim `verify` could not put — no daemon, no login session, an
unreadable path — is `unknown` and never `true`. A verifier that quietly passes what it cannot see is
worse than no verifier. Exit is non-zero when any claim is false, so it works from CI.

`verify` reports and never repairs. An orphaned run directory left by a killed process is named, and
left exactly where it is.

## `receipt undo` — the rollback, from outside a failing run

```sh
aart marketplace receipt undo company/mcp/github --profile claude
aart marketplace receipt undo company/mcp/github --profile claude --yes
```

`rollback_record` already existed — with its ownership checks and its plan binding — and ran exactly
once, on the failure path inside a run. This wires it to the persisted record.

It is a mutation, so it takes the same boundary as every other mutation: without `--yes` it prints
what it would reverse and changes nothing, and `--expect <digest>` binds the decision to the exact
undo that was read.

The review names every effect it will reverse **and every effect it will not, with the reason**:

```text
keeps: aart/mcp/github:1.0.0
  step    1
  module  docker.build@1
  reason  the tag named an image before this run, so it is not removed — but it now points
          at what this run built, and the receipt never recorded the earlier image id, so
          the undo cannot restore the original binding (LAF-58)
```

That is a defect this release does not fix, said out loud before consent. An operator who reads it
beforehand is not surprised by it afterwards, which is the difference between a known limit and a bug.

## The review is printed where the decision is made

`marketplace setup` composed a complete review — effects, capabilities, entrypoint, trust, and the
manual route to `SETUP.md` — and emitted it under `--json` only. At a terminal it printed counts. So
`--approve-setup-effects` approved a list the operator had never been shown, and a planning failure
read `planned=0, failures=1`.

The rule now is: **where the JSON payload holds a detail, an artifact key, a remediation or a manual
alternative, the text renderer prints it. Counts may accompany that content and may not replace it.**

And a path with nothing to report says that it checked — `Setup: no selected artifact declares a
setup recipe; nothing to configure.` — because success that prints nothing is indistinguishable from
a flag that was dropped.

## A failing build reports the instruction that failed

`docker build` prints progress first and the error last, so truncating a transcript to its first 512
characters kept exactly the half that cannot explain the failure. Capture now keeps the tail, and
where both ends carry meaning it keeps both with the middle elided — at all three capture sites,
because a rule applied at two of three is how this comes back.

## One redactor, and it runs at the exits

There were two, with different rules, and neither was a superset of the other. The weaker of them was
the one on the path that writes the persisted record — so a credential could be correctly hidden on
screen and written out in full to a file, in the same run.

They are now one function. It hides a credential name with any prefix (`COMPANY_GHE_TOKEN=`, not only
`TOKEN=`), a credential in a URL's userinfo or query string, and a credential-shaped value standing
alone with no name beside it — which is the form a `git clone` failure actually prints, and the one
form the other three rules cannot reach. Detection is by shape and never by entropy, so the digests
and plan hashes a receipt exists to carry are returned untouched.

**Nothing about how a secret is collected changed, because nothing about it was wrong.** `security
add-generic-password -w` is invoked with no value after the flag, so the `security` tool prompts at
the terminal without echo and reads the value directly. The token goes from your keyboard into the
Keychain; it never passes through AART. What `shell.env-from-keychain@1` writes into a shell profile
is a lookup — the question, not the answer.

**A record written before this release is reported, not repaired.** `verify` says a record contains
credential-shaped text, without printing the value, and says that deleting it and re-running setup is
the only thing that removes it. Rewriting a persisted record would destroy the thing receipts exist
to be.

The test that holds this is written against the **exits** rather than the call sites: known values are
planted where a run would meet them, the real machinery runs, and every channel is checked — the
record in memory, the persisted record read back as bytes, the working copy during and after a run,
the three `--json` payloads, the text they render to, and the review. The payload walks are
structural, so a field added later is covered without anyone remembering to extend the test. That is
the property the persisted record did not have when it grew the field this defect escaped through.

## Both front-ends, one implementation

All three actions are in the Action menu of the line-oriented and the full-screen front-end. Both call
one function, and a test fails if either skin renders a receipt on its own — because a maintainer
action that exists in one skin and not the other is half-shipped, and one that exists in both with two
implementations is worse.

## Upgrading

Nothing to do. No state migration, no re-`build`, no index recompilation. A `2.5.0` data root is fully
readable by `2.6.0`, and a `2.6.0` data root is fully readable by `2.5.0`.

This is the first release in three with **no obligation for a registry maintainer** in either
direction. Nothing here publishes into an index; every command it adds reads a file under the
consumer's own data root.

The v14 schema freeze differs from v13 in one input — `agent_artifacts/setup.py`, a rename and the
departure of the redaction rules to a module that parses nothing — and carries identical protocol
versions. That is the machine-checked statement that no boundary moved.

## Known defects shipped open

- **A pre-existing image tag keeps its name through an undo and loses its binding** (`LAF-58`). The id
  it pointed at before the run was never recorded. Named in the undo review before consent.
- **A killed run's working copy is not swept** (`LAF-61`). `receipt verify` now names it and where it
  is; removing it is still yours to do, deliberately — deciding when AART may delete something it may
  not own is a separate question.
- **An older record keeps text this release would no longer write** (`LAF-73`). `receipt show` on a
  record written before this release prints the old `rollback` sentence, and nothing reports the
  disagreement. The same shape as the credential case below, without the answer.
- The two installation routes still disagree on image identity (`LAF-57`).

What is open is recorded in [`residue-register.md`](../testing/residue-register.md), with a disposition
and — where something closed — the reproduction that closed it. `docs-check` fails if any current plan,
design or compatibility document disagrees with it. That register is this release's answer to a finding
about the project rather than the code: closure was recorded in prose, so a cross-reference over 58
findings misclassified 50 of them, and items were re-discovered instead of resolved.

## Verifying this release

```sh
python scripts/version.py check-tag v2.6.0
python scripts/release.py wheel-digest
```

The wheel attached to this release is byte-reproducible from the tagged commit; its digest is printed
above.

## Not in this release

The index-version boundary (`LAF-62`) and the rehearsal refusals (`LAF-43`, `RS-03`) are untouched.
They need their own stream, and folding them in here would have made this a list again.
