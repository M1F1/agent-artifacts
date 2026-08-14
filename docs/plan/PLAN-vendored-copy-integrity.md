# Plan: vendored copy integrity, and what a consumer receives

Status: **not started.** Implements
[the design](../design/DESIGN-vendored-copy-integrity.md). Closes `LAF-41`, `LAF-42`, and `LAF-46`
of [the third live-acceptance run](../testing/PROGRESS-live-acceptance-v3.md). Each landed package
records what it found in a "What the plan did not anticipate" section; those sections, not this
line, are the run record.

Target release: **`2.4.0`, contract v12.** Additive — two new refusals, one new review check, two new
audit findings. No protocol, schema, store, or on-disk revision, and no consumer-side change
(design §9).

Sequenced by boundary: the pure function first, then the gates that call it, then the reporting, then
the words. Every work package ends with stdlib `unittest` coverage and a clean `git diff --check`.
Run tests with `python3 -m unittest discover -s tests -p "*_test.py"`; `make quality` gates the
branch and must be green on all nine gates before a package is committed.

## Guardrails

- **No new document, field, or protocol revision.** Every check reads what `2.3.0` already wrote. A
  package vendored by `2.3.0` must verify on this release with no migration and no network
  (design §3).
- **No claim gets stronger.** A verified copy is *internally consistent*, never "verified",
  "authentic", or "safe". The origin is not authenticated by any of this (design §8).
- **No install effect changes.** `LAF-46` is closed by documenting delivery and refusing a config
  that cannot work, not by delivering more (design §8).
- **Every disposition `2.3.0` defined keeps its meaning and its exit code.** `unreachable` is still
  never `up-to-date`; `--check` still writes nothing.
- **`promote-native` is untouched.** A native reference ships no bytes.

## VI-1 — the copy's digest, recomputed from the copy

**Files:** `agent_artifacts/registry_maintenance/vendoring.py`

1. Add `verify_vendored_copy(files, base, payload_root, authored, recorded)`: reconstruct the taken
   subtree from the package's payload — every payload file whose package-relative path is not in
   `authored`, re-rooted by stripping the payload root, with content and executable bit — add the
   ancestor directory entries, and digest it with `source_snapshot_digest` under
   `SnapshotOrigin.IMMUTABLE_GIT`.
2. Return a `CopyIntegrity(recorded, recomputed, files)` value, not a boolean: every caller renders
   both digests, and a caller that could only ask "does it match" would have nothing to print.
3. Refuse, rather than report a mismatch, when the package cannot be reconstructed at all: no payload
   file outside `authored`, or a payload path that is not a safe relative path. Those are malformed
   packages, and reporting them as drift would name the wrong defect.
4. Add `copy_integrity_message(identity, integrity)` so validate, audit, and revendor say the same
   sentence: what mismatched, both digests, and the three plausible causes — a local edit, a
   line-ending translation, a substitution — with the supported route for the first (fork upstream,
   vendor the fork).

**Tests:** a projected package verifies against its own `input_digest`; an authored file inside the
payload is excluded, and adding one to `authored` that upstream supplied changes the digest rather
than hiding the file; one changed byte, one added file, one removed file, and one flipped executable
bit each mismatch; a nested payload reproduces the digest of the subtree it was taken from
(the directory-derivation property, design §3); a package with no unauthored payload file refuses.

**What the plan did not anticipate:**

- **The payload root is read from the manifest, not assumed.** `project_vendored_package` writes
  `payload/` and `_PAYLOAD_ROOT` is a module constant, so hard-coding it here would have looked
  right. A package declaring any other root would then have had *no* payload file matched, which the
  refusal in item 3 reports as a malformed package — a check that fails loudly on a legal package is
  worse than no check. `PayloadSpec.root` is the authority and is passed in.
- **The `authored` evasion closes by arithmetic, not by a rule.** `aart.vendor.authored` is not
  covered by `options_digest` — that digest covers URL, ref, and path — so a tamperer can add a file
  they edited to the authored list. It does not help: excluding a file upstream supplied removes it
  from the recomputed tree, which is a different digest, not a matching one. A test states this,
  because the reasoning is not visible from the code.
- **Verified against packages nothing in this repository produced.** The two artifacts the
  acceptance run vendored from `modelcontextprotocol/servers` — 12 and 17 payload files, one with a
  two-level payload — both reproduce their recorded digests under this function, and the
  reconstructed two-month-old copy that produced `LAF-41` mismatches. The unit fixtures prove the
  function; those packages prove the derivation matches what `2.3.0` actually wrote to disk.
