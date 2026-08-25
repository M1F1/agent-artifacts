# Residue stream — 2026-08-15

Everything four releases deferred, gathered into one stream and read as a single body of evidence
rather than as twenty-eight separate defects.

- **Input:** `compatibility-v13` §Known defects; the `Residues this plan records and does not own`
  sections of `PLAN-vendored-copy-integrity.md`, `PLAN-registry-vendoring.md`,
  `PLAN-subscription-identity-binding.md`, `PLAN-setup-build-context.md`; the per-release residue
  paragraphs in `PROGRESS.md`; and `LAF-62`, recorded 2026-08-15.
- **Output:** six clusters, one attractor, one composed residue — carried into
  [`DESIGN-readable-receipt.md`](../design/DESIGN-readable-receipt.md).

## What gathering the stream revealed before any item was read

There is no document that says what is open **now**.

`compatibility-v13` is the only compatibility document in the repository carrying a
`Known defects shipped with this release` section; `v10`, `v11` and `v12` have none. Everything else
is recorded as prose, in three different places with three different conventions: a plan's residue
section, a `PROGRESS.md` release paragraph, or a run-log line in a live-acceptance ledger. Closure is
recorded the same way — `LAF-28 closed` appears in a run log, not in a status column.

The mechanical consequence is measurable. A cross-reference over all 58 `LAF-*` findings against
every plan, release document and `PROGRESS.md` classifies 50 of them as *no closure statement found*,
which is not the truth: whole batches were closed by the `WP-1`..`WP-6` remediation and said so in
prose the matcher cannot see. **The register cannot be derived, so nobody can be sure what is open,
so items are re-discovered rather than resolved.** That is cluster 6 below, and it is the reason this
document had to be written by hand.

## The stream

Twenty-eight deferred items. `LAF-*` ids are as recorded in the live-acceptance ledgers; unnumbered
items were recorded in prose and are given a stream id here (`RS-*`) so they can be referred to at
all — which is itself part of the finding above.

### From `2.5.0` — shipped open, listed in `compatibility-v13`

| ID | One line |
|---|---|
| `LAF-52` | A setup planning failure is reported as a number, not as the failure |
| `LAF-53` | Nothing reverses a setup that succeeded, though every review line promises it does |
| `LAF-54` | The setup review is composed and never printed by any CLI path |
| `LAF-55` | With no terminal the Keychain step stores an empty secret and reports success |
| `LAF-57` | The two installation routes agree on content and disagree on image identity |
| `LAF-58` | `preexisting` protects a tag's name, not its meaning; rollback restores neither |
| `LAF-59` | A failing build's transcript is truncated from the front, cutting off the failing instruction |
| `LAF-61` | A killed run leaves its working copy under the data root, and nothing sweeps it |

### From `2.4.0` — recorded by `PLAN-vendored-copy-integrity`, owned by nobody

| ID | One line |
|---|---|
| `LAF-43` | Vendoring refuses a `file://` upstream, so `changed` and the symlink refusal cannot be rehearsed live |
| `LAF-45` | `audit --check-upstream` prints nothing when all is current: success is indistinguishable from a dropped flag |
| `LAF-47` | Uninstall leaves the `.mcp.json` it created, reduced to `{"mcpServers": {}}` |
| `LAF-49` | The allowlisted Git environment drops `https_proxy`, undocumented |
| `RS-01` | An owned, non-vendored `mcp` package with a wrongly-shaped descriptor is never checked |
| `RS-02` | `commands/registry.py` stamps dead `1.0.0`/`2.0.0` AART bounds on every non-`init` request |

### From `2.3.0` — recorded by `PLAN-registry-vendoring` and the `PROGRESS.md` release paragraph

| ID | One line |
|---|---|
| `RS-03` | A repository containing *any* symlink cannot be acquired at all, bounding vendoring more than the design rule does |
| `RS-04` | `vendor` is create-only, and its refusal cannot name `revendor`, the command that does adopt movement |
| `RS-05` | `io/cache.py` is unreferenced by shipping code |
| `RS-06` | `DESIGN-upstream.md` carries no superseded banner |

### From `2.2.0` — recorded by `PLAN-subscription-identity-binding`

| ID | One line |
|---|---|
| `RS-07` | `marketplace status` under a removed sole subscription refuses `no-source-configured` instead of reporting `source-unavailable` |
| `RS-08` | A snapshot carrying a *malformed* `aart-registry.json` skips the identity comparison entirely |
| `RS-09` | No `registry` refusal carries remediation at all — the field is empty in both renderers |
| `RS-10` | The last uninstall of a *merge* effect leaves the merge file behind |

