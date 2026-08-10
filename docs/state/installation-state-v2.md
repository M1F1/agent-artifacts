# Installation state v2 and legacy migration

This document records the implemented STATE01 boundary. It refines
[`SPEC-aart-1.0.md` section 16.4](../design/SPEC-aart-1.0.md#164-state) without yet replacing
the legacy install/update/uninstall command orchestration; INS01 through LIFE01 consume this state
contract, and MIG01 adds the complete public compatibility workflow.

## Domain boundary

`agent_artifacts.install_state` owns immutable installation evidence, strict canonical schema-v2
parsing/writing, platform-independent path policy, and pure legacy migration planning. The
application service exposes three distinct operations:

1. `prepare` reads the explicit legacy manifest and returns an immutable dry-run plan;
2. `apply` executes exactly that reviewed plan or reports a stale/busy/IO diagnostic;
3. `rollback` restores the exact legacy bytes from the deterministic backup.

The local filesystem adapter owns bounded no-follow reads, private atomic writes, the exclusive
migration lock, fsync, backup, journaling, compensation, and rollback. The pure planner imports no
filesystem or process modules.

## Canonical manifest

The top-level document has exactly `schema_version: 2` and a deterministically sorted
`installations` array. Each installation records:

- qualified source alias, declared source ID, kind, credential-free origin, immutable resolved
  commit, and the Git subscription ref used by a later explicit update;
- artifact type/name, SemVer, manifest digest, payload digest, and immutable object digest;
- harness profile/version and a non-crossing `project` or `user` scope;
- requested mode plus the actual mode and digest proof of every individual effect;
- merge locator/mode/identity digest where applicable; and
- only a non-secret setup-state reference, never credentials or raw setup output.

Project destinations are canonical relative paths. User destinations are normalized absolute
paths. Unknown fields, duplicate JSON keys, floats, invalid Unicode, unsafe paths, noncanonical
digests, unsafe Git origins/refs, inconsistent coordinates, incomplete effect variants, duplicate
installation identities, and schema versions other than `2` fail closed.

Canonical output is UTF-8 JSON with sorted object keys, no insignificant whitespace, and one final
newline. Parsing and rewriting the same value is byte-stable.

## State paths

Path resolution is pure and requires explicit normalized roots:

```text
project legacy and v2:
  <project>/.agent-artifacts/manifest.json

user legacy:
  <user-home>/.agent-artifacts/manifest.json

user v2:
  <platform-data-root>/state/manifest.json
```

Backups, journals, and the migration lock live beside the selected v2 state boundary, never in a
source checkout or Python environment. Tests provide fake project, home, and data roots; runtime
path/environment resolution remains outside this context.

## Explicit legacy evidence

The 0.1.x manifest does not contain canonical source aliases/IDs, artifact versions, or all three
content digests. Migration therefore requires exactly one `LegacyMigrationCandidate` for every
legacy `(type, artifact, profile, source)` key. Zero matches is `state-migration-source-missing`;
multiple matches is `state-migration-source-ambiguous`.

Each candidate must prove the exact legacy destinations, file/value digests, requested/actual mode,
symlink disposition, merge locator/mode/identity digest, profile version, canonical source, and
artifact evidence. A credential-bearing legacy Git subscription, duplicate-key/non-strict legacy
JSON, or evidence mismatch is rejected before a backup is created.

## Transaction and recovery

The dry-run plan binds paths and exact legacy/replacement digests into a review digest. Its journal
is canonical and contains only paths/digests, not file contents or setup output. Constructors and
the adapter independently reject replacement bytes or metadata that no longer match the review.

Apply acquires a private lock and rechecks the legacy bytes immediately before mutation. It creates
`manifest-v1-<full-legacy-sha256>.json` as a mode-`0600` backup, atomically writes v2, writes the
review journal, then removes the old user-global manifest only after all new state is durable.
Project migration replaces the same manifest path. Reapplying the same successful plan is an
explicit no-op.

Failures after an atomic replace, journal write, or legacy unlink compensate back to usable legacy
state. Rollback likewise verifies the exact backup, v2 bytes, and journal before mutation; if a
rollback step fails, it compensates back to the complete migrated state so the operation can be
retried. Unexpected concurrent content is never overwritten during compensation.

The backup remains after rollback as recovery evidence. Future cleanup is an explicit retention/GC
decision, not a side effect of migration.
