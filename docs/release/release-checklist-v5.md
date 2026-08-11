# AART 1.3.0 release checklist and evidence

The `1.3.0` release is a fail-closed minor-release contract, versioned separately from the immutable
v1–v4 evidence.

Run from a clean checkout whose release commit is already reachable from `origin/main`, with a clean
fetched clone of the approved public reference registry:

```shell
make quality
make system-matrix
make release-check REGISTRY=/path/to/agent-artifacts-registry
python scripts/version.py check-tag v1.3.0
```

`make release-check` rejects incomplete tasks, a mismatched version, a source commit not merged into
`origin/main`, stale schema evidence, a dirty worktree/generated output, the wrong or stale registry
origin, failed registry format/validate/lock/build/audit/compatibility, a failed system matrix, or an
invalid wheel.

## Release boundary

- Executable: `1.3.0`, a minor bump for a new consent default and federated reporting routes.
- Native Source/Registry Protocol: v1, unchanged.
- Reporting protocol and serialized report schema: v1, unchanged.
- Configuration schema document: v1, with prompt mode now valid without a central destination.
- Existing explicit `disabled` remains silent; `automatic` still requires an explicit destination.
- All installation state, source-store, setup, security, profile, platform, scope, mode, and
  zero-runtime-dependency boundaries remain as in `1.2.0`.
- Frozen input digests: [`schema-freeze-v5.json`](schema-freeze-v5.json).
- Compatibility: [`compatibility-v5.md`](compatibility-v5.md).

## Acceptance evidence

- Configuration tests cover omitted reporting, explicit disabled, prompt with and without a central
  destination, automatic validation, organization policy, and the documented downgrade boundary.
- Projection and application tests prove results are partitioned before serialization, each
  registry sees only its artifacts, identical endpoints are deduplicated, and direct sources are
  omitted.
- Destination tests prove routing uses enabled registry-git local snapshots without implicit fetch
  and rejects invalid or policy-denied advertisements.
- TUI tests prove every proposed Issue retains both default-No confirmation boundaries.
- Full quality, system matrix, wheel, and public reference-registry gates pass.

## Non-goals

- No reporting payload field for a local source alias and no reporting protocol bump.
- No automatic mode driven by registry metadata.
- No network fetch while discovering reporting routes.
- No automatic `requires_aart` bump for registries or artifacts.
