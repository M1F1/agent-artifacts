# Changelog

All notable AART changes are documented here. The project follows semantic versioning for the
executable; protocol, schema, artifact, importer, profile, and registry versions remain independent.

## 2.8.4 — 2026-08-20

`2.8.3` fixed one of the two branches that produce the Docker recovery note, and left the branch an
ordinary first install reaches (`AD-38`).

### Fixed

- Both Docker recovery notes open with `Docker image …` and carry the tag or image they are about.
  The branch for a tag this run created used to read *Rollback removes this tag, which only this run
  created*, naming neither Docker nor the tag — the same defect the sibling branch had, left
  standing on the common path.
- The note says rollback removes the tag with `docker image rm`, that this also deletes the image
  when no other tag refers to it, and not to remove the tag by hand because the server runs from it.
- `docker.pull@1` had it too. It now says rollback **leaves** the image — `_rollback_receipt`
  returns `False` for a pulled image on purpose, because it can back other containers — and that
  removal is the operator's, after checking nothing else uses it.

### Documentation

- The README states the development dependencies and what each of the nine quality gates runs. The
  installed runtime still has none: standard library only.

### Known defects shipped open

- `AD-39`: a run configuring several artifacts prints the `2.8.3` reload reminder once per artifact.
  Noise rather than wrong advice, recorded and left for its own change.

## 2.8.3 — 2026-08-19

Setup writes variables into a shell file, prints `configured`, and stops. The shell it was launched
from still holds the environment it started with, and so does every process that shell goes on to
spawn — the agent harness among them (`AD-37`). A child process cannot alter its parent's
environment; what was missing is that nobody said so.

### Fixed

- A run that wrote variables into a shell file ends with a `Next step` block naming that file, the
  `source` command, and the alternative of opening a new terminal and starting the harness there.
  The alternative matters: `.zshrc` is read by interactive shells only, so a harness launched from
  the GUI never sees the exports regardless of how many times it is restarted.
- The path comes from the shell step's own receipt, so a recipe writing somewhere other than
  `~/.zshrc` is named correctly. Several shell steps produce one block per distinct file, in write
  order. It prints as `~/.zshrc`, not the operator's home directory in full.
- The advice used to exist only glued to the end of a `security` remediation command, so it appeared
  where a secret was suspected and nowhere else.
- The Docker build step's recovery note no longer says the pre-existing tag is left alone and should
  be removed by hand. `docker build --tag` reassigns the tag, and removing it breaks the server.
  Measured on Docker 29.5.2 with the containerd snapshotter: the previously tagged image is deleted,
  not left dangling, so nothing can restore the old binding.

### Documentation

- The README states the licence: MIT, free for any use including commercial, with no warranty and no
  liability on the author.

## 2.8.2 — 2026-08-19

The advisory `2.8.0` and `2.8.1` added was read by one surface, and not the one people use. Setup
run through the wizard printed `configured` and nothing else: the measurement happened, the receipt
carried it, and `tui.py` read only the `recovery` field (`AD-36`). Reported from a real run in which
the value was replaced, truncated to 128 bytes again, and never mentioned.

### Fixed

- The wizard prints the advisory. `advisory_messages` and `render_setup_advisories` live in
  `setup.py` beside `recovery_messages`, both surfaces call them, and the JSON renderer renders
  through the same body, so the two cannot drift.
- A recovery note carries its command on its own line, never wrapped. It is sanitised per segment,
  because `public_text` flattens line breaks and would erase the split before it could be read.
- A replaced Keychain value says so: *This account already had a value in the Keychain and this run
  replaced it.* The note used to read as an instruction to type something, when it is the undo for
  something already done.

Protocol versions, persisted schemas, commands, flags and the setup recipe language do not change.
No receipt field is added or renamed.

## 2.8.1 — 2026-08-19

Setup now says something about a Keychain item it left alone. Finding the item already there is the
normal outcome of every run after the first, and that path measured nothing and reported nothing:
if the credential was rotated since it was stored, the run said `configured` and the server kept
authenticating with the old value (`AD-35`). The reload command also printed the operator's home
directory in full, which reads like a path the tool baked in.

### Changed

- A Keychain step that keeps an existing item now measures it and records `existing_secret_kept`,
  `stored_length`, an `advisory` and `remediation_commands` — the same command that fixes a
  truncated paste replaces a rotated one, so both findings are reported as one.
- The receipt field `truncation_detail` is now `advisory`, because it carries both findings.
  `truncation_suspected` and `stored_length` keep their meaning.
- The reload in the printed command is `~/.zshrc`, not the absolute path. The tilde is left
  unquoted so the shell still expands it; anything needing quotes is quoted after the first slash.
- The commands header reads `to replace what is stored:`, which is true whether the value was
  truncated or simply old.

Nothing is written on this path. An advisory is not a change: the run still leaves the existing
item exactly as it found it, and the pre-prompt warning is not printed for a prompt that never
happens. Protocol versions, persisted schemas, commands, flags and the setup recipe language do
not change.

## 2.8.0 — 2026-08-19

Setup now says when a Keychain secret was truncated at the prompt. `security` reads its prompt
through `getpass(3)`, whose buffer is 128 bytes, and it asks twice — so two identically truncated
pastes agree with each other and the short value is stored without an error (`AD-34`). This is a
minor release because the setup `--json` payload gains an optional `warnings` array and the runtime
gains a public seam. Protocol versions, persisted schemas, commands, flags, registry documents and
the setup recipe language do not change; schema freeze v18 has the same protocol values and
normative input digests as v17.

### Added

- The Keychain step warns before the prompt that the tool asks twice, keeps at most 128 bytes, and
  that this run will measure what was stored.
- A successful add records `stored_length` in its receipt. At exactly 128 it also records
  `truncation_suspected`, `truncation_detail` and `remediation_commands`.
- The run ends with a `Warnings` block after the summary carrying two copy-ready commands: one that
  sets the value from the clipboard, one that proves its length. Commands are never wrapped.
- `aart marketplace install --json` gains an optional top-level `warnings` array, present only when
  a warning fired.
- `SetupRuntime.secret_length` is a new seam, inert by default so no test run reaches a real
  Keychain. `production_runtime()` wires the real probe.

The measurement never holds the secret. `security` writes into a pipe that only `wc` reads, AART
closes its own copy of the read end, and AART reads the count. It takes two counts, not one:
`security -w` prints a value that is not printable ASCII as hex, with nothing marking it as hex,
and a password made only of hex digits prints literally — so `-g`, which writes `password: 0x` for
the hex form and a quoted string otherwise, is counted by `grep` to tell the two apart. A failed or
unavailable measurement leaves the receipt silent, because no measurement is not the same claim as
no problem.

