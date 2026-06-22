# agent-artifacts - Design: upstream tracking for vendored artifacts

Companion to [DESIGN.md](DESIGN.md) and [DESIGN-memory.md](DESIGN-memory.md). This document
adds a maintainer workflow for tracking third-party or cross-repo artifacts that have been
copied into the source-of-truth catalog.

The important boundary is unchanged: consumer projects install from, check against, and update
from **one curated agent-artifacts repo**. Upstream tracking is for catalog maintainers. It
helps them notice that a vendored skill, memory file, hook, MCP definition, or guideline has
changed upstream, import the change into this repo, review the git diff, and merge it through
the normal PR process.

---

## 1. Goal and scope

The base design deliberately kept "external artifact sources" out of MVP. That was the right
choice for consumer safety: a normal `aart update` should not chase random third-party repos and
silently rewrite a user's local agent setup. But the catalog repo still needs a way to keep
vendored artifacts fresh.

This change introduces **upstream tracking**:

- record where a vendored artifact came from (`repo`, `ref`, `path`);
- record what upstream commit and content hash it was last synced from;
- check whether the upstream artifact content changed;
- update the local catalog artifact from upstream in a reviewable working-tree diff;
- support selection by artifact name, type, bundle, or all tracked artifacts.

**In scope**
- A repo-level upstream tracking file for artifact origins and last-sync state.
- New maintainer-facing CLI surface: `aart upstream check` and `aart upstream update`.
- GitHub upstreams first, using the existing stdlib network/cache layer.
- Content-aware checks: a repo commit moving does not count as an artifact update unless the
  tracked path's content changes.
- Drift/conflict protection when the local catalog artifact has been edited since the last
  upstream sync.
- `--dry-run`, `--json`, `--force`, and bundle/type/name selectors.

**Out of scope**
- Consumer-project multi-source update by default.
- Automatic PR creation or automatic merging.
- Running or trusting upstream hook commands during import.
- Per-artifact package registry semantics, semver resolution, or dependency solving.
- Signing/provenance verification beyond recording upstream commit and content hash.

## 2. Glossary

- **Catalog repo** - this source-of-truth `agent-artifacts` repo. Consumers trust this repo.
- **Vendored artifact** - an artifact physically copied into the catalog repo, but maintained
  elsewhere upstream.
- **Upstream origin** - the remote location of a vendored artifact: GitHub repo, ref, and path.
- **Tracked artifact** - a catalog artifact with an upstream origin entry.
- **Last sync** - the upstream commit and content hash that produced the current local copy.
- **Upstream drift** - the upstream tracked path changed since `last_synced`.
- **Local catalog drift** - the local catalog artifact changed since `last_synced`, before an
  upstream update is applied.

## 3. Trust boundary

There are three layers:

```
 upstream repos                 catalog repo                    consumer project
 (Superpowers, Karpathy, ...)   (reviewed source of truth)       (installed artifacts)
        |                                  |                              |
        | aart upstream check/update       | aart check/update            |
        v                                  v                              v
 reviewed git diff in catalog repo   curated main branch          local harness files
```

The existing consumer commands keep their meaning:

- `aart install` installs from one catalog source.
- `aart status` remains local-only.
- `aart check` compares a consumer's installed catalog commit against the catalog repo.
- `aart update` updates the consumer from the catalog repo.

The new upstream commands operate **inside the catalog repo** and change the catalog working
tree, not a consumer project.

This preserves review as the safety gate. Upstream changes become ordinary source changes:
humans or agents inspect the diff, tests validate the catalog, and a PR merges the curated
result.

## 4. Repo layout and metadata

Upstream tracking is stored in one repo-level JSON file:

```
agent-artifacts/
├── upstreams.json
├── skills/
├── guidelines/
├── mcp/
├── hooks/
├── memory/
└── bundles/
```

`upstreams.json` is intentionally separate from artifact bodies. That avoids modifying
third-party `SKILL.md` frontmatter, works for every artifact type, and keeps origin metadata
queryable without reading every artifact file. The file is source-side catalog metadata, not
consumer-project state; it must not be confused with `<consumer>/.agent-artifacts/manifest.json`.

### 4.1 Schema

Draft schema:

