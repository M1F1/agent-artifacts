# Live acceptance v7 — progress

Eighth live acceptance run. Subject: `RS-07`, the `marketplace status` that refuses when the last
source subscription is removed. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
(`RS-12`), v5 (`LAF-75`) and v6 (`LAF-73`) records are on their own unmerged branches and are
therefore not linked from here.

**Status: agent scope complete for `RS-07`.** Three scenarios, three passes, nothing blocked. The
subject needs no credentials, no network and no terminal: a local source, one installed skill, and
the removal the product itself tells an operator to perform. One finding recorded and not fixed:
`LAF-86`.

## What this run establishes

The unit test proves `status` answers after the only subscription is removed. It cannot show that
the *operator's* way out is open — that the report names the coordinate, and that the coordinate it
names is the one `uninstall` accepts while no source exists. That is what this walks.

1. **Both sides are walked.** `venv` holds the wheel built from the branch; `venv-before` holds a
   wheel built from `main`. Same source tree, same project, same commands.
2. **The observation is discriminating.** After the removal, `main` refuses `status` with
   `no-source-configured` and exit `1`; the branch reports `source-unavailable` and exits `0`.
   Nothing else about the two runs differs.
3. **The exit is executed, not admired.** The coordinate `status` prints is passed to `uninstall`,
   with no source configured, and the installed file is gone afterwards.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/status-names-the-missing-source-rs07` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel sha256 | `941fae3ddd592a30659adf3c06b027e0a817307823374928f2cb735a9349dc2c` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home` (branch) and `$LAB/home-before` (`main`); the real `~` is neither read nor written for this run |
| Source | `$LAB/source`, source id `la-rs07-source`, added as `source-local` under alias `la`; a real native source tree on disk, seeded from the `native-source-v1` protocol fixture with its identity renamed |
| Consumer project | `$LAB/consumer` (branch), `$LAB/consumer-before` (`main`) |
| Artifact | `la/skill/code-review@1.0.0`, installed `copy` into `.claude/skills/code-review` |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## Scenario map

| id | scenario |
|---|---|
| `LA-S-11` | The project is still readable after the last subscription goes |
| `LA-S-12` | Fetching still refuses without a source |
| `LA-S-13` | The lifecycle closes without a source |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-S-11` | **pass** | — | Branch: `Status outcome: no-op / Selected: 1; source-unavailable=1` and `la/skill/code-review@1.0.0#claude/project: source-unavailable — recorded source unavailable`, exit `0`; JSON `ok: true`, one item, `status: source-unavailable`, `key` carrying the coordinate. `main`, same sequence: `error: this content operation requires at least one enabled source`, exit `1`. In both runs `.claude/skills/code-review/SKILL.md` is on disk throughout |
| `LA-S-12` | **pass** | — | With no source configured, `marketplace install la/skill/code-review --yes`, `marketplace update` and `marketplace list` each exit `1` with `no-source-configured` and the remediation naming `aart source add --help`. `marketplace setup la/skill/code-review` refuses the same way. The exemption reaches `status` and `uninstall` and nothing else |
| `LA-S-13` | **pass** | `LAF-86` | `marketplace uninstall la/skill/code-review --profile claude` reviewed and exited `0` without changing anything, then `--yes` reported `Selected: 1; removed=1`. The project tree afterwards holds no file at all, and the next `status` exits `0` with `Selected: 0` |

## Findings

Recorded, not fixed, per the run rules.

- **`LAF-86` — `uninstall` without a coordinate points at a command that cannot answer.** Run
  `aart marketplace uninstall --profile claude` with nothing else and the refusal advises *run `aart
  marketplace list --json` to see available coordinates*
  ([marketplace.py:342](../../agent_artifacts/commands/marketplace.py)). `list` browses what the
  configured sources offer, not what this project installed, and with no source configured it
  refuses outright — measured above in `LA-S-12`. So the operator who has just removed their last
  subscription is told to run the one command that cannot help them. `status` is what answers, and
  after this branch it answers in exactly that situation; the remediation still names `list`. This
  is `RS-07`'s neighbour and is deliberately not repaired inside `RS-07`'s package.

## What this run does not establish

- Nothing about the curses front-end. The Sources stage's Remove action dispatches the same
  application request, and the exemption lives in the request the command builds, so the behaviour
  should follow — but that path is human-gated and was not walked.
- Nothing about `--scope user`. The whole walk is project scope; the `content_required` gate does
  not read scope, so there is no reason to expect a difference, and no measurement of one either.
- Nothing about a *disabled* source, as opposed to a removed one. `source disable` leaves the
  configuration entry in place, which is a different state from the empty one walked here.
