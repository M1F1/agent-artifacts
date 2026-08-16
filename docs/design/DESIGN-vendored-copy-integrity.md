# Design: vendored copy integrity, and what a consumer receives

A registry that vendors somebody else's code makes exactly one claim about it: *these bytes are the
bytes that were at this URL, at this commit, under this path.* This design gives that claim a gate,
makes the drift report a statement about the bytes on disk rather than about a record, and writes
down what an installed artifact actually delivers.

Companion to [DESIGN-registry-vendoring.md](DESIGN-registry-vendoring.md), which built the feature.
It answers three findings of the third live-acceptance run,
[PROGRESS-live-acceptance-v3.md](../testing/PROGRESS-live-acceptance-v3.md): `LAF-41`, `LAF-42`,
`LAF-46`.

## 1. What the run found

**`LAF-41` — the copy's own record is never checked against the copy.** `origin.input_digest` is
written when the package is vendored and read by nothing afterwards. Replace every byte under
`payload/`, re-run `registry lock --yes` and `registry build --yes`, and `registry validate --strict
--frozen` and `registry audit` are both green. They are green *by construction*: the lock and the
index are derived from the bytes that are there, so they agree with any substitution. The one
document that says what the bytes were supposed to be is the one document nothing consults.

**`LAF-42` — a copy two months behind upstream was reported `up-to-date`.** `plan_artifact_revendor`
compares the freshly resolved subtree against the *recorded* `input_digest`
(`registry_commands/planning.py:750`), not against the payload. A copy whose bytes no longer match
its own record is therefore compared as though they did, and the answer describes a package the
registry does not ship. The same block prints `recorded commit:` and `resolved commit:` around the
word `up-to-date` with no line reconciling them — and in a monorepo, where most commits do not touch
the vendored subtree, two differing commits under `up-to-date` is also the *healthy* output. The
operator has no way to tell one from the other.

**`LAF-46` — for `mcp`, the copied payload never reaches the consumer.** Installing a vendored
`mcp/mcp-git` wrote one thing: the server entry from `payload/mcp.json`, merged into `.mcp.json`.
The other twelve copied files stayed in the registry. The `2.3.0` tutorial's worked example —
`{"command": "node", "args": ["payload/index.js"]}` — cannot run on any consumer machine, because
`payload/index.js` is never delivered there. Nothing states this, and for this one type the vendor
review reports risk found in bytes the consumer never executes.

## 2. One root cause

AART verifies the **instruction** and does not verify the **result**.

`vendor_options_digest` covers the URL, the ref, and the subtree path
(`registry_maintenance/vendoring.py:186`), and `read_vendor_record` refuses a `provenance.json` whose
`aart.vendor` no longer matches it (`vendoring.py:257`). That is why editing `origin.url` by hand is
caught, live, and reported by name. `origin.input_digest` — the field that describes the *outcome* of
following that instruction — is covered by nothing.

The asymmetry is the whole of `LAF-41`, and it is also the mechanism of `LAF-42`: a drift comparison
that starts from an unverified record inherits its unverifiability. Fix the first and the second
becomes a rendering question.

`LAF-46` is a different kind of gap in the same claim. Vendoring says where bytes came from. It never
said which of them a consumer gets, and for four of the five artifact types the answer is "all of
them", which is why nobody wrote it down.

## 3. The copy already verifies itself

No new field, no format revision, and no re-acquisition is needed. `origin.input_digest` is
recomputable from the package on disk.

`project_vendored_package` writes the taken subtree at `payload/<path>` for every file entry and the
maintainer's own files beside them (`vendoring.py:465`). Two properties make the inverse exact:

- **The two sets are disjoint.** `_authored_files` refuses an authored path that collides with a
  taken one — *"never silently over-write a taken byte"* (`vendoring.py:358`) — so subtracting the
  paths recorded in `aart.vendor.authored` from the payload leaves precisely the taken files, with
  their content and executable bits.
- **The taken directories are derivable.** `take_subtree` refuses symlinks and special files
  outright and carries only files and directories, and a Git tree holds no empty directory. So the
  directory entries of the taken snapshot are exactly the ancestors of the taken files.

Feed those entries to `source_snapshot_digest` under `SnapshotOrigin.IMMUTABLE_GIT` and the result is
the value `take_subtree` produced when the copy was made. This is not an inference. Run against the
two packages the acceptance run vendored from `modelcontextprotocol/servers`, the recomputation
reproduces both recorded digests byte for byte, and reports a mismatch for the reconstructed
two-month-old copy that produced `LAF-41` and `LAF-42`.

That matters for compatibility more than for elegance: **every package vendored by `2.3.0` is
verifiable by this release with no re-vendoring, no migration, and no network.**

### What a mismatch means, and what it does not

A mismatch means the shipped bytes are not the bytes the provenance describes. It does not say who
changed them or why — a local patch, a bad merge, an editor writing CRLF, or a substitution — and the
diagnostic must not pretend to know. It names the two digests, the package, and the three plausible
causes, so the maintainer can tell which one it is.

