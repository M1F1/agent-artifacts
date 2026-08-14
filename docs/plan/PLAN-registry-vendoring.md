# Plan: registry vendoring

Status: **`VN-1` … `VN-8` landed; `VN-9` open.** Implements
[the design](../design/DESIGN-registry-vendoring.md). Each landed package records what it found in a
"What the plan did not anticipate" section; those sections, not this line, are the run record.

Target release: **`2.3.0`, contract v11.** Additive — two new registry verbs, two new audit findings,
one removed dead module. No protocol, schema, or on-disk format revision (design §2), so the same
"no registry precondition" property as `2.1.0` and `2.2.0`.

Sequenced by boundary. Every work package ends with stdlib/`unittest` coverage and a clean
`git diff --check`. Run tests with `python3 -m unittest discover -s tests -p "*_test.py"`;
`make quality` gates the branch.

**This plan starts after `2.2.0` ships.** `VN-8` must not land before `SI-9`'s protocol text, because
`SI-9` names vendoring as the supported route for foreign content and would otherwise document a
command that does not exist (design §8).

**`VN-1` … `VN-3` are not glue.** The receiving half of vendoring already exists — the
`provenance.json` format, its index projection, four baseline cross-check rules, the installer's
credential-free-origin check, and a passing end-to-end test at
`tests/canonical_install_planning_test.py:415`. That inventory (design §2, "What exists, and what
this design has to build") makes the shape of the work easy to misjudge in the other direction: none
of the *producing* half exists. Subtree extraction, package projection from foreign bytes, and the
command itself are written from nothing. What the existing half buys is not implementation, it is
scope — no format revision, no consumer change, and `2.0.0` reads the result.

## Guardrails

- **Vendoring never claims safety.** No surface reports a vendored artifact as verified, trusted, or
  safe. The word used is what was found. Design §3.
- **No refusal is loosened.** `vendor` adds a gate — an approved review record — and adds two new
  refusals. It removes none.
- **No credentials, ever.** No token field, flag, or environment variable is added. `VN-7` removes
  the one that exists in dead code.
- **`promote-native` is untouched.** Not one line of its planning path changes; both modes ship side
  by side. If a package needs to change it, the package is wrong.
- **Owned packages stay owned packages.** A vendored artifact must be indistinguishable to a
  `2.0.0` consumer from a hand-authored one, except for carrying `provenance.json` — which that
  consumer already understands.

## VN-1 — a subtree acquisition that fails closed

**Files:** `agent_artifacts/sources/` (subtree extraction beside the existing snapshot path)

1. Extract one `SafeRelativePath` subtree from an acquired immutable `SourceSnapshot`, re-rooting
   entries at the subtree, preserving executable bits, and applying `SnapshotLimits` to the taken
   subtree rather than to the whole repository.
2. Refuse a symlink whose target leaves the subtree, with a diagnostic naming the link and target.
   Neither drop it nor follow it.
3. Refuse an empty result, naming the requested path.
4. Return the subtree's deterministic input digest — the value that becomes
   `OriginProvenance.input_digest`.

**Tests:** a repository with no AART markers yields a subtree; a link escaping the subtree refuses;
`../` and absolute targets refuse; a typo'd path refuses as empty rather than succeeding; executable
bits survive; the same commit and path yield the same input digest twice.

**What the plan did not anticipate:**

- **A contained symlink had to be refused too, and for a different reason.** Item 2 refuses a link
  whose target *leaves* the subtree, which reads as though a link staying inside is carried. It
  cannot be: `tree_digest` knows files and directories only (`EntryKind`), and
  `source_snapshot_digest` refuses any other kind outright, so there is no representation for a
  symlink in the package tree or in the digest that binds it. Carrying one is a format revision,
  which this release explicitly does not make. Both cases refuse, with different messages, because
  reporting an escape that did not happen would send the maintainer looking for the wrong thing.
- **The escape check is relative to the link, not to the subtree root.** A link at
  `lib/up.js` targeting `../../other` escapes while `../index.js` does not; judging both against the
  root would accept the first. It is judged in the subtree's own coordinate space, after re-rooting,
  because that is the tree the maintainer reviews and the one the package will contain.
- **A `--path` naming a file is refused as a path, not as emptiness.** Taking a file's "subtree"
  yields nothing under `path/`, so the empty rule would have covered it with a message about
  emptiness that hides the actual mistake.
- **The origin is required to be immutable Git.** `OriginProvenance` binds a resolved commit and a
  local tree has none, so a local snapshot is refused here rather than at the point where the
  provenance cannot be written.
- **Limits bound the taken subtree, and a test holds the other half of that.** A repository far past
  `max_total_bytes` still yields a small subtree — refusing it for the size of content nobody asked
  for would be the wrong boundary — and depth is measured after re-rooting, so a package taken from
  deep inside a monorepo is shallow.

**Recorded residue, not fixed here:** a repository containing *any* symlink cannot be acquired at
all, so it cannot reach this step. `git.py` accepts only modes `100644`/`100755` and `local.py`
refuses `S_ISLNK` outright, both repository-wide. Foreign repositories — the ones vendoring exists
for — routinely contain symlinks somewhere, so this bounds the feature more than design §5's rule
does. Widening it means teaching the snapshot digest a third entry kind, which is a format change
and belongs to whichever release takes that decision, not to `VN-1`. `VN-3` should state the
limitation in the command's help rather than let it surface as an acquisition error.

**Exit:** design §5. Everything else depends on this.

## VN-2 — projecting a canonical package from foreign bytes

**Files:** `agent_artifacts/registry_maintenance/`

1. Build a `NativeArtifactPackage` from (taken subtree → `payload/`) plus a maintainer-authored
   `artifact.json`: identity, version, summary, payload spec, compatibility, install spec, and
   optional setup reference.
2. Write `provenance.json` — `OriginProvenance(kind="git", url, resolved_commit, path, input_digest)`
   and `ImporterProvenance(id="registry-vendor-v1", version=<AART SemVer>, options_digest)`, where
   `options_digest` covers url, ref, path, and every acquisition option, so two vendorings of one
   upstream state are comparable.
3. Carry acquisition warnings into `Provenance.warnings`, which the baseline already surfaces as
   `importer-warning`.
4. Emit the package into `artifacts/<kind>/<name>/` as ordinary owned registry content.

**Tests:** the projected package loads through `load_native_source` unchanged; the index built from
it carries `IndexProvenance` matching `provenance.json`; the baseline raises no
`provenance-index-mismatch`; `registry validate --strict --frozen` passes.

**What the plan did not anticipate** (`agent_artifacts/registry_maintenance/vendoring.py`,
`tests/registry_vendoring_projection_test.py`):

- **The taken subtree alone almost never makes a loadable payload, so the projection refuses and
  names what is missing.** `_validate_primary_payload` requires `payload/SKILL.md` for a skill and
  `payload/mcp.json` / `payload/hook.json` for an mcp or hook. An upstream repository was never
  shaped for AART, so it contains none of them. That document is the maintainer's wrapper — it is
  authored, and it is reviewed and assessed like any other file they add. Refusing at projection
  time names the document; emitting the package instead would fail later inside `registry validate`,
  against a manifest the maintainer never wrote by hand.
- **`guideline` and `memory` are vendorable only from a single Markdown document.** The loader
  requires exactly one payload file and that it be `.md`, so the projection applies the same rule
  with a message about what the subtree contributed. This is a real narrowing of what "vendor a
  subtree" means for those two kinds, not an implementation detail.
- **`artifact.json` and `provenance.json` are refused as authored input by name.** They are the two
  documents the projection derives from its inputs; a maintainer passing one is trying to override
  the evidence. Refusing them as "not canonical package content" would have been wrong — they are
  canonical — so they refuse with their own message.
- **Everything else authored is bounded to the loader's own allowed roots** (`README.md`, `SETUP.md`,
  `payload/`, `setup/`) and may not collide with a taken byte. A silent overwrite would mean the
  maintainer reviews upstream content their registry does not ship.
