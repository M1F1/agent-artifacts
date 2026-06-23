# agent-artifacts - Design: per-artifact profile compatibility

Companion to [DESIGN.md](DESIGN.md) and GitHub issue
[#6](https://github.com/M1F1/agent-artifacts/issues/6).

Some artifact types are mechanically supported by a profile but still semantically wrong for a
specific harness. A hook may rely on Claude event semantics. An MCP server descriptor may have
only been tested against Tabnine. Today the installer can only answer "does this profile support
this artifact type?", not "is this artifact intended for this profile?".

This design adds an optional, explicit allow-list under `compatibility.profiles`.

## 1. Goal and scope

Add first-class artifact-level profile compatibility.

**In scope**

- Allow an artifact to declare the exact profiles it is compatible with.
- Keep existing artifacts without compatibility metadata installable exactly as today.
- Reject explicit installs of incompatible artifacts with a clear usage error.
- Skip incompatible artifacts that arrive through broad selections such as bundles or `--all`.
- Include machine-readable skip/rejection reasons in JSON and dry-run output.
- Apply compatibility checks during install and update.
- Document the metadata shape for all current artifact packaging formats.

**Out of scope**

- A separate `harness` concept distinct from `profile`.
- Negative rules such as "all except vibe".
- Compatibility on bundle entries.
- Per-file compatibility inside a directory artifact.
- Full YAML parsing or a new runtime dependency.

## 2. Current packaging model

An artifact is not always one source file.

| Type | Source package | Install behavior |
| --- | --- | --- |
| `skill` | `skills/<name>/` with required `SKILL.md` and optional `scripts/`, `references/`, `assets/` | copy the whole tree |
| `hook` | `hooks/<name>/` with required `hook.json` and optional payload files | copy the tree and merge registration |
| `guideline` | `guidelines/<name>.md` | copy a markdown file |
| `memory` | `memory/<name>.md` | write/copy/merge markdown into the profile memory target |
| `mcp` | `mcp/<name>.json` | merge descriptor into profile config |

Compatibility is therefore metadata on the **artifact package**, not on each copied payload
file. For directory artifacts, the descriptor that already identifies the package carries the
metadata:

- `skills/<name>/SKILL.md` frontmatter for skills.
- `hooks/<name>/hook.json` for hooks.
- `mcp/<name>.json` for MCP.
- Markdown frontmatter for `guideline` and `memory`.

Bundles remain tables of contents. They select artifacts by type/name and do not override an
artifact's compatibility.

## 3. Metadata shape

The conceptual schema is:

```json
{
  "compatibility": {
    "profiles": ["claude", "tabnine"]
  }
}
```

For JSON descriptors (`mcp`, `hook`), use that object literally:

```json
{
  "name": "postgres",
  "description": "MCP server for PostgreSQL",
  "compatibility": {
    "profiles": ["tabnine"]
  },
  "server": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"]
  }
}
```

For Markdown/frontmatter descriptors (`skill`, `guideline`, `memory`), the canonical persisted
form is a dotted flat key:

```markdown
---
name: code-review
description: Review code changes for correctness.
compatibility.profiles: claude, tabnine
---
```

The dotted key keeps the current zero-dependency, flat frontmatter parser. The value is parsed
as a comma-separated list; optional bracket syntax may be accepted as a convenience:

```markdown
compatibility.profiles: [claude, tabnine]
```

Do not add a top-level `profiles` shorthand in v1. It is less explicit, easier to confuse with
profile definitions, and harder to evolve.

## 4. Domain model

Add a small immutable value:

```python
@dataclass(frozen=True, slots=True)
class Compatibility:
    profiles: Tuple[str, ...]
```

Then extend `Artifact`:

```python
@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType
    name: str
    root: str
    compatibility: Optional[Compatibility] = None
```

Rules:

- `compatibility is None` means unrestricted, subject only to existing type support.
- `compatibility.profiles` is an explicit allow-list.
- An empty profile list is invalid.
- Duplicate profile names are de-duplicated while preserving order.
- Profile names are validated syntactically, not against only built-ins, because projects can
  define custom profiles in `.agent-artifacts/profiles.json`.

The key pure predicate is:

```python
def check_profile_compatibility(artifact: Artifact, profile_name: str) -> CompatibilityDecision:
    ...
```

`CompatibilityDecision` should expose:

- `ok: bool`
- `reason: Optional[str]`, using stable machine values such as `incompatible-profile`
- `allowed_profiles: Tuple[str, ...]`

This keeps command behavior data-driven and testable.

## 5. Install behavior

Compatibility is checked after artifact and profile resolution and before planning.

The installer already has two broad selection categories:

- explicit by-name selection: `aart install postgres --profile claude`
- broad selection: `aart install --bundle backend ...` or `aart install --all ...`

Use the same shape as unsupported type handling:

| Selection source | Incompatible artifact/profile target | Result |
| --- | --- | --- |
| explicit by-name | artifact allow-list excludes the profile | usage error, exit code 2 |
| bundle or `--all` | artifact allow-list excludes the profile | skip target with warning |

The explicit error should name the artifact, type, selected profile, and allowed profiles:

```text
mcp 'postgres' is not compatible with profile 'claude' (allowed: tabnine)
```

For a multi-profile install, compatibility is target-specific. The same artifact may be
installed into `tabnine` and skipped for `claude` in one command.

## 6. Dry-run and JSON output

Human dry-run should show skip warnings alongside the planned actions:

```text
warn        skipped mcp 'postgres' for profile 'claude': incompatible-profile (allowed: tabnine)
copy-tree   ...
```

JSON output should not force agents to parse warning strings. Add a structured `skipped`
collection to command JSON where the command currently emits an object. For dry-run JSON, prefer
the same wrapper shape instead of a bare action array once compatibility skips are present:

```json
{
  "actions": [
    {"action": "copy-tree", "src": "...", "dst": "..."}
  ],
  "skipped": [
    {
      "artifact": "postgres",
      "type": "mcp",
      "profile": "claude",
      "reason": "incompatible-profile",
      "allowed_profiles": ["tabnine"]
    }
  ],
  "warnings": [
    "skipped mcp 'postgres' for profile 'claude': incompatible-profile"
  ]
}
```

Existing JSON shapes without skips should remain stable where practical. If a command must
change from a bare array to an object for dry-run compatibility reporting, document that as a
small contract version bump in tests and README.

## 7. Update behavior

`aart update` must validate compatibility against the current source metadata before refreshing
an installed entry.

Rules:

- If an explicitly named update target is now incompatible with its installed profile, fail with
  usage exit code 2 and leave the installed files and manifest unchanged.
- If a broad update encounters an incompatible installed entry, skip that entry, report
  `reason: "incompatible-profile"`, and leave its existing manifest entry untouched.
- Do not uninstall or prune an incompatible entry automatically. Incompatibility means "do not
  install/update into this profile"; removal remains an explicit uninstall decision.

This handles the case where a catalog maintainer narrows compatibility after an artifact was
already installed.

## 8. List and catalog visibility

`aart list --json` should include compatibility metadata so agents and humans can inspect the
catalog before installing:

```json
{
  "type": "mcp",
  "name": "postgres",
  "compatibility": {
    "profiles": ["tabnine"]
  }
}
```

Human list output can stay concise. It may show compatibility only in verbose output later; v1
does not need a new flag.

## 9. Validation

Catalog parsing should validate the metadata shape:

- `compatibility` in JSON descriptors, when present, must be an object.
- `compatibility.profiles`, when present, must be a non-empty list of strings for JSON
  descriptors.
- Markdown `compatibility.profiles` must parse to at least one non-empty profile name.
- Profile names should use the existing CLI-friendly identifier style:
  `[A-Za-z0-9][A-Za-z0-9_-]*`.

Do not reject a syntactically valid profile name only because it is not one of the built-in
profiles. Custom profile overrides are project-local and may not be visible during catalog
validation.

## 10. Backward compatibility

Existing artifacts without compatibility metadata behave exactly as today.

Existing manifests do not need migration. The manifest records what was installed; compatibility
is source metadata used when planning new installs and updates.

Existing bundles do not need migration. Compatibility belongs to the referenced artifact.

## 11. Examples

Tabnine-only MCP descriptor:

```json
{
  "name": "postgres",
  "description": "Postgres MCP for Tabnine-tested projects.",
  "compatibility": {
    "profiles": ["tabnine"]
  },
  "server": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"]
  }
}
```

Claude-only hook package:

```json
{
  "name": "block-secrets",
  "description": "Block writes that introduce obvious secrets.",
  "compatibility": {
    "profiles": ["claude"]
  },
  "events": ["PreToolUse"],
  "matcher": "Edit|Write|MultiEdit",
  "command": "python3 ${SCRIPT_DIR}/guard.py",
  "files": ["scripts/guard.py"]
}
```

Multi-profile skill package:

```markdown
---
name: code-review
description: Review code changes for correctness.
compatibility.profiles: claude, opencode, tabnine
---
```

## 12. Deferred decisions

- Negative selectors such as `except: ["vibe"]`.
- A separate `compatibility.harnesses` field.
- Per-bundle compatibility overrides.
- Per-file compatibility inside skill/hook payload directories.
- Rich YAML frontmatter parsing.
