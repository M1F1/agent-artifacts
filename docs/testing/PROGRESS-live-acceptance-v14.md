# Live acceptance v14 — progress

Fifteenth live acceptance run. Subject: the change after `2.8.4` — one shape for a queue, on both
surfaces (`AD-39`, `AD-40`, `AD-41`, `AD-42`). Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the earlier records are read
against this one and none of them is ever rewritten.

**Status: agent scope complete.** Both surfaces walked end to end, both sides of every claim
observed, nothing blocked. The curses screen stays human-gated (design §10): the wizard was walked
through its plain-text fallback over a pty with `TERM=dumb`, which is the same code path
(`_canonical_setup_run`) reaching the same renderers. No secret was typed by the walker; every
input in the fixture is declared `text`.

## What this run establishes

The register says the reload reminder repeats, that a queue never says whose turn it is, and that
the command line never saw a recovery note. Tests now assert all three. A test cannot show that an
operator watching a real three-server queue sees the difference, and it cannot show that the
release before this one really did print what the register claims it printed.

So both executables were walked over the same fixture:

1. **Two wheels, side by side.** `venv` holds a wheel built from this branch; `venv284` holds a
   wheel built from the released tag `v2.8.4` in a detached worktree. Every probe prints
   `agent_artifacts.__file__`, so the record shows which copy answered — the trap `v13` walked into
   and caught.
2. **The observation is discriminating.** Every claim below was seen to be **false on `2.8.4` and
   true on the branch**, over one fixture, one sandbox, one set of commands.
3. **Three artifacts, one selection.** This is the shape `AD-39` and `AD-40` were reported from and
   the shape no test covered: the existing queue test is one artifact across two profiles.

## Run header

| Field | Value |
|---|---|
| AART commit under test | the tree that became `<COMMIT>` (`feat/mark-where-each-setup-starts-and-ends`); no source file was edited between the build and the commit |
| Wheel | `agent_artifacts-2.8.4-py3-none-any.whl`, 581 642 bytes, **built locally** — no release carries this change |
| Wheel sha256 | `c8065fde91aec54ec5b94d6bc482a34dc0f88c3417dbb147c96c6d1ad491e90b` |
| Comparison executable | `d439b47` (tag `v2.8.4`), built the same way, 577 066 bytes, `90922839c5e6e8edb0289c1c8c186f6b47677eacf80bc41e8547661a86102aa1` |
| `aart --version` | `agent-artifacts 2.8.4` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | six throwaway homes under the scratch lab; the real `~` is neither read nor written for this run |
| Registry | one fresh `git init` checkout, three hand-written `mcp/*` artifacts, **never pushed** |

## The fixture, and why it is shaped this way

Three MCP artifacts in one local registry, selected together for one profile, so the queue is three
items:

| Artifact | Setup recipe | Why |
|---|---|---|
| `mcp/walk-alpha` | `shell.env-from-input@1` → `~/.zshrc`, then `restart.notice@1` | writes a shell file |
| `mcp/walk-beta` | `json.managed-merge@1` over a pre-seeded value, then `shell.env-from-input@1` → **the same** `~/.zshrc` | writes the same shell file, and produces a real `recovery` note by replacing a prior value |
| `mcp/walk-gamma` | `command.verify@1` running `/usr/bin/false` | one item fails, so the run carries a failure and a retry |

Two artifacts writing to one shell file is the whole of `AD-39`: the de-duplication inside one
receipt was always correct, and the queue reintroduced the repetition across receipts. The pre-
seeded JSON value is how a `recovery` note is obtained without Docker, without the Keychain, and
without a secret — the note `AD-42` says the command line never printed.

## Scenarios

