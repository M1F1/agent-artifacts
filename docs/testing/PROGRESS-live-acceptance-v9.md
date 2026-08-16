# Live acceptance v9 — progress

Tenth live acceptance run. Subject: `RS-08`, the malformed `aart-registry.json` that skipped the
identity check instead of failing it. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
(`RS-12`), v5 (`LAF-75`), v6 (`LAF-73`), v7 (`RS-07`) and v8 (`LAF-45`) records are on their own
unmerged branches and are therefore not linked from here.

**Status: agent scope complete for `RS-08`.** Three scenarios, three passes, nothing blocked. No
credentials, no network, no terminal: a local source, one marker file, and the four states it can be
in. No new findings.

## What this run establishes

The unit tests prove the refusal fires. What they cannot show is what the silence *cost* — that on
the earlier executable the subscription is admitted, an artifact installs from it, and the consumer's
own manifest ends up recording an identity that nothing corroborated.

1. **Both sides are walked.** `venv` holds the wheel built from the branch; `venv-before` holds a
   wheel built from `main`. Same source tree, same commands.
2. **The observation is discriminating.** With the same broken marker, `main` prints `source added:
   la; snapshot published` and the branch refuses with exit `1`.
3. **The cost is measured, not asserted.** On `main` the run continues: `marketplace install`
   succeeds and `.agent-artifacts/manifest.json` records `declared_id: la-rs08-source` — an identity
   read from `aart-source.json` alone, while the registry document that exists to corroborate it
   could not be read at all.
4. **The refusal does not destroy anything.** A subscription that was healthy when it was made and
   whose marker breaks later fails its *sync* and keeps its last-known-good snapshot.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/broken-registry-descriptor-fails-rs08` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel size / sha256 | 542 843 bytes; `b9119a5af3e19c29a5cd481aba428e3eb6a21a482929bcff01d0dac5f6e4d8f1` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home` (branch) and `$LAB/home-before` (`main`); the real `~` is neither read nor written for this run |
| Source | `$LAB/source`, source id `la-rs08-source`, added as `source-local` under alias `la`; a real native source tree on disk, seeded from the `native-source-v1` protocol fixture with its identity renamed |
| Consumer project | `$LAB/consumer` (branch), `$LAB/consumer-before` (`main`) |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## Scenario map

| id | scenario |
|---|---|
| `LA-S-14` | An unreadable registry marker is refused |
| `LA-S-15` | The same break upstream, at sync |
| `LA-S-16` | A source with no marker is unaffected |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-S-14` | **pass** | — | Three shapes, three refusals, exit `1` each, nothing left in `source list`. A document missing a required field: *aart-registry.json is present and does not parse, so the identity this source declares cannot be checked: missing required field 'default_channel'*. Bytes that are not JSON: the same sentence ending *invalid JSON: Expecting value*. A **directory** under that name: *is present and is not a regular file*. Both remediation lines appear each time. `main`, same source, same command: `source added: la; snapshot published`, exit `0`, then `marketplace install` succeeds and the manifest records `declared_id: la-rs08-source` |
| `LA-S-15` | **pass** | — | Subscribed and installed while the source carried no marker, then a broken marker was written upstream. `source sync --alias la` reports `la: failed` with the same refusal and exits `1`; `source list` still shows `la … healthy; configured`, `marketplace status` still reports the installation `current`, and `.claude/skills/code-review` is still on disk. The refusal withholds a republish; it does not take away what the operator already has |
| `LA-S-16` | **pass** | — | The same source with no `aart-registry.json` at all: `source added: la; snapshot published; default=no`, exit `0`. Absence is not the case this refusal answers |

## Findings

None. Nothing surfaced during this walk that was not already the subject.

## What this run does not establish

- Nothing about the registry path (`--kind registry-git`). There the workspace validation already
  refused a broken marker before this check is reached, which is why `RS-08` was confined to the
  direct and local paths; that pre-existing refusal was not re-measured here.
- Nothing about a marker that parses but disagrees — that is `LAF-37`, closed in `2.2.0` and covered
  by `tests/identity_agreement_test.py`.
- Nothing about the TUI Sources stage. It dispatches the same application request, so the refusal
  should follow, but that path is human-gated and was not walked.