```json
{
  "version": 1,
  "artifacts": {
    "skill/superpowers": {
      "source": {
        "kind": "github",
        "repo": "example/superpowers",
        "ref": "main",
        "path": "skills/superpowers"
      },
      "last_synced": {
        "sha": "abc123...",
        "content_hash": "sha256:...",
        "synced_at": "2026-06-22T10:00:00Z"
      }
    },
    "memory/karpathy-prompting": {
      "source": {
        "kind": "github",
        "repo": "example/karpathy-skills",
        "ref": "main",
        "path": "memory/prompting.md"
      },
      "last_synced": {
        "sha": "def456...",
        "content_hash": "sha256:...",
        "synced_at": "2026-06-22T10:00:00Z"
      }
    }
  }
}
```

The artifact key is `<type>/<name>`, matching the catalog's identity model. The local
destination is inferred from the artifact type:

| Type | Local destination |
| --- | --- |
| `skill` | `skills/<name>/` |
| `guideline` | `guidelines/<name>.md` |
| `mcp` | `mcp/<name>.json` |
| `hook` | `hooks/<name>/` |
| `memory` | `memory/<name>.md` |

The upstream `path` points at either a directory or a file. Type validation decides what is
acceptable: `skill` and `hook` import trees; `guideline`, `mcp`, and `memory` import single
files.

### 4.2 Why content hash, not only commit

A GitHub branch can move because unrelated files changed. `aart upstream check` should not tell
maintainers to import `skill/superpowers` merely because `README.md` changed upstream.

For each tracked artifact, the command resolves `ref` to a commit, reads the tracked path from
that commit snapshot, computes a deterministic content hash, and compares it to
`last_synced.content_hash`.

The resolved upstream SHA is still recorded because it answers "which upstream commit did we
sync from?" and enables diagnostics. The content hash answers "did the artifact we track
actually change?"

## 5. Command surface

Nested subcommands:

```sh
aart upstream check [NAME...] [--bundle B...] [--type T] [--all] [--source DIR] [--json]
aart upstream update [NAME...] [--bundle B...] [--type T] [--all] [--source DIR]
                   [--dry-run] [--force] [--json]
```

`--source DIR` means "the catalog repo to maintain"; it defaults to the current working
directory. `--project` is ignored for `upstream` commands because these commands do not target
a consumer project.

### 5.1 Selection rules

Selectors mirror existing artifact selection:

- Names select artifacts by name; `--type` disambiguates when needed.
- `type/name` may be accepted as an explicit upstream key.
- `--bundle B` selects tracked artifacts included by the resolved bundle.
- `--all` selects all tracked artifacts.
- `check` with no selector may default to all tracked artifacts.
- `update` should require an explicit selector (`NAME`, `--bundle`, or `--all`) so a broad
  mutating operation is intentional.

Untracked artifacts selected through a bundle are skipped with a warning. Selecting an
untracked artifact by explicit name is a usage error unless `--allow-untracked` is added later.

### 5.2 `aart upstream check`

For every selected tracked artifact:

1. validate the local artifact exists in the catalog;
2. resolve the upstream `repo@ref` to a commit SHA;
3. materialize or reuse the upstream snapshot through the existing cache;
4. hash the upstream tracked path;
5. compare it to `last_synced.content_hash`;
6. report `up_to_date`, `changed`, `missing_upstream`, `local_drift`, or `invalid`.

Human output should be compact and grouped by state. JSON output should include enough
information for automation:

```json
{
  "checked": [
    {
      "artifact": "skill/superpowers",
      "state": "changed",
      "repo": "example/superpowers",
      "ref": "main",
      "base_sha": "abc123...",
      "head_sha": "fed999...",
      "base_hash": "sha256:...",
      "head_hash": "sha256:..."
    }
  ]
}
```

`check` does not write files or update `upstreams.json`.

### 5.3 `aart upstream update`

For every selected tracked artifact:

1. fetch and stage the upstream tracked path;
2. validate the staged artifact with the existing catalog parsers;
3. classify local catalog state against the upstream sync state:
   - `disk == base`, `new == base`: no-op;
   - `disk == base`, `new != base`: clean update;
   - `disk != base`, `new == base`: keep local drift, warn;
   - `disk != base`, `new != base`: conflict unless `--force`;
   - upstream path missing: warn and leave the local artifact in place.
4. for a clean update, replace the local artifact root with the staged content;
5. update `last_synced.sha`, `last_synced.content_hash`, and `last_synced.synced_at`;
6. leave a normal git diff for review.

Conflict behavior mirrors the consumer update policy. For file artifacts, write an upstream
candidate sidecar such as `<artifact>.agent-artifacts-upstream-new`. For tree artifacts, copy
the candidate tree to `<artifact>.agent-artifacts-upstream-new/`. With `--force`, overwrite
the local artifact and update the sync metadata.

