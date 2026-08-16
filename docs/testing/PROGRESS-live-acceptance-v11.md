# Live acceptance v11 — progress

Twelfth live acceptance run. Subject: `LAF-47` and `RS-10`, the merge file uninstall emptied and left
behind. Methodology unchanged: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs;
the [v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4–v10
records are on their own unmerged branches and are therefore not linked from here.

**Status: agent scope complete for `LAF-47` and `RS-10`.** Five scenarios, five passes, nothing
blocked. No credentials, no network, no terminal. **Two new findings**, both recorded and not fixed.

## What this run establishes

The design note for this fix reasoned from the code. This run measures the file system, which is
where the finding was made in the first place — `LAF-47` is a `git status --porcelain` observation,
not a code reading.

1. **Both sides are walked.** `venv-main` holds a wheel built from `main`; `venv-branch` holds a
   wheel built from the branch. Same registry, authored by the `main` wheel and committed before
   either was pointed at it.
2. **The observation is discriminating.** After install and uninstall of the same two artifacts, in
   the same clean repository, `main` leaves `?? .claude/` and `?? .mcp.json` and the branch leaves
   nothing.
3. **The refusals were measured, not asserted.** A file that existed before the install survives it
   byte-identical. A file AART created that an operator has written into survives with their key.
4. **The limit was walked too.** The design names one case it does not close. It reproduces exactly,
   and the asymmetry is now on the record in both directions.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/uninstall-removes-the-file-it-made` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel size / sha256 | 542 648 bytes; `73426b33ecce6d1e094d39f2689419afbfc90b5516d9c7942d5da14d5a146fd7` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home`, shared by both executables; the real `~` is neither read nor written for this run |
| Registry | `$LAB/reg`, source id `lab-registry`, a real git checkout; `mcp/atlassian`, `mcp/jira`, `hook/guard`, all scaffolded and built by the `main` wheel |
| Consumer projects | one fresh git repository per scenario under `$LAB`, each clean before the walk |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove --force`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## Scenario map

| id | scenario |
|---|---|
| `LA-U-31` | The created merge file goes with its last identity |
| `LA-U-32` | The same for a list merge |
| `LA-U-33` | The operator's own file is never removed |
| `LA-U-34` | A created file holding anything else is kept |
| `LA-U-35` | Reclamation depends on uninstall order |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-U-31` | **pass** | `LAF-88` | Clean repository, `marketplace install lab/mcp/atlassian lab/hook/guard --profile claude --yes`, then uninstall both. `main`: `git status --porcelain` reports `?? .claude/` and `?? .mcp.json`. Branch: no output — clean. The `.mcp.json` that `main` leaves is `{"mcpServers":{}}` |
| `LA-U-32` | **pass** | — | Same walk, the `hook` half. `main` leaves `.claude/settings.json` as `{"hooks":{"PreToolUse":[]}}`; the branch removes it. `RS-10` is right that both merge modes are affected — `key` leaves an empty object, `list` an empty array |
| `LA-U-33` | **pass** | — | `.mcp.json` written as `{"mcpServers":{}}` and **committed before any install**. Install, uninstall: the file is still there and `git status --porcelain` is empty, so it is byte-identical to what the operator committed. `created_destination` is `false` for it and the first condition excludes it before anything else is looked at |
| `LA-U-34` | **pass** | — | Install, then add `"$schema": "https://example.invalid/mcp.json"` at the document root by hand, then uninstall. The file survives as `{"$schema":"…","mcpServers":{}}` — the operator's key intact, the container emptied. The same walk with nothing added removes the file, on the same executable |
| `LA-U-35` | **pass** | `LAF-89` | Two `mcp` artifacts installed in **separate** commands: the record shows `atlassian created_destination=True`, `jira created_destination=False`. Uninstall in install order and `.mcp.json` survives as `{"mcpServers":{}}` with `?? .mcp.json` untracked. Repeat in reverse order — `jira` first, `atlassian` last — and the file is removed and the repository is clean. The design names this case; it behaves exactly as named |

## Findings

| id | severity | scenario | component | what | reproduction |
|---|---|---|---|---|---|
| `LAF-88` | low | `LA-U-31` | uninstall teardown | **The emptied directory outlives the file it held.** After the last uninstall the branch removes `.claude/settings.json` and leaves `.claude/` behind, empty. `git status --porcelain` is clean because git does not track empty directories, so the `LAF-17` standard is met and the directory is still there. `ls -la` shows it holding nothing | clean repo, install one `hook`, uninstall it, `ls -la .claude` |
| `LAF-89` | low | `LA-U-35` | uninstall, merge destinations | **Whether the created merge file is reclaimed depends on uninstall order.** `created_destination` is per effect; the second artifact into one file records `false`, and the record carrying `true` is deleted by the first uninstall. Install order leaves the file, reverse order removes it. Named in `DESIGN-uninstall-file-reclamation.md` §4 as the case the fix does not close, and measured here | install two `mcp` artifacts in separate commands, uninstall in each order, compare |

Neither was fixed in this run. Both are residues of the walk, recorded in the register as `open`.

## What this run does not establish

- **Nothing about user scope.** Every scenario is `--scope project`. The case that matters at user
  scope is `~/.claude.json`, which on any real machine predates AART and is therefore excluded by the
  first condition — but that was reasoned, not walked, because walking it means writing into a real
  home directory.
- **Nothing about `managed-block` or `write-file` destinations.** They already reclaim what they
  emptied and were not re-measured.
- **Nothing about the TUI.** It dispatches the same uninstall request, so the behaviour should
  follow, but that path is human-gated and was not walked.
- **Nothing about a merge under a deeper path than two levels.** `hooks.PreToolUse` is the deepest
  chain any shipped profile uses, and that is what was walked.