| ID | Result | What was done | What was seen |
|---|---|---|---|
| `LA-0-13` | **pass** | wizard (text fallback over a pty), three artifacts in one selection, branch wheel | one `START` rule per item before any prompt — `walk/mcp/walk-alpha@claude (user) — setup 1/3 — START` — then a `SUMMARY` rule per item, then one `RUN SUMMARY` |
| `LA-0-14` | **pass** | the same wizard run on the `2.8.4` wheel | no boundary anywhere: `Setup input:` and five `Approve 1./2.` prompts arrive with no artifact named, effect numbering restarts at `1` three times, and the header is the prose line `Setup outcome: configured=2, incomplete=1.` |
| `LA-0-15` | **pass** | count the reload reminder in both wizard runs | `2.8.4`: **`Next step` printed twice**, once under alpha and once under beta. Branch: **once**, after the run summary, for two artifacts that both wrote `~/.zshrc` |
| `LA-0-16` | **pass** | `marketplace setup` for the three, text output, branch wheel | `START` rules on **stderr**; the report on stdout closes with `RUN SUMMARY`, `selected 3 / configured 1 / incomplete 2`, a `Not configured` block naming each failure, and one `Next step` |
| `LA-0-17` | **pass** | the same command with `--json`, branch wheel | stdout parses as **exactly one JSON document**; no rule ever entered it. `setup.items[]` carry `coordinate`, `profile`, `scope`, `successful`, `retry`, `recovery` beside the unchanged `key` |
| `LA-0-18` | **pass** | the same `--json` command on the `2.8.4` wheel | `items[]` carry `key`, `status`, `detail` and nothing else — **no `recovery`, no `retry`** — and `next_steps[]` holds **two rows**, each with a `key`, for one machine and one shell file |
| `LA-0-19` | **pass** | fresh run on the branch, read `setup.next_steps[]` | **one row**, `key` absent, `commands: ["source ~/.zshrc"]` — the path home-relative, from a receipt holding the absolute one |
| `LA-0-20` | **pass** | read the `recovery` note on the command line, branch wheel | `Recovery / Restore the prior value manually at …` reaches `marketplace setup` for the first time, in the text report and in the payload |
| `LA-0-21` | **pass** | compare the retry command in both wizard runs | `2.8.4` folds it across two lines, breaking after `--yes`; the branch prints it whole on its own line. The fold is the defect `AD-34`/`AD-35` closed for the Keychain command, still standing on the retry until now |
| `LA-0-22` | **pass** | `setup_banner` from the installed wheel at widths 100, 60, 40, 28 | the rule surrounds the label at 100 and **gives way** below it: the words wrap and a plain rule follows. Nothing is truncated. At 16 columns the coordinate itself breaks mid-word, which is below any real terminal and is recorded rather than acted on |
| `LA-0-23` | **pass** | `unittest discover` on both trees | `v2.8.4`: 1624 tests, and **50 module-level `test_*` functions in five files that the loader never collected**. Branch: 1692, with those functions collected — `AD-41` measured on both sides rather than asserted |

## Findings

Recorded, not repaired. This run changes nothing; each row is a candidate for the register.

| ID | Severity | Where | What was seen |
|---|---|---|---|
| `W-1` | medium | both wheels | **A recovery note's path is folded mid-word and is not home-relative.** `json.managed-merge@1` writes *Restore the prior value manually at `<absolute path>` JSON path …*, and the renderer wraps it as prose, so the path arrives broken across three lines — `…/-Users-mifi-code-age` / `nt-artifacts/…`. `_recovery_lines` protects a **command** from folding; a path is not a command and falls through. Two lines below it the reload reminder prints `~/.zshrc`, because `AD-37` decided paths go through `home_relative`. One screen, two conventions, and the folded one cannot be copied |
| `W-2` | medium | both wheels | **Every declared input is prompted before the run discovers the item needs nothing.** Running setup for two already-configured artifacts still asks both `Setup input:` questions; answer them and the items report `already-configured`, answer nothing and they report **`cancelled`**. For a Keychain recipe that is a password requested for a server that is already set up — the prompt that `AD-40` has just given an owner still has no reason |
| `W-3` | low | both wheels | **`warning: usage report projection failed; the marketplace outcome is unchanged` on every command-line setup run in this fixture.** It names nothing that failed and nothing an operator could do. Present identically on `2.8.4`, so it is not this change |
| `W-4` | low | branch, new surface | **A retry is offered for a failure the same command cannot fix.** `walk-beta`'s first run failed with *JSON path collision at `servers.beta.mode`*; the printed retry is byte-identical to the command that just failed, and `--force` does not change the outcome — only the recipe's `replace_existing` does, which the operator does not control. The retry is not new; this change is what puts it on the command line, where it will be pasted |
| `W-5` | low | both wheels | **`registry init` and `registry validate` disagree about what a registry workspace is.** On a directory holding `aart-source.json` and no `aart-registry.json`, `init` refuses — *refuses an existing registry workspace* — and `validate` refuses — *requires aart-registry.json … create one with `aart registry init`*. Each remediation points at the other command. Found while building this fixture |
| `W-6` | low | branch | **In a piped run the `START` rule is glued to the tail of the previous prompt.** `Setup input: …: ` ends without a newline, because on a terminal the newline comes from the operator's own return key. Captured to a file, the next item's rule continues that line. On a tty — the wizard transcript above — every rule starts clean. Cosmetic, and only outside a terminal |

`W-1`, `W-2`, `W-3` and `W-5` reproduce on the released `2.8.4` and are not regressions. `W-4` and
`W-6` exist only where this change put new text, and neither is a reason to hold it.

## Methodology notes

- **The wizard was reached without curses.** `run()` prefers a curses front-end and degrades to the
  plain `input()`/`print()` flow when `setupterm` fails. Driving it under a pty with `TERM=dumb`
  takes the documented fallback, which is the surface that calls `_canonical_setup_run` — the same
  function the curses path calls after teardown. The curses screen itself remains human-gated.
- **Piping is not the same as a terminal.** The first command-line captures put the `START` rule on
  the tail of an unfinished prompt line (`W-6`), which reads like a defect until the same run is
  watched on a pty. Both were done before either was believed.
- **The counterfactual was built, not remembered.** `v2.8.4` was checked out into its own worktree
  and rebuilt, rather than trusting the register's description of what `2.8.4` prints. Two of the
  eleven scenarios exist only to observe the old behaviour.