### From `2.5.0`'s plan — format and protocol questions deliberately not opened

| ID | One line |
|---|---|
| `RS-11` | `inputs` accepts only `type: "secret"`; a recipe cannot prompt for a username |
| `RS-12` | Setup process steps run without `HOME`, so Docker reads no `config.json` and a private base image cannot authenticate |
| `RS-13` | No `shell.zshrc-managed-block@1`; the convenience module does not exist |
| `RS-14` | The recipe format has no comment convention, and every `_comment` was refused |
| `RS-15` | A package cannot carry an auxiliary script at its root |

### From `2026-08-15`

| ID | One line |
|---|---|
| `LAF-62` | A `≤2.4.0` consumer cannot `source add` a registry rebuilt on `2.5.0`; it fails before any artifact is named |
| `LAF-63` | Credential redaction misses every namespaced name — `GITHUB_TOKEN=…` and `AWS_SECRET_ACCESS_KEY=…` are printed and **persisted** in full |
| `LAF-64` | `_curses_install_scope` answers with two different types depending on a keyword argument, and the wrong one is silently a cancel |

`LAF-63` was found while implementing `RR-2A`, not during a run, and is recorded rather than fixed
there. `_SENSITIVE_ASSIGNMENT` (`setup.py:131`) opens with `\b(token|password|secret|api[_-]?key…)`,
and in `GITHUB_TOKEN` the position before `TOKEN` sits between two word characters, so no boundary
exists and no match is made. Measured: a bare `TOKEN` assignment redacts, a `GITHUB_TOKEN` one
does not,
`secret=abc` redacts, `AWS_SECRET_ACCESS_KEY=abc` does not. The prefixed forms are the ones real
recipes use. The same pattern is what `_redact` applies before writing the setup state file
(`setup.py:1400`), so this is a credential reaching disk, not only a terminal — which also means
`RR-2B`'s guarantee that redaction precedes truncation is intact and simply weaker than it reads.
`tests/setup_render_test.py::test_laf63_a_prefixed_credential_name_is_not_redacted_today` holds the
gap visible so it cannot be assumed closed.

`LAF-64` was found while implementing `RR-5`, by writing a second caller of a helper that had had
exactly one. `_curses_install_scope(…, wizard=True)` returns a `WizardInput` whose `selected` holds
the *index*; without `wizard=True` it returns the `InstallScope` itself. A new caller that writes the
obvious `if isinstance(result, WizardInput): return` compiles, typechecks, and silently treats every
successful selection as a cancel — which is what the first draft of `_run_receipt_curses` did, and
what its test caught. The existing call site (`tui.py:4269`) handles both shapes with eleven lines of
branching, so the defect is not that the shapes are unhandled but that handling them is the caller's
job and nothing says so. This is `C1`'s shape moved into the code: the function knows which mode it
is in and returns a type that does not.

**What is open today is not in this document.** This is a dated gathering; the answer to *what is
still true* is [`residue-register.md`](residue-register.md), which `docs_check` requires every current
plan, design and release document to agree with. That register is `RR-7`, and it is this stream's own
`C6` answered.

## Clusters

**C1 — The system knows more than it says.** `LAF-52`, `LAF-54`, `LAF-59`, `LAF-45`, `RS-09`,
`LAF-32`-shaped remediation loss. In each, a complete structured account exists in memory and the
operator-facing surface is a lossy projection of it: a count instead of the failure, silence instead
of a confirmation, the wrong end of a transcript, an empty `remediation` array. Nothing here is a
missing computation. Everything here is a discarded one.

**C2 — Nothing undoes what a run did.** `LAF-53`, `LAF-58`, `LAF-61`, `LAF-47`, `RS-10`. Teardown is
partial by construction: it reclaims what AART owns outright and abandons everything it shares with
the operator — a tag that existed before, a merge file that may have been theirs, a working copy left
by a killed process.

**C3 — A step that could not have succeeded reports success.** `LAF-55` above all: `security
add-generic-password -w` with no terminal exits 0 having stored nothing. `LAF-45` is the reporting
form of the same thing, `RS-08` the validation form — a malformed file skips the check instead of
failing it.

**C4 — A version boundary is invisible from both sides.** `LAF-62`, `LAF-60`, `RS-02`. The index
vocabulary splits at `2.5.0`, and neither the registry that rebuilt nor the consumer that did not
upgrade can see which side it is on until an unrelated command fails.