### Upgrading from 2.7.1

Upgrade normally. No installation record, state document, harness file or recipe changes, and no
setup step needs re-running. A secret stored by an earlier version is not re-measured; to check one,
run the `find-generic-password … | wc -c` command the warning prints. A consumer that rejects
unknown top-level JSON keys should be updated before it meets `warnings`.

### Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low`. The ceiling
itself is Apple's and is unchanged — a 193-byte Atlassian token still cannot pass through this
prompt, so `AD-34` stays open and this release ends its silence rather than its cause. `AD-30` and
`AD-31`, the other two sides of the same credential join, also remain open.

## 2.7.1 — 2026-08-18

This patch restores the Tabnine MCP target used by the company build after 2.7.0 replaced measured
target-environment evidence with a path from documentation for another or unmeasured build. No
protocol, persisted schema, command, flag, or registry shape changes; schema freeze v17 retains the
v16 protocol versions and normative input digests.

### Fixed

- Project MCP entries again merge into `.tabnine/agent/settings.json` under `mcpServers`; user
  entries use `~/.tabnine/agent/settings.json`. The user scope added in 2.7.0 remains available.
- The Tabnine filesystem E2E now requires both company-build settings files, requires both
  `mcp_servers.json` alternatives to remain absent, checks status, and removes either scope without
  touching the other.
- Current tutorials and profile designs state the evidence boundary: `disconnected` proves the
  company build parsed the settings entry and reached a separate server-runtime failure. Published
  standalone-file documentation remains an unmeasured verify item for that build.

### Upgrading from 2.7.0

An MCP installation already written by 2.7.0 remains owned at `mcp_servers.json`. Update fails
closed rather than orphaning it. Run the exact `marketplace uninstall` command it reports, then
install the artifact under 2.7.1; the new installation lands in `settings.json`. Installations from
2.6.1 already use the restored project target and do not need this file migration.

### Known defects shipped open

Fifty-seven findings remain open: one `major`, two `high`, 33 `medium`, and 21 `low`. `AD-29` is the
new medium profile-override hazard found while auditing this repair: a partial same-name override
replaces the whole builtin record. It is separate from the target reversal. No high-severity
adoption finding remains open.

## 2.7.0 — 2026-08-18

The company-adoption stream closes all 27 `AD` findings. This is a minor release because it adds
public maintainer commands and a reporting option, and extends setup recipe v2 with a new input
kind. Protocol version numbers and persisted document shapes remain unchanged; schema freeze v16
records the changed implementations.

### Added

- The README has a tested 3×3 no-clone install matrix for `pip`, `pipx`, and `uv tool`, plus one
  company-registry path from first source through Tabnine install.
- Registry maintainers can author collections, conservatively discover candidates, finalize an
  explicit batch-vendoring manifest, vendor a single loose file, and review then publish lock,
  index, audit evidence, and one Git commit through `registry collection`, `discover`,
  `vendor-batch`, and `publish`.
- `registry init --usage-reporting-repository OWNER/REPOSITORY` activates the reporting templates.
  Finalized CLI and TUI actions explain unusable routes; interactive CLI reporting retains both
  consents while JSON and non-interactive modes remain inert.
- Setup recipe v2 accepts reviewed, echoed `text` inputs through `shell.env-from-input@1`; secrets
  remain Keychain-only. Packages using this addition must require AART 2.7.0 or later.

### Fixed

- Source freshness is an origin/revision/snapshot comparison rather than an age guess. Automatic
  mode synchronizes before projection; manual mode reports `not-synchronized` separately from
  `could-not-check`.
- Tabnine MCP installs use the documented `.tabnine/mcp_servers.json` project and user targets.
  Distinct named memories can share one instruction file and be removed independently.
- Setup install/update exit status, policy projection, manual routes, Keychain context, target
  preflight, persistence diagnostics, compensation receipts, and same-version recipe updates now
  preserve their reviewed lifecycle contracts.
- Registry initialization, discovery, vendoring, batch finalization, collections, lock/build, and
  publish diagnostics now name concrete repairs and keep preview runs inert.
- The live runtime-requirements key is `aart.runtime-requirements`; the retired
  `com.m1f1.runtime-requirements` spelling fails with an exact migration diagnostic.

### Known defects shipped open

Fifty-six unrelated findings remain open: one `major`, two `high`, 32 `medium`, and 21 `low`.
`LAF-15` is the major gap (`security scan` has no producer for its canonical envelope);
`LAF-85` and `LAF-101` are the two high register/audit uncertainties. The adoption stream introduces
no known open finding; the residue register remains authoritative.

## 2.6.1 — 2026-08-16

Fifteen recorded defects stop happening. Nothing is added: no command, no flag, no field, no schema,
no protocol version, and no obligation for a registry maintainer in either direction. The v15 freeze
carries protocol versions identical to v14 and differs in exactly one input,
`agent_artifacts/setup.py`, where `rollback_command` was split so a persisted record can compose the
same sentence from its own coordinates.

Composed from [`residue-register.md`](docs/testing/residue-register.md) during one unattended
overnight run. The register's open rows were taken in priority order, each on its own branch, each
with a failing test first, and — for anything larger than a message string or a document — a live
walk against a real locally built wheel installed into a throwaway venv, with no patched executable
and no monkeypatching at the boundary. Ten such runs, `v4` through `v13`; nine of them walk both a
branch wheel and a `main` wheel so the record distinguishes the change rather than describing the
product.

### Fixed

- A setup step that pulls from a private registry can authenticate. The docker adapters were given a
  sanitised environment that dropped `HOME` and `DOCKER_CONFIG`, so `docker pull` could not find the
  credentials the operator had already stored, and the failure named neither (`RS-12`).
- `release wheel-digest` hands over the wheel whose digest it printed. It built a wheel in a
  temporary directory, hashed it, deleted it, and left the operator to upload a different one built
  by `build_wheel.py`; `--output` writes the stamped artifact where the digest can be checked against
  the file that is actually published (`LAF-75`).
- The install-scope selector answers with one type. It returned either a scope or `None` for cancel
  and `None` for *keep the default*, so a caller could not tell a choice from a refusal (`LAF-64`).
- `docs-check` fails in both directions. It failed a document that called an open finding shipped
  open, and passed one that called an open finding `closed` — the direction that asserts a safety
  which is not there. `DOC010` is the second direction, and it reproduces on the row that stayed
  wrong for a whole release while the gate was green (`LAF-69`).
