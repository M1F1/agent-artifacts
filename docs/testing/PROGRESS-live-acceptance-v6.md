# Live acceptance v6 — progress

Seventh live acceptance run. Subject: `LAF-73`, the record written before `2.6.0` that still tells
an operator there is no undo. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
(`RS-12`) and v5 (`LAF-75`) records are on their own unmerged branches and are therefore not linked
from here.

**Status: agent scope complete for `LAF-73`.** Four scenarios, four passes, nothing blocked. This
subject needs no credentials, no daemon and no terminal: the recipe writes one managed block into a
sandbox home. Two findings recorded and not fixed: `LAF-84` and `LAF-85`.

## What this run establishes

The unit tests prove the claim is planned and answered. They cannot show that a *real* record on
disk, written by a real run, is read by a real executable and produces the report — and that the
report's advice is a command that actually reverses the setup. That is what this walks.

1. **Both sides are walked.** `venv` holds the wheel built from the branch; `venv-before` holds a
   wheel built from `main`. Same sandbox, same record, same command.
2. **The observation is discriminating.** The aged record makes the two executables disagree by
   exactly one claim: `main` reports `true=3, false=0`; the branch reports `true=3, false=1` and
   names the command that works.
3. **The advice is executed, not admired.** The command the claim prints is run, and the file the
   setup created is gone afterwards.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/receipt-verify-stale-rollback-laf73` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel sha256 | `3674e1c9d74408d1c52d920607bd839ca0e5e9583c9d41aa1b7542be50daa8b7` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home`; the real `~` is neither read nor written for this run |
| Registry | `$LAB/registry`, source id `la-laf73`, added as `source-local`; **never pushed** |
| Consumer project | `$LAB/consumer` |
| Artifact | `mcp/notes`, one `file.managed-block@1` step writing `~/.notes-profile` |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| `$LAB/home/.notes-profile` written by the setup | removed by the undo in `LA-M-15`, which is the scenario |
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## Scenario map

| id | scenario |
|---|---|
| `LA-M-12` | A fresh record verifies its own rollback line |
| `LA-M-13` | A record written before the undo command |
| `LA-M-14` | The earlier executable says nothing |
| `LA-M-15` | The advice the claim gives works |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-M-12` | **pass** | — | A real `marketplace setup` wrote the block and the record. `receipt verify` reports `true: the rollback command this record recorded` — *this executable accepts the recorded rollback command* — among `true=4, false=0, unknown=0` |
| `LA-M-13` | **pass** | `LAF-85` | With `rollback_command` set to the pre-`2.6.0` sentence, `verify` reports `false` and prints *the command that reverses this setup today is: aart marketplace receipt undo mcp/notes --profile claude --scope user --yes*. Exit status `1`. The record file's sha256 is identical before and after: `8683d932…` both times — reported, never rewritten |
| `LA-M-14` | **pass** | — | The `main` wheel, same record, same command: `Verification: true=3, false=0, unknown=0`, and no claim about the rollback line at all. The branch reports `true=3, false=1` |
| `LA-M-15` | **pass** | `LAF-84` | The command the claim names was run: `Undo: reverses=1, keeps=0`, and `~/.notes-profile` no longer exists. `receipt show` still prints the old sentence out of the record, which is the design — the record is evidence |

## Findings

Recorded, not fixed, per the run rules.

- **`LAF-84` — a completed undo leaves the receipt reading `skipped`.** After `receipt undo`
  succeeds, the record's status is `skipped` with detail *Setup rollback completed*, so
  `receipt show` says `status skipped` and the undo's own last line reads `Undo outcome: skipped —
  Setup rollback completed`. In this vocabulary `skipped` means *setup did not run*. What happened
  is that it ran and was reversed, and there is no status that says so.
- **`LAF-85` — something wrote to the real user data root during this session, and it was not the
  quality gates.** `~/Library/Application Support/agent-artifacts/state/object-references.json`
  and the object shard directories have mtimes of `23:34`–`23:36` on `2026-08-15`, inside this
  unattended run's window, while every live scenario ran under a sandbox `HOME`. Measured
  afterwards: `make integration`, `make unit`, `make validate` and `make packaging-check` each
  touched **zero** paths under that root. So the gates are clear and the writer is unidentified.
  The same timestamp was noticed during the `RS-12` iteration and set aside; it is recorded here
  because an unexplained write to a user's real state during an unattended run is exactly the kind
  of thing that should not be set aside twice.

## What this run does not establish

- Nothing about records written by `2.5.0` *in the field*. The aged record here was produced by
  taking a real record and setting one field to the string `2.5.0` wrote, which is the shape of the
  case; it is not an archaeological artefact recovered from an old machine.
- Nothing about `receipt show`. It still prints the recorded sentence, deliberately — the record is
  evidence of what a run reported. Whether `show` should point at `verify` is a separate question
  and was not answered here.
- Nothing about the keychain or docker claims: this recipe touches neither.
