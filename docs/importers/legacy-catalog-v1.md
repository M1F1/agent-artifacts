# Legacy catalog importer v1

`legacy-catalog-v1` is the built-in Maintainer-time bridge from an AART 0.1.x catalog to a
canonical native source. It is deliberately not available from consumer install, update, list, or
marketplace paths. Protocol v1 has a closed importer registry and does not load repository code or
external plugins.

## Accepted input

The caller must first acquire an immutable Git snapshot and supply its credential-free repository
URL, exact 40-hex commit, and optional safe root. The importer recognizes this legacy layout:

```text
skills/<name>/SKILL.md
guidelines/<name>.md
mcp/<name>.json | mcp/<name>/mcp.json
hooks/<name>/hook.json
memory/<name>.md
bundles/<name>.json
upstreams.json
```

Names, descriptors, bundle structure, upstream records, UTF-8, JSON, paths, entry kinds, file
sizes, entry count, and total bytes are checked against fixed bounds. A symlink, special file,
duplicate identity, ambiguous MCP layout, stale tracked payload, unpinned upstream, unknown
semantic field, unsafe origin, or missing tracked artifact rejects the import. Unrelated files
outside recognized roots are ignored; unknown fields inside recognized semantic documents are not.

## Deterministic mapping

| Legacy input | Canonical output |
|---|---|
| `skills/<name>/` | `artifacts/skill/<name>/payload/` |
| `guidelines/<name>.md` | `artifacts/guideline/<name>/payload/<name>.md` |
| `mcp/<name>.json` or directory | `artifacts/mcp/<name>/payload/mcp.json` |
| `hooks/<name>/` | `artifacts/hook/<name>/payload/` |
| `memory/<name>.md` | `artifacts/memory/<name>/payload/<name>.md` |
| `bundles/<name>.json` | `collections/<name>.json` |
| legacy `setup/` content | canonical artifact `setup/` content |

Every artifact receives `artifact.json` and `provenance.json`. Tracked content records the exact
upstream URL, commit, path, actual canonical input digest, legacy ref, and legacy content hash.
Untracked catalog-owned content records the pinned catalog origin. Legacy bundle pins survive in
the namespaced `com.m1f1.legacy-pins` collection extension. The nondeterministic legacy
`synced_at` value is intentionally omitted.

The maintainer supplies all catalog-wide choices explicitly: canonical source ID and display name,
artifact version, supported profiles and platforms, install scopes, and install modes. These
options have a canonical digest and are part of every import plan and artifact importer provenance.
Given the same pinned tree, importer version, and options, output paths, bytes, executable bits,
warnings, and digests are identical.

## Review and apply workflow

```text
scan -> plan -> materialize -> native validate -> diff -> stage -> review -> apply
```

The first six phases do not change the destination. Materialization creates inert bytes only: MCP
descriptors, hook scripts, and setup recipes are copied but never imported, sourced, or executed.
The output is validated with the native source loader before it can be staged.

The diff binds the previous destination digest, output digest, and every added, changed, removed,
or unchanged path into a review digest. Apply requires that exact digest, re-hashes both the private
sibling stage and current destination, then publishes with verified filesystem renames. A detected
change or ordinary publish failure preserves or restores the reviewed destination; a no-op removes
the stage and reports that nothing changed. An abrupt process or machine failure between filesystem
renames can leave a private stage or `.previous` sibling, so full crash recovery remains a later
migration/registry-command responsibility.

## Scope and limitations

- This task exposes the typed Python application service and filesystem output adapter; Maintainer
  CLI commands arrive with the registry command work.
- The result is a canonical native source, not a registry lock or compiled index. IMP02 supplies
  the exact recorded-importer rerun check; REG01 will expose it through maintainer commands and
  registry quality gates. See
  [`registry maintenance planning v1`](../registry/maintenance-planning-v1.md).
- Foreign layouts that cannot be mapped without guessing must first be converted to the native AART
  standard. One-off converter plugins are intentionally unsupported.
- Import diagnostics never include credentials, local checkout paths, raw setup output, or arbitrary
  payload content.