**C5 — The tool's own refusals block rehearsing the tool.** `LAF-43`, `RS-03`, and the patched
executable the `2.5.0` live run needed. What cannot be exercised locally is exercised for the first
time by a user.

**C6 — Deferred items have no register.** The finding above: disposition is prose, scattered across
three document families, and cannot be derived.

## The attractor

C1, C2 and C3 are one shape seen three times.

AART already computes, for every mutating action, a complete and canonical account of what it is
about to do and what it did: the review, the assessment, the receipt. `setup_runtime` builds a
receipt per step and `rollback_record` can already replay one — `receipt_matches_plan` binds it to
the reviewed plan, so the machinery for a bound undo exists and is exercised.

**The account is durable, and it has no reader.**

The first reading of this stream assumed the receipt was thrown away with the run directory, because
`_RunWorkspace.close()` removes it on success and failure alike (`setup_runtime.py:406`) and neither
`install_state/` nor `lifecycle/` mentions a receipt. That is wrong, and the correction is what makes
this composition worth doing. `_record_to_dict` serialises `"receipt": _redact(record.receipt)` into
the setup state file (`setup.py:1400`), and `LocalSetupAdapter.persist_setup` writes that file
atomically with the install-state pointer and a CAS reference, under a lock, with compensation
(`setup_engine/io.py:89`). The receipt survives the run, redacted, bound to a reviewed plan by
`receipt_matches_plan` (`setup.py:1276`), and `rollback_record` can already replay one
(`setup_runtime.py:1331`).

**`agent_artifacts/cli.py` contains no occurrence of `receipt` or `rollback`.** The only caller of
`rollback_record` is the failure path inside a run (`setup_engine/application.py:692`). So the
attractor is not that the truth is discarded — it is that **the truth is computed, verified,
persisted, and unreachable.** Every symptom in C1 is that record being projected lossily by the one
surface that does render something; every symptom in C2 is that record being unread when it is
exactly what teardown needs; `LAF-55` in C3 is that record faithfully recording a step which
reported success, with nothing that ever re-reads it to ask whether the success was real.

`LAF-53`'s remediation — *undo them from the receipt, which records exactly what was done* — is
therefore not false. It describes an object that exists, in a file the operator can find, and names
no command, because none exists.

## The composed residue

**Give the persisted account a reader, and let teardown, reporting and verification all be that
reader.**

Not eight fixes, and — this is the point — almost no new mechanism. The record is already written,
already redacted, already plan-bound, already replayable. What is missing is the last mile:

1. **`receipt show`** prints the persisted account, which is the review that `LAF-54` says is
   composed and never printed, and the failure detail that `LAF-52` reduces to a count and `LAF-59`
   truncates from the wrong end. The data is in the file today.
2. **`receipt verify`** re-reads what the receipt claims and reports whether it is still true. This
   is the only item needing genuinely new logic, and it is what turns `LAF-55`'s empty secret from an
   invisible success into a checkable one — the receipt records a Keychain item; asking the Keychain
   whether it holds anything is a question nothing currently asks.
3. **`receipt undo`** calls `rollback_record` against the persisted record rather than the in-process
   one — the same function, the same ownership checks, the same `receipt_matches_plan` binding,
   reached from outside a failing run. That is what `LAF-53` and `LAF-58` need, and it is a wiring
   change more than an implementation.

Ranked by what it reaches: `LAF-53`, `LAF-54`, `LAF-52`, `LAF-59`, `LAF-55`, `LAF-58` directly;
`LAF-61`, `LAF-45`, `LAF-47`, `RS-10` by giving teardown and reporting something to consult; C6 by
applying the same discipline to documents — a register that is derived rather than maintained.

Ranked by what it reaches: `LAF-53`, `LAF-54`, `LAF-52`, `LAF-59`, `LAF-55`, `LAF-61`, `LAF-58`
directly; `LAF-45`, `LAF-47`, `RS-10` by giving teardown something to consult; C6 by making the
open-residue register derivable from the same discipline applied to documents.

## What this composition does not answer

C4 and C5 are untouched by it, and saying so is part of the composition. A durable receipt does not
tell a `2.4.0` consumer which side of the index boundary it is on (`LAF-62`), and does not let a
`file://` upstream be rehearsed (`LAF-43`, `RS-03`). Those belong to a different stream, and folding
them in here would make the design a list again.