- `receipt verify` states the rollback command **this** executable accepts, composed from the
  persisted record's own coordinates rather than from a sentence written for a run in flight
  (`LAF-73`).
- Every `registry` refusal and every `validate`/`audit` finding carries a next step. They named what
  was wrong and stopped there (`RS-09`).
- `marketplace status` reads the project after the last subscription is removed, and names the source
  it could not find instead of reporting an empty project (`RS-07`).
- `audit --check-upstream` says it checked when everything is current, so a pass is distinguishable
  from a dropped flag (`LAF-45`).
- A malformed `aart-registry.json` fails the identity check instead of being skipped as though the
  file were absent (`RS-08`).
- An `mcp` package written by hand is checked like a vendored one — the vendoring-specific advice is
  no longer attached to packages that were never vendored (`RS-01`).
- `marketplace uninstall` removes a `.mcp.json` or `.claude/settings.json` that AART itself created
  and has just emptied, and still never removes one that existed before the install (`LAF-47`,
  `RS-10`).
- The `vendor` refusal on an existing package names `revendor`, the command that would work
  (`RS-04`).
- A registry request stops stamping a compatibility window taken from an AART that no longer runs;
  the default window is derived from the running executable (`RS-02`).
- The wizard suggests a window the running executable is inside. `registry init` offered
  `1.0.0`/`2.0.0` by pressing return, wrote them, and then `registry validate` — the first command
  its own success message recommends — refused the registry it had just created (`LAF-90`).
- The Git environment AART hands a subprocess is documented (`LAF-49`).

### Known defects shipped open

Fifty-seven, of which one is `major` and two are `high`. The count is larger than at `2.6.0` because
the same run that closed fifteen findings spent the rest of its budget measuring the product and the
record, and measurement produces findings. Three bound what this release should be trusted to do:

- `LAF-15` (`major`): `security scan` requires a canonical object envelope that no `aart` command
  emits. The scanner is correct when fed one by hand; nothing ships that produces one.
- `LAF-105`, `LAF-116`, `LAF-117`: the object store's garbage collector exists, is specified, and has
  no caller, while a plan-only review, `marketplace status` and `source remove` all leave content on
  disk. Nothing an operator can run removes any of it.
- `LAF-85` (`high`): an unidentified writer touched the real data root during an unattended session.
  Re-read read-only the next day — nothing has changed since, the trace is reproduced by an ordinary
  install-then-uninstall, and the first, more alarming reading was refuted. What wrote is still
  unknown.
- `LAF-101` (`high`): the register itself is incomplete. It was seeded from one walk's findings table
  and took the open rows, so three findings from that walk — two of them `major` — exist only as a
  sentence in a run log. That is the form of record this register was written to replace.

The rest, with dispositions and reproductions, in the residue register.

## 2.6.0 — 2026-08-15

The persisted setup receipt gets a reader. `2.2.0` began writing a complete, redacted, plan-bound
account of every setup run — plan hash, installer hash, timings, exit status, one receipt per step —
and no shipped code path could look at it. `marketplace uninstall` reported `setup skipped` and left
the image tag, the keychain item and the shell block, while every effect's review line promised
`removes only changes created by this run`. Three actions now read that account, ask whether it is
still true, and reverse it. Two rendering paths stop printing counts over payloads that already held
the answer. Minor: no field, no schema, no protocol version, and no obligation for a registry
maintainer in either direction — the v14 freeze carries protocol versions identical to v13 and differs
in exactly one input, `agent_artifacts/setup.py`, where the difference is a single rename.

Composed from [`residue-stream-2026-08-15.md`](docs/testing/residue-stream-2026-08-15.md), which
gathered twenty-eight deferred items from `2.2.0`..`2.5.0` into six clusters. Three clusters are
answered here; two are left alone on purpose.

### Added

- `aart marketplace receipt show <coordinate>` renders the persisted record for one installation
  without a run in flight and without taking a lock, so it does not block or fail during an unrelated
  install. Three absences get three sentences — never installed, installed with no setup run recorded,
  and a pointer whose target is gone — because an operator holding a refusal needs to know which one
  they are in.
- `aart marketplace receipt verify <coordinate>` asks this machine whether each receipt's claim still
  holds: does the tag resolve to the recorded image id, does the file still carry the block that was
  installed, does the Keychain item exist **and hold a non-empty value**. Three statuses, not two — a
  claim it could not put is `unknown` and never `true`. Non-zero exit on any false claim. It reports
  and never repairs: an orphaned run directory is named and left.
- `aart marketplace receipt undo <coordinate>` calls the existing `rollback_record` against the
  persisted record instead of the in-process one, with its ownership checks and its
  `receipt_matches_plan` binding unchanged. Review-first like every other mutation: without `--yes`
  nothing changes, and `--expect <digest>` binds the decision. The review names every effect it will
  reverse **and every effect it will not, with the reason**.
- All three in both front-ends, from the Action menu, through one shared function — with a guard that
  fails if either skin renders a receipt on its own.
- `docs/testing/residue-register.md`: one place that says what is open, with a disposition per finding
  and, where something closed, the reproduction that closed it. Four `docs-check` rules
  (`DOC006`..`DOC009`) hold it and every current plan, design and compatibility document in agreement.

### Fixed

- A setup review is printed by a CLI path. It was composed in full and emitted under `--json` only, so
  `--approve-setup-effects` approved a list the operator had never been shown.
- A setup planning failure prints the detail, the artifact key and the manual route instead of
  `planned=0, failures=1`. Counts still appear — after the content, never instead of it.
- A failing build reports the instruction that failed and its exit code. `docker build` prints
  progress first and the error last, so head-truncating the transcript kept exactly the half that could
  not explain the failure. One helper, used at all three capture sites.
- An unattended Keychain step that stores nothing is now detectable. `security add-generic-password -w`
  with no terminal exits 0 having stored nothing and every check downstream agreed the item existed;
  `verify` asks the Keychain and measures the length without reading the value.
- A path with nothing to report says that it checked, so success is distinguishable from a dropped
  flag.

### Known defects shipped open

- `LAF-58`: a tag that existed before a run keeps its name through an undo and points at what the run
  built. The earlier binding was never recorded. Named in the undo review before consent.
- `LAF-63`: credential redaction misses namespaced names — `GITHUB_TOKEN=…` is printed **and
  persisted** in full — found while building this release.
- The rest, with dispositions, in the residue register.

## 2.5.0 — 2026-08-14