- **`options_digest` includes the ref, deliberately, even though a ref moves.** A tag and a branch
  that happen to resolve to one commit are two different standing instructions, and `VN-5`'s drift
  check compares instructions rather than only outcomes.
- **`importer_version` is passed in, not read from `runtime_contract`.** The projection stays a pure
  function of its inputs; the caller (`VN-3`) supplies `EXECUTABLE_VERSION`.
- **`validate --strict --frozen` is not reachable on its own.** It sets `require_compiled`, so the
  test must run `lock --yes` and `build --yes` first, and every registry mutation refuses without a
  writable local Git checkout — the test `git init`s a temporary registry. It builds a fresh registry
  rather than adding the vendored package to the `registry-v1` fixture, whose `entries/mcp/` native
  reference would have to be acquired during `lock`. `VN-3`'s tests inherit all of this.

**Exit:** design §2. Depends on `VN-1`.

## VN-3 — `registry vendor`, review-first

**Files:** `agent_artifacts/cli.py`, `agent_artifacts/commands/registry.py`,
`agent_artifacts/curation/`

1. `registry vendor <kind> <name> --url --ref --path --version [--summary] [--profile] [--platform]
   [--setup-recipe] [--yes] [--json]`, following the review/finalize contract every other registry
   mutation uses.
