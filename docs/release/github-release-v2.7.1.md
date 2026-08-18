# AART 2.7.1

AART 2.7.1 puts Tabnine MCP entries back in the settings file the target company build demonstrably
reads. Version 2.7.0 moved them to a standalone file based on published documentation and evidence
from a different machine; that was the wrong evidence boundary for the environment being shipped
to.

## Restored targets

| Scope | AART 2.7.1 target | JSON path |
|---|---|---|
| project | `.tabnine/agent/settings.json` | `mcpServers` |
| user | `~/.tabnine/agent/settings.json` | `mcpServers` |

The user scope added in 2.7.0 remains. Skills, guidelines, hooks and memory targets do not move.

The company build surfaced an entry from the project settings file as `disconnected`. That means
it parsed the entry and attempted to start the server; the connection failure is downstream of file
discovery. Other hand-authored servers in that file work. The published standalone-file contract
may describe another build, and whether this company build also reads it remains unmeasured.

## Upgrading from 2.7.0

If 2.7.0 already manages a Tabnine MCP entry, 2.7.1 update refuses before writing because the old
standalone destination must be retired transactionally. Follow the exact commands it prints:

```sh
aart marketplace uninstall SOURCE/mcp/NAME --profile tabnine --yes
aart marketplace install SOURCE/mcp/NAME --profile tabnine --yes
```

Add `--scope user` to both commands for a user-scope installation. The uninstall removes the
2.7.0-owned entry; reinstall writes the restored settings target. A 2.6.1 project installation
already uses the restored file and does not need this target migration.

## What this does not fix

An MCP entry that Tabnine reports as `disconnected` has passed configuration discovery but still
has a server startup or connection failure. This patch does not change the artifact command, Docker
image name, derived image tag, credentials or network behavior.

The profile override loader also remains a separate medium finding (`AD-29`): a partial same-name
override replaces the complete builtin record. The builtin Tabnine profile does not require an
override after this release.

## Compatibility

This is a profile-data patch. Protocol versions, persisted schemas, commands, flags, registry
documents, setup recipe and runtime dependencies are unchanged. Schema freeze v17 has the same
protocol values and normative input digests as v16.

## Known defects shipped open

Fifty-seven findings remain open: one `major`, two `high`, 33 `medium`, and 21 `low`. No
high-severity adoption finding remains open.

## Verifying this release

```sh
python scripts/version.py check-tag v2.7.1
git checkout v2.7.1
python scripts/release.py wheel-digest --output dist
```

The attached wheel is byte-reproducible from the tagged commit. Its exact digest is appended below
when the GitHub release is created.