- **Both digests travel, and the message is built once.** `copy_integrity_message` lives beside the
  check rather than in each caller: three commands report this condition, and three phrasings of
  "the copy is not the copy" would read as three different defects.

## VI-2 — a copy that contradicts its record fails the gates

**Files:** `agent_artifacts/registry_commands/planning.py`

1. In `audit_registry_workspace`, where a vendored package is already read
   (`planning.py:1316`), verify the copy and append an **error** diagnostic on mismatch. It ranks
   above the licence warning deliberately: this is a defect in the registry, not a fact about the
   world (design §4).
2. In `validate_registry_workspace`, walk the declared artifact roots for packages whose provenance
   importer is `registry-vendor-v1` and apply the same verification. Validate reaches no network, and
   this check does not either.
3. Both callers use one helper over one package, so the two commands cannot diverge in what they
   accept.

**Tests:** a vendored fixture passes validate and audit; the same fixture with one payload byte
changed fails both, with a diagnostic naming the identity and both digests; a re-locked and re-built
tampered registry still fails, which is the exact `LAF-41` reproduction; an owned package with no
provenance, a `promote-native` provenance, and a vendored package with a hand-edited `aart.vendor`
each behave as they did on `2.3.0`.

**What the plan did not anticipate:**

- **Validate had no package walk to hook into.** `audit_registry_workspace` already visits every
  `artifact.json` under the declared roots; `validate_registry_workspace` does not visit packages at
  all — it reads the markers, the lock, and the index. `_vendored_packages` is that walk, written
  once and used by validate, while audit calls the per-package check inside the loop it already has.
  Two walks would have been two definitions of "a vendored package".
- **Validate now reports a record it could not read, which audit already did.** A package whose
  provenance names `registry-vendor-v1` but whose `aart.vendor` does not verify is refused by
  validate on this release, having passed on `2.3.0`. It is the same defect audit named live
  (`LA3-A-02`), and leaving validate silent about it would have left the hole open: tamper the
  payload *and* the record, and the integrity check would never run. The compatibility note in
  `VI-6` states it.
- **Item 3's "one helper" is two.** `vendored_copy_diagnostics` takes one already-read package —
  which is what audit has — and `_vendored_packages` finds them, which is what validate needs. One
  function doing both would have forced audit to read every package twice and report the read
  failures twice with it.
- **Verified against the registries that produced the finding.** `registry validate` on the
  reconstructed drift registry from the acceptance sandbox now fails, naming `mcp/mcp-git` and both
  digests; the untouched registry beside it passes both gates unchanged.

## VI-3 — drift is measured against the bytes on disk

**Files:** `agent_artifacts/registry_commands/planning.py`, `agent_artifacts/curation/runtime.py`

1. `plan_artifact_revendor` verifies the copy before it compares anything, and refuses on mismatch.
   The comparison that follows uses the recomputed digest, not `vendored.input_digest`
   (`planning.py:750`).
2. `_vendored_upstream_findings` likewise compares upstream against the recomputed digest
   (`planning.py:1208`), so "behind upstream" is a claim about what the registry ships.
3. `CurationRuntime._prepare_revendor` verifies **before acquiring**, and on mismatch returns an
   informational review carrying a failing `vendor-copy-integrity` check — the shape `unreachable`
   already uses, so `--check` exits non-zero and nothing is written. No network call is made for a
   copy that is already known not to be the copy.
4. `_drift_check` reconciles the two commits it prints. Three variants, chosen by fact: the ref has
   not moved; the ref moved and nothing under the subtree changed, so the copy stays pinned; the
   subtree changed, already reported with counts (design §6).

**Tests:** a tampered copy makes `revendor --check` fail with the integrity check and no acquisition
attempted; upstream unchanged and copy unchanged still reports `up-to-date`; upstream moved reports
`changed` with counts; an `up-to-date` result whose resolved commit differs from the recorded one
carries the reconciling line, and one whose commits agree does not; `unreachable` is unaffected.

## VI-4 — the review says what a consumer will receive

**Files:** `agent_artifacts/registry_maintenance/vendoring.py`,
`agent_artifacts/curation/runtime.py`, `agent_artifacts/registry_commands/planning.py`