A setup recipe can build from the package it belongs to. An MCP server that has to be built on the
machine it runs on was not expressible: a package could carry a `Dockerfile` and nothing could say
*build these bytes*, so a maintainer either published an image every consumer could reach or wrote a
`SETUP.md` and hoped. This release adds the primitive — a private writable copy of a package-relative
subtree — the two modules that use it, and the module reference AART had never written. Nothing is
pushed, and no code path could push. Minor: no command, flag, field, document format, or install
effect changes, and the v13 schema freeze carries protocol versions identical to v12, differing in
exactly one input, `agent_artifacts/setup.py`, which is the module catalog and not a parsed field.

The live acceptance run for this release then found that none of it was reachable, in this release or
any before it, and that fix is the *Fixed* entry below.

### Added

- `docker.build@1`: builds one local image from a package-relative context. The tag is derived,
  `aart/<type>/<name>:<version>`, and a recipe declaring its own is refused — which is what lets
  `payload/mcp.json` name the image before it exists and gives rollback a rule it can hold. The
  reviewed argv is what executes, the receipt records the context digest, the tag, the image id and
  whether the tag pre-existed, and rollback removes a tag this run created and leaves one that was
  already there. One build per recipe, refused at parse time, because "the context" is a definite
  article.
- A recipe can name a subtree of its own package to be read. AART copies it into a private `0o700`
  directory under the data root, builds there, and removes it when the run ends — after success,
  after failure, and after a consumer declines. **The package is never written to**, held by the
  store's object digest rather than by a file comparison. A symlink in the subtree is refused, as
  everywhere else in AART, and the path is resolved at plan time so the review already names what
  will be read.
- `trust-store.export-certificates@1` and the `trust-store` capability, distinct from `keychain`
  because reading a public certificate list is a materially smaller claim than credential-store
  access. It writes a PEM bundle into the build context and nowhere else; a substring matching
  nothing fails and names it; an export that would overwrite a file the package ships is refused; and
  an export without a build, or ordered after it, is refused at parse time.