2. Review states: origin and resolved commit, taken subtree and file count, target path, declared
   version, and the license finding from `VN-6`.
3. Finalize requires an approved review record, exactly as `plan_native_promotion` already requires
   (`registry_maintenance/planning.py:643`).
4. Add `CurationAction.VENDOR` beside `PROMOTE_NATIVE`, so the curation runtime and its review digest
   cover the new action.

**Tests:** without `--yes` nothing is written and no snapshot is published; `--yes` without an
approved review refuses; the emitted registry passes `validate`/`lock`/`build`/`audit`; an upstream
with no AART markers succeeds where `promote-native` refuses — the same fixture proving both.

**What the plan did not anticipate** (`registry_commands/planning.py:plan_artifact_vendor`,
`curation/runtime.py:_prepare_vendor`, `tests/registry_vendor_command_test.py`):

- **`vendor` is a workspace operation, not a registry mutation, despite reading as
  `promote-native`'s sibling.** `RegistryMutationPlan` allows exactly three path shapes —
  `aart.lock.json`, `aart.index.json`, and `entries/<kind>/<name>.json` — so it cannot carry payload
  bytes under `artifacts/`, nor an executable bit. The vendor plan is a `RegistryWorkspacePlan` with
  a new `RegistryOperation.VENDOR`, the same machinery `scaffold` uses. It follows that a vendor
  leaves the lock and index stale, so `CurationAction.VENDOR` joins `INIT`/`SCAFFOLD` in
  `_follow_up`: the review points at `lock` and `build` before `validate --strict`, which would
  otherwise fail and send the maintainer looking for a fault in the copy.
- **No flag can carry file bytes, so `vendor` adopts what the maintainer has already authored at the
  target path.** `VN-2` refuses a projection whose payload lacks the kind's required document, and a
  foreign subtree essentially never contains it. Everything already present under
  `artifacts/<kind>/<name>/` except `artifact.json` and `provenance.json` is adopted as authored
  content and projected with the taken bytes, where `VN-2`'s collision and canonical-root refusals
  judge it. A vendor over an existing `artifact.json` refuses, so adoption can never overwrite a
  package. The same mechanism is what makes `--setup-recipe` usable: the recipe and its `SETUP.md`
  are authored beside the payload, and the plan refuses when a declared recipe is not present.
- **The approved review record gates the plan and is not persisted.** `plan_native_promotion` stores
  its record in the `entries/` document it writes; an owned package has none, and
  `index_artifact_from_package` projects `review=None` for owned content. So the gate is real at
  plan time and invisible afterwards — the baseline reports `review-missing` for a vendored
  artifact. **Recorded residue, owned by `VN-4`:** that package already has to persist the
  assessment with the artifact, and the review decision belongs in the same place.
- **The review's origin statement is a `CurationCheck` named `vendor-origin`.** `CurationReview`
  carries changes, checks, and warnings, and only those are covered by the review digest — there is
  no free-text field to state origin, ref, resolved commit, subtree, target, declared version, and
  payload file count. Putting them in a check means the maintainer approves a digest that includes
  them. The license finding is absent from those details until `VN-6`.
- **`--version` is spelled `--artifact-version`,** matching `scaffold`. Design §4 requires that the
  maintainer supply the version, not that the flag be spelled `--version`, which at that parser
  level would read as the executable's own version flag.
