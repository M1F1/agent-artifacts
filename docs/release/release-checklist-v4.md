# AART 1.2.0 release checklist and evidence

The `1.2.0` release is a fail-closed minor-release contract, versioned separately from the immutable
v1–v3 evidence.

Run from a clean checkout whose release commit is already reachable from `origin/main`, with a clean
fetched clone of the approved public reference registry:

```shell
make quality
make system-matrix
make release-check REGISTRY=/path/to/agent-artifacts-registry
python scripts/version.py check-tag v1.2.0
```

`make release-check` rejects incomplete tasks, a mismatched version, a source commit not merged into
`origin/main`, stale schema evidence, a dirty worktree/generated output, the wrong or stale registry
origin, failed registry format/validate/lock/build/audit/compatibility, a failed system matrix, or an
invalid wheel.

## Release boundary

- Executable: `1.2.0`, a minor bump for additive collection lifecycle and runtime-health commands.
- Native Source/Registry Protocol: v1, unchanged.
- Advisory runtime requirement extension: v1, carried through the existing namespaced-extension
  mechanism and deliberately absent from installation compatibility.
- All installation state, configuration, source-store, setup, security, reporting, profile,
  platform, scope, mode, and zero-runtime-dependency boundaries remain as in `1.1.1`.
- Frozen input digests: [`schema-freeze-v4.json`](schema-freeze-v4.json).
- Compatibility: [`compatibility-v4.md`](compatibility-v4.md).

## Acceptance evidence

- CLI and TUI tests cover collection discovery, exact member expansion, ambiguity/not-found
  diagnostics, Review, Copy/Symlink, and project/user lifecycle behavior.
- Runtime metadata tests cover absent/valid/malformed declarations and strict repository inventory
  parsing without process probes.
- Evaluator tests cover satisfied, unsatisfied, and unknown observations.
- End-to-end testing proves an unsatisfied Python observation returns a valid advisory report and
  the same artifact still installs successfully.
- Full quality, system matrix, wheel, and public reference-registry gates pass.

## Non-goals

- No runtime or package installation, arbitrary command execution, or ambient-environment probing.
- No strict AART mode that converts advisory health into an installation gate.
- No automatic `requires_aart` bump for registries or artifacts.
- No compiled-index or native protocol version increase.
