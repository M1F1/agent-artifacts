# AART 1.0.0 release checklist and evidence

The `1.0.0` release is fail-closed. Run from a clean checkout whose release commit is already
reachable from `origin/main`, with a clean fetched clone of the approved public reference registry:

```shell
make quality
make system-matrix
make release-check REGISTRY=/path/to/agent-artifacts-registry
python scripts/version.py check-tag v1.0.0
```

`make release-check` rejects incomplete `PROGRESS.md`, a non-stable or mismatched version, a source
commit not merged into `origin/main`, missing migration/release documents, stale schema-freeze
evidence, a dirty worktree/generated output, wrong registry origin, a dirty/noncurrent/stale-remote
registry revision, noncanonical formatting, incompatible protocol bounds, stale lock/index, audit
failure, failed minimum/latest compatibility, system-matrix failure, or an invalid wheel. It checks
source/registry cleanliness and the registry's origin-advertised default commit both before and
after external gates. Receipts expose stable codes and the accepted reference-registry commit
without captured subprocess output.

## Frozen release boundary

- Executable: `1.0.0`.
- Native Source/Registry Protocol and artifact manifests: v1.
- Configuration, setup, reporting, security assessment/attestation: schema/protocol v1.
- Installation state: schema v2.
- Frozen input digests: [`schema-freeze-v1.json`](schema-freeze-v1.json).
- Compatibility: [`compatibility-v1.md`](compatibility-v1.md).
- Migration and rollback: [`migration-v1.md`](migration-v1.md).

## Acceptance evidence

- Every task P00–REL01 is complete in [`PROGRESS.md`](../../PROGRESS.md).
- The thirteen-scenario system matrix covers direct-only, public/company/team, native reference,
  foreign import, collisions, trust downgrade, offline, concurrency, corruption, partial setup,
  analyzer failure, absent reporting, and migration/rollback.
- The local distribution smoke proves editable-to-wheel replacement, environment deletion and
  recreation, Copy/Symlink lifecycle, and zero runtime dependencies without an index.
- The public registry is exactly
  [`M1F1/agent-artifacts-registry`](https://github.com/M1F1/agent-artifacts-registry), is public,
  has a frozen lock/index, and passes current strict/minimum/latest AART checks.
- Packaging rejects operational catalog roots and validates every wheel member and RECORD digest.
- Nexus/PyPI publication is neither performed nor required.

The GitHub `v1.0.0` tag/release workflow repeats `make quality` on Python 3.10 and 3.14, fetches
`origin/main`, proves the tag commit is already merged there, clones and rechecks the approved
registry, validates `v1.0.0`, builds the local wheel, and attaches it to the GitHub release. Later
versions require their own versioned release contract rather than silently reusing 1.0.0 gates.
