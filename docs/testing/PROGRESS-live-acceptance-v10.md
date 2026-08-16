# Live acceptance v10 — progress

Eleventh live acceptance run. Subject: `RS-01`, the `mcp` package a maintainer writes themselves,
which no check ever looked at. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. The v4
(`RS-12`), v5 (`LAF-75`), v6 (`LAF-73`), v7 (`RS-07`), v8 (`LAF-45`) and v9 (`RS-08`) records are on
their own unmerged branches and are therefore not linked from here.

**Status: agent scope complete for `RS-01`.** Three scenarios, three passes, nothing blocked. No
credentials, no network, no terminal: one local registry, three `mcp` packages, and one consumer
project. No new findings.

## What this run establishes

The unit tests prove the new audit error fires. What they cannot show is the shape of the whole
situation: that the registry is authored entirely by the *old* executable, that nothing in it is
vendored, and that the artifact the audit now refuses is one a consumer installs successfully and
gets an empty entry from.

1. **Both sides are walked.** `venv-main` holds a wheel built from `main`; `venv-branch` holds a
   wheel built from the branch. Same source tree, same commands, same registry on disk.
2. **The registry is not the new executable's work.** `registry init`, `registry scaffold`,
   `registry lock` and `registry build` were all run from the `main` wheel and committed before the
   branch wheel was pointed at the result. Nothing about the finding can be an artefact of how the
   package was written.
3. **The observation is discriminating.** On the same registry, `main` prints `registry audit:
   passed` and exits `0`; the branch prints two errors, names both faulty packages, and exits `1`.
4. **The harm is measured, not asserted.** `LA-R-36` installs the refused artifact from a consumer
   project on the *branch* wheel. It installs. The project's `.mcp.json` ends up holding
   `"atlassian": {}` — a named server that starts no process. That empty object is the whole reason
   the audit error exists, and it is also why the check is not a load-time refusal.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `fix/owned-mcp-descriptor-is-checked-rs01` |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, **built locally from the branch** — no release carries this fix |
| Wheel size / sha256 | 542 714 bytes; `1c577cf066b84f7ab8145f8eda9791cba0eca7da06eafd3d95f0bcdee4dc66bd` |
| Comparison executable | `e3894fe` (`main`), built the same way, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home`, shared by both executables; the real `~` is neither read nor written for this run |
| Registry | `$LAB/reg`, source id `company-registry`, a real git checkout; three owned `mcp` packages, no vendoring, no external references |
| Consumer project | `$LAB/project` |

## Machine state this run mutates

| Mutation | Restore |
|---|---|
| A git worktree at `$LAB/main-src` for the comparison build | `git worktree remove --force`; `git worktree list` shows only the repository |
| Everything else | under `$LAB`, outside the repository and outside the real `~` |

## The registry under test

Three packages, each scaffolded by `registry scaffold --source $LAB/reg mcp <name>` on the `main`
wheel, then given a descriptor by hand — which is exactly how an owned `mcp` artifact is authored:

| package | `payload/mcp.json` | what a consumer would get |
|---|---|---|
| `mcp/atlassian` | `{"mcpServers": {"atlassian": {"command": "npx", …}}}` — the harness file's shape | a named entry containing `{}` |
| `mcp/jira` | `{"name": …, "server": {"command": "node", "args": ["payload/index.js"]}}` | a command naming a file that stays in the registry |
| `mcp/confluence` | `{"name": …, "server": {"command": "npx", "args": ["-y", "@atlassian/confluence-mcp"]}}` | a server the consumer's machine can start |

`confluence` is in the registry to hold the boundary: a check that fails a registry rather than a
package would be indistinguishable from one that works, on a registry where everything is broken.

## Scenario map

| id | scenario |
|---|---|
| `LA-R-34` | An authored descriptor that starts nothing is named |
| `LA-R-35` | An authored descriptor launching a withheld file |
| `LA-R-36` | The refusal stops at the maintainer's boundary |

## Results

| id | outcome | findings | evidence |
|---|---|---|---|
| `LA-R-34` | **pass** | — | Branch wheel, `registry audit --source $LAB/reg`: exit `1`, *error: mcp descriptor declares no server, so installing it writes an empty entry: mcp/atlassian needs payload/mcp.json shaped {"name": …, "server": {"command": …}}; a document shaped like the harness file it merges into installs and starts nothing*. `main`, same registry, same command: `registry audit: passed`, exit `0`, eight warnings, none of them about this. The sentence does not contain the word `vendored`, and there is nothing vendored in the registry to which it could refer |
| `LA-R-35` | **pass** | — | Same two runs. Branch: *error: mcp descriptor names a payload file consumers never receive: mcp/jira launches payload/index.js, and installing this artifact writes only the server entry from payload/mcp.json. State a command the consumer's machine already resolves*. `main`: silent. `mcp/confluence` is named by neither run: the two errors are the two faulty packages and no others |
| `LA-R-36` | **pass** | — | On the branch wheel and the same registry: `registry validate --strict --frozen` → `registry validate: passed`, exit `0` — deliberately unchanged, because that predicate is also the consumer's gate on a candidate source. Then from `$LAB/project`: `source add --alias lab --kind source-local` → `source added: lab; snapshot published`; `marketplace list` shows all three as `[healthy]`; `marketplace install lab/mcp/atlassian --profile claude --yes` → `Install outcome: succeeded`, exit `0`; and `$LAB/project/.mcp.json` contains `{"mcpServers": {"atlassian": {}}}`. The subscriber is not broken by the upgrade, and the empty entry is exactly what the maintainer is now told about before publishing |

## Findings

None. Nothing surfaced during this walk that was not already the subject.

## What this run does not establish

- **Nothing about vendored packages.** Their half of this check is `VI-4`/`VI-5`, shipped in `2.4.0`
  and covered by `tests/registry_vendor_delivery_test.py`; the message wording for a vendored package
  is unchanged and was not re-walked live.
- **Nothing about the marketplace's health vocabulary.** `marketplace list` labels the empty-server
  artifact `[healthy]` in `LA-R-36`. That is reconciliation health, not runnability, and it is the
  consequence of the `VI-5` decision to keep such a registry loading rather than a new defect — but
  it is the reason a consumer cannot see this for themselves, and the reason the maintainer's audit
  is where the check has to live.
- **Nothing about the setup path or the TUI.** Neither is involved in `registry audit`.
- **Nothing about a registry with a hundred `mcp` packages.** The check reads one descriptor per
  package during a walk the audit already performs; cost was not measured.