Local patching deserves a straight answer, because vendoring invites it: the bytes are right there.
AART has no representation for a patched copy, and inventing one here would be a format revision
answering a question this release is not asking. The supported route is to fork upstream, patch the
fork, and vendor from it — the fork is then a real origin with a real commit, and the copy's claim
stays true. The diagnostic says so.

## 4. Where the check runs

One function, three callers, and the same answer in all three. It is a pure function of the
committed snapshot, so it costs no network and works offline and in CI.

| Caller | On mismatch | Why there |
|---|---|---|
| `registry validate` | **error**, gate fails | A package that contradicts its own provenance is malformed. Validate is where "this registry is well-formed" is decided, and it already refuses a manifest naming a setup recipe that is not there. |
| `registry audit` | **error**, audit fails | Audit already fails a hand-edited `aart.vendor`. A copy that no longer matches its record is the same class of defect and must not rank below a missing licence, which is a warning. |
| `registry revendor` | **failing check**, nothing planned | Re-vendoring overwrites the payload. Doing that over an unexplained local difference would erase evidence the maintainer has not seen yet. |

The audit finding is an error rather than a warning on purpose. The two findings `2.3.0` added report
facts about the world — no declared licence, behind upstream — and the audit is right not to fail on
those. This one reports a fact about the registry: what it publishes is not what it says it
publishes. That is a defect, and the release that adds it says so in one line.

## 5. Drift is a statement about the bytes on disk

`revendor` compares upstream against the copy, in this order:

1. **Verify the copy against its record.** On mismatch: report it, plan nothing, fail the check.
   `--check` exits non-zero. A copy that does not match its own record is not a copy whose currency
   can be discussed, and calling it `up-to-date` or `changed` would answer a question the maintainer
   did not ask.
2. **Compare upstream against the recomputed digest** — the bytes on disk, not the recorded value.
   For a healthy copy the two are equal, which is exactly what step 1 establishes; the point is that
   the comparison no longer *depends* on that being true.

The same substitution applies to `registry audit --check-upstream`
(`_vendored_upstream_findings`, `planning.py:1208`): "behind upstream" becomes a claim about what the
registry ships.

This preserves every disposition `2.3.0` defined. `up-to-date`, `changed`, and `unreachable` keep
their meanings and their exit codes, and an unreachable upstream is still never up-to-date. What
changes is that a fourth state — *the copy is not the copy* — stops being silently folded into the
first.

## 6. The commit that moved without moving anything

`up-to-date` over two differing commits is correct and reads as a contradiction. It is the normal
result of vendoring one directory out of a monorepo: the ref advanced, the subtree did not, and the
copy stays pinned to the commit it was taken at deliberately — re-pinning would produce a diff
claiming a refresh that did not happen (`planning.py:733`). That reasoning exists only in a
docstring.

The drift report says it in the output where the two commits appear:

```
disposition: up-to-date
recorded commit: 0588ec09f0a1
resolved commit: 76d64c822f51
the ref moved, and nothing under src/git changed; the copy stays pinned to the recorded commit
```

Three variants, each a fact rather than a reassurance: the ref has not moved; the ref moved and the
subtree did not; the subtree changed (already reported, with counts). An operator reading the third
line never has to decide whether two differing commits mean trouble.

## 7. What a consumer receives

Installing an artifact does not deliver the package. It applies the effects the type declares
(`INSTALL_EFFECTS_BY_TYPE`, `protocol/native_models.py:31`), and for one type those effects touch a
single file of the payload:

| Type | Effects | What reaches the consumer | Can the payload be referenced? |
|---|---|---|---|
| `skill` | `copy-tree` | the whole payload tree | yes, it is there |
| `guideline` | `write-file` | the one Markdown document | that is the whole payload |
| `memory` | `write-file`, `managed-block` | the one Markdown document | that is the whole payload |
| `hook` | `copy-tree`, `merge-json` | the whole payload tree, plus the merged entry | yes — `${SCRIPT_DIR}` resolves to where it was copied |
| `mcp` | `merge-json` | **the `server` object from `payload/mcp.json`, and nothing else** | **no** |

For `mcp`, `_MergePayload` receives `descriptor["server"]` and no operation copies anything
(`installation/application.py:382`). Every other payload file stays in the registry and the object
store. The type is not broken — an MCP server is normally launched by `npx`, `uvx`, `docker`, or an
absolute path, all of which resolve on the consumer's machine — but a `command` or `args` naming a
path inside the payload names a file that will not be there.

This release states that in three places and enforces the consequence in one:

- the protocol document tabulates delivery per type, beside the payload formats it already defines;
- the vendoring tutorial's worked example uses a command the consumer can actually run, and says why;
- the vendor and re-vendor review carries a `vendor-delivery` check for `mcp`: it reports how many
  copied files are not delivered, and **fails** when the descriptor's `command` or `args` names a
  file that exists inside the payload. `registry audit` reports the same condition.

