# Live acceptance v5 — progress

Sixth live acceptance run. Subject: `LAF-75`, the release command that printed the digest of a wheel
it then deleted. Methodology unchanged: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md)
governs; the [v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
record — the `RS-12` run — is not linked because it is still on its own unmerged branch; both
branches are cut from `main` and neither depends on the other.

**Status: agent scope complete for `LAF-75`.** Four scenarios, four passes, nothing blocked — this
subject needs no credentials, no daemon and no terminal. Two findings recorded and not fixed:
`LAF-80` and `LAF-81`.

## What this run establishes

`LAF-75` is a defect of *evidence*, not of behaviour: both wheels install, both report `2.6.0`, and
the tool works either way. What fails is the claim that the published digest describes the published
file. A unit test can assert that the command writes a file whose bytes hash to what it printed; it
cannot show that the file a publisher would otherwise have attached is a **different one**. That is
what this run shows, by walking both routes on one machine.

1. **Both sides are walked.** `$LAB/old` is a clone of `main` (`e3894fe`); `$LAB/new` is a clone of
   the branch (`1c659a3`). The comparison is not across machines or dates.
2. **The observation is discriminating.** On the old side the command prints a digest and leaves an
   empty tree, so the only file a publisher can attach is the one `build_wheel.py` produces — and
   that file hashes to something else. Both numbers are recorded below.
3. **The emitted wheel is installed, not just hashed.** A file with a matching digest that does not
   install would satisfy the letter of the fix and none of its purpose.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `1c659a3` (`fix/wheel-digest-emits-what-it-hashes-laf75`) |
| Comparison executable | `e3894fe` (`main`), one commit earlier in effect — the only difference exercised is `scripts/release.py` |
| Wheel emitted by the new command | `agent_artifacts-2.6.0-py3-none-any.whl`, 542 189 bytes |
| Its sha256 | `e552d4732c83c2403c4982721baeabb67f57171ca9222616a328cc8c72845a79` |
| The wheel `build_wheel.py` produces beside it | same name, 542 151 bytes, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from the emitted wheel |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| `$LAB` | a scratch directory outside the repository |

No network, no daemon, no registry, no keychain: nothing this run touches is remote.

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| Two git clones and a venv under `$LAB` | outside the repository; removed with `$LAB` |
| `dist/` inside those clones | inside `$LAB`, never the repository's own `dist/` |
| The repository worktree | untouched — every command ran in a clone |

## Scenario map

| id | scenario |
|---|---|
| `LA-0-07` | The digest describes a file that exists |
| `LA-0-08` | The earlier executable leaves nothing |
| `LA-0-09` | The emitted wheel is the publishable one |
| `LA-0-10` | A stale wheel in `dist/` is replaced |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-0-07` | **pass** | — | `wheel-digest` printed `sha256:e552d473…  agent_artifacts-2.6.0-py3-none-any.whl` and `wrote $LAB/new/dist/agent_artifacts-2.6.0-py3-none-any.whl`; `shasum -a 256` of that path returned `e552d473…`. Run again with `--output $LAB/attach`, the same digest and a second copy — the value is a property of the commit, not of the destination |
| `LA-0-08` | **pass (reproduces the defect on the old side)** | — | `main`'s `wheel-digest` printed `sha256:8ed1226d…` and left no `dist/` at all. `python scripts/build_wheel.py` then produced a wheel of the same name hashing `fcdf95d9…`. One checkout, one command sequence, two numbers: this is the shape of the mistake `2.6.0` came within one `curl` of publishing |
| `LA-0-09` | **pass** | — | `pip install --no-index` of the emitted wheel into a clean venv; `aart --version` → `agent-artifacts 2.6.0`; `_commit.COMMIT` → `1c659a344b5708d6e96696931eeb51cd46cfd473`, equal to the checkout's `HEAD`, and `COMMIT_EPOCH` → `1786831659`. The `build_wheel.py` wheel beside it carries `COMMIT = "unknown"`, `COMMIT_EPOCH = 0`, and dates its members `1980-01-01` |
| `LA-0-10` | **pass** | `LAF-80`, `LAF-81` | With `dist/` already holding the unstamped `fcdf95d9…`, `wheel-digest` replaced it: after the run, `dist/` holds `e552d473…` under the same name — the file the digest describes. The trap closes even for a publisher who built first and read the digest second |

## Findings

Recorded, not fixed, per the run rules.

- **`LAF-80` — `make wheel` leaves the checkout dirty and no document says so.** `make wheel` runs
  `scripts/inject_commit.py`, which rewrites the *tracked* `agent_artifacts/_commit.py` with a real
  sha. `git status` afterwards reports ` M agent_artifacts/_commit.py`, and
  `wheel-reproducibility-v1.md` — which recommends `make wheel` as the way to verify a published
  wheel — never mentions restoring it. A verifier who follows the document and then runs
  `release check`, or switches branches, is carrying a modification they did not make.
  Observed: `git status --porcelain=v1` empty before, ` M agent_artifacts/_commit.py` after.
- **`LAF-81` — `wheel-digest` builds from the working tree and stamps `HEAD`.** The copy it builds
  from is the checkout as it stands, uncommitted changes included, while the stamp written into it
  is `git rev-parse HEAD`. On a dirty checkout the result is a wheel that claims a commit it does
  not contain. This was true before this change; what the change alters is that the claim now
  **persists as a file** in `dist/` rather than vanishing with the temporary directory. The
  checklist's `git checkout v<tag>` step is the current defence, and a defence a human has to
  remember is what this register calls a defect.

## What this run does not establish

- Nothing about a **published** release. No tag was cut and no asset was uploaded; the next release
  is the first time this command's output reaches a GitHub release, and the checklist step that
  compares the attachment against the printed digest stays until it has.
- Nothing about `release check` as a whole — only the `wheel-digest` subcommand was walked.
- Nothing about other platforms: one macOS host, one Python. Byte-reproducibility across hosts is
  the standing claim of `tests/packaging_test.py::ReproducibleWheelTest` and was not re-measured
  here.
