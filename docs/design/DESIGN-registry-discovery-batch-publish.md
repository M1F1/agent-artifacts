# Registry discovery, batch vendoring, and publishing

Status: implemented for the company-adoption repair stream (`AD-05`, `AD-08`, `AD-14`).

## Boundary

Discovery is suggestion, not import. `registry discover` reads one inert local checkout through the
bounded, non-symlink-following source reader and recognises only conventional file shapes. It emits
a schema-versioned JSON document; every candidate is rejected unless the operator explicitly sets
`accept` to `true`. Names and summaries are proposed data in that document, never upstream facts.

The manifest records one credential-free Git URL and ref. The checkout supplies discovery evidence;
the later vendoring resolves the recorded origin independently, so working-tree bytes are never
silently published as if they came from a commit.

## Manifest and acceptance

The manifest holds origin, shared defaults, and artifact items. An accepted item must state kind,
name, path, summary, version, profiles, platforms, scopes, modes, and review policy, either directly
or through defaults. Optional licence and setup-recipe declarations preserve the single-artifact
vendoring contract. Rejected items are inert and may remain as the durable review record.

Conventional recognition covers:

- directories containing `SKILL.md`;
- Markdown documents below `guideline`, `guidelines`, or `rules` directories;
- conventional MCP JSON descriptors;
- `hook.json` below a hooks directory;
- loose harness-memory documents such as `CLAUDE.md`, `AGENTS.md`, and `TABNINE.md`.

This is intentionally conservative. Missing a candidate costs a manual manifest item; inventing one
could turn unrelated repository content into a package.

## Batch semantics

`registry vendor-batch` is orchestration over `plan_artifact_vendor`, not a second importer. It:

1. parses and validates accepted items before contacting upstream;
2. resolves the manifest origin exactly once;
3. projects each ordinary vendor plan into the next in-memory snapshot;
4. aggregates their files into one `RegistryOperation.VENDOR_BATCH` plan;
5. applies only the digest the maintainer reviewed.

Every item therefore retains ordinary provenance, licence discovery, baseline security assessment,
delivery checks, and package-shape validation. Any refusal aborts the aggregate; the filesystem sees
all packages or none. A regular file is a supported subtree, which keeps loose memory/guideline
documents on the provenance and re-vendoring path.

## Publisher semantics

`registry publish` replaces the remembered command sequence with one reviewed transaction:

1. acquire each approved native reference;
2. plan the lock over the current snapshot;
3. project it and plan the index;
4. project both and run compiled validation and audit;
5. aggregate lock and index into one digest-bound workspace plan;
6. list the aggregate plus every pre-existing Git change;
7. with `--yes`, apply, `git add -A`, and create one commit.

A failing planner, validation, or audit gate stops before the commit. Preview writes nothing. An
unchanged clean rerun creates no commit. The command never pushes and offers no gate-bypass flag.
The explicit file list is part of the review because pre-existing Git changes are intentionally part
of the same `git add -A` commit.
