# AART 2.4.0 release checklist and evidence

This minor release closes three findings the `2.3.0` live acceptance run recorded: nothing verified
the shipped payload against the origin digest the package itself carries (`LAF-41`), `revendor`
reported `up-to-date` from the record rather than the bytes and printed two differing commits with
nothing to reconcile them (`LAF-42`), and a vendored `mcp` payload never reaches the consumer, which
was documented nowhere and taught wrongly in the tutorial (`LAF-46`). One further defect was found
while fixing the third and is closed with it: a descriptor shaped like the harness file it is merged
into installs an empty entry and starts nothing.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.4.0
python -m build --wheel
python scripts/release.py wheel-digest
```

The release check must pass repository/version evidence, schema freeze v12, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit,
and the release notes must carry the `sha256:<hex>  <wheel filename>` line
`python scripts/release.py wheel-digest` prints at the tag.

## Registry precondition

**None for the contract**, and one for content. A registry published on the `2.0.0` contract —
window `>= 2.0.0, < 3.0.0`, setup recipes at `2`/`2` with a package-root `SETUP.md` — satisfies
`registry test --compatibility all --latest-version 2.4.0` unchanged.

But a registry whose vendored content was already broken now fails, where it passed on `2.3.0`. The
three cases and their remedies are in [compatibility-v12.md](compatibility-v12.md) under *Upgrade
notes*: an edited vendored payload, an `mcp` descriptor naming a file inside `payload/`, and an
`mcp` descriptor written in the `{"mcpServers": …}` shape. Consumers are unaffected in all three.

## Acceptance

The copy is checked against the record it carries:

- the digest of the taken subtree is recomputed from the package on disk — payload minus
  `aart.vendor.authored`, under the immutable-Git snapshot origin — and equals `origin.input_digest`
  for a copy that was not touched;
- a single edited byte, an added file, a deleted file, and a changed executable bit each make it
  differ; hand-editing the authored list to hide a removal changes it too, because the digest covers
  the files that remain;
- `registry validate --strict` and `registry audit` fail on the mismatch, offline, and re-locking and
  rebuilding do not make either pass;
- the check is a consistency statement, not an authentication, and the release says so: a payload
  edited *and* re-digested is a consistent lie that only the network can catch.

Drift is a statement about the bytes on disk:

- `revendor` recomputes the copy's digest **before** it opens a connection; a copy that no longer
  matches its record is refused with upstream never contacted and no drift computed;
- the refusal fails the read-only `--check` and the mutating `--yes` alike, and writes nothing;
- `up-to-date` with a recorded and a resolved commit that differ carries the line that reconciles
  them — the ref moved and nothing under the taken subtree changed — and where the ref itself has
  not moved, it says that instead;
- the three dispositions still mean what they meant: an upstream that cannot be read is reported
  `unreachable`, never `up-to-date`.

The review says what a consumer will receive:

- for `mcp`, the vendor and re-vendor review carries a `vendor-delivery` check stating that
  installing merges the `server` object from `payload/mcp.json` and copies nothing, and how many
  copied files are therefore not delivered;
- it states, beside the assessment rather than after it, that the assessment covered bytes no
  consumer of this artifact receives;
- it **fails** when the descriptor's `command` or `args` names a file present under `payload/`, and
  when the descriptor declares no `server`; `registry audit` reports both as errors;
- the match is narrow by construction — only a string resolving to a file actually in the payload
  counts — so a path-shaped argument the consumer resolves is not refused for a guess;
- the four types that deliver their whole payload produce no finding at all.

The documentation states what the code enforces:

- the native source protocol tabulates, per type, the install effects, what reaches the consumer,
  and whether the payload may be referenced;
- the registry protocol states that a vendored copy is verified against its own record, and that
  `mcp` is the one type where the assessed set and the delivered set differ;
- the vendoring tutorial's worked descriptor is one the checks pass, and a test feeds every JSON
  fence in that tutorial to the same function the review uses, so a documented example that would
  fail the review fails the suite.

Protocol and packaging:

- the v12 schema freeze carries protocol versions identical to v11 and differs in two inputs —
  `docs/protocol/registry-v1.md` and `docs/protocol/native-source-v1.md` — neither of which is a
  parsed field;
- no document format, field, command, or flag is added, and no install effect changes;
- two builds of one commit at different wall-clock times produce byte-identical wheels;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

Nothing was loosened:

- every behavioural change in this release is a refusal added. The one refusal considered and
  rejected is recorded: refusing a wrongly-shaped `mcp` descriptor in the loader would make every
  registry already carrying one unloadable on upgrade, consumers included, so the refusal lives
  where a maintainer is asked to approve something.

## Evidence

Design: [DESIGN-vendored-copy-integrity.md](../design/DESIGN-vendored-copy-integrity.md). Plan and
work-package record, including what each package found that the plan did not anticipate:
[PLAN-vendored-copy-integrity.md](../plan/PLAN-vendored-copy-integrity.md). The maintainer's path is
[the vendoring tutorial](../tutorials/vendoring-v1.md).

The three findings originate in the `2.3.0` live acceptance run,
[PROGRESS-live-acceptance-v3.md](../testing/PROGRESS-live-acceptance-v3.md), whose findings ledger
records them with the transcripts that produced them.

Residues carried forward, recorded against no package because none owns them: `LAF-45`
(`audit --check-upstream` prints nothing when every vendored artifact is current), `LAF-47`
(uninstall leaves an empty `.mcp.json`), `LAF-43` (vendoring refuses a `file://` upstream, so the
`changed` disposition cannot be rehearsed locally), `LAF-49` (the allowlisted Git environment drops
`https_proxy`, undocumented), an owned non-vendored `mcp` package with a wrongly-shaped descriptor
being unchecked, and `commands/registry.py` stamping dead `1.0.0`/`2.0.0` AART bounds on every
non-`init` curation request.