The check is deliberately narrow. It fires only on a string that resolves to a file present under
`payload/` — not on any relative-looking path — because a false positive on an argument that happens
to look like a path would be a refusal for a guess.

### The descriptor that merges nothing

*Amended after `VI-4` landed; found while testing it.* The delivered object is `descriptor["server"]`,
so a `payload/mcp.json` that has no `server` key delivers `{}` — a named entry in the consumer's
`.mcp.json` that starts no process. The shape that produces it is not exotic. It is
`{"mcpServers": {"<name>": {"command": …}}}`: the shape of the file the entry is merged *into*, which
everyone has seen and nobody has been told is not the artifact format. `aart-mcp-v1` wants
`{"name": …, "server": {"command": …, "args": [...]}}`. The wrong one parses as valid JSON, satisfies
the descriptor schema's required keys by having none of them contradicted, loads, builds, validates,
and installs — every gate green, nothing runs.

The refusal belongs in the review and in `audit`, not in the loader. Rejecting the shape in
`compile_native_package` would make every registry that already contains such a file unloadable on
upgrade, on the consumer's side as well as the maintainer's — a break taken for a defect that harms
nobody who has not yet tried to start the server. So the vendor review fails its `vendor-delivery`
check and `audit` errors, both saying what the descriptor should look like; a registry that already
has one keeps loading and is told.

This narrows to vendored packages, because that is where the delivery finding is computed. An owned
`mcp` package authored in place with the same mistake is still unchecked, and is recorded as a
residue rather than fixed by widening `validate` in this release.

### The owned package is checked too

*Amended after `2.6.0`, closing the residue `RS-01` the paragraph above records. The paragraph
stands as written: it is what `2.4.0` shipped.*

The narrowing was an accident of where the code sat, not a decision about what is wrong. The finding
is computed inside the branch that reads a vendored package's `provenance.json`, so a maintainer who
writes `payload/mcp.json` by hand — the ordinary way to author an `mcp` artifact, and what `registry
scaffold mcp` sets up — never reached it. Nothing in the consequence depends on where the bytes came
from: the install merges `descriptor["server"]`, and a descriptor shaped like the harness file
delivers `{}` whether it was copied from upstream or typed in place.

`registry audit` now runs the delivery check for every artifact package it walks. Two things stayed
deliberate:

- **It is `audit`, not `validate`.** `validate_registry_workspace` is not only the publisher's gate;
  the consumer runs it over a candidate source through `validate_registry_source_candidate`. A new
  hard failure there makes every registry that already carries such a descriptor unloadable on
  upgrade, on the subscriber's side too — the protocol break the paragraph above rejected, arrived
  at by a different route. `audit` is maintainer-side, and is the command the generated registry CI
  runs.
- **An owned package is not called vendored.** The message drops the word rather than sending a
  maintainer looking for an upstream that does not exist; the fault and the remedy are identical.

### The assessment scans what the consumer will not run

For `mcp`, the vendor review's assessment covers the whole copied subtree while the install delivers
one JSON object. Both facts are worth having: the registry is redistributing those bytes, and a
maintainer deciding whether to publish them should see what is in them. But a finding in
`payload/install.sh` of a vendored `mcp` is a finding in something no consumer of *this artifact*
executes. The review says which it is rather than leaving a reader to infer that the risk it just
reported is not the risk they think it is.

## 8. What this deliberately does not do

- **It does not authenticate the origin.** A recomputed digest proves the package is internally
  consistent, not that it came from upstream. Someone who edits the payload *and* rewrites
  `origin.input_digest` produces a consistent lie, and only the network can catch that — which is
  what `revendor` and `audit --check-upstream` are for. Provenance is a record, not a signature, and
  this release does not start claiming otherwise.
- **It does not add a document, a field, or a protocol revision.** The check reads what `2.3.0`
  already wrote.
- **It does not introduce a "patched copy".** §3 states the supported route instead.
- **It does not touch `promote-native`.** A native reference ships no bytes, so it has nothing to
  verify.
- **It does not change any install effect.** `LAF-46` is a documentation and review gap; changing
  what `mcp` delivers would be a consumer-visible protocol decision belonging to a release that takes
  it deliberately.
- **It does not close `LAF-45`** — `audit --check-upstream` is still silent when everything is
  current. Adjacent, not the same finding; recorded in the plan against no package.

## 9. Release shape

**`2.4.0`, contract v12.** Additive and minor: two new refusals, one new review check, two new audit
findings, and three documentation changes. No protocol revision, no schema, no store layout, no
on-disk format, and no consumer-side change — a `2.4.0` data root is fully readable by every `2.x`.

The one upgrade note that matters: a registry whose vendored payload has been edited since it was
vendored will fail `registry validate` and `registry audit` on this release, having passed on
`2.3.0`. That is the finding, working. The diagnostic names the package, both digests, and the route
back.