- **Two warnings, not one.** Besides design §3's "not a safety claim", the review states that this
  registry now owns the copy and that upstream fixes reach consumers only when it is vendored again
  — the consequence a maintainer is most likely to discover later.
- **A new registry verb fails `tests/registry_cli_test.py` until it is listed there.** That test
  asserts the registry subparser's action set exactly, which is the guard that a verb cannot be
  added without a command boundary; it had to be extended, not worked around.

**Recorded residue, not fixed here:** `vendor` is create-only — a second vendor of the same identity
refuses with `artifact package already exists`, and that message does not name the command that does
adopt upstream movement, because `SI-6` requires every command AART names to be one the executable
accepts. When `VN-5` lands `revendor`, that refusal should name it.

**Exit:** design §1 and §8. Depends on `VN-2`.

## VN-4 — the assessment is part of the review

**Files:** `agent_artifacts/commands/registry.py`, `agent_artifacts/security/`

1. Run `assess_installation_risk` over the projected package's immutable object during the vendor
   review and render the findings inline, in text and JSON.
2. Render the framing verbatim from the `security` command: assessments reduce uncertainty; they are
   not safety guarantees. No surface says verified, trusted, or safe.
3. Persist the assessment with the artifact so a second reviewer sees what the first saw.

**Tests:** a planted `curl … | sh` in the authored `install.sh` appears as
`shell-pipe-to-interpreter` — proving the maintainer's own wrapper is assessed, not only the payload;
a committed credential in the upstream subtree appears as `embedded-credential`; an unpinned install
appears as `unpinned-package-install`; the rendered review contains no word claiming safety.

**What the plan did not anticipate**

- **The assessment cannot live in `provenance.json`.** The obvious home is circular: the assessment
  names the object digest of the package, and `provenance.json` is one of the package's files, so
  writing the assessment into it changes the digest the assessment describes. The evidence is
  therefore written as its own canonical document at `security/attestations/<attestation-digest>.json`
  — the exact path `SecurityIndexEntry` already requires — with `AttestationOriginKind.LOCAL`,
  because this ran on the maintainer's machine and a `registry-ci` origin would have to name a
  resolved registry revision that does not exist until the vendoring is committed.
- **It is deliberately not written into `security/index.json`.** That index binds the compiled
  `registry_inputs_digest`, which does not exist until `build` runs, and `registry audit` demands
  evidence coverage for *every* compiled object once an index is present — so writing one here would
  make audit fail for any registry that already has other artifacts, breaking design acceptance 4. A
  loose attestation document is additive: `security/` is excluded from `registry_inputs_digest`, so
  committed evidence cannot make the lock or index read as stale. A test holds that.
- **`FilesystemRegistryWorkspace` could not see `security/` at all.** Its managed roots were
  `entries`, `artifacts`, `collections`. A plan writing an attestation therefore failed apply
  *verification* — the file was written and the re-read snapshot did not contain it. Adding
  `security` to the reader's roots (and to `_managed_path`) fixes a second, pre-existing defect in
  passing: `audit_registry_workspace` reads `security/index.json` out of that same snapshot, so
  until now its security-evidence branch was unreachable from `registry audit` on a real checkout.
- **A finding does not refuse the vendor.** The `vendor-assessment` check passes when the assessment
  *ran to completion*, not when it found nothing: an assessment that completed and reported a
  critical credential has done its job, and design §3 gives the decision to the maintainer. Refusing
  here would have converted evidence into a policy AART does not own.
- **VN-3's own wording had to change.** Its warning said "a clean vendor reports what was found";
  with an assessment in the review that reads as a verdict, so it now says "a successful vendor
  reports what was copied". The test asserts no `safe|verified|trusted|secure|vetted` token appears
  in either rendering.
- **The maintainer's wrapper is assessed because it is part of the object, not by a special case.**
  The test authors a declared custom setup entrypoint (`setup/installer.json` +
  `setup/install.sh`), which the loader requires to be executable and to carry the manual-setup
  header — an unexpected gate that is correct: an entrypoint no one can find from `SETUP.md` is
  exactly what should not be adopted silently.

**Exit:** design §3. Depends on `VN-3`.

## VN-5 — `registry revendor` and three honest dispositions

