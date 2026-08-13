# Registry maintenance planning v1

IMP02 defines the review boundary for adding native references, promoting them into a registry, and
checking both native and materialized upstreams. The implementation is a pure functional planner
over inert snapshots. Filesystem access, Git acquisition, credentials, commit, push, and pull-request
creation remain outside this bounded context.

## Native entry and promotion

Adding an entry authors one canonical `entries/<type>/<name>.json` document. Pending, rejected, and
approved review records can be stored for a maintainer workflow, but only an approved entry can be
promoted into generated consumer outputs.

Promotion receives an acquisition proof containing the entry's exact credential-free URL and ref,
a lowercase 40-hex resolved commit, and an immutable Git snapshot. It validates the upstream as a
native AART source and requires the declared package path and identity to match exactly. The
resulting change set is limited to:

- the canonical entry document;
- `aart.lock.json`, with commit, version, manifest, payload, object, review, and provenance digests;
- `aart.index.json`, with the payload-free package projection and derived collection membership.

The payload is not copied into the registry. The index retains the upstream native `source_id`;
registry-owned packages retain the registry's own identity. Existing registry-owned packages are
revalidated and rebuilt into the projection, so adding an external reference cannot remove them.
The registry marker and its native-source marker must identify the same source, including when the
registry declares a non-default artifact root.

## Locked native updates

An upstream check repeats the same promotion plan against the current workspace. Before proposing
an update, AART requires authored entries, the committed lock, and the compiled index to agree on
registry inputs, identities, source, version, manifest/payload/object digests, review evidence, and
provenance presence. A source-identity change is rejected rather than silently reclassifying an
artifact.

The same acquisition is an explicit `up-to-date` no-op. A new commit or changed canonical package
produces a reviewable `changed` plan. Advancing a ref never mutates the workspace automatically.

## Retired foreign layouts

Registry maintenance accepts only native AART sources. A foreign or legacy layout must be
re-authored outside the normal AART runtime before it can be promoted; there is no importer or
automatic migration path.

## Review and apply boundary

Every registry mutation binds the expected registry-input digest, resulting input digest, ordered
paths, change kinds, prior digests, and resulting bytes' digests into one review digest. Apply
requires that exact digest. Both changed and no-op finalization recheck the current workspace, and
the injected output port must return a receipt matching the reviewed digest, resulting input
digest, and changed-path count.

The port has no commit or push operation. REG01 will expose these planners through maintainer
commands and registry quality gates; Git publication remains an explicit action after reviewing the
generated diff. The consumer-side lock and index invariants are specified in
[`registry protocol v1`](../protocol/registry-v1.md).
