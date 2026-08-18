# AART 2.7.1 compatibility matrix

AART `2.7.1` is a patch over `2.7.0`. It restores the Tabnine MCP file read by the target company
build and retains the project/user scope behavior introduced in 2.7.0. Protocol versions,
persisted schemas, commands, flags, registry documents and setup capabilities do not change.

| Boundary | Supported in 2.7.1 | Change from 2.7.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Configuration schema | v1 | none | configuration tests |
| Source store | v2 | none | source runtime tests |
| Installation state | v2 | none | lifecycle and schema tests |
| Setup recipe | v2 only | none | setup parser/runtime tests |
| Runtime-requirements extension | `aart.runtime-requirements` | none | runtime-requirements tests |
| Tabnine project MCP | `.tabnine/agent/settings.json` · `mcpServers` | restores company-build target | Tabnine CLI E2E and cross-version live walk |
| Tabnine user MCP | `~/.tabnine/agent/settings.json` · `mcpServers` | restores file; keeps user scope | Tabnine CLI E2E and cross-version live walk |
| Security assessment | v1, ruleset `baseline-v1.1` | none | security tests |
| Published wheel | byte-reproducible from the tag | new patch artifact | packaging and release checks |

## Evidence boundary

The target company Tabnine build surfaced an AART-installed project entry from
`.tabnine/agent/settings.json` as `disconnected`. That state is downstream of discovering and
parsing the `mcpServers` entry; the server then failed at runtime. Other hand-authored servers in
the same file work. This target-environment measurement outranks a generic documentation page.

Published Tabnine documentation names standalone `mcp_servers.json` files, and another machine has
the documented user file. Whether the company build also reads them remains unmeasured. AART has
one `MergeSpec` per scope, so 2.7.1 chooses the proven target. The server's `disconnected` runtime
state is a separate problem and is not claimed fixed here.

## Upgrade direction

- From **2.6.1**: project installations already use `.tabnine/agent/settings.json`; no target
  migration is required. The user-scope capability first added in 2.7.0 remains available.
- From **2.7.0 with no Tabnine MCP installation**: upgrade normally.
- From **2.7.0 with a managed Tabnine MCP installation**: the installation record still owns an
  entry in `mcp_servers.json`. A 2.7.1 update refuses before writing because it cannot
  transactionally retire that destination. Run the exact `marketplace uninstall` and then
  `marketplace install` commands in the diagnostic. The uninstall removes the 2.7.0-owned entry;
  reinstall writes the restored settings target.

The update refusal is intentional and generic: replacing an installation record without removing
an effect absent from its replacement would orphan bytes after dropping their ownership proof.

## Downgrade direction

The state and protocol documents remain readable by 2.7.0 and 2.6.1. Do not reinstall a managed
Tabnine MCP artifact under 2.7.0, because that executable targets the unproven standalone file.
Version 2.6.1 uses the restored project file but does not carry the user-scope addition or the other
2.7.0 adoption features.

## Schema-freeze comparison

Schema freeze v17 retains every v16 protocol number and every normative input digest. Only the
freeze document's `release_version` changes from `2.7.0` to `2.7.1`; the repaired builtin profile,
tests and current documentation are outside the frozen schema inputs.

## Residues

The target regression and the reopened evidence question are repaired by this patch. `AD-29`
remains a separate medium finding: a partial same-name project profile override replaces the whole
builtin profile. It predates this repair and is not needed for the restored builtin target.