**Files:** `agent_artifacts/registry_maintenance/`, `agent_artifacts/commands/registry.py`

1. Re-resolve the recorded `origin.url` at the recorded ref, take the recorded subtree, and compare
   its input digest with `origin.input_digest`.
2. Report `up-to-date`, `changed`, or `unreachable`, reusing the disposition shape of
   `check_native_reference`. Never report `unreachable` as `up-to-date`.
3. On `changed`, render the file-level diff and refuse to finalize without an explicit `--version`.
4. On `up-to-date`, finalize is a no-op that says so.

**Tests:** an unmoved upstream is `up-to-date`; a moved one is `changed` with the correct
added/changed/removed counts and refuses without `--version`; an unreachable origin is `unreachable`
and mutates nothing; a re-vendor at the recorded commit reproduces `origin.input_digest` exactly
(design acceptance 11).

**What the plan did not anticipate**

- **Nothing recorded the ref.** Design §6 says re-resolve "the recorded `origin.url` at the recorded
  ref", and `provenance.json` records the URL, the resolved commit, the path and the input digest —
  but not the ref, because a commit is what a copy is pinned to and a ref is only how it was found.
  `origin` could not hold it either: that object rejects unknown fields, and widening it is the
  format revision this release promised not to make. The ref is therefore written as a namespaced
  extension, `aart.vendor`, which every AART from `2.0.0` already preserves unchanged. It is read
  back through `importer.options_digest` — the digest `VN-2` already computed over URL, ref and path
  — so a ref edited by hand into that extension is refused rather than silently re-vendored from
  somewhere the copy never came from.
- **The same extension has to record which files are the maintainer's.** A file present in the
  package but absent from upstream's subtree is either their wrapper or an upstream deletion, and
  nothing else in the package distinguishes the two. The alternative — re-acquiring at the recorded
  commit to recover the old file list — was rejected on a practical ground: fetching an arbitrary
  commit SHA is refused by many hosts, so an ordinary drift check would fail as `unreachable` for a
  reason that has nothing to do with reachability. The authored list is small by construction: it is
  what the maintainer wrote, and if they wrote five hundred files, recording five hundred paths is
  proportionate.
- **The workspace plan could not express removal at all.** `WorkspaceChangeKind` had `added`,
  `changed` and `unchanged`, and `after_digest` was mandatory — every other registry operation
  writes a fixed set of derived documents and has nothing to delete. Re-vendoring is the first
  operation where upstream's deletion must reach the copy, so `removed` was added, with
  `after_digest` `None` and pruning confined to the package's own directory. Existing review digests
  are unaffected: the serialization changes only for plans that contain a removal.
- **An emptied directory is deliberately left behind.** The applier verifies itself by re-reading
  the workspace and comparing it with the projection, and the directory is still there after the
  file is unlinked — so a projection that pruned it would fail its own verification. Git does not
  track empty directories, so the maintainer's commit is identical either way.
- **`up-to-date` does not re-pin the commit**, even when the ref has advanced over content outside
  the subtree. Nothing this registry ships changed, and writing a new `resolved_commit` would
  produce a diff claiming the copy was refreshed when it was not.
- **The refusal without `--artifact-version` had to come after the diff, not instead of it.** The
  maintainer cannot state the version a movement deserves without first seeing the movement, so a
  moved upstream with no stated version is a complete review — counts, commits, both dispositions —
  that plans nothing and fails.
- **`--check` had to start counting a failed check as drift.** It exited zero whenever no path
  changed, which for `revendor` against an unreachable upstream is exactly the reading design §6
  forbids: writing nothing is not being current. The rule now also requires every check to pass,
  which is correct for the other actions too.
- **`CurationRequest.artifact_version` became optional.** It defaulted to `1.0.0`, and a default
  here would silently answer the one question the command exists to ask.

**Questions raised while building this, deliberately not answered here:** whether `--path` should
accept a single file rather than only a directory (`VN-1` refuses it today, and neither design nor
plan asks for it), and whether a bulk `revendor --all` should exist (it cannot be one action while
design §4 requires a stated version per artifact). Both are product decisions for the maintainer,
not defects.

**Residues found, recorded against the package that will own them:**

