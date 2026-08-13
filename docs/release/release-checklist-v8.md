# AART 2.0.0 release checklist and evidence

This major release is the canonical remediation. It removes the legacy catalog product from the
binary, puts one package compiler before every publication and consumption boundary, reconciles the
lifecycle through a single snapshot-bound plan, and makes artifact dependencies first-class.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.0.0
python -m build --wheel
```

The release check must pass repository/version evidence, schema freeze v8, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit.

## Registry precondition

**`make release-check` requires a registry already re-authored for this release**, and unlike the
`1.4.0` precondition this one is satisfiable. The registry must declare a `requires_aart` window
that admits `2.0.0` — the conventional `max_exclusive: "2.0.0"` excludes it — and any setup-capable
artifact must declare a `2`/`2` recipe with a package-root `SETUP.md`. That combination is rejected
by every released `1.x` executable, so the registry and the executable must be released in that
order: publish the executable, then repoint registry CI at the released tag.

The `1.4.0` checklist recorded the opposite precondition and could not be met by any registry; see
the contradiction section of [compatibility-v8.md](compatibility-v8.md).

## Acceptance

One product, one interface:

- the top level exposes only `marketplace`, `source`, `registry`, `security`, `reporting`, and
  `upgrade`; the nine removed verbs are absent rather than deprecated;
- no runtime module reads, writes, or advertises a legacy catalog, and no active document links one;
- an empty Git checkout is not classified as a registry, so a consumer is never routed into
  maintainer curation;
- a retired 0.1 state file produces one typed diagnostic naming remove-and-reinstall, not a set of
  generic schema complaints.

One compiler before every boundary:

- registry validation, lock, build, audit, source snapshot compilation, object materialization,
  security export, install planning, and setup planning consume the same `CompiledArtifact`;
- a package-root `SETUP.md` is valid at publication and at consumption under one rule;
- an artifact that passes publication cannot fail at consumption for a structural reason;
- a package whose setup object fails to compile places no payload effect, so a failed install
  leaves no MCP configuration behind.

One reconciliation plan:

- status, check, update, prune, uninstall, review, and outcome rendering are projections of one
  snapshot-bound plan;
- a bare `update` reconciles every installation in the requested scope rather than doing nothing;
- finalization is reported from durable state, never independently of it;
- a forced memory replace preserves the displaced bytes and uninstall restores them; a missing
  sidecar is a typed conflict, never a silent delete.

Dependencies and consent:

- a runnable artifact cannot be installed without its declared required artifacts, and an
  unsatisfied dependency fails without mutation;
- command review/finalize is the only mutation contract; `--json` is a rendering and changes no
  effect, so an agent can read a plan without installing it;
- setup authorizations are never implied; TUI cancellation is explicit and a TUI is human-only
  policy, not a security control.

Packaging:

- the built wheel reproduces the checkout's typed diagnostics byte for byte, not merely its imports;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

## Evidence

Recorded in [PROGRESS.md](../../PROGRESS.md) under the canonical remediation entry, and in the
remediation run record required by WP-7 of
[PLAN-post-live-acceptance-remediation.md](../plan/PLAN-post-live-acceptance-remediation.md). The
original live-acceptance evidence in
[PROGRESS-live-acceptance.md](../testing/PROGRESS-live-acceptance.md) is not rewritten; this release
is the response to it.