Tree imports are **replace-tree** operations, not overlay copies. A clean update of
`skills/foo/` or `hooks/foo/` first stages the complete upstream tree, validates it, then makes
the local tree match that staged tree exactly. Stale local files that disappeared upstream are
removed only when the local tree is clean against `last_synced` or when `--force` is used.
This avoids the `copy_tree(..., dirs_exist_ok=True)` trap where deleted upstream files linger
forever.

`--dry-run` prints or serializes the planned actions without touching disk.

## 6. Validation and safety

The upstream file is part of catalog validation:

- every `type/name` key must resolve to an artifact in the catalog;
- source kind must be known;
- GitHub repo must be `owner/name`;
- ref and path must be non-empty strings;
- `last_synced.sha` and `last_synced.content_hash` must be present after an artifact is first
  synced;
- imported staged content must parse as the declared artifact type before the local artifact
  is replaced.

`aart upstream update` should also be conservative around the working tree:

- warn when the destination artifact has local catalog drift;
- refuse conflicts unless `--force`;
- never delete a catalog artifact just because the upstream path vanished;
- never execute upstream scripts or hook commands;
- advance `last_synced` only after the artifact update actions succeed;
- preserve the zero-runtime-dependency rule.

An optional later enhancement can refuse to run on a dirty git worktree unless
`--allow-dirty` is provided. The MVP can rely on the content-hash conflict check, which is
more precise than a broad git status check.

## 7. Interaction with bundles

Bundles remain a catalog composition feature. They do not point to upstream repos directly.

When `aart upstream check --bundle backend` runs:

1. resolve `backend` through the existing bundle resolver;
2. intersect the resolved artifact set with `upstreams.json`;
3. check only those tracked artifacts;
4. warn about untracked bundle members if useful.

This keeps bundles as "what we ship" and upstream metadata as "where this vendored artifact
came from."

## 8. Interaction with consumer manifests

Consumer manifests do not need to record third-party upstream origins. A consumer installed
`skill/superpowers` from the catalog repo, not from `example/superpowers`.

When maintainers import upstream changes and merge them into the catalog repo, consumers see
that as a normal catalog update:

```sh
aart check
aart update
```

This is deliberate. It avoids teaching consumer commands to resolve many repos, authenticate
against many remotes, or trust unreviewed upstream content.

## 9. Network and cache behavior

The MVP uses GitHub upstreams because the existing IO layer already knows how to resolve refs,
fetch tarballs, compare commits, and cache immutable snapshots.

For efficiency:

- group selected entries by `(repo, resolved_sha)`;
- fetch each snapshot once;
- hash multiple tracked paths from the same snapshot;
- reuse `~/.cache/agent-artifacts/<repo>/<sha>/`.

Private upstream repos use the same `GITHUB_TOKEN` / `GH_TOKEN` story as existing remote
source commands.

Local upstream sources can be added later for testing or air-gapped mirrors:

```json
{
  "kind": "local",
  "path": "../some-catalog",
  "artifact_path": "skills/foo"
}
```

Local support is not required for the first GitHub-focused implementation if tests inject the
network opener as existing tests do.

## 10. Non-goals and rejected alternatives

- **Direct consumer multi-source update** - rejected as the default because it bypasses the
  catalog review boundary.
- **Putting origin metadata in `SKILL.md` frontmatter** - rejected for MVP because it only
  fits markdown artifacts and modifies third-party files.
- **Symlinking to upstream checkouts** - rejected for the same reason symlinks are rejected in
  the base design: copying is portable and reviewable.
- **Automatic PR creation** - useful later, but out of MVP. The first version should produce
  a clean working-tree diff and machine-readable JSON.
- **Package-manager semantics** - no dependency graph, semver range resolution, or registry.
  This is vendored content tracking.

## 11. Open questions

1. Should `upstream update` default to refusing any dirty git worktree, or only protect the
   tracked artifact roots with content hashes?
2. Should `check` fetch tarballs for exact content hashes, or first use GitHub compare as a
   cheaper path filter and fetch only when a tracked path changed?
3. Should first-time adoption have `aart upstream add type/name --repo ... --path ...` in MVP,
   or is hand-editing `upstreams.json` acceptable for the first release?
4. Should upstream metadata support optional patch files later, for catalogs that intentionally
   carry local modifications on top of upstream?
5. Should `upstreams.json` eventually move under `.agent-artifacts/`, or is a top-level file
   better because it is catalog source data? The design currently chooses top-level visibility.