- `VN-6`: `registry audit` runs read-only over a workspace snapshot and has no acquirer, so the
  behind-upstream finding needs one injected — and the audit must stay green when it cannot reach an
  upstream, which is the same distinction `revendor` draws between `changed` and `unreachable`.
- `VN-8`: `registry vendor --help` still says "A clean vendor reports what was found", while the
  review says "a successful vendor reports what was copied". `VN-8` owns the help text.

**Exit:** design §4 and §6. Depends on `VN-3`.

## VN-6 — license capture, and drift visible from CI

**Files:** `agent_artifacts/registry_maintenance/`, `registry audit`

1. Discover a license file in the taken subtree; pre-fill `ArtifactManifest.license` when
   unambiguous; report what was found — or that nothing was — in the vendor review.
2. `registry audit` reports a vendored artifact with no recorded license.
3. `registry audit` reports vendored artifacts behind upstream, read-only, with unreachable origins
   reported as unknown rather than as drift.
4. Neither finding fails the audit on its own.

**Tests:** a subtree with `LICENSE` pre-fills and reports it; two license files report ambiguity and
pre-fill nothing; audit lists the unlicensed vendored artifact and still exits successfully; audit
distinguishes behind-upstream from unreachable.

**What the plan did not anticipate**

- **"Unambiguous" had to be defined twice.** One licence file settles nothing by existing: the
  identifier has to come out of the text. So a subtree is unambiguous when exactly one licence file
  sits at its root *and* that file's opening matches one of a short table of SPDX texts — MIT, ISC,
  Apache-2.0, MPL-2.0, BSD-2/3-Clause, Unlicense. The table is ordered and first-match-wins because
  the markers are not disjoint: every BSD-3-Clause text contains the whole BSD-2-Clause text.
- **The GPL family is recognised and deliberately not completed.** Its text names the version but
  not the grant — `-only` and `-or-later` are chosen by the work that applies the licence, not by
  the licence document — so the review names the family and asks for `--license`. Filling in one of
  the two would be a guess presented as this registry's own statement about what it redistributes.
- **A licence below the subtree root is reported and never adopted.** A `LICENSE` beside a bundled
  dependency covers the dependency; adopting it would record a claim nobody made.
- **`--license` had to exist, or the audit finding was unactionable.** The plan asks the audit to
  report a vendored artifact with no recorded licence, and nothing else in the release lets a
  maintainer record one: the manifest is derived, not authored. A stated licence always wins over a
  discovered one, and the review shows both.
- **Re-vendoring was silently dropping the licence.** `plan_artifact_revendor` rebuilds
  `VendorOptions` from the stored manifest, and the new field would have defaulted to `None` — every
  upstream movement would have turned a licensed copy into an unlicensed one. The recorded value is
  carried through rather than re-derived: it is this registry's statement, not upstream's.
- **The generic audit finding already existed.** `registry audit` warned "owned package has no
  declared license" for every owned package. A vendored one now gets its own wording, because
  redistributing somebody else's bytes with no licence recorded is a different fact from a
  first-party package that never filled the field in — and emitting both would be noise.
- **Upstream resolution in `audit` is opt-in, via `--check-upstream`.** Design §6 says the audit
  gains the check "in read-only form"; it does not say the audit starts using the network. Making it
  unconditional would break every offline run and make a green CI depend on somebody else's uptime,
  so the acquirer is injected and absent by default — without the flag the audit stays a pure
  function of the snapshot. With it, findings still only report: behind-upstream and unreachable are
  both warnings, and unreachable is worded as unknown, never as drift.
- **A hand-edited vendoring record now fails the audit.** Reading the `aart.vendor` extension to
  find the origin means verifying it against `importer.options_digest`, and a record that fails that
  check is tampering with the input of the next re-vendor — an error, not a warning. This is the one
  finding in this package that is not merely reported.
- **`read_vendored_artifact` was split.** It resolved a package by identity under the first artifact
  root; the audit walks every root by path, so the reading half became `read_vendored_package`,
  taking a located package. Resolving the identity again would have looked in the wrong place in a
  registry that declares more than one root.
- **`NativeAcquirer` moved to `registry_maintenance/model.py`.** It lived in `curation/runtime.py`,
  which a pure planner must not import; declaring it beside the acquisition it produces lets the
  audit accept one without dragging in the Git runtime. `_default_native_acquirer` lost its
  underscore for the same reason: it is now called from `commands/registry.py`.

