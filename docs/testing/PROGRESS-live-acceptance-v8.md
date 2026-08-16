# Live acceptance v8 — progress

Ninth live acceptance run, and a short one. Subject: `LAF-45`, the `registry audit --check-upstream`
whose success prints nothing. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
(`RS-12`), v5 (`LAF-75`), v6 (`LAF-73`) and v7 (`RS-07`) records are on their own unmerged branches
and are therefore not linked from here.

**Status: two passes, one blocked.** The blocked one is the interesting half, and it is blocked by
`LAF-43` — vendoring refuses a local repository, so a registry holding a real vendored package
cannot be built in a sandbox without publishing content to a remote this run is not allowed to
touch. One finding recorded and not fixed: `LAF-87`.

## What this run establishes

The unit tests prove the line is produced. What they cannot show is the thing the finding is
actually about: that on a real executable, run the way CI runs it, *the flag made no difference to
the output at all*.

1. **Both sides are walked.** `venv` holds the wheel built from the branch; `venv-before` holds a
   wheel built from `main`. Same registry, same commands.
2. **The observation is exact.** On `main`, the audit's output with `--check-upstream` and its
   output without the flag are **byte-identical** — `diff` reports no difference. On the branch they
   differ by exactly one line.
3. **The envelope carries it too.** `--json` reports the same statement as
   `severity: info, code: registry-audit-note`, so a CI job that reads JSON sees it without parsing
   prose.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/audit-upstream-says-it-checked-laf45` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel size / sha256 | 542 927 bytes; `6f0e2f89e13f870992d99908c6bff1451cc312fb36d19f5e62270ecc6b90beea` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home`; the real `~` is neither read nor written for this run |
| Registry | `$LAB/registry`, a copy of the `registry-v1` protocol fixture — one owned skill, nothing vendored |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## Scenario map

| id | scenario |
|---|---|
| `LA-R-31` | A completed upstream check says so |
| `LA-R-32` | The same audit without the flag |
| `LA-R-33` | The counts on a real vendored copy |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-R-31` | **pass** | — | Branch: `registry audit: passed` followed by `info: no vendored artifacts to check against upstream` and the three pre-existing warnings, exit `0`. `--json` reports it as `registry-audit-note` at severity `info`, and `ok` stays `true` |
| `LA-R-32` | **pass** | — | The same command without `--check-upstream` prints the three warnings and no note. On the branch the two outputs differ by that one line; on the `main` wheel they are **byte-identical**, which is the finding as an operator meets it |
| `LA-R-33` | **blocked** | `LAF-43` | A registry holding a real vendored package needs an upstream the runner controls. `registry vendor` refuses `file://` and plain paths — *Git source location must be credential-free HTTPS/SSH* — and this run may not publish content to a remote. Covered hermetically instead: `tests/registry_vendor_license_test.py` drives the whole audit through the real CLI with the acquirer supplied at the network boundary, for `up-to-date`, `changed` and `unreachable`. **Not** covered live, exactly as `LA3-D-04` and `LA3-X-03` were not |

## Findings

Recorded, not fixed, per the run rules.

- **`LAF-87` — the stressor namespace has no home, and three unmerged branches collided in it.**
  `live-acceptance-scenarios.md` carries a stressor register that stops at `LAS-30`, and reads as if
  the next free number were `LAS-31`. It is not: `LAS-31`..`LAS-40` are defined in the v2 record,
  `LAS-41`..`LAS-48` in v3, and `LAS-49`..`LAS-56` in the setup-build record — each run appended its
  new stressors to its own progress document instead. Three branches of this overnight run took
  `LAS-31` (the `LAF-75` run), `LAS-32` (`LAF-73`) and `LAS-33` (`RS-07`) for new meanings while
  those ids already mean *a data root written by the previous release*, *a subscription ended while
  its artifacts are still installed*, and *an origin re-declares its identity*. Nothing detects
  this: no gate reads the stressor ids, and the collision is invisible until someone reads two
  documents at once. This run starts at `LAS-57` and states the arithmetic in the scenarios file;
  the three branches still need renumbering before they merge, and that is a separate package.

## What this run does not establish

- Nothing about the counts. Every live scenario here ran against a registry with **zero** vendored
  artifacts, so the singular/plural forms and the three counters are proved by unit test only.
- Nothing about a registry whose vendored copy is behind or unreachable — same reason, `LAF-43`.
- Nothing about `registry validate`, which shares the report renderer but never resolves an origin.
