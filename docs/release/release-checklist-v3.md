# AART 1.1.1 release checklist and evidence

The `1.1.1` release is a fail-closed patch contract, versioned separately from the immutable
`1.0.0` and `1.1.0` evidence.

Run from a clean checkout whose release commit is already reachable from `origin/main`, with a
clean fetched clone of the approved public reference registry:

```shell
make quality
make system-matrix
make release-check REGISTRY=/path/to/agent-artifacts-registry
python scripts/version.py check-tag v1.1.1
```

`make release-check` rejects incomplete historical tasks, a mismatched version, a source commit not
merged into `origin/main`, stale schema evidence, a dirty worktree/generated output, the wrong or a
stale registry origin, registry format/validate/lock/build/audit/compatibility failures, a failed
system matrix, or an invalid wheel.

## Release boundary

- Executable: `1.1.1` — patching the missing per-artifact compatibility implementation.
- Native Source/Registry Protocol: v1 with optional artifact `requires_aart` parsing and canonical
  projection.
- All other protocol/schema versions, source-store layout, profiles, installation scopes/modes,
  and zero-runtime-dependency delivery remain as in `1.1.0`.
- Frozen input digests: [`schema-freeze-v3.json`](schema-freeze-v3.json).
- Compatibility: [`compatibility-v3.md`](compatibility-v3.md).

## Acceptance evidence

- Strict parser tests cover absent, valid, malformed, and inverted artifact bounds.
- Registry build and parse round-trip the bound through `aart.index.json`.
- Runtime compatibility rejects only a selected incompatible artifact; source loading itself does
  not reinterpret the field as a registry-wide minimum.
- Marketplace JSON omits the bound for unrestricted artifacts, exposes declared bounds, and reports
  current-AART compatibility; the human marketplace keeps incompatible items visible with an
  unavailable reason.
- Install and security verification fail closed when manifest and index bounds disagree.
- Full quality, system matrix, wheel, and public reference-registry gates pass.

## Non-goals

- No automatic minimum bump when the AART executable version changes.
- No new runtime dependency.
- No REG02 registry payload changes in this executable release; those follow only after `1.1.1` is
  published.
