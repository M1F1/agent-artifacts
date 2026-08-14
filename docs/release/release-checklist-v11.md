# AART 2.3.0 release checklist and evidence

This minor release answers a residue the `2.2.0` contract recorded and deliberately did not close:
a promoted native reference is not a `requires` target, so a registry that wanted to depend on
foreign content had no way to publish it. `registry vendor` is that way — it copies a subtree of any
repository into the registry as a package the registry owns, and records where the bytes came from.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.3.0
python -m build --wheel
python scripts/release.py wheel-digest
```

The release check must pass repository/version evidence, schema freeze v11, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit,
and the release notes must carry the `sha256:<hex>  <wheel filename>` line
`python scripts/release.py wheel-digest` prints at the tag.

## Registry precondition

**None.** A registry already published on the `2.0.0` contract — window `>= 2.0.0, < 3.0.0`, setup
recipes at `2`/`2` with a package-root `SETUP.md` — satisfies
`registry test --compatibility all --latest-version 2.3.0` unchanged.

A registry that starts vendoring does not need to raise its floor either. A vendored artifact is an
ordinary owned package carrying `provenance.json`, so every AART in that window installs it.

## Acceptance

A foreign subtree becomes a package this registry owns:

- an upstream with no `aart-source.json`, no `artifact.json`, and an arbitrary layout is vendored
  from a named subtree at a resolved commit, and the copy is what the registry ships;
- the subtree is taken whole or not at all: a repository containing a symlink anywhere cannot be
  acquired, and a symlink inside the taken subtree is refused;
- the wrapper the maintainer authored beside the copy — the payload document the type requires, a
  `SETUP.md`, a setup recipe — is adopted, not overwritten, on the first vendoring and on every
  re-vendoring after it;
- `requires` resolves against a vendored identity, because it is registry-owned; the `2.2.0` residue
  is closed by making the content owned, not by loosening the dependency rule.

The copy states where it came from, and cannot lie about it:

- `provenance.json` records the credential-free URL, the lowercase 40-hex resolved commit, the
  subtree path, the input digest, and importer `registry-vendor-v1`;
- the ref and the authored file list are written as the namespaced extension `aart.vendor`, verified
  against `importer.options_digest`, so a hand-edited record fails `registry audit`;
- no loader, index, lock, or installer treats the package specially.

Drift is visible, and silence is never mistaken for agreement:

- `revendor` reports `up-to-date`, `changed`, or `unreachable`, and an upstream that cannot be read
  is never reported as up-to-date;
- `revendor --check` writes nothing and exits non-zero on `changed`, including on `unreachable`,
  which is the one reading the design forbids treating as success;
- applying a movement requires the version the maintainer states; there is no default, because
  upstream declares no version this registry can trust;
- `registry audit --check-upstream` reports vendored artifacts behind their origin and unreachable
  origins as unknown; without the flag the audit reaches no network at all.

The review reports what the assessment found, and claims nothing more:

- the assessment runs over the exact bytes that would be written, wrapper included, and its findings
  are rendered before Finalize with the attestation committed beside the package;
- a critical finding does not block the vendoring: the decision is the maintainer's, and
  `review-missing` records that no decision has been attached;
- the review warns, in both the vendor and re-vendor cases, that a successful run reports what was
  copied and is not a safety claim, and that upstream's fixes do not reach consumers until the
  artifact is vendored again.

Licensing is recorded or its absence is visible:

- a licence file at the subtree root pre-fills the manifest where the text settles the SPDX
  identifier; the GNU family is recognised but `-only`/`-or-later` is never guessed;
- `--license` states one explicitly and wins over the discovered value, and survives re-vendoring
  rather than being erased when upstream moves;
- `registry audit` reports a vendored artifact that records no licence, and still exits successfully.

The same action is available in the text front-end:

- `vendor` and `revendor` are canonical maintainer actions producing the same `CurationRequest` as
  flag mode for one fixture, asserted by test, and rendering the same review including the
  assessment;
- a blank version at the `revendor` prompt means what omitting `--artifact-version` means: report
  what moved, plan nothing.

The package no longer advertises a credential it never had:

- `agent_artifacts/io/net.py` is deleted; nothing shipped imported it;
- the `validate` gate refuses any file under `agent_artifacts/` naming `GITHUB_TOKEN` or
  `GITHUB_API_URL`, so the promise cannot return by accident;
- the two superseded upstream-import design documents carry banners, and the fact that AART holds no
  credentials of its own — true since `2.0.0` — is recorded in `compatibility-v10-addendum.md`.

Protocol and packaging:

- the v11 schema freeze carries protocol versions identical to v10 and differs in two inputs —
  `docs/protocol/registry-v1.md` and `docs/protocol/native-source-v1.md` — neither of which is a
  parsed field: both document what vendoring is and what it costs;
- two builds of one commit at different wall-clock times produce byte-identical wheels;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

Nothing was loosened:

- every refusal in this release is added, and the one deletion removes an unused module rather than
  a rule. The `requires` rule that produced the originating residue is unchanged: the answer is that
  vendored content is owned, not that foreign content became a dependency target.

## Evidence

Design: [DESIGN-registry-vendoring.md](../design/DESIGN-registry-vendoring.md). Plan and work-package
record, including what each package found that the plan did not anticipate:
[PLAN-registry-vendoring.md](../plan/PLAN-registry-vendoring.md). The worked path a maintainer
follows is [the vendoring tutorial](../tutorials/vendoring-v1.md).

The originating residue is recorded in the `2.2.0` evidence
([release-checklist-v10.md](release-checklist-v10.md)) as the last of the four not closed there.

Residues carried forward, recorded against no package because none owns them:
`agent_artifacts/io/cache.py` is now unreferenced by shipping code, `docs/design/DESIGN-upstream.md`
carries no superseded banner, and `commands/registry.py` stamps dead `1.0.0`/`2.0.0` AART bounds on
every non-`init` curation request.
