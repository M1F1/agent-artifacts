# Design: what uninstall may remove

Status: accepted — implemented and walked live
([PROGRESS-live-acceptance-v11.md](../testing/PROGRESS-live-acceptance-v11.md)). The case §4 leaves
open is `LAF-89`; the directory question §5 leaves open is `LAF-88`.

Answers `LAF-47` and `RS-10`, which are one finding seen from two sides. `LAF-47` is the observation:
uninstalling the last `mcp` artifact leaves `.mcp.json` behind as `{"mcpServers": {}}`. `RS-10` is the
general statement: the last uninstall of *any* merge effect leaves the merge file behind.

This note decides what uninstall removes and, more importantly, **on what evidence AART is allowed to
conclude a file is its own**. It does not decide anything about files AART did not create. Those stay.

## 1. What is actually left

Reproduced on a locally built `2.6.0` wheel
(`fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174`), in a git repository that was
clean before, with a sandbox `HOME`:

| Step | Result |
|---|---|
| `marketplace install lab/mcp/atlassian lab/hook/guard --profile claude --yes` | `.mcp.json`, `.claude/settings.json`, `.claude/hooks/guard/`, `.agent-artifacts/` |
| `marketplace uninstall` both, `--yes` | `.agent-artifacts/` gone, `.claude/hooks/guard/` gone |
| what survives | `.mcp.json` as `{"mcpServers":{}}`, `.claude/settings.json` as `{"hooks":{"PreToolUse":[]}}`, and the `.claude/` directory holding it |
| `git status --porcelain` | `?? .mcp.json` and `?? .claude/` on a repository that was clean |

So this is not an `mcp` quirk. Both merge modes leave their file: `key` leaves an empty object,
`list` leaves an empty array. `LAF-17` reclaimed the directories and the manifest in `2.2.0`; the
created destination *file* is the case that was never done.

## 2. There is already code for this, and it cannot fire

`lifecycle/application.py:578`:

```python
if effect.created_destination and isinstance(updated, JsonObject) and not updated.entries:
    return UninstallOperation(effect, absolute, snapshot, "remove"), None
```

`updated` is the **whole document** with the merged identity taken out — not the container the merge
wrote into. For `.mcp.json` the container is at `json_path = "mcpServers"`, so after the last removal
`updated` is `{"mcpServers": {}}`, whose `entries` is one entry, and the branch does not fire.

Every merge destination in every shipped profile has a non-empty `json_path`: `mcpServers` for
`claude` and `tabnine`, `mcp` for `opencode`, `hooks.PreToolUse` / `hooks.BeforeTool` / `hooks` for
the hook targets (`profiles/builtin.py`). The branch is therefore dead code today. It was written for
a merge at the document root, which no profile asks for.

That is the whole mechanical defect. The rest of this note is about not making it worse.

## 3. What evidence AART actually has

Three facts are available at uninstall time, and one that seems available is not.

**`created_destination` on the effect.** Recorded by the applier at install time from one
observation: the destination path was `absent` immediately before this effect wrote it
(`installation/application.py:866`). It is a fact about the file, recorded when it was true, and
carried forward across reinstalls of the same artifact (`:941`). It is the only evidence AART has
that the file is its own.

**The identity proof the uninstall already requires.** A merge is only reversed when exactly one
entry matches the recorded identity evidence and its digest still matches what was installed;
anything else is a refusal (`managed merge drifted`, `managed merge identity is ambiguous`). So by the
time removal is being considered, AART has proven that the entry it is taking out is the entry it put
in.

**What remains in the document afterwards.** Available exactly, as parsed JSON.

**What is not available: whether another AART effect created this file.** `created_destination` is
per effect, and the second artifact into the same file records `false` — correctly, the file was
there. Measured:

```
atlassian -> .mcp.json created_destination= True      (installed first)
jira      -> .mcp.json created_destination= False     (installed second)
```

Uninstall `atlassian` and then `jira`, and the last effect out is the one that says `false`, while the
record that said `true` was deleted with the first uninstall. **The evidence for the file's origin can
be destroyed before the file is last touched.** Any rule that asks only the effect in front of it will
be wrong whenever uninstall order differs from install order.

## 4. The rule

