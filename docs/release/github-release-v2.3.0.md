# AART 2.3.0

`2.2.0` closed nine live-acceptance residues and left four open. This release answers one of them,
and it is the one that had no small fix: a promoted native reference is not a `requires` target, so
a registry that wanted to depend on foreign content — or simply publish it to consumers who must
reach one origin — had nowhere to put it.

## Vendoring

```sh
aart registry vendor --source . mcp atlassian \
  --url https://github.com/example/atlassian-mcp.git \
  --ref v1.4.0 --path packages/atlassian-mcp \
  --artifact-version 1.0.0 --summary "Atlassian MCP server, vendored from upstream." \
  --profile claude --platform darwin
```

That copies a subtree of any Git repository into the registry as a package the registry owns, pinned
to a resolved commit, with `provenance.json` recording where the bytes came from. The upstream needs
no AART markers, no `artifact.json`, and no interest in acquiring either.

**It is not a third document format.** A vendored artifact is an ordinary owned package that carries
a provenance document — the one AART has read since `2.0.0` — so every loader, lock, index, and
installer handles it with code that already existed, and an AART that predates this release reads it
without being taught anything. It is also, being registry-owned, a valid `requires` target. That is
how the residue is closed: by making the content owned, not by loosening the dependency rule.

The two facts re-vendoring needs and provenance does not carry — the ref the copy was taken at, and
which files you authored rather than copied — are written as the namespaced extension `aart.vendor`,
verified against `importer.options_digest`. Edit that record by hand and `registry audit` refuses it.

## What the review tells you, and what it refuses to tell you

The assessment runs over the exact bytes that would be written — the copied payload *and* the
wrapper you authored beside it — and renders its findings before Finalize:

```
  - check vendor-assessment: passed
      installation risk: critical
      findings: 5
      shell-pipe-to-interpreter (critical): Shell content pipes downloaded bytes directly to an interpreter. [payload/install.sh]
      setup-capability-keychain (high): Setup requests credential-store access.
      review-missing (medium): No registry review decision is attached to this artifact.
  warning: Vendoring copies upstream bytes into this registry and pins them to a commit; a successful vendor reports what was copied, and is not a safety claim.
  warning: This registry now owns the copy: upstream fixes do not reach consumers until it is vendored again.
```

The critical finding does not block the vendoring, and that is deliberate: the decision is yours, and
`review-missing` is AART recording that you have not attached one yet. What the tool will not do is
imply that a clean run means the content is safe. After a vendoring, your registry is the distributor
of somebody else's work — your consumers install those bytes on your word, having never seen the
origin, and upstream's later fixes, security fixes included, do not reach them until you vendor the
artifact again. That sentence is now in the registry protocol document, not only in a tutorial.

## When upstream moves

```sh
aart registry revendor --source . mcp atlassian --check
```

Three dispositions — `up-to-date`, `changed`, `unreachable` — and the third is the point: **an
upstream that cannot be read is never reported as up-to-date.** Silence is not evidence that nothing
changed. `--check` writes nothing and exits non-zero on drift, so it belongs in a scheduled job.

Applying a movement requires the version you state for it. Upstream declares no version this
registry can trust, so there is no default and no inference; a default would answer the one question
the command exists to ask.

## Licensing, and drift visible from CI

Vendoring reads a licence file at the subtree root and pre-fills the manifest where the text settles
the SPDX identifier — never guessing between GNU `-only` and `-or-later` — and reports what it found
or that it found nothing. `--license` states one explicitly, wins over the discovered value, and is
carried through re-vendoring instead of being erased the next time upstream moves.

`aart registry audit` reports a vendored artifact that records no licence. With the new
`--check-upstream` it also reports the ones behind their origin, and reports an unreachable origin
as unknown. Neither finding fails the audit — being behind upstream is a fact about the world, not a
defect in the registry — and without the flag the audit reaches no network at all, so it still works
offline and in CI with no remote.

## Also in this release

`vendor` and `revendor` are canonical actions in the maintainer text front-end, producing the same
request as the flags and rendering the same review; a test drives both front-ends over one fixture
and requires the two requests to be equal.

`registry vendor`, `revendor`, `promote-native`, and `refresh-native` each name their counterpart in
`--help`, because the choice between referencing a package and copying it is the decision that
matters and it was previously undocumented.

`agent_artifacts/io/net.py` is gone. It was an unreferenced GitHub-API helper reading `GITHUB_TOKEN`
and `GITHUB_API_URL` — a credential AART does not hold and has not held since `2.0.0`, when it
started reaching remotes by running system Git. Nothing shipped imported it. The `validate` gate now
refuses any package file naming either variable, so the promise cannot come back by accident.

## Verifying this release

The wheel is byte-reproducible from the tagged commit:

```sh
git checkout v2.3.0
make wheel
shasum -a 256 dist/agent_artifacts-2.3.0-py3-none-any.whl
```

Compare the result with the digest published in this release's verification section.

## Upgrading

Nothing to do. No protocol revision, schema, store layout, or on-disk format changed. No
`requires_aart` window needs re-authoring; `>= 2.0.0, < 3.0.0` admits this release, and a registry
that starts vendoring does not need to raise its floor — the packages it publishes are readable by
every AART in that window. A `2.3.0` data root is fully readable by `2.2.0`, `2.1.0`, and `2.0.0`.

Start here: [the vendoring tutorial](../tutorials/vendoring-v1.md). See also the
[2.3.0 compatibility matrix](compatibility-v11.md) and [release evidence](release-checklist-v11.md).
