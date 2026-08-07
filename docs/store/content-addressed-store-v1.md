# Content-addressed artifact store v1

This document records the implemented CAS01 boundary. It refines
[`SPEC-aart-1.0.md` section 14.3](../design/SPEC-aart-1.0.md#143-content-addressed-objects)
without wiring marketplace resolution, installation, setup, or CLI commands, which are later
tasks.

## Domain and application boundary

The `agent_artifacts.store` package owns pure immutable values for canonical object envelopes,
durable references, verified status, and garbage-collection plans. The application layer replaces
one owner/kind reference set and plans or executes collection through injected ports. It performs
no filesystem IO.

The filesystem adapters own staging, publication, verification, reference persistence, and the
global store lease. Runtime code remains Python-standard-library-only.

## Canonical object contract

An object digest is the SHA-256 of one canonical JSON envelope. The envelope contains
`schema_version: 1` and a path-sorted `entries` array. A file entry carries its safe relative path,
kind, executable bit, and canonical Base64 content; a directory entry carries no content. Parent
directories omitted by a producer are derived deterministically before hashing.

Parsing rejects non-canonical JSON/Base64, duplicate or conflicting paths, traversal, symlinks,
special files, invalid executable metadata, a mismatched expected digest, and forged value objects
whose entries do not match their canonical bytes. Bounds are enforced before publication:

- at most 20,000 total entries and 10,000 files;
- at most 10 MiB per file and 100 MiB total file content;
- at most 64 path components and a 150 MiB canonical envelope.

The same envelope is accepted by the compiler materialization adapter, so its `ObjectPlan.digest`
continues to bind the exact bytes that reconstruct the stored tree.

## Managed layout

The data-root-derived layout is fixed and cannot be redirected by constructing individual path
fields:

```text
<data-root>/
  objects/
    sha256/<first-two-hex>/<remaining-62-hex>/
    quarantine/
  state/object-references.json
  locks/store.lock/
  tmp/objects/
```

The filesystem root is not a valid data root. Existing managed root, `objects`, `sha256`, digest
prefix, `state`, reference, and quarantine boundaries are inspected without following symlinks.
Readers open object directories and files relative to verified directory descriptors with
`O_NOFOLLOW` where the platform provides it, then compare device, inode, type, and size to detect
replacement races.

## Publication, verification, and repair

Publication writes a private sibling stage, flushes file and directory metadata, applies read-only
modes, and atomically renames the complete tree to its digest path. Files are mode `0400` or `0500`
when executable; inner directories and the published root are mode `0500`. Independent concurrent
writers of identical content converge on the same verified object.

Every successful publication is read back and digest-verified. An existing verified object is
reused. A digest-path object with safe but mismatched canonical content is moved to quarantine and
replaced atomically; unsafe, unavailable, or symlinked targets fail closed instead of being treated
as repairable corruption. A failed replacement restores and re-freezes the prior object when that
is safe.

Status has three explicit outcomes: `missing`, `verified`, and `degraded`. A verified status binds
the same digest as its stored object; a degraded status carries typed diagnostics from verification.

## References and collection

The canonical private reference index supports these retention roots:

- `installed` for project/user installation manifests;
- `setup` and `transaction` for setup work and active operations;
- `source-current` for current compiled source snapshots;
- `retained` and `rollback` for explicit history policy.

An owner/kind update replaces only that owner's selected reference set. Updates and garbage
collection use the same global lease, so a collector cannot observe a partially replaced index.
The index write is staged, flushed, atomically replaced, mode `0600`, and strict-canonical on read.

Callers that create a newly referenced object use this sequence to close the publication/GC gap:

1. create a `transaction` reference for the intended digest;
2. publish and verify the object;
3. add its durable `installed`, `setup`, `source-current`, `retained`, or `rollback` reference;
4. remove the transaction reference.

References may intentionally precede object publication. Later installation/source tasks own this
orchestration and recovery of abandoned transaction references.

Collection defaults to dry-run and always computes the deterministic referenced/candidate
partition under the global lease. Execute mode deletes only candidates from that same plan. Each
target is renamed to a unique quarantine tombstone first. If physical removal fails before changing
content, the complete digest-verified tree is restored and re-frozen; a partially changed tombstone
is never restored as a valid object. Referenced digests are never candidates, regardless of
reference kind.

## Failure and compatibility behavior

Filesystem, lock, digest, schema, unsafe-entry, and partial-delete failures are returned as typed
diagnostics. Diagnostic text is redacted. Missing objects and an absent reference index are normal
read outcomes. Deletion of an already missing exact digest is idempotent.

CAS01 does not change legacy install/update behavior. Marketplace, manifest-v2, Copy/Symlink,
setup, and TUI tasks consume these ports incrementally; no migration or external package index is
assumed here.
