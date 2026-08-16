# Live acceptance v12 — progress

Thirteenth live acceptance run. Subject: `RS-02`, the dead compatibility window stamped on every
registry request that is not `init`. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4–v11
records are on their own unmerged branches and are therefore not linked from here.

**Status: agent scope complete for `RS-02`.** Five scenarios, five passes, nothing blocked. No
credentials, no network beyond a local `git init`, no terminal. No new findings from the walk; one
finding was made reading the code before it and is recorded in the register, not here.

## Why this run exists, and what it can and cannot show

`RS-02` deletes values. Nothing read them, so nothing a user sees changes — and a walk that expects
a visible difference would be dishonest about that. This run is here for the two things unit tests
genuinely cannot cover:

1. **`cli.py` gained an import.** The fix gives the compatibility window one definition and has the
   flag skin import it. `cli.py` is the entry point: an import that resolves under the test runner
   and not under an installed wheel is a failure every unit test passes through. `LA-R-37` is that
   check and it is the reason this run was worth its minutes.
2. **The claim of inertness is measurable.** `LA-R-40` runs the same scaffold under a `main` wheel
   and under the branch wheel and compares the trees. Identical is the pass condition here, which is
   the reverse of the usual reading: a difference would mean the deleted values were not dead after
   all, and the register row would be wrong.

`LA-R-38`, `LA-R-39` and `LA-R-41` walk the one path that does read a window — `init` — end to end,
from the documented default through the written manifest to the validator that reads it back.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/registry-requests-stop-stamping-dead-bounds-rs02` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel size / sha256 | 542 306 bytes; `f367c89216e7089145c1e44e8963646cd736e55d64506f8710bdcc278525a6e5` |
| Comparison executable | `e3894fe` (`main`), built the same way, 542 151 bytes, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home`, shared by both executables; the real `~` is neither read nor written for this run |

Unlike v1–v3, which ran published release assets, this is a **pre-release run against a locally
built wheel**. The digest above is the artifact that was installed and walked, not a release.

## Scenarios

Stressor `LAS-61` — *a compatibility window declared by a release that is no longer the running
one*. The literals `1.0.0` and `2.0.0` were correct while AART was `1.x`. The executable moved and
they did not.

| ID | Result | What was observed |
|---|---|---|
| `LA-R-37` | `pass` | `aart --version` prints `agent-artifacts 2.6.0` from both venvs. The entry point imports with the window now coming from `curation.model` |
| `LA-R-38` | `pass` | `registry init --help` documents `default: 2.6.0` and `default: 3.0.0` on both executables. The flag skin no longer derives the ceiling itself; it prints the same one the boundary uses |
| `LA-R-39` | `pass` | `registry init --yes` writes `"requires_aart": {"max_exclusive": "3.0.0", "min_inclusive": "2.6.0"}` into `aart-registry.json`. Identical from both wheels — `init` was already correct, and this run is what says so rather than assuming it |
| `LA-R-40` | `pass` | `registry scaffold mcp atlassian --profile claude --platform darwin --yes` under each wheel, into two registries authored the same way; `diff -r` excluding `.git` reports no difference. The deleted values reached no file |
| `LA-R-41` | `pass` | `registry validate --source .` on the branch-authored workspace prints `registry validate: passed`, exit `0` |

## Findings

None from the walk.

One finding was made **before** the walk, reading the code the fix touches, and is recorded in
[residue-register.md](residue-register.md) as `LAF-90`: the curses wizard offers the same two
literals, `1.0.0` and `2.0.0`, as its defaults for `registry init` — where they are not dead at all.
It is not part of this package and was not fixed.

Both halves of it were measured here without a terminal, because the wizard's question loop takes
its reader as an argument:

- `_prompt_curation_request(CurationAction.INIT, …)` driven by a scripted reader that accepts every
  offered default returns `minimum_version="1.0.0"`, `maximum_version="2.0.0"`, against a
  `2.6.0` executable.
- Writing exactly that window into the `aart-registry.json` of the registry authored in `LA-R-39`
  and re-running `registry validate --source .` gives `registry validate: failed` /
  `error: registry workspace is incompatible with this AART version`.

So a registry initialised through the wizard, by an operator who accepts what the wizard suggests,
is refused by the AART that created it. What remains human-gated (design §10) is only the screen
itself. **What the human has to do:** run `aart` on a real TTY, choose Maintainer → Init, press
return at both version prompts, finish the wizard, and read `requires_aart` out of the file it
writes — confirming the shipped curses path reaches the same values this reproduction reaches
headlessly.

## Teardown

Both venvs, both wheels, both registries and the `main` worktree were removed after the run. The
worktree came out with `git worktree remove --force`; the sandbox `HOME` never pointed at the real
one.
