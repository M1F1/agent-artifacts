# AART 2.4.0 compatibility matrix

AART `2.4.0` is a minor release over `2.3.0`. It adds no command, no flag, no document format, and
no field. What it adds is verification: the vendored payload a registry ships is now checked against
the origin digest that same package records, and the vendor review states what a consumer of an
`mcp` artifact actually receives. Every `2.0.0`…`2.3.0` configuration, source store, object store,
installation record, registry, and artifact is read and written exactly as before.

It is minor rather than patch for one reason: **a registry that passed `2.3.0` can fail `2.4.0`.**
The three cases are listed under *Upgrade notes* and each of them is a registry that was already
broken and was not being told.

| Boundary | Supported in 2.4.0 | Change from 2.3.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | unchanged | none | native tree and registry gates |
| Provenance document | v1 with `aart.vendor` | none written; `origin.input_digest` now **read and checked** | vendoring and integrity tests |
| Configuration schema | v1 | none | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | none | setup parser and canonical setup tests |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1 | none | security tests |
| Install effects | unchanged | none — what `mcp` delivers is now **documented**, not changed | installation tests |
| CLI surface | unchanged | none | CLI and e2e tests |
| Maintainer text front-end | unchanged | none | TUI parity tests |
| Registry validate | **one refusal added** | vendored payload contradicting `origin.input_digest` | integrity gate tests |
| Registry audit findings | **three added, all errors** | copy/record mismatch; `mcp` descriptor naming a withheld payload file; `mcp` descriptor declaring no server | audit tests |
| Vendor and re-vendor review | **one check added** | `vendor-delivery` | curation review tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is minor and not a protocol move

Nothing new is written to disk. `origin.input_digest` has been written by every vendoring since
`2.3.0`; this release reads it. The recomputation needs no network and no new field: the payload
files not listed in `aart.vendor.authored` are exactly the files that were taken, because vendoring
refuses an authored path that collides with a copied one, and a Git tree carries no empty directory.
So the taken subtree is recoverable from the package alone, and its digest is comparable with the
one the package already records.

The schema freeze differs from v11 in **two inputs and no protocol version**.
`schema-freeze-v12.json` and `schema-freeze-v11.json` carry identical `protocol_versions`;
`docs/protocol/registry-v1.md` and `docs/protocol/native-source-v1.md` differ, and neither is a
parsed field. Both documents gained prose: what installation delivers per type, and that a vendored
copy is verified against the record it carries. That is the machine-checked statement that this
release moves no protocol boundary.

## Added

### The copy is checked against the origin it records

`aart registry validate --strict` and `aart registry audit` recompute the digest of the copied
subtree from the package on disk and compare it with `origin.input_digest`. A mismatch is an error:
a package that claims an origin and does not match it is a defect in the registry, not a fact about
the world a maintainer may accept. Both work offline; upstream is not contacted.

`aart registry revendor` performs the same check **before** it opens a connection, so a copy that no
longer matches its record is reported instantly, upstream is never reached, and no drift is computed
from bytes that are already untrustworthy. The check runs in `--check` and in `--yes` alike, and
nothing is written when it fails.

This is a consistency check, not an authentication. It proves the package agrees with its own
record; someone who edits the payload *and* rewrites the digest produces a consistent lie, and only
`--check-upstream` or a re-vendor can catch that. Provenance remains a record, not a signature.

### `vendor-delivery` in the vendor and re-vendor review

For `mcp` — the one type whose install effects do not deliver the payload — the review now states
that installing merges the `server` object from `payload/mcp.json` and copies nothing, how many
copied files are therefore not delivered, and that the assessment above covered bytes no consumer of
this artifact receives. The check **fails** when the descriptor's `command` or `args` names a file
that exists inside the payload, because that configuration cannot start on any consumer machine, and
when the descriptor declares no `server` at all, because installing it merges an empty entry.

The match is narrow by construction: only a string resolving to a file actually present under
`payload/` counts, so an argument that merely looks like a path is not refused for a guess.

`registry audit` reports both conditions for vendored artifacts, as errors.

## Changed

`revendor`'s `up-to-date` disposition now prints the line that reconciles a recorded and a resolved
commit that differ — the normal result of vendoring one directory out of a monorepo — rather than
leaving two commits under the word `up-to-date` with nothing to explain them. Where the ref itself
has not moved, it says that instead. And `up-to-date` is now a statement about the bytes on disk,
not only about the record.

The vendoring tutorial's worked `payload/mcp.json` was wrong in both ways this release can now
detect, and is corrected. The `2.3.0` example was shaped like the harness file it is merged into,
and launched a payload file consumers never receive.

## Upgrade notes

A registry that passed `2.3.0` fails `2.4.0` in exactly these cases, and each is a registry that was
already broken:

1. **A vendored payload was edited after vendoring.** `validate --strict` and `audit` now fail.
   Re-locking and rebuilding do not clear it, by design: the digest is recomputed from the bytes.
   The supported route is to change the content upstream — or in a fork you vendor from — and vendor
   again. If the edit was a deletion you wanted, vendor a narrower subtree.
2. **A vendored `mcp` descriptor names a file inside `payload/`.** `audit` now fails. That artifact
   could never start on a consumer machine; installation delivers one JSON object and copies
   nothing. Launch the server the way a consumer can resolve it, or ship the bytes as a `skill` or
   `hook`, which do copy their payload.
3. **A vendored `mcp` descriptor is shaped `{"mcpServers": {…}}`.** `audit` now fails. That is the
   shape of the harness file the entry is merged into; the artifact format is
   `{"name": …, "server": {…}}`, and the wrong one merges an empty entry that starts no process.

Consumers are unaffected in all three cases: nothing about installation changed, and a registry
already published keeps installing exactly as it did.

## What did not change

No protocol revision, no schema, no store layout, no on-disk format, no consent semantics, and no
install effect. `promote-native` is untouched — a native reference ships no bytes, so it has nothing
to verify. Without `--yes` every action still stops after Review and changes nothing, and AART still
never commits or pushes a maintainer checkout.

## Downgrade

A `2.4.0` data root is fully readable by `2.3.0`, `2.2.0`, `2.1.0`, and `2.0.0`. Nothing new is
written, so there is nothing for an older executable to fail to understand. The asymmetry is
operational: an older executable does not perform the integrity check, so a registry it calls valid
may be one `2.4.0` refuses.

## `requires_aart` windows

No window needs re-authoring. A registry or artifact declaring `min_inclusive: "2.0.0"`,
`max_exclusive: "3.0.0"` admits this release unchanged, and a registry that vendors artifacts does
not need to raise its floor — the packages it publishes are unchanged by this release.

## Published wheel

`agent_artifacts-2.4.0-py3-none-any.whl` is byte-reproducible: rebuilding the tagged commit anywhere
produces the same sha256, not merely the same member contents. The expected digest is published with
the release artifacts rather than committed, because it is a property of the tagged commit and
cannot live inside it. See [wheel-reproducibility-v1.md](wheel-reproducibility-v1.md).
