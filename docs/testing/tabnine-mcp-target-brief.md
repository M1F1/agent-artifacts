# Repair brief — put the Tabnine MCP target back on `settings.json`

## What to change

In `agent_artifacts/profiles/builtin.py`, `_TABNINE`:

| Scope | Now (2.7.0, wrong) | Put back |
|---|---|---|
| project | `.tabnine/mcp_servers.json` | `.tabnine/agent/settings.json` |
| user | `~/.tabnine/mcp_servers.json` | `~/.tabnine/agent/settings.json` |

`json_path` stays `mcpServers` and `mode` stays `key`. Nothing else about the profile moves.

This reverts the `mcp` half of `a6b48a1` *Settle Tabnine MCP scope targets*. The `user`-scope
**addition** in that commit is good and stays — before it there was no user-scope MCP target at all.
Only the file name is wrong.

## Why

`.tabnine/agent/settings.json` is the file the company's Tabnine build actually reads, measured on
the machine that matters.

The proof is in `AD-04`'s own evidence and it was misread. AART installed a server into
`.tabnine/agent/settings.json` at project scope. Tabnine then listed that server as **`disconnected`**.
Not absent. Not unknown. `disconnected` means Tabnine parsed the file, found the entry, tried to
start the server and failed to connect — a runtime failure of the server, downstream of a file that
was read correctly. The operator also reports that other MCP servers they configured by hand in the
same file work.

So the file is read. That is a measurement from the target environment.

`a6b48a1` set against it two things that cannot outrank it:

1. **Current published Tabnine documentation**, which names `mcp_servers.json`. Documentation
   describes some build. The company runs a specific one.
2. **A user-scope `~/.tabnine/mcp_servers.json` on the maintainer's own machine**, with a documented
   shape and an active server. That is a different machine, a different Tabnine install, and a
   different scope from the one that was measured contradicting it.

The commit's register row calls the contradicting measurement *one IDE build accepted the old
settings-file fallback*. That inverts the burden. The one build we have a measurement from is the
one we are shipping to.

The code comment that `a6b48a1` deleted had already said the right thing:
*DOC CAVEAT … Verify in-environment.* The verification happened in a different environment.

## What ships wrong right now

2.7.0 is tagged and released, so this is a shipped regression, not a pending mistake.

- `tests/tabnine_mcp_e2e_test.py:96-97` asserts `.tabnine/agent/settings.json` **does not exist**
  after install, at both scopes. AART does not merely prefer the new file; it is now pinned against
  writing the working one.
- The target-migration guard added in the v16 work makes `marketplace update` exit `1` with a
  migration conflict and hand the operator `uninstall` then `install`, which moves a working
  installation onto the file their Tabnine may not read.

## Do not settle this from documentation again

The one thing that would make this cheap to get right is a measurement nobody has taken: **does the
company Tabnine build read `mcp_servers.json` at all?**

Three outcomes, three different repairs:

- **Reads only `settings.json`** — revert as above and the matter is closed.
- **Reads both** — revert as above anyway. `settings.json` is proven and `mcp_servers.json` is not,
  and a profile carries one `MergeSpec` per scope.
- **Reads both, and the published docs are where Tabnine is going** — still revert now, and open a
  separate row for a per-build target, because a single hardcoded file cannot serve two builds.

Ask the operator to check on their machine before choosing. Do not choose from the docs.

## Register

Per the stream's rules, an id is never renumbered and never reused.

- **Reopen `AD-04`.** Its row currently reads `closed` and its stated evidence is wrong for the
  environment the finding came from. Change the state and say plainly in the row that the
  documentation-based resolution was reverted, and why.
- **File a new id for the regression itself** — a released version moved a working install target
  onto an unproven one and pinned a test against the working one. That is a different defect from
  the original *which file does Tabnine read* question, and it has its own fix and its own test.

Also correct the two tutorials and `DESIGN-memory.md` §6.1, which `a6b48a1` rewrote to state the new
target as settled fact.

## Tests

The e2e assertions must flip, not just relax:

- assert `.tabnine/agent/settings.json` exists with the entry under `mcpServers`, at both scopes;
- assert the scopes can still be removed independently, which is the property `a6b48a1` added and is
  worth keeping;
- add a regression that pins the target file by name, so the next reader who finds a docs page
  disagreeing with it has to change a test that says why.

## One more thing worth a row

The override loader is the operator's only escape while this is broken, and it is sharper than it
looks. `load_profiles` overlays **by profile name, replacing the whole record**
(`profiles/loader.py:145-146`). A
`.agent-artifacts/profiles.json` that sets only `mcp` silently drops that profile's skills,
guidelines, hooks and memory targets, because `_profile_from_dict` turns every absent section into
`None` and a missing section means *this harness does not support that type*. Overriding one file
path requires restating the entire profile. Worth its own finding.

## Not in scope

The operator's live `mcp disconnected` is a **separate** problem and this repair will not fix it.
The entry is read; the server fails to start. The open hypothesis is a derived-image-tag mismatch:
`docker.build@1` derives `aart/mcp/atlassian:1.0.0` while the hand-written proof-of-concept used
`company-atlassian-mcp:latest`. Do not fold the two together.
