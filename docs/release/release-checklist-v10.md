# AART 2.2.0 release checklist and evidence

This minor release answers a live-acceptance run rather than a feature request. Live acceptance v2
walked `2.1.0` through forty scenarios and filed thirteen residues; `2.2.0` closes nine of them —
every finding whose fix does not require a major — and takes the three open questions as decisions.
The theme is that a refusal now names the layer that failed and the command that fixes it, and that
the review an operator reads is the one that gets finalized.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.2.0
python -m build --wheel
python scripts/release.py wheel-digest
```

The release check must pass repository/version evidence, schema freeze v10, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit.

**New from this contract:** run `python scripts/release.py wheel-digest` at the tag and paste its
`sha256:<hex>  <wheel filename>` line into the release notes' verification section. The digest is a
property of the tagged commit, so it cannot be committed to the tree that determines it; publishing
it beside the artifact is what makes the reproducibility promise checkable by someone who did not
build it. See [wheel-reproducibility-v1.md](wheel-reproducibility-v1.md).

## Registry precondition

**None.** As in `2.1.0`, no registry needs re-authoring first. A registry already published on the
`2.0.0` contract — window `>= 2.0.0, < 3.0.0`, setup recipes at `2`/`2` with a package-root
`SETUP.md` — satisfies `registry test --compatibility all --latest-version 2.2.0` unchanged.

One caveat, and it is not a precondition: a registry whose `aart-registry.json` and
`aart-source.json` declare **different** identities is now refused at consumer acquisition. Such a
registry already failed `registry validate --strict --frozen`, so no registry that passes its own
maintainer gate is affected.

## Acceptance

A refusal names the layer that failed:

- an alias that was never configured, one configured but never synchronized, and a cold cache read
  under `--offline` each carry their own diagnostic and remediation, instead of three different
  problems arriving as `artifact-not-found` about the one part of the request that was never wrong;
- a registry whose two identity documents disagree is refused where it is acquired, naming both
  values and both files, on the direct and local paths as well as registry-git;
- a `requires` that cannot resolve says the dependency must be published by this registry, and
  distinguishes an identity absent from it from one it references from another origin.

The review an operator reads is the one that gets finalized:

- two reviews of one unchanged workspace produce one digest, seconds apart, live;
- `--expect` refuses when the recomputed review differs and renders the new plan in both text and
  JSON, so re-authorization is never blind;
- `source resubscribe --expect <from>:<to>` binds the transition, not the destination.

An adopted identity change reconciles:

- an installation whose origin re-declared its `source_id` reports `identity-changed` rather than
  `source-unavailable`, and `marketplace update` rebinds the record in the project that owns it;
- the rebinding review field is digest-bound, so consent for one identity cannot apply another.

Every command AART names exists:

- every user-visible `aart …` mention in the shipped package — not only `Diagnostic.remediation` —
  is parsed by the real `cli.build_parser()`, including display reasons and TUI hints;
- a command removed in `2.0.0` is legible to that guard because the compatibility tables record the
  removal, which makes the `2.0.0` addendum part of the gate rather than a note beside it;
- text and JSON carry the same remediation for every family that renders both.

Teardown leaves the repository as it found it:

- clean checkout → install → uninstall everything → `git status --porcelain` is empty, verified
  against a real git repository;
- a pre-existing profile directory holding foreign content survives, because `rmdir` is the guard
  rather than a check in front of one;
- a harness root such as `.claude` is never reclaimed;
- teardown runs inside the scope lock, after the removal it belongs to has been proven, and cannot
  fail it: litter that cannot be cleared is reported in the item's detail.

Protocol and packaging:

- the v10 schema freeze carries protocol versions identical to v9, and differs in two inputs —
  `agent_artifacts/setup.py` and `docs/protocol/registry-v1.md` — neither of which is a parsed
  field: one is the text of a rendered command, one documents a rule the compiler already enforced;
- two builds of one commit at different wall-clock times produce byte-identical wheels, and member
  order, compression, permissions, and create-system are pinned rather than left to a default;
- `SOURCE_DATE_EPOCH` is deliberately not read — an environment variable that silently moves the
  published bytes is the defect being removed, not a feature to add;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

Nothing was loosened, with one stated exception:

- `no-source-configured` no longer gates `marketplace uninstall`, because uninstall is not a content
  operation — it reads what the project already has, and `source remove`'s own review names
  uninstalling as a valid exit. Collections remain the exception, since the manifest never records a
  registry-side grouping. Every other refusal in this release is added or re-typed, never removed.

## Evidence

Design: [DESIGN-subscription-identity-binding.md](../design/DESIGN-subscription-identity-binding.md).
Plan and work-package record, including what each package found that the plan did not anticipate:
[PLAN-subscription-identity-binding.md](../plan/PLAN-subscription-identity-binding.md).
The originating residues — `LAF-16`/`LAF-35`, `LAF-17`, `LAF-30`, `LAF-31`, `LAF-32`, `LAF-33`,
`LAF-34`, `LAF-36`, `LAF-37`, `LAF-38`, `LAF-40` — are recorded in
[PROGRESS-live-acceptance-v2.md](../testing/PROGRESS-live-acceptance-v2.md); that ledger is appended
to, never rewritten.

Four residues are deliberately not closed here and are recorded against the package that owns them:
`marketplace status` in a project whose only subscription was removed, a malformed
`aart-registry.json` skipping the identity comparison, no CLI surface reversing a completed setup,
and a promoted artifact not being a `requires` target — the last of which `2.3.0` answers with
`registry vendor`.
