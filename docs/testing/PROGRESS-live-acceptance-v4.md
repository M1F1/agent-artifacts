# Live acceptance v4 — progress

Fifth live acceptance run, and the first whose subject is a **fix rather than a feature**: `RS-12`,
the setup environment that gave the docker CLI no way to know who the user is. Methodology
unchanged: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten.

**Status: agent scope complete for `RS-12`.** Two scenarios pass, one added mid-run passes, two are
`blocked` for stated reasons — one needs credentials, one needs a second docker context, and the
agent supplies neither. One finding, `LAF-78`, recorded and not fixed.

## What makes this run different

The four prior runs asked what a command does. This one asks whether a **change** did what its unit
tests say, and it is built to answer that in the only way that settles it: the same scenario, on the
same machine, against two executables that differ by one commit.

1. **Both sides are walked.** `venv` holds the wheel built from `87b7fbb` (the fix); `venv-before`
   holds a wheel built from `e3894fe` — `main`, one commit earlier. Same version string, same
   recipe, same sandbox, same daemon.
2. **The observation is discriminating, not suggestive.** A pull that succeeds proves nothing about
   whether a config file was read. So the sandbox `config.json` names a credential helper that does
   not exist: a run that reads it must fail with that helper's name, and a run that ignores it
   cannot. That is `LA-M-08a`, added during the run.
3. **Nothing is mocked.** A real daemon, a real Docker Hub, a real registry index built by
   `aart registry` commands, a real consumer project.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `87b7fbb` (`fix/setup-docker-credentials-rs12`) |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl` (542 649 bytes), **built locally from the branch** — unlike v1–v3, this is not a published release asset, and no release exists that carries this fix |
| Wheel sha256 | `e96d60e2e35b5e2385a40407e0f69314ed7b0a98c779677e45f379d24707f32f` |
| `aart --version` | `agent-artifacts 2.6.0` — both executables report the same string; the version is not what distinguishes them |
| Comparison executable | `e3894fe` (`main`), built the same way into `$LAB/venv-before` (542 151 bytes) |
| Platform | macOS (darwin 25.2.0), Python 3.11 |
| Docker | Engine 29.5.2, context `desktop-linux` |
| Sandbox `HOME` | `$LAB/home` — the real `~` is neither read nor written; checked by timestamp afterwards |
| Registry | `$LAB/registry`, source id `la-rs12`, a local git checkout added as `source-local`; **never pushed** |
| Consumer project | `$LAB/consumer` |

`$LAB` is a scratch directory outside the repository.

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| `docker.io/library/hello-world@sha256:5dd0d3e6…` pulled (twice — once per executable) | `docker image rm`; the image was **absent before the run** and is absent after it |
| A git worktree at `$LAB/before` for the comparison build | `git worktree remove --force`; `git worktree list` shows only the repository |
| Everything else | lives under `$LAB`, outside the repository and outside the real `~` |

Nothing under `~/Library/Application Support/agent-artifacts` has an mtime inside this run's window.

## Scenario map

| id | scenario |
|---|---|
| `LA-M-08` | A docker step reaches a public image with the widened environment |
| `LA-M-08a` | The config file is actually read — added mid-run, because `LA-M-08` cannot tell |
| `LA-M-09` | A pull that is denied says so, in docker's words |
| `LA-M-10` | A private image with credentials — **blocked**, human-gated |
| `LA-M-11` | Rollback under a non-default context — **blocked**, needs a second context |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-0-0x` (harness) | pass (finding) | `LAF-78` | The rehearsal registry was authored with the shipped maintainer commands: `registry init` → `scaffold mcp private-base` → recipe → `format`/`lock`/`build` → `validate --strict --frozen: passed`. Reaching a setup-bearing artifact took four successive refusals, each correct and each naming exactly what was missing: the recipe must sit beside `artifact.json` and not inside `payload/`; `artifact.json` must declare `setup.recipe`; a package-root `SETUP.md` is required; `help_urls` is not optional. The refusals did their job — `scaffold` writing none of it is `LAF-78` |
| `LA-M-08` | pass | — | With the fix, `marketplace setup … --approve-setup-effects` pulls `hello-world@sha256:5dd0d3e6…` and reaches `configured`; `docker image inspect` finds the image afterwards where it found nothing before. The widened environment breaks nothing that worked |
| `LA-M-08a` | **pass — and this is the whole run** | — | Sandbox `$HOME/.docker/config.json` set to `{"credsStore":"aart-nonexistent"}`, image removed first, both executables run against the same recipe: **with the fix** the run fails `apply-failed-rolled-back` with `error getting credentials - err: exec: "docker-credential-aart-nonexistent": executable file not found in $PATH`; **without it** the same run reaches `configured` and pulls the image. A file that changes the outcome on one side and cannot be seen at all on the other is the difference `RS-12` names, measured rather than argued |
| `LA-M-09` | pass | — | A second artifact, `mcp/denied-base`, pinned to `docker.io/aartrs12private/nothing@sha256:1111…`, a repository this machine cannot read. **With the fix:** `Error response from daemon: pull access denied for aartrs12private/nothing, repository does not exist or may require 'docker login'`. **Without it:** `docker pull failed`. The first sentence tells an operator to log in; the second tells them nothing |
| `LA-M-10` | blocked | — | A pull that *authenticates* needs a real credential in a real store. The agent supplies no credentials (design §10). What the pass needs: `docker login` to the company registry, a recipe pinned to a private image, and `configured` as the outcome |
| `LA-M-11` | blocked | — | Needs a second daemon or docker context on the machine to show that rollback removes the tag from the context that holds it. The unit guard (`test_rs12_removing_a_built_tag_asks_the_daemon_that_built_it`) asserts the environments are equal; only a second context can show that the equality matters |

## Findings

*Recorded during the run, not fixed in it.*

| id | severity | seen at | surface | finding | reproduce |
|---|---|---|---|---|---|
| `LAF-78` | low | harness | `registry scaffold` | **`scaffold` cannot scaffold a setup-bearing artifact.** It writes `artifact.json` and a starter payload and stops. Every setup recipe in existence is therefore hand-written against a reference, and the shape is learned through four refusals — where the recipe file lives, the `setup.recipe` declaration, the package-root `SETUP.md`, the mandatory `help_urls`. Each refusal is correct and names its missing piece, which is why this is `low` and not higher: the maintainer is never misled, only slowed | `registry scaffold` any artifact, then try to give it a recipe without reading `setup-recipe-v2.md` |

## What this run does not establish

- That a pull **authenticates** against a private registry (`LA-M-10`). The evidence here is that
  the credential configuration is now *reached*; whether a real credential in it works is one
  human-gated step further.
- That the context half of `DOCKER_CONFIG` matters in practice (`LA-M-11`). The code keeps the run
  and its rollback on one environment; no second context existed to show the consequence.
- Anything about `LAF-76` — a `custom.install@1` script still runs with the narrow environment, and
  no scenario here exercises the custom route.