1. Add `describe_delivery(kind, payload)`: for `mcp`, how many copied payload files are not
   delivered, and which strings in the descriptor's `server.command`/`server.args` name a file that
   exists inside the payload. Every other type delivers its whole payload and has no finding
   (design §7).
2. Add a `vendor-delivery` check to the vendor and re-vendor reviews. It states what installing this
   artifact delivers, and **fails** when the descriptor references a withheld payload file — a
   configuration that cannot work on any consumer machine.
3. For `mcp`, the review states that the assessment covered bytes the consumer never receives, beside
   the assessment rather than after it.
4. `registry audit` reports the same referenced-withheld-file condition, as an error.
5. The match is narrow by construction: only a string that resolves to a file actually present under
   `payload/` counts, so an argument that merely looks like a path is not a refusal for a guess.

**Tests:** an `mcp` descriptor naming `payload/index.js` fails the check in both the vendor and the
re-vendor review and fails the audit; one naming `npx` passes; one naming `./scripts/run.sh` that is
not in the payload passes; a `skill` and a `guideline` produce no delivery finding; the withheld
count is what the payload holds minus the delivered document.

## VI-5 — the tutorial's example runs, and delivery is written down

**Files:** `docs/tutorials/vendoring-v1.md`, `docs/protocol/native-source-v1.md`,
`docs/protocol/registry-v1.md`

1. Replace the tutorial's `{"command": "node", "args": ["payload/index.js"]}` with a command a
   consumer can actually run, and say in one paragraph why the first one cannot: installing an `mcp`
   artifact merges one JSON object and copies nothing.
2. Add the delivery table (design §7) to the native source protocol document, beside the payload
   formats it already defines: type, effects, what reaches the consumer, whether the payload can be
   referenced.
3. State in the registry protocol document that for `mcp` the vendor assessment covers bytes the
   consumer never receives, and that this is the one type where the two differ.
4. The vendoring tutorial links the new design document where it describes what the copy claims.

**Tests:** the docs gate; the release-check `REQUIRED_PERSISTENT_DOCS` list; a test asserting the
tutorial contains no `payload/` path inside an example MCP command, so the example cannot regress.

## VI-6 — the `2.4.0` release commit

**Files:** `pyproject.toml`, `agent_artifacts/__init__.py` or wherever `version.py set` writes,
`scripts/release.py`, `docs/release/`, `CHANGELOG.md`, `PROGRESS.md`

1. `python scripts/version.py set 2.4.0`; `EXPECTED_VERSION` and `RELEASE_CONTRACT_VERSION = 12`.
2. `docs/release/compatibility-v12.md`, `release-checklist-v12.md`, `github-release-v2.4.0.md`, and
   the v12 schema freeze written by `scripts/release.py freeze --write`.
3. The compatibility matrix states the one upgrade note: a registry whose vendored payload was edited
   after vendoring fails validate and audit on this release having passed on `2.3.0` (design §9).
4. `CHANGELOG.md` and `PROGRESS.md` record the three findings closed and the residues left open.

**Publication is the maintainer's.** This package prepares the commit; it does not tag, push, or
release.

## Dependency graph

```
VI-1 ──┬── VI-2 ──┐
       └── VI-3 ──┼── VI-6
VI-4 ── VI-5 ─────┘
```

`VI-1` is the only package everything else waits on. `VI-4` is independent of `VI-1`…`VI-3` but
touches the same two files as `VI-3`, so it is sequenced after it rather than in parallel. `VI-5`
documents what `VI-4` enforces and must not land before it.

## Residues this plan records and does not own

- **`LAF-45`** — `audit --check-upstream` prints nothing when every vendored artifact is current, so
  "checked, all current" is indistinguishable from "the flag was dropped". Adjacent to `VI-3`'s
  reporting work and deliberately out of its scope (design §8).
- **`LAF-47`** — uninstall leaves the `.mcp.json` it created as `{"mcpServers":{}}`. Same acceptance
  scenario as `LAF-46`, different component; it belongs to the teardown family `LAF-17` tracks.
- **`LAF-43`** — vendoring refuses a `file://` upstream, so neither the `changed` disposition nor the
  symlink refusal can be rehearsed live. It bounds what this plan's live re-test can cover, and
  widening it is a separate decision.
- **`LAF-49`** — the allowlisted Git environment drops `https_proxy`, undocumented.
- `commands/registry.py` stamps dead `1.0.0`/`2.0.0` AART bounds on every non-`init` curation
  request, carried from `VN-9`.
