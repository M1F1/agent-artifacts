# AART 2.4.0

`2.3.0` shipped vendoring: copy a subtree of any Git repository into your registry as a package you
own, with a `provenance.json` recording where the bytes came from. A live acceptance run against a
real upstream then found the gap. AART verified the *instruction* — the URL, the ref, the subtree
path, all covered by `importer.options_digest` — and verified the *result* nowhere. The digest of
what was actually taken sat in `origin.input_digest`, written by every vendoring and read by nothing.

So a maintainer could edit a vendored payload by hand, re-lock, rebuild, and watch
`registry validate --strict --frozen`, `registry audit`, and `registry revendor --check` all report
success on a copy that no longer matched the origin it claimed. This release closes that.

## The copy is checked against the record it carries

Nothing new is written to disk, and no network call is added. The taken subtree is recoverable from
the package alone — the payload files not listed in `aart.vendor.authored` are exactly the copied
ones — so its digest can be recomputed and compared with the one already recorded:

```
$ aart registry audit --source .
error: artifacts/mcp/atlassian: the vendored copy does not match the origin it records
```

`registry validate --strict` fails the same way, offline. Re-locking and rebuilding do not clear it,
because the digest is recomputed from the bytes rather than read from the lock.

`registry revendor` runs the check **before** it opens a connection, so a broken copy is refused
instantly, upstream is never contacted, and no drift is computed from bytes that are already
untrustworthy.

**This is a consistency check, not an authentication.** It proves the package agrees with its own
record. Someone who edits the payload *and* rewrites the digest produces a consistent lie, and only
`--check-upstream` or a re-vendor can catch that. Provenance remains a record, not a signature, and
this release does not start claiming otherwise.

Patching upstream in place was never supported and now says so: fork, vendor from the fork, and the
provenance names where the bytes actually came from.

## `up-to-date` now explains itself

Vendoring one directory out of a monorepo normally leaves a recorded commit and a resolved commit
that differ, which read as a contradiction under the word `up-to-date`. The line that reconciles
them is now printed where they are:

```
  - check vendor-drift: passed
      disposition: up-to-date
      recorded commit: 4d9f2c1b…
      resolved commit: 9b1c7e4a…
      the ref moved, and nothing under packages/atlassian-mcp changed; the copy stays pinned to the recorded commit
```

Where the ref itself has not moved, it says that instead.

## What a consumer of an `mcp` artifact actually receives

Installing an artifact does not deliver the package; it applies the effects the type declares. For
four of the five types the whole payload arrives. For `mcp` it does not: installation merges the
`server` object out of `payload/mcp.json` and copies nothing.

That was documented nowhere, and the `2.3.0` tutorial taught an example that could not run. The
vendor review now says it, and refuses the two configurations that cannot work:

```
  - check vendor-delivery: passed
      installing this artifact merges the server entry from payload/mcp.json into the profile's MCP file and copies nothing; 4 copied payload files are not delivered to consumers
      the assessment above covers the copied bytes, including the ones no consumer of this artifact receives
```

- A `command` or `args` naming a file inside `payload/` names a file no consumer will have. The
  check fails; `registry audit` errors.
- A descriptor shaped `{"mcpServers": {…}}` — the shape of the harness file the entry is merged
  *into*, rather than the artifact's own `{"name": …, "server": {…}}` — has no `server` key at all,
  so installing it merges an empty entry that starts no process. It parsed, loaded, validated, and
  installed on `2.3.0` with every gate green. The check fails; `registry audit` errors.

The second line matters as much as the refusals: a `critical` assessment finding in a vendored
`install.sh` is a finding in a file no consumer of that artifact executes. Your registry is still
redistributing those bytes — which is why the assessment covers them — but the review now says which
risk you are looking at instead of leaving you to infer it.

The per-type delivery table is in the native source protocol document, and the tutorial's worked
example is one the checks pass, held there by a test that feeds every JSON fence in it to the same
function the review uses.

## Upgrading

A registry that passed `2.3.0` can fail `2.4.0`, in exactly three cases, each of them a registry
that was already broken and was not being told: an edited vendored payload, an `mcp` descriptor
naming a file inside `payload/`, and an `mcp` descriptor in the `{"mcpServers": …}` shape. The
remedies are in [the compatibility matrix](compatibility-v12.md).

**Consumers are unaffected.** No install effect changed, no document format changed, no field was
added, and a registry already published installs exactly as it did. Contract v12 carries protocol
versions identical to v11 and differs in two inputs, both protocol prose, neither a parsed field.

## Verifying this release

The wheel is byte-reproducible from the tagged commit:

```sh
git checkout v2.4.0
make wheel
shasum -a 256 dist/agent_artifacts-2.4.0-py3-none-any.whl
```

Compare the result with the digest published in this release's verification section.

## Not in this release

The one refusal considered and rejected: a wrongly-shaped `mcp` descriptor is not refused by the
loader. Doing that would make every registry already carrying one unloadable on upgrade — on the
consumer's side too — for a defect that harms nobody who has not yet tried to start the server. The
refusal lives where a maintainer is being asked to approve something. An owned, non-vendored `mcp`
package with the same mistake is still unchecked, and is recorded as a residue.

Start here: [the vendoring tutorial](../tutorials/vendoring-v1.md). See also the
[2.4.0 compatibility matrix](compatibility-v12.md) and
[release evidence](release-checklist-v12.md).