**Residues found, recorded against the package that will own them:**

- `VN-8`: the `registry vendor --help` text still says "A clean vendor reports what was found" while
  the review says "a successful vendor reports what was copied" (carried over from `VN-5`), and
  `--license` and `--check-upstream` are new surfaces the protocol text and tutorial do not mention.

**Exit:** design §6 and §7. Depends on `VN-5`.

## VN-7 — delete the token module that promises what AART does not do

**Files:** `agent_artifacts/io/net.py`, `tests/net_test.py`, `docs/design/`

1. Delete `agent_artifacts/io/net.py` and its test. It is imported by nothing else, and it is the
   only place in the package naming `GITHUB_TOKEN` or `GITHUB_API_URL` — including a hint telling a
   reader to set them for GitHub Enterprise, which does nothing.
2. Add a guard asserting no module in `agent_artifacts/` mentions either name, so the promise cannot
   reappear.
3. Mark `DESIGN-upstream-import.md` and `DESIGN-upstream-github-hosts.md` as superseded, pointing at
   this design, and record in the compatibility addendum that AART holds no tokens and reaches
   private hosts through system Git's own configuration.

**Tests:** the guard fails on a planted mention. Independent of every other package.

**What the plan did not anticipate**

- **The test file was not only that module's test.** `tests/net_test.py` also covered
  `agent_artifacts/io/cache.py`, the immutable snapshot cache. Deleting it wholesale would have left
  a live module with no test at all, so the two cache tests moved to `tests/snapshot_cache_test.py`
  and lost the HTTP fixture with the client: the cache takes a `fetch` callable and never knew where
  the bytes came from, so an in-memory tarball is the whole setup it needs.
- **`io/cache.py` itself is now imported by nothing** — it is the other half of the removed
  importer, and design §9 names only `net.py`, because `net.py` is the one advertising a capability
  the product does not have. A dead module that promises nothing false is a different defect, and
  removing it was not this package's licence to grant. Recorded below.
- **The guard lives in the `validate` gate, not in a test.** A test asserts; a gate refuses. It is
  the same place `non_stdlib_imports` already keeps the zero-dependency promise, which is the same
  kind of promise — something true of every module, enforced once, rather than remembered. The unit
  test drives the gate's function over a planted file, so both exist for their own reasons.
- **`.github/workflows/release.yml` still names `GITHUB_TOKEN` and is deliberately untouched.** That
  is GitHub Actions authenticating to GitHub to publish a release, not AART reading a credential.
  The guard scans `agent_artifacts/` only, so the distinction is enforced rather than hoped for.
- **The compatibility record was written as an addendum to `v10`, not as `v11`.** The `2.3.0`
  compatibility document does not exist until the release commit, and the fact this package records
  — AART holds no credentials of its own; Git authenticates — has been true since `2.0.0`. So
  `compatibility-v10-addendum.md` states the rule and names what `2.3.0` removes, following the
  precedent `compatibility-v8-addendum.md` set: written during a later release, changing nothing
  about the one it names. It is linked from `compatibility-v10.md`, or nobody would find it.
- **Only the two designs the plan named were marked.** Their companion plans
  (`PLAN-upstream-import.md`, `PLAN-upstream-github-hosts.md`) are dated implementation records of
  work that happened; the designs are what a reader takes as current intent. Banner-marking the
  plans as well would blur that distinction across a dozen historical documents.

**Residues found, recorded against the package that will own them:**

- No package owns these; they are findings for the maintainer, not defects this release created.
  `agent_artifacts/io/cache.py` is now unreferenced by shipping code (a GitHub-tarball cache for a
  catalog model that no longer exists), and `docs/design/DESIGN-upstream.md` — the parent of both
  superseded documents, describing the `aart upstream` verb `2.0.0` removed — carries no banner,
  because this plan named two documents and marking a third was not its call.

## VN-8 — the protocol says what a vendored artifact is

**Files:** `docs/protocol/registry-v1.md`, `docs/protocol/native-source-v1.md`,
`agent_artifacts/cli.py` help, tutorials

1. State in the registry protocol that a registry may own, reference, or vendor content, and what
   each means for who the consumer must reach and who owns the version.