Uninstall removes a merge destination when **all** of these hold:

1. The effect being reversed carries `created_destination: true`. The file did not exist before AART
   wrote it. A file that existed is never removed, whatever it contains.
2. The merge was proven reversible by the checks already in place — one matching identity, digest
   unchanged, no drift, no `--force` needed to get here.
3. After the identity is removed, what remains is **only the empty container chain on the effect's own
   `json_path`**. For `json_path = "mcpServers"` that is exactly `{"mcpServers": {}}`; for
   `hooks.PreToolUse` exactly `{"hooks": {"PreToolUse": []}}`. One extra key anywhere in the document,
   at any depth, means the file is not empty and it stays.

Condition 3 is what makes condition 1 safe to act on. A file AART created is still a file an operator
may have written into afterwards. If they did, the document is not the bare chain any more and nothing
is removed. AART does not need to know who wrote the extra key; it only needs to see that something is
there.

The remaining case — the file was created by AART, and the last artifact out is not the one that
created it — is **left open deliberately**, because closing it needs a durable per-destination
ownership fact in the install state, which is a state-schema change and belongs with the version
boundary work (`LAF-62`, cluster C4). Until then that case behaves exactly as it does today: the file
stays. The finding rows should say so rather than claiming more than the fix delivers — they do, as
`LAF-89`, and `LA-U-35` walks the asymmetry in both directions: install order leaves the file,
reverse order removes it.

## 5. What this does not do

- **It does not remove a file that existed before AART.** Not when it is empty, not with `--force`,
  not ever through this path. `~/.claude.json` at user scope is the case that matters: on any real
  machine it is the operator's own configuration file, `created_destination` is `false` for it, and
  condition 1 excludes it before anything else is looked at.
- **It does not remove a file with anything else in it.** Including keys AART itself wrote through a
  different profile target, and including keys an operator added by hand.
- **It does not touch `managed-block` or `write-file` effects.** They already remove a file they
  emptied (`:597`) or restore what they displaced (`:606`).
- **It does not add a state field, a schema version, or a protocol revision.** It reads
  `created_destination`, which `2.2.0` already writes.
- **It does not make anything visible to `receipt verify`.** The correction recorded in the residue
  register stands: `verify` reads a *setup* record and these are *install* effects. Removing the file
  is the answer here, not reporting it.
- **It does not decide directory reclamation.** `.claude/` survives today because it holds
  `settings.json`. Once that file goes, whether the directory goes with it is decided by the existing
  teardown (`lifecycle/io.py:80`, `rmdir` used as its own guard), and the implementation must show
  which happens rather than assume. *It did: the directory stays, empty. `git status --porcelain` is
  clean because git does not track empty directories. Recorded as `LAF-88`, not fixed here.*

## 6. Why not the alternatives

**Always remove an emptied merge file.** Rejected. An operator who wrote `{"mcpServers": {}}`
themselves before installing would have their file deleted by an uninstall. The stream's own reading
of cluster C2 is that teardown "abandons everything it shares with the operator" — the answer to that
is to stop abandoning what AART owns, not to start taking what it does not.

**Record file ownership per destination in the install state.** The complete answer, and the way to
close the reverse-order case. Rejected *for now* because it changes the state document, which every
`2.x` reads, and that boundary has its own unfinished stream. Noted here so the next design does not
have to rediscover it.

**Report the leftover instead of removing it.** That is what the design note this corrects already
claimed, and the register refuted it: nothing in the shipped response makes either finding observable.
A file AART created, emptied and abandoned is litter whether or not a command mentions it.

## 7. Acceptance criteria

1. Install one `mcp` artifact into a clean repository, uninstall it, and `git status --porcelain` is
   empty. Same for one `hook` artifact and `.claude/settings.json`.
2. An operator's own `.mcp.json` — present before any install, containing only `{"mcpServers": {}}` —
   survives install and uninstall untouched.
3. A file AART created that also holds a key AART did not write survives, with that key intact.
4. Two artifacts installed separately into one created file, uninstalled in reverse order: the file
   stays, and the register row says that is the known limit rather than a failure.
5. Walked live against a locally built wheel, both the removal and the two refusals, recorded in a new
   `PROGRESS-live-acceptance-v*.md` with its digest in the header.
