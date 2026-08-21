# AART 2.8.5

Select three MCP servers in one go and watch what `2.8.4` prints. Every item looks the same:
the same effect list, the same `Approve this exact effect? [y/N]`, effect numbering restarting at
`1`, and `security` taking over the terminal to ask for a password twice while naming no artifact
at all. Nothing says whose turn it is.

That is not only a reading problem. With five servers selected, the credential prompt that belongs
to the fourth is indistinguishable from the one that belongs to the second, so the wrong token can
be typed into the right-looking prompt.

## What 2.8.5 does

**Every setup has a boundary.**

```
---------------- mcp/atlassian@claude (user) — setup 2/3 — START -----------------
Setup input: Atlassian site URL:
```

The rule is printed before anything asks for anything, so the request has an owner, and the same
rule closes the item over its outcome. On a narrow terminal the rule gives way and the words stay:
nothing is ever truncated to fit.

**The run ends with what the run did.**

```
------------------------------- RUN SUMMARY --------------------------------
  selected    3
  configured  2
  incomplete  1
Not configured
  mcp/postgres-docker@claude (user)
    status  verification-failed
    why     verification command failed
    aart marketplace setup mcp/postgres-docker --profile claude --scope user --yes --approve-setup-effects
Next step
  what  this run put variables in ~/.zshrc, and a shell that is already open does not
        have them yet
    source ~/.zshrc
  or open a new terminal window and start the agent harness from there
```

**`Next step` is printed once for the run.** `2.8.3` added it and `tui.py` rendered it inside the
per-item loop, so three servers writing to `~/.zshrc` printed the same block three times. Reloading
a shell is a property of the machine, not of an artifact.

**The command line catches up.** `aart marketplace setup` prints the recovery note and the retry
command for the first time. Everything `2.8.4` shipped — the note that names the Docker image, the
tag, and what a rollback would and would not remove — was visible only in the wizard, because
`recovery_messages` had exactly one caller. `--json` `setup.items[]` now carry `coordinate`,
`profile`, `scope`, `successful`, `retry` and `recovery` beside the unchanged `key`. The opening
rule goes to stderr; stdout is still exactly one JSON document.

**A command is never folded.** The retry used to arrive wrapped across two lines, which is a
command that cannot be pasted — the defect already fixed for the Keychain commands and still
standing here.

**Fifty tests that had never run now run.** Five test modules are written as bare module-level
functions. `unittest`'s loader collects `TestCase` subclasses and nothing else, so the suite
reported `OK` over 1624 tests while fifty written ones — covering the payload renderer, the receipt
and verification — never executed. All fifty pass. The suite is 1692.

## Compatibility

Nothing about what a run *does* changes. No protocol version, persisted schema, receipt field,
command, flag or recipe construct moves. `--json` gains fields and loses one: `setup.next_steps[]`
rows no longer carry `key`, because the row is now one per shell file for the whole run rather than
one per artifact. Schema freeze v18 differs from the `2.8.4` freeze in `release_version` and in one
input.

Install or upgrade with the wheel attached to this release. AART installs with no runtime
dependencies: standard library only.

## Known defects shipped open

Six, all found by the live walk this release was held for, recorded in
`docs/testing/PROGRESS-live-acceptance-v14.md`. Four reproduce on `2.8.4` and are older than this
release; two exist only where this release puts new text.

- `AD-43` — a recovery note's absolute path is folded mid-word and is not shortened to `~`.
- `AD-44` — a run asks for every declared input before finding the item is already configured.
- `AD-45` — an unexplained *usage report projection failed* warning on command-line setup runs.
- `AD-46` — a retry is offered for a failure that the same command cannot fix.
- `AD-47` — `registry init` and `registry validate` disagree about what a registry workspace is.
- `AD-48` — outside a terminal the opening rule continues the previous prompt's line.
