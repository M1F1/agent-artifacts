# AART 1.1.0 release checklist and evidence

The `1.1.0` release is fail-closed, and its contract is versioned separately from `1.0.0`. The
REL01 evidence — [`schema-freeze-v1.json`](schema-freeze-v1.json),
[`release-checklist-v1.md`](release-checklist-v1.md),
[`compatibility-v1.md`](compatibility-v1.md), and
[`github-release-v1.0.0.md`](github-release-v1.0.0.md) — is immutable and is never regenerated,
edited, or re-run by this checklist.

Run from a clean checkout whose release commit is already reachable from `origin/main`, with a
clean fetched clone of the approved public reference registry:

```shell
make quality
make system-matrix
make release-check REGISTRY=/path/to/agent-artifacts-registry
python scripts/version.py check-tag v1.1.0
```

`make release-check` rejects incomplete `PROGRESS.md`, a non-stable or mismatched version, a source
commit not merged into `origin/main`, missing release documents, stale schema-freeze evidence, a
dirty worktree/generated output, wrong registry origin, a dirty/noncurrent/stale-remote registry
revision, noncanonical formatting, incompatible protocol bounds, stale lock/index, audit failure,
failed minimum/latest compatibility, system-matrix failure, or an invalid wheel. It checks
source/registry cleanliness and the registry's origin-advertised default commit both before and
after external gates. Receipts expose stable codes and the accepted reference-registry commit
without captured subprocess output.

## Release boundary

- Executable: `1.1.0` — a minor release adding public command surface.
- Native Source/Registry Protocol and artifact manifests: v1, **unchanged since 1.0.0**.
- Configuration, setup, reporting, security assessment/attestation: schema/protocol v1.
- Installation state: schema v2, unchanged.
- Managed source store layout: **v2 (ref-aware)** — new in this release.
- Frozen input digests: [`schema-freeze-v2.json`](schema-freeze-v2.json). Exactly one input differs
  from the v1 freeze: `agent_artifacts/configuration/schema.py`, from the relaxed origin-and-ref
  uniqueness rule.
- Compatibility: [`compatibility-v2.md`](compatibility-v2.md).
- Migration from 0.1.x: unchanged, `migration-v1.md`.

## Acceptance evidence

- Every task through `REL01` remains complete in [`PROGRESS.md`](../../PROGRESS.md), and the
  post-1.0 catalog-boundary tasks `CB01`, `LIFE02`, `SRC02`, and `CFG02` are merged to `main`.
- The canonical non-interactive lifecycle (`aart marketplace install/update/uninstall/status/setup`)
  reviews before it finalizes: without `--yes` no command mutates, and `--yes` finalizes the digest
  of the review computed in the same process.
- Setup authorizations are never implied: untrusted sources, custom entrypoints, and effect consent
  each require their own explicit flag.
- The source store is ref-aware, its migration is planned purely and applied atomically, and it
  refuses to guess on conflict or ambiguity.
- Reviewed source-management configuration writes are lock-guarded and compare-and-swap; a
  concurrent writer is refused rather than overwritten.
- The thirteen-scenario system matrix continues to pass unchanged.
- The local distribution smoke proves editable-to-wheel replacement, environment deletion and
  recreation, Copy/Symlink lifecycle, and zero runtime dependencies without an index.

## Upgrade note carried into the release notes

The first `1.1.0` run against a `1.0.0` source store reports configured sources as `missing` until
`aart source doctor --apply` or `aart source sync` runs. This is deliberate: no stale pointer is
silently reused, and user data is never moved as a side effect of a read. `aart source health`
reports `pending_store_migration` and names the remedy.

## Not in this release

- No protocol, artifact, registry, or installation-state schema change.
- No change to `M1F1/agent-artifacts-registry` content; registry skill updates are tracked
  separately as `REG02` and land only after this executable version is published.