- The security baseline reads `Dockerfile`, `Containerfile`, and `*.dockerfile`, extracting `RUN`
  instructions and rejoining `\` continuations first, so `curl … | sh` is seen whole. Two rules for
  the new capabilities, `setup-capability-docker-build` (high) and `setup-capability-trust-store`
  (medium), keep the distinction the release draws instead of reporting both as unknown. The ruleset
  revision is `baseline-v1.1`, so evidence recorded under the old rules is reported stale rather than
  silently reused.
- `docs/protocol/setup-recipe-v2.md`: the first module reference AART has had — all ten modules, all
  capabilities, what the review shows, and the manual command for each. A test asserts that every
  module and capability appears there, and another feeds the worked recipe to the parser a consumer
  uses.
- `docs/design/DESIGN-setup-build-context.md`, `docs/plan/PLAN-setup-build-context.md`, and
  `docs/testing/PROGRESS-live-acceptance-setup-build.md` — the design, the work-package record, and
  the live acceptance ledger for this release, the last written during the run rather than after it.

### Fixed

- **A registry index published capabilities no consumer could match, so setup planning refused every
  recipe beyond a keychain-only one.** The index carried the author's declared vocabulary
  (`filesystem`, `docker`) while the consumer recomputed the policy vocabulary (`managed-file`,
  `docker-build`) and required equality. Both vocabularies remain, because they say different things;
  one function now decides what a recipe's steps need, the index publishes that, the consumer
  recomputes it from the same bytes, and the gate detects a tampered index instead of refusing
  everything. Pre-existing in every release that had the check. **A registry must re-run
  `registry build` on `2.5.0` and move the AART ref its CI pins in the same change**: a committed
  index passes `registry validate --strict --frozen` under `2.5.0` or under `≤2.4.0` and never both.
  Consumers are unaffected in both directions, because a consumer recompiles the index from the
  source snapshot rather than trusting the committed one.

### Changed

- `docs/configuration/config-policy-v1.md` states that `allowed_setup_capabilities` is written in the
  policy vocabulary and lists its values.
- The setup recipe reference's manual build carries the `chmod -R u+w` the object store's read-only
  modes require, and states what an older executable actually does with a new module — it refuses the
  whole source at `source add`, and an existing subscriber freezes at last-known-good — rather than
  implying a `requires_aart` floor protects anyone.

### Known defects shipped open

Eight findings from the acceptance run ship unfixed, listed with their blast radius in
[`compatibility-v13.md`](docs/release/compatibility-v13.md) and with their transcripts in the ledger.
The two that change what a consumer should do: **nothing a consumer can invoke reverses a setup that
succeeded**, though every effect's review line promises otherwise; and **an unattended keychain step
stores an empty secret and reports success**, so a secret-bearing recipe should be set up
interactively.

## 2.4.0 — 2026-08-14

Vendored copy integrity. The `2.3.0` live acceptance run found that AART verified the vendoring
*instruction* — URL, ref, subtree path, all covered by `importer.options_digest` — and verified the
*result* nowhere: `origin.input_digest` was written by every vendoring and read by nothing. This
release reads it. Minor, and every behavioural change is a refusal added: no command, flag, field,
document format, or install effect changes. The v12 schema freeze carries protocol versions
identical to v11 and differs in two inputs, both protocol prose, neither a parsed field.

### Added

- The vendored copy is checked against the origin it records. The digest of the taken subtree is
  recomputed from the package on disk — the payload files not listed in `aart.vendor.authored` are
  exactly the copied ones — and compared with `origin.input_digest`. `registry validate --strict`
  and `registry audit` fail on a mismatch, offline, and re-locking or rebuilding does not clear it.
  It is a consistency check, not an authentication: a payload edited *and* re-digested is a
  consistent lie only the network can catch, and the release says so rather than implying more.
- `registry revendor` runs the same check **before** it opens a connection, in `--check` and `--yes`
  alike. A copy that no longer matches its record is refused with upstream never contacted and no
  drift computed from bytes already known to be untrustworthy.
- `vendor-delivery`, a check in the vendor and re-vendor review for `mcp`: installing merges the
  `server` object from `payload/mcp.json` and copies nothing, so the check states how many copied
  files are not delivered and that the assessment covered bytes no consumer of this artifact
  receives. It **fails**, and `registry audit` errors, when the descriptor's `command` or `args`
  names a file present under `payload/`, and when the descriptor declares no `server` — the shape
  `{"mcpServers": {…}}`, which parsed, loaded, installed, and merged an empty entry on `2.3.0`. The
  match is narrow by construction: only a string resolving to a file actually in the payload counts.
- `docs/design/DESIGN-vendored-copy-integrity.md` and
  `docs/plan/PLAN-vendored-copy-integrity.md`, the design and work-package record for this release.

### Changed

- `revendor`'s `up-to-date` disposition prints the line that reconciles a recorded and a resolved
  commit that differ — the normal result of vendoring one directory out of a monorepo — and says so
  differently where the ref itself has not moved. Two commits no longer sit under `up-to-date` with
  nothing to explain them.
- `docs/protocol/native-source-v1.md` tabulates, per type, the install effects, what reaches the
  consumer, and whether the payload may be referenced.
- `docs/protocol/registry-v1.md` states that a vendored copy is verified against the record it
  carries, and that `mcp` is the one type where the assessed set and the delivered set differ.
- `docs/tutorials/vendoring-v1.md`: the worked `payload/mcp.json` was wrong in both ways this
  release detects — the harness shape, launching a payload file consumers never receive — and is
  corrected. A test feeds every JSON fence in that tutorial to the function the review uses, so a
  documented example that would fail the review fails the suite.

## 2.3.0 — 2026-08-14

Registry vendoring. `2.2.0` left four residues open; this release answers the one with no small fix
— a promoted native reference is not a `requires` target — by giving a registry a way to own foreign
content instead of referencing it. Minor and additive: two maintainer commands, two audit findings,
one flag, one unreferenced module removed. The v11 schema freeze carries protocol versions identical
to v10 and differs in two inputs, both of them protocol prose, neither a parsed field.

### Added

- `aart registry vendor`: copies a subtree of any Git repository into this registry as an owned
  package pinned to a resolved commit, with `provenance.json` recording the origin. The upstream
  needs no AART markers. A vendored artifact is an ordinary owned package — no new document format,
  no protocol revision, and a valid `requires` target because the registry owns it. The subtree is
  taken whole or not at all: a repository containing a symlink anywhere cannot be acquired, and a
  symlink inside the subtree is refused. A wrapper authored beside the copy is adopted, not
  overwritten.
- `aart registry revendor`: re-resolves the ref the copy was taken at and reports `up-to-date`,
  `changed`, or `unreachable`. **An upstream that cannot be read is never reported as up-to-date.**
  `--check` writes nothing and exits non-zero on drift. Applying a movement requires the version the
  maintainer states, because upstream declares no version this registry can trust.
- The security assessment runs over the exact bytes a vendoring would write — copied payload and
  authored wrapper alike — and its findings are rendered in the review before Finalize, with the
  attestation committed beside the package. Findings do not block the action; the review states that
  a successful vendor reports what was copied and is not a safety claim.
- Licence discovery: a licence file at the subtree root pre-fills the manifest's `license` where the
  text settles the SPDX identifier. The GNU family is recognised but `-only`/`-or-later` is never
  guessed. `--license` states one explicitly, wins over the discovered value, and survives
  re-vendoring instead of being erased when upstream moves.
- Two `aart registry audit` findings: a vendored artifact recording no licence, and — under the new
  `--check-upstream` — vendored artifacts behind their origin, with unreachable origins reported as
  unknown. Neither fails the audit. Without the flag the audit reaches no network, so it stays a
  pure function of the committed snapshot. A hand-edited `aart.vendor` record does fail it.
- `vendor` and `revendor` as canonical maintainer actions in the text front-end, producing the same
  request value as flag mode and rendering the same review, asserted by test over one fixture.
- `docs/tutorials/vendoring-v1.md`, a worked vendoring from a marker-less monorepo through the
  assessment to re-vendoring when upstream moves.

### Changed

- `registry vendor`, `revendor`, `promote-native`, and `refresh-native` each name their counterpart
  in `--help`: the choice between referencing a package and copying it is the decision that matters.
- `docs/protocol/registry-v1.md` tabulates the three delivery modes — authored here, referenced,
  vendored — against who the consumer reaches, who owns the version, who can change delivered bytes,
  whether upstream must speak AART, and whether the identity is a `requires` target, and states in
  the protocol that vendoring moves the trust boundary into the registry.
- `docs/protocol/native-source-v1.md` states what a vendored package is on disk, including the
  namespaced `aart.vendor` extension holding the ref and the authored file list, verified against
  `importer.options_digest`.

### Removed

- `agent_artifacts/io/net.py`, an unreferenced GitHub-API helper reading `GITHUB_TOKEN` and
  `GITHUB_API_URL`. AART holds no credentials of its own and reaches remotes by running system Git;
  nothing shipped imported the module. The `validate` gate now refuses any package file naming
  either variable. The fact itself, true since `2.0.0`, is recorded in
  `docs/release/compatibility-v10-addendum.md`.

## 2.2.0 — 2026-08-14

Live acceptance v2 ran forty scenarios against `2.1.0` and filed thirteen residues; this release
closes nine — every finding whose fix does not require a major — and decides the three open
questions. Minor and additive: one flag on existing commands, one computed reconciliation status,
one refusal that the maintainer gate already enforced. The v10 schema freeze carries protocol
versions identical to v9 and differs in two inputs, neither of them a parsed field.

### Added

- `--expect <review-digest>` on every review-first consumer command, and `--expect <from>:<to>` on
  `aart source resubscribe`. Finalize proceeds only when the recomputed review still matches what
  was read; otherwise it refuses and renders the new plan in both text and JSON, so an operator who
  cannot see the new plan cannot re-authorize it. `--yes` alone keeps its exact meaning.
- `identity-changed`: an installation whose subscription is intact but whose origin now declares a
  different `source_id` reconciles as that instead of `source-unavailable` forever.
  `aart marketplace update` rebinds the record in the project that owns the installation, and the
  review field is digest-bound, so consent for one identity cannot apply another.
- A consumer-side refusal for a snapshot whose `aart-registry.json` and `aart-source.json` declare
  different identities, naming both values and both files, on the direct and local paths as well as
  registry-git. `registry validate --strict --frozen` already refused it; no registry that passes
  its own maintainer gate is affected.
- `python scripts/release.py wheel-digest`, which stamps `HEAD` into a throwaway copy, builds, and
  prints the digest of the wheel this commit publishes. Publishing that line with the release
  artifacts is a checklist step from v10 onward.

### Changed

- The plan review digest no longer moves on an unchanged workspace: `source_age_seconds` and source
  health left the digested value. Freshness is rendered instead — a `Source freshness:` line in text
  and a `source_freshness` field beside `review` in JSON, never inside it.
- Resolution failures name the layer that failed. An alias never configured, one configured but
  never synchronized, and a cold cache read under `--offline` each carry their own diagnostic and
  remediation; `artifact-not-found` survives for the case where it is true.
- `aart marketplace uninstall` plans from the durable manifest rather than resolving through the
  source, so an artifact whose subscription is gone can still be removed. **This is the one refusal
  loosened in this release**: `no-source-configured` no longer gates uninstall, because uninstall is
  not a content operation. Collections remain the exception.
- Uninstall reclaims what it emptied — the profile directories the removed record created, and the
  manifest and its lock with the last record in a scope. A directory holding anything the install
  did not put there is never removed, and a harness root such as `.claude` is never reclaimed.
  Uninstalling everything no longer leaves `.agent-artifacts/` behind.
- The `requires` refusal states its rule: the dependency must be published by this registry, with an
  identity the registry does not publish distinguished from one it references from another origin.
  The rule is unchanged and is now written down in `docs/protocol/registry-v1.md`.
- Per-source diagnostics render their remediation in text mode, not only under `--json`. A busy
  source lock reports the holder's age, pid, host, liveness, and the stale window; every
  `store-unavailable` failure carries remediation instead of a bare errno.
- `aart setup retry` and `aart setup rollback` are gone from rendered text. The retry names
  `aart marketplace setup`, which is the canonical verb; the rollback field names the artifact,
  profile, and scope to undo from the recorded receipt and states that no command does it.

### Packaging

- `agent_artifacts-2.2.0-py3-none-any.whl` is byte-reproducible: member dates come from the
  committer date stamped into the source, and member order, compression, permissions, and
  create-system are pinned rather than taken from the build platform. `SOURCE_DATE_EPOCH` is
  deliberately not read.

### Testing

- Every user-visible `aart …` mention in the shipped package — display reasons and TUI hints
  included, not only `Diagnostic.remediation` — is parsed by the real `cli.build_parser()`. Commands
  removed in `2.0.0` are legible to that guard because it reads the removals out of the
  compatibility tables, which makes the addendum part of the gate.
- Text and JSON carry the same remediation for every command family that renders both.
- Clean checkout → install → uninstall everything → `git status --porcelain` is empty, against a
  real git repository; a pre-existing profile directory holding foreign content survives.
- Two builds of one commit at different wall-clock times produce byte-identical wheels.

### Compatibility

No protocol revision, schema, store layout, or on-disk format changed, and no `requires_aart` window
needs re-authoring: `>= 2.0.0, < 3.0.0` admits this release. A `2.2.0` data root is fully readable by
`2.1.0` and `2.0.0`. See [compatibility-v10.md](docs/release/compatibility-v10.md).

## 2.1.0 — 2026-08-13

The source subscription lifecycle closes. `2.0.0` could subscribe to a source and refresh it, but
could not end a subscription or follow a source through a declared identity change. Minor, and
strictly additive: two commands are added, nothing is removed, renamed, or narrowed, and the v9
schema freeze is byte-identical to v8 in every declared input.

### Added

- `aart source remove` ends one subscription and owns both places it lives: the configuration entry
  and the managed snapshot, plus the `default_registry` pointer when it named that alias. The
  snapshot is discarded before the configuration is written, so an interrupted removal leaves a
  subscription `aart source sync` repairs rather than an unsubscribed origin whose store still binds
  an unreachable identity. Installed files and durable manifests are never touched.
- `aart source resubscribe` adopts a changed declared `source_id` at an unchanged origin and ref,
  keeping alias, kind, location, ref, and the default-registry flag — by writing no configuration at
  all. The review renders both identities, both revisions, and both snapshot digests, and finalize
  applies that exact transition or refuses, so an upstream that moves again between review and
  finalize is never absorbed silently. Resubscribing an unchanged identity is refused, naming
  `aart source sync`.
- Both commands reach the curses Sources stage on `r` and `i`, dispatching the same application
  request values as the flag-mode paths.

### Changed

- The `source sync` identity refusal names `aart source resubscribe --alias <alias>` instead of
  advising a "replace" that did not exist; the alias-already-configured and origin-already-configured
  refusals name `sync`, `resubscribe`, and `remove`. Diagnostic text only — no refusal was loosened,
  and adoption is never implicit.

### Testing

- The 2026-08-13 live-acceptance reproduction (`LAF-28`) is a test: recovery uses shipped commands
  only, with no hand-edited configuration and no directory deleted from the data root.
- Every source operation runs against a project holding an installed payload and a durable manifest,
  with the project tree compared byte for byte including `st_mtime_ns`; a managed symlink still
  resolves after its source is removed, and a durable manifest outlives its subscription and
  reconciles as `source-unavailable`.
- Every `aart …` command named in a source-area remediation is parsed by the real
  `cli.build_parser()`, so remediation text cannot drift from the shipped surface.

### Compatibility

No protocol revision, schema, store layout, or on-disk format changed, and no `requires_aart` window
needs re-authoring: `>= 2.0.0, < 3.0.0` admits this release. A `2.1.0` data root is fully readable by
`2.0.0`. See [compatibility-v9.md](docs/release/compatibility-v9.md).

## 2.0.0 — 2026-08-13

The canonical remediation: one product, one interface, one compiler before every boundary.

Major for the executable, and deliberately so. Nine top-level commands were removed, which is
exactly the criterion `1.4.0` cited when it argued for a minor. Every registry and artifact
declaring the conventional `requires_aart` ceiling of `2.0.0` must raise its window to
`>= 2.0.0, < 3.0.0` before this release will read it. See Compatibility below.

### Removed

- The legacy catalog product: `list`, `install`, `status`, `check`, `update`, `uninstall`, `setup`,
  `migrate`, and `upstream` at the top level, `registry migrate`, the legacy catalog readers and
  writers, the legacy plan/merge/execute engine, the legacy install confirmation in the TUI, and
  the legacy `--source`/`--repo` inputs. The canonical `aart marketplace` family replaces the
  lifecycle verbs; `migrate` and `upstream` have no replacement.
- The 0.1 state conversion path. A recognized 0.1 state file is now refused at the boundary with
  one typed diagnostic naming remove-and-reinstall. `docs/release/migration-v1.md` is retained as
  released `1.0.0` evidence and marked historical.

### Added

- `SETUP.md` is a valid canonical package-root file, which is what makes the setup v2 migration
  documented in `1.4.0` actually performable — see Compatibility.
- Artifact dependencies: a manifest may declare `requires`, the transitive closure is resolved
  before review, and an unsatisfied dependency fails without mutation.
- `--memory-mode` on the canonical install verb. The modes were implemented and recorded in state,
  but the only flag that set them lived on a removed command.

### Changed

- Status, check, update, prune, uninstall, review, and outcome rendering are projections of one
  snapshot-bound reconciliation plan, so finalization is never reported independently of durable
  state. A bare `update` reconciles every installation in the requested scope.
- The published index carries the setup capabilities the recipe declares, so a host missing a
  required capability is refused before a credential is requested.
- `registry test --latest-version` and `registry init --minimum-version` default to the running
  release instead of a literal `1.0.0`.

### Fixed

- A forced memory replace preserves the displaced content as a managed sidecar and restores it on
  uninstall; a missing sidecar is a typed conflict rather than a silent delete.
- The semantic digest of an artifact declaring dependencies hashed its last requirement instead of
  itself.
- An empty Git checkout is no longer classified as a registry, so a consumer is not routed into
  maintainer curation.

### Compatibility

`1.4.0` required a package-root `SETUP.md` for setup v2 while its own package validation refused
any such file, so its documented migration produced a registry `1.4.0` itself rejected. `2.0.0`
resolves the contradiction; a registry that migrated its recipes requires `2.0.0` or later.

## 1.4.0 — 2026-08-12

Typed wizard errors, a transparent setup review, and a manual route out of every installer.

Minor for the executable: no command, subcommand, or flag was removed or renamed, and every
artifact declaring the conventional `requires_aart` ceiling of `2.0.0` keeps working. The one
breaking change belongs to the independently versioned setup-recipe protocol, which now supports a
single revision — a registry publishing a `1`/`1` recipe must be rebuilt before its setup-capable
artifacts install again. See Compatibility below.

### Changed

- Every wizard stage now reports failure through one typed diagnostic algebra instead of ad-hoc
  strings, and three previously indistinguishable outcomes are now separate and separately
  actionable:
  - **Recognized AART 0.1 installation state** (`install-state-legacy`) states the exact state
    path, the detected and required schema, and previews migration for the project and user scope
    independently. It is a report, not an action.
  - **Unreadable installation state** (`install-state-invalid`) keeps the parser's own precise
    location — file, line, column — and never suggests migration, because migration cannot repair
    a file that is not valid state.
  - **A defect in AART** (`tui-stage-internal`) names the stage, the operation, and the exception
    type only. No message, traceback, subprocess output, or setup input is displayed, and the
    wizard is not restarted after one.
- A stage-blocking failure opens the scrollable record with Retry/Back/Quit; a problem local to a
  row of a still-usable list stays in the fixed pane below that list. The status bar advertises
  keys and is never the only place an error appears.
- Setup review projects each effect as a bounded record with its identity, target, capability and
  recovery, replacing the terminal-width-dependent `module: summary -> target` line.
- Every setup review and every incomplete setup outcome names the package's `SETUP.md` route, with
  a commit-pinned HTTPS URL or a contained local path. Declining automation is a supported way to
  finish; it never rolls back an installed payload, and following the manual route is never
  recorded as consent.

### Fixed

- The packaging gate now proves a built wheel reproduces the checkout's typed diagnostics, rather
  than only proving the package imports.

### Compatibility

- **Breaking — setup recipes support exactly one revision.** `schema_version` and
  `protocol_version` must both be `2`, which is what makes the package-root `SETUP.md` mandatory. A
  recipe declaring the superseded `1`/`1` pair is refused when the catalog is read, and the error
  names the migration: raise both fields to `2` and add the document. A registry that still
  publishes a `1`/`1` recipe will have those artifacts rejected at discovery until it is rebuilt.
  Artifacts without a setup recipe are unaffected.
- **No installation state is migrated, rewritten, or deleted automatically.** Recognized 0.1 state
  is reported with the explicit `aart migrate state --from 0.1 … --dry-run` preview that a person
  chooses to run; `--apply` and `--rollback` remain separate explicit steps. State written by an
  earlier version stays readable exactly as written, and an already-recorded setup receipt keeps
  its stored version fields — rejecting an old *input* is not rewriting existing *state*.
- The CLI surface is backward compatible: no command, subcommand, or flag was removed or renamed,
  and `--yes`, `--approve-setup-effects`, trust authorization, and per-effect consent behave
  exactly as before.
- Installation state stays at v2, the native source/registry protocol at v1, and reporting at v1.
  No per-artifact `requires_aart` floor is raised by this release.

## 1.3.1 — 2026-08-11

Patch release fixing the read-only JSON Review for declarative marketplace setup.

### Fixed

- `aart marketplace setup ... --json` without `--yes` now projects setup-capable reviewed items as
  pending and prepares their exact canonical setup plans from already-installed immutable records.
- Review remains non-mutating and never grants source, custom-code, or effect authorization. Missing
  installation evidence remains a planning failure rather than an inferred or executable plan.
- Artifacts without a setup recipe remain `not-required`, and the existing Finalize path is
  unchanged.

### Compatibility

- No protocol, schema, configuration, installation-state, registry, reporting, or setup-recipe
  version changes.
- Registry and per-artifact `requires_aart` floors do not rise. Existing artifacts remain visible
  and installable; `1.3.1` is needed only by agents that require a complete non-mutating setup
  Review before deciding whether to finalize it.

## 1.3.0 — 2026-08-11

Minor release making consent-based usage reporting the default for new configurations and routing
reports to the registry that advertised each installed artifact.

### Changed

- New user configurations default to consent-based `prompt` reporting. Without an explicit central
  destination, results are partitioned by the registry through which each artifact was selected.
- Each advertising registry receives only its own artifact results. Source aliases stay local,
  identical endpoints are deduplicated, direct sources are omitted, and every proposed Issue keeps
  both default-No confirmations.
- Explicit `disabled` remains silent, while `automatic` still requires one explicit destination and
  can never be enabled by a registry advertisement.

### Compatibility

- Reporting protocol v1 and its serialized payload are unchanged. Registry aliases are routing-only
  client state and are never sent to a reporting destination.
- Existing explicit `disabled`, `prompt`, and `automatic` configurations retain their meaning. A
  missing reporting section now resolves to `prompt` without requiring a central destination.
- AART `1.2.0` rejects the new prompt-without-destination configuration form, so downgrading a
  configuration written by `1.3.0` requires adding a destination or explicitly disabling reporting.
- Registry and per-artifact `requires_aart` floors are not raised by this client-side behavior.

## 1.2.0 — 2026-08-11

Minor release adding collection selection to the canonical marketplace lifecycle and advisory
runtime health over repository-supplied environment inventories.

### Added

- Canonical marketplace lifecycle commands accept `<source>/collection/<name>` and expand it to
  the exact versioned member coordinates compiled by the selected source before Review.
- The human TUI exposes compatible collections as bundle rows and explains why an incompatible
  collection cannot be selected.
- Artifacts may publish optional `com.m1f1.runtime-requirements` namespaced metadata with generic
  capability IDs and SemVer bounds.
- `aart marketplace health [COORDINATE ...] --environment PATH --json` compares those declarations
  with one explicit runtime inventory owned by the consuming repository.

### Compatibility

- The native Source/Registry Protocol remains v1. Runtime requirements use its existing opaque,
  namespaced artifact-extension boundary rather than a new compiled-index field.
- AART does not probe or install runtimes. Health is advisory, a valid report exits zero regardless
  of requirement status, and the JSON contract states `installation_blocking: false`.
- Missing environment evidence reports `unknown`; an out-of-range observed version reports
  `unsatisfied`. Neither result affects Install, Update, or Setup.
- Existing AART `1.1.1` clients ignore the advisory extension, keep artifacts visible/installable,
  and can install collection members individually.
- Registry and per-artifact `requires_aart` floors do not rise merely because this executable adds
  the shortcut and health command. A publisher changes a bound only if its payload actually invokes
  a new AART capability.

## 1.1.1 — 2026-08-11

Patch release implementing the per-artifact AART compatibility boundary documented for `1.1.0`.
The field is opt-in and manually maintained; ordinary executable changes do not raise artifact
minimums.

### Fixed

- Native artifact manifests and compiled registry index records now accept an optional
  `requires_aart` half-open version range.
- Compatibility checks reject only a selected artifact outside that range; an unrestricted
  artifact behaves exactly as before.
- Registry compilation propagates the bound deterministically, marketplace JSON exposes it when
  present, and install/security verification detects a manifest/index mismatch.

### Compatibility

- Existing artifacts omit `requires_aart` and gain no new restriction.
- A producer adds or raises the field only when that artifact actually depends on executable
  behavior unavailable in an older AART version; a patch release alone is never a reason.
- `1.1.0` did not parse this documented field. Therefore a source that begins authoring it must
  advertise `1.1.1` as its source-level parser floor, even when an individual artifact's functional
  minimum is `1.1.0`.

## 1.1.0 — 2026-08-11

Canonical non-interactive agent surface over configured sources, and a ref-aware managed source
store. No protocol, artifact, registry, or installation-state schema changed.

### Added

- `aart marketplace install/update/uninstall/status/setup`: JSON-first lifecycle over configured
  sources, with source-qualified `<source>/<kind>/<name>[@<version>]` coordinates and a deterministic
  ambiguity diagnostic instead of a guessed source.
- An explicit Review/Finalize boundary for non-interactive use: without `--yes` a command changes
  nothing, and `--yes` finalizes the digest of the review computed in the same process.
- Explicit setup authorization flags (`--authorize-untrusted-source`,
  `--authorize-custom-entrypoint`, `--approve-setup-effects`); omitting one denies rather than
  prompts.
- `aart source sync/health/doctor` for refreshing, diagnosing, and migrating configured sources
  without re-adding an existing alias.
- Ref-aware source storage keyed by `(kind, location, ref)`, so one Git origin can be tracked at
  several refs with separate mirrors, snapshots, and pointers.
- A versioned source-store layout (`<data_root>/sources/store.json`) with pure migration planning,
  atomic application, crash-resume, and explicit conflict/ambiguity refusal.

### Changed

- The repository ships no operational catalog: `skills/`, `guidelines/`, `mcp/`, `hooks/`,
  `memory/`, and `bundles/` were removed, the first-run `bundled-legacy` fallback is gone, and a
  validation gate keeps them from returning. Legacy external-checkout import is unchanged.
- Configuration uniqueness moved from Git origin to origin *and* ref. A `1.1.0` configuration using
  multi-ref sources is **not readable by `1.0.0`**; every `1.0.0` configuration still loads here.
- Reviewed source-management configuration writes are guarded by a configuration lock and an
  expected-digest compare-and-swap; a concurrent writer is refused with `config-write-conflict`
  rather than silently overwritten.
- The legacy `--source`/`--repo` warning names `aart marketplace` alongside the TUI.

### Upgrade note

The first run against a `1.0.0` source store reports configured sources as `missing` until
`aart source doctor --apply` or `aart source sync` runs; `aart source health` reports
`pending_store_migration`. Migration is never implicit.

## 1.0.0 — 2026-08-10

First stable release of AART as a standalone, zero-runtime-dependency compiler and package manager
for agent artifacts.

### Added

- Federated local/Git sources and optional public, company, team, or private registries.
- Strict native source, canonical artifact, registry entry/lock/index, configuration, reporting,
  security evidence, setup, and installation-state protocols.
- Deterministic marketplace compilation with qualified coordinates, compatibility, collections,
  provenance, locally derived trust, and collision-safe resolution.
- Durable source snapshots and a content-addressed object store with offline last-known-good,
  repair, locking, references, and garbage collection.
- Reviewed Copy and immutable managed Symlink installation for project and user scopes, including
  status, check, update, uninstall, retry, rollback, and explicit typed outcomes.
- Source-aware User and Maintainer TUI workflows with persistent basket/back navigation, health,
  descriptions, security evidence, setup queues, and preview-before-finalize curation.
- Built-in deterministic legacy-catalog import, native promotion, registry maintenance, 0.1.x
  state migration, exact backup, and later-process rollback.
- Zero-dependency risk baseline, optional isolated analyzers, attestations, bundle aggregation, and
  optional policy-approved usage reporting.
- Hermetic local editable/wheel lifecycle smoke and thirteen-scenario system/fault matrix.

### Changed

- The operational marketplace is no longer packaged with the executable. The public reference
  catalog is maintained independently at `M1F1/agent-artifacts-registry`.
- A registry and default registry are optional; direct-source-only use is a first-class path.
- Legacy `--source`/`--repo` catalog use is an explicit compatibility path instead of an implicit
  package-local default.

### Compatibility

- Python 3.10 through 3.14 are release-gated; the installed runtime uses only the standard library.
- Native Source/Registry Protocol v1 is stable; canonical installation state is schema v2.
- Delivery is from a local checkout or local wheel. Nexus/PyPI publication remains future work and
  is not required by any runtime, registry, state, Copy, or Symlink contract.

See the [compatibility matrix](docs/release/compatibility-v1.md),
`migration guide`, and
[release evidence](docs/release/release-checklist-v1.md).