2. State the maintainer responsibility in the protocol document, not only in a tutorial: vendoring
   moves the trust boundary into the registry, and a clean vendor is not a safety claim.
3. One line each in `registry --help` distinguishing `vendor`/`revendor` from
   `promote-native`/`refresh-native`.
4. A worked tutorial: vendoring one MCP server from a repository with an arbitrary layout, adding
   `install.sh` and `SETUP.md` as the setup recipe, reading the assessment, and re-vendoring when
   upstream moves.

**Must land after `SI-9`.** Depends on `VN-6`.

**What the plan did not anticipate**

- **The tutorial's setup recipe is not upstream's `install.sh`.** Item 4 reads "adding `install.sh`
  and `SETUP.md` as the setup recipe", but a setup recipe v2 is a JSON document AART parses, and a
  shell script cannot be one. The reading taken: upstream's `install.sh` is *payload* — bytes the
  registry redistributes, and exactly what the assessment flags as
  `shell-pipe-to-interpreter (critical)` — while the maintainer authors a real recipe plus `SETUP.md`
  beside it. That is the more instructive tutorial anyway: it shows the copied script being judged
  rather than trusted, which is the point of assessing the bytes that would be written.
- **A v2 recipe's package-relative path must be exactly `setup/installer.json`.** Discovered by
  writing the walkthrough: `setup/atlassian.json` is refused with "version-2 installer path must be
  below a package setup/ directory" (`agent_artifacts/setup.py`, `_manual_path`). The recipe must
  also declare `help_urls`, or the artifact is refused as an invalid setup installer. Both are
  pre-existing rules, both are invisible until a maintainer hits them, so the tutorial states them.
- **The tutorial is a carried-forward release document.** Added to `REQUIRED_PERSISTENT_DOCS` in
  `scripts/release.py` beside the other two tutorials, so a later release cannot quietly drop it.
- **`docs/tutorials/company-registry-v1.md` claimed foreign content is converted by a built-in
  importer.** That importer was removed in `2.0.0`; vendoring is what replaces it. The sentence was
  corrected here rather than left as a residue, because `VN-8` owns the tutorials and the false
  sentence is precisely what this package exists to replace.

**Residue closed:** the `registry vendor --help` text now says "A successful vendor reports what was
copied", matching the review (carried from `VN-5` through `VN-6`).

## VN-9 — the same action in the text front-end

**Files:** `agent_artifacts/tui.py`, `agent_artifacts/curation/`

1. Add `vendor` and `revendor` to the maintainer action list beside the existing
   `promote-native`/`refresh-native` entries (`tui.py:193`).
2. The TUI path produces the same request value as flag mode, and shows the same assessment.

**Tests:** the TUI request value equals the flag-mode request for one fixture; the rendered review
contains the assessment. Depends on `VN-4`.

## Dependency order

```mermaid
flowchart LR
  VN1["VN-1 subtree acquisition"] --> VN2["VN-2 package projection"]
  VN2 --> VN3["VN-3 vendor"]
  VN3 --> VN4["VN-4 assessment in review"]
  VN3 --> VN5["VN-5 revendor"]
  VN5 --> VN6["VN-6 license + drift audit"]
  VN6 --> VN8["VN-8 protocol + tutorial"]
  VN4 --> VN9["VN-9 TUI"]
  VN7["VN-7 remove io/net.py"]
  SI9["SI-9 (2.2.0)"] -.-> VN8
```

`VN-7` is independent of everything and can land first. `VN-1` gates the rest of the chain. `VN-4`
and `VN-5` are independent of each other once `VN-3` exists. `VN-8` is dashed from `SI-9` because it
is an ordering constraint across releases, not a code dependency.

## Release shape

**`2.3.0`, contract v11** — `VN-1` through `VN-9`. Two new registry verbs, two new audit findings,
one dead module removed. No protocol, schema, or format revision: a vendored artifact is an owned
package carrying `provenance.json`, which every AART from `2.0.0` already reads.

The honest paragraph for the release notes: vendoring puts foreign bytes in your registry and makes
your registry their distributor. It removes the requirement that upstream speak AART, and it removes
the requirement that consumers reach upstream at all. What it does not remove is the maintainer's
responsibility for what they copied — and the release notes should say that in those words.
