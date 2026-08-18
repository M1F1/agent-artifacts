# Company adoption repair progress

Chronological execution record for the repair brief in
[`adoption-stream-repair-brief.md`](adoption-stream-repair-brief.md). The
[`residue-register.md`](residue-register.md) remains the authoritative record of finding
dispositions.

## 2026-08-18

### 02:25 CEST — baseline

- Started from clean branch `stream/company-adoption` at `6c85451`.
- Confirmed all 27 findings, `AD-01` through `AD-27`, are `open` in the residue register.
- Confirmed the fast documentation gate passes: `python3 scripts/docs_check.py`.
- Began with the setup lifecycle cluster `AD-27`, `AD-25`, and `AD-23`, following the repair
  brief's user-impact order.

### 02:32 CEST — `AD-27` and `AD-23` closed

- `AD-27`: setup persistence now accepts the setup-reference digest captured by Review and moves
  it to the newly installed object. The regression changes package bytes at the same version,
  reproduces the installation state written by an update, and runs setup twice afterwards.
- `AD-23`: install and update now report the payload transaction in their exit code. An
  unauthorizable setup queue remains visible as pending work but no longer turns a successful
  payload operation into exit `1`; the explicit setup command still owns setup failure.
- Targeted verification passed:
  `python3 -m unittest tests.marketplace_lifecycle_cli_test.SetupAuthorizationTests.test_install_and_update_exit_on_the_payload_not_an_unauthorizable_setup_queue tests.canonical_setup_application_test.CanonicalSetupApplicationTest.test_setup_moves_a_superseded_reference_and_succeeds_again_after_object_update`.
- No matching caveat was present in the adoption tutorial; its second-run warning at line 151 is
  a recipe idempotence rule, not either repaired lifecycle defect.

### 02:36 CEST — `AD-25` closed

- Setup finalization now carries the storage adapter's exact failure into the outcome instead of
  replacing it with a generic sentence.
- After compensating effects, it makes one best-effort transactional write of a failure receipt.
  Compensated steps remain visible for audit but are explicitly marked so verification makes no
  live-world claim and undo does not replay them. A second persistent write failure is also named.
- The regression injects a one-shot storage failure, proves the managed file was compensated,
  and reads the persisted failure through the shared `receipt show` service.
- Targeted cluster verification passed: `python3 -m pytest -q
  tests/canonical_setup_application_test.py tests/setup_undo_test.py tests/setup_verify_test.py
  tests/marketplace_lifecycle_cli_test.py` — 74 tests and 16 subtests.
- Checkpoint commit: `da1794b` (`Close adoption setup lifecycle findings`).

### 02:41 CEST — `AD-26`, `AD-24`, `AD-17`, and `AD-21` closed

- `AD-26`: a runtime preflight stats every managed-file target outside the deterministic plan
  hash and refuses symlinks before prompts, processes, or effects.
- `AD-24`: each Keychain prompt is preceded immediately by the declared value purpose, service,
  and account. Context goes to stderr so JSON stdout stays valid.
- `AD-17` and duplicate `RS-11`: recipe v2 accepts a distinct `text` input consumed only by
  `shell.env-from-input@1`. It is reviewed, prompted with echo, validated, shell-quoted, and written
  into a reversible owned block. Secret inputs remain Keychain-only. The protocol page and MCP
  porting tutorial now use the corrected pattern.
- `AD-21`: TUI compatibility now carries organization setup policy and distinguishes an unset
  allowlist from an explicitly empty one.
- Targeted verification passed: 144 tests and 41 subtests across setup parsing, runtime, review,
  capability vocabulary, receipts, TUI marketplace, text TUI, and curses TUI. The documentation
  gate also passes.
- The first typecheck found one narrowing error in the new text-input collector. Rewriting the set
  comprehension as an explicitly narrowed loop fixed it; the full 167-module mypy gate then
  passed.
- Checkpoint commit: `3bd1f01` (`Repair setup machine and TUI adoption paths`).

### 02:47 CEST — `AD-19`, `AD-20`, and `AD-22` closed

- `AD-19`: registry mutation refusals distinguish a directory that needs `git init` from a
  registry nested below another checkout; each diagnostic names the exact repair and paths.
- `AD-20`: MCP vendoring names the full authored `payload/mcp.json` destination when missing, and
  the inverse upstream-collision branch names the authored copy that must be removed.
- `AD-22`: the manual setup route now includes the artifact package root under the pinned commit,
  and setup policy refusals name the relevant authorization flag or organization-policy action.
- Targeted verification passed: 59 tests and 2 subtests across workspace mutation, vendoring
  projection, canonical setup application, setup review, and registry command boundaries.
- Ruff, focused mypy, and the documentation gate pass. The company tutorial contains no caveat
  matching these three repaired diagnostic defects.
- Checkpoint commit: `b0fc533` (`Repair adoption path diagnostics`).

### 02:57 CEST — `AD-16` closed

- Source freshness now compares validated origin identity, revision, and snapshot digest. Age is
  still reported but no longer decides whether a source is current.
- Effective `sync.mode` now changes behavior: `auto` synchronizes before source-bearing entry
  points project their data; `manual` performs the same comparison without publishing.
- The TUI and marketplace vocabulary separately expose `not-synchronized` (comparison completed
  and differed) and `could-not-check` (comparison could not complete).
- A new design note records the policy, lock boundary, failure semantics, and entry points. The
  company tutorial's review example now says that `healthy` is based on an origin match.
- Source, marketplace, and source-facing TUI verification passed: 326 tests and 117 subtests.
  Focused mypy, Ruff, and the documentation gate also pass.
- The first complete unit gate exposed two diagnostic tests whose cold-source fixture still used
  the default `auto` mode and therefore now synchronized successfully. Pinning those scenarios to
  `manual` preserves their intended never-synchronized condition. The full gate then passed all
  1,572 tests; full-package mypy also passes across 167 modules.

### 03:24 CEST — maintainer authoring and publishing cluster closed

- `AD-11`: vendoring accepts one regular file as a subtree, so loose memory/guideline documents
  retain pinned provenance instead of falling onto a copy-and-paste path.
- `AD-08` and `AD-05`: `registry discover` emits a durable reject-by-default candidate manifest;
  `registry vendor-batch` resolves its origin once and aggregates accepted ordinary vendor plans
  into one atomic review/finalization.
- `AD-07` and `AD-10`: collection authoring is available through the CLI and Maintainer TUI, and
  lock validates collection selectors before it writes anything.
- `AD-13`: registry initialization now writes a managed `.gitignore` for build, AART state, and all
  built-in harness destinations.
- `AD-15`: build's diagnostic now asks for a valid lock, not a committed lock.
- `AD-14`: `registry publish` plans lock/build in memory, runs validate/audit over the exact
  projection, lists every Git path, and creates one commit without pushing. There is no gate-bypass
  flag. Preview, unchanged rerun, and malformed collection behavior are regression-covered.
- Added `docs/design/DESIGN-registry-discovery-batch-publish.md`; replaced the tutorial's stopgap
  scripts and stale caveats with the shipped commands.
- Full-package mypy passes across 168 modules. The focused maintainer cluster passes 54 tests and
  9 subtests, including the new discovery, batch, publish, collection, lock, init, and TUI coverage.
- The first full unit run correctly tripped the former product invariant that no registry command
  may commit. The boundary test now permits exactly one Git commit call inside `_run_publish` and
  still forbids push everywhere and commit in the functional core/workspace adapter. The repeated
  full gate passes all 1,582 tests; Ruff, format-check, mypy, and docs-check pass as well.

### 03:35 CEST — first-contact and naming cluster closed

- `AD-01`: README now has the requested installer × source grid and separates adoption from the
  editable developer workflow. Each of the nine `pip`, `pipx`, and `uv tool` commands was executed
  in an isolated temporary environment against the local 2.6.1 wheel, the published GitHub release
  wheel, or the tagged Git repository; every installed executable printed `agent-artifacts 2.6.1`.
- `AD-02` and `AD-03`: README explains reference versus vendored ownership, provenance, integrity,
  and re-vendoring, and links the walked Tabnine company-registry tutorial instead of inlining it.
- `AD-06`: removed the unused `Bundle`/`Catalog`/`ResolvedBundle` values and renamed the live
  basket/choice/UI vocabulary to `collection`.
- `AD-18`: the live extension is `aart.runtime-requirements`; the personal namespace is rejected
  with an exact migration diagnostic rather than accepted as an alias. Current docs and fixtures
  use only the live key.
- Focused verification passes 83 tests and 20 subtests across README contracts, runtime
  requirements, the text/curses consumer TUI, wizard state, and smoke coverage. Full-package mypy,
  Ruff, docs-check, and diff-check pass. The full unit gate passes all 1,586 tests.

### 03:41 CEST — `AD-12` closed

- Distinct named memory artifacts can now share one instruction file through their existing
  name-scoped managed-block markers. Admission requires another recorded block to remain current;
  same-name marker collisions remain forbidden by install-state ownership validation.
- The real marketplace/Tabnine regression installs two memories into `TABNINE.md`, verifies both
  are current, removes either block independently, and proves the file disappears only after the
  final block is uninstalled. The tutorial's merge-by-hand workaround is removed.
- Ruff and full-package mypy pass. The first direct pytest command exposed that this checkout's
  test imports require the repository on `PYTHONPATH`; rerunning with
  `PYTHONPATH=/Users/mifi/code/agent-artifacts` passed 77 tests and 16 subtests across memory E2E,
  install-state schema, lifecycle, and install planning.

### 03:52 CEST — `AD-09` closed

- Registry initialization accepts `--usage-reporting-repository OWNER/REPOSITORY` and writes the
  service advertisement that activates its generated Issue Form/workflows. Omitting the option is
  still valid but Review now says the templates are inert and gives the exact enabling flag.
- Prompt-only route discovery retains a local reason for every rejected registry. The TUI and CLI
  show the reason only for registries represented in the completed action; disabled reporting and
  direct sources remain intentionally silent.
- Finalized marketplace CLI actions now project `interface=cli` reports. TTY prompt mode keeps two
  default-No consents, JSON returns the exact inert plan, non-interactive text never opens a
  browser, and automatic/provider failures cannot change the artifact result or exit code.
- Full-package mypy passes. Ruff/format pass, and the reporting/registry/consumer/TUI cluster passes
  93 tests and 42 subtests. Documentation now walks the authoring flag and post-install behavior.

### 03:58 CEST — `AD-04` closed; all adoption findings disposed

- Current official Tabnine documentation explicitly names `.tabnine/mcp_servers.json` at project
  scope and `~/.tabnine/mcp_servers.json` at user scope. The local Tabnine home on this machine has
  the latter with the documented `mcpServers` object and a named server; no credential values were
  printed or copied. The earlier project observation established that one IDE build also read the
  old settings-file fallback, but it is not the canonical publication contract.
- The built-in profile now targets the standalone MCP file at both scopes. A new real CLI E2E
  synchronizes a source, installs one MCP artifact into project and user scope, checks both JSON
  destinations and status, proves no `.tabnine/agent/settings.json` was created, and uninstalls the
  scopes independently.
- Ruff and full-package mypy pass. The Tabnine/profile/lifecycle cluster passes 90 tests and 29
  subtests. The company tutorial and MCP porting tutorial no longer carry the location caveat.
- Every `AD-01` through `AD-27` row is now `closed`; full quality, live acceptance, and release
  validation remain before publication.

### 04:04 CEST — full quality gate green

- `make quality` passed all nine repository gates: format-check, lint, typecheck, unit,
  integration, validate/version, coverage, packaging-check, and docs-check.
- Unit discovery passed 1,596 tests; the separate E2E discovery passed 46 tests. Coverage is
  83.19% over 26,477 statements. The zero-dependency wheel packaging check built and validated
  `agent_artifacts-2.6.1-py3-none-any.whl`.
- No regression or gate bypass was required. The next phase is a wheel-installed live acceptance
  walk in fresh repositories/HOME directories, followed by the new release contract and release
  process rather than reusing the already-published `2.6.1` evidence.

### 04:06 CEST — release series and contract selected

- Selected stable `2.7.0` and release contract v16. This is a minor release because the stream adds
  public `registry collection`, `discover`, `vendor-batch`, and `publish` commands, a registry-init
  reporting option, and a setup recipe capability; reusing the immutable 2.6.1/v15 evidence would
  have misclassified the boundary.
- Synchronized the three executable version sources, the README 3×3 installation matrix, and its
  regression. Added v16 compatibility, checklist, and GitHub release documents; v15 remains
  untouched as historical evidence. The current release documents now record the setup-text,
  shared-memory downgrade, runtime-extension rename, and Tabnine target migration boundaries.
- Updated the changelog and moved the residue register's checked-document pointers from the old
  release documents to v16. Schema freeze generation, focused release-contract verification, and
  live acceptance are next.

### 04:09 CEST — v16 verified; Tabnine upgrade path made fail-closed

- Generated schema freeze v16. It retains every v15 protocol number and changes exactly one
  normative input, `agent_artifacts/setup.py`, which owns the setup recipe and persistence changes.
  Version check, docs check, release/version tests (37 tests + 17 subtests), Ruff, and focused mypy
  are green.
- While checking the release note's Tabnine migration claim, found that a generic update could write
  a new profile destination and replace its state record without transactionally removing an old
  destination. That would orphan the old settings entry, so the claimed automatic move was false.
- Update planning now detects any recorded effect locator absent from the replacement record and
  returns a conflict with exact `marketplace uninstall` then `marketplace install` commands. It
  performs no write. The canonical regression installs into a legacy MCP target, proves update
  refuses without touching either target, removes the old target through its recorded ownership,
  and installs into the current target.
- Lifecycle, Tabnine MCP, and shared-memory verification passed: 49 tests. Focused mypy, Ruff,
  docs-check, and diff whitespace checks also pass. v16 upgrade notes now state the proven
  fail-closed uninstall/reinstall route rather than the disproved automatic update claim.

### 04:13 CEST — maintainer-path live acceptance green

- Built the stamped `agent_artifacts-2.7.0-py3-none-any.whl` from checkpoint `87e56b8`; digest
  `sha256:b10a8841981e34a8d5d96bae5631409209066ea3a7077fd721c0d5b1bc17db91`. Installed it with
  `pip --no-index --no-deps` into an isolated venv; `aart --version` returned 2.7.0.
- In a fresh real Git repository and isolated HOME/XDG roots, init preview wrote nothing; finalize
  wrote the 2.7.0 compatibility floor, reporting service, workflows, templates, and ignore rules.
  Scaffold and collection finalize succeeded; collection preview remained inert.
- Discovery found three conventional shapes and rejected all by default. A real HTTPS acquisition
  vendored root `README.md` as one memory artifact. Batch vendoring acquired the same public origin
  and atomically wrote two accepted single-file memories while leaving one rejected missing path
  inert. Every owned copy carries provenance.
- Publish preview produced neither lock/index nor Git HEAD. Finalize passed all internal checks and
  committed 24 listed paths once at registry commit
  `a4c2c136df55486ce61e48afa4b196c502d8c6f4`, without pushing. An unchanged rerun created no commit.
  Post-publish `format --check`, strict frozen validate, lock/build checks, audit, and Git-clean checks
  all passed.
- Machine receipt: `/tmp/aart-270-live-87e56b8.0JrujN/maintainer-receipt.json`. A first runner
  attempt stopped only because its assertion expected the review-only `applied` field in finalized
  JSON; the product init had succeeded, and the corrected runner continued from that exact state.

### 04:15 CEST — consumer lifecycle live acceptance green

- Extended the live registry with a Tabnine MCP scaffold, published it through the same gates, and
  consumed the committed registry through an isolated local source. An attempted `--default` local
  source correctly refused because only `registry-git` may become the default; explicit
  `--no-default` synchronized it and projected all five artifacts plus the collection.
- Collection preview was inert. Finalized install wrote the skill, and repeated install plus status
  returned `no-op/current`. Two vendored memories installed as distinct named blocks in the same
  Tabnine `TABNINE.md`; both were current, removing one retained the other, and its status remained
  current.
- The MCP installed independently at project and user scope into the documented
  `.tabnine/mcp_servers.json` targets under `mcpServers`; neither scope wrote
  `.tabnine/agent/settings.json`. Repeated install and update were `no-op/current`. Removing project
  scope retained user scope, then user uninstall removed its own file.
- Final uninstalls reclaimed the remaining owned memory and skill files. Machine receipt:
  `/tmp/aart-270-live-87e56b8.0JrujN/consumer-receipt.json`.
- The first consumer runner stopped after the successful initial skill install because it expected
  `succeeded` on the deliberate repeat; the actual terminal contract was the stronger `no-op` with
  item status `current`. The resumed runner asserted that idempotent result and completed green.

### 04:22 CEST — setup, cross-version migration, freshness, and reporting live acceptance green

- A fresh setup-bearing local source used setup recipe v2 `text` input and
  `shell.env-from-input@1`. Source validation first rejected a non-canonical step id in the live
  fixture before configuration was written; renaming it to `account_env` made the source valid.
  Review named the echoed prompt and target. Finalize prompted on stderr, safely shell-quoted an
  apostrophe-containing value, and wrote one owned block.
- Repeated setup kept the managed file byte-identical and reported `already-configured`. After
  changing only `SETUP.md` while keeping artifact version 1.0.0, automatic source sync published a
  new object, marketplace update returned `changed`, setup completed without conflict, and the
  setup reference moved from object
  `sha256:d37b20bff5928e520b2916d49cd6efdbe2d43bc28a562dd3165b3972a46940ab` to
  `sha256:2a712cb96365ad14eb0ec1d1337c6c47122c7d1664d49d111454f8d69aecaa5e`. A further setup was
  `already-configured` with identical file and reference bytes. Receipt:
  `/tmp/aart-270-live-87e56b8.0JrujN/setup-receipt.json`.
- Installed the published 2.6.1 release wheel into a separate venv and used it to create a real
  Tabnine project MCP installation at `.tabnine/agent/settings.json`. The 2.7.0 wheel's update
  exited 1 with the reviewed target-migration conflict, exact uninstall/install remediation, and
  identical state/settings hashes before and after; the new target did not exist. Executing those
  two commands with 2.7.0 removed the old file, wrote `.tabnine/mcp_servers.json`, and ended
  `current`. Receipt: `/tmp/aart-270-live-87e56b8.0JrujN/migration-receipt.json`.
- Added the real public reference registry over HTTPS as `registry-git`. In manual mode, changed
  only its cached publication timestamp to epoch second 1 and compared it to the real origin. At
  age 1,787,019,737 seconds, matching source id, revision
  `f25eba97bf71c4e6a4b224f2b081a6bb7c7327f9`, and snapshot digest remained `healthy`, proving age
  is evidence rather than freshness classification at the CLI boundary.
- A finalized JSON install from that remote returned a relevant unavailable-reporting notice and
  the exact `registry init --usage-reporting-repository OWNER/REPOSITORY` remediation; it performed
  no browser effect. Receipt:
  `/tmp/aart-270-live-87e56b8.0JrujN/remote-freshness-reporting-receipt.json`.

### 04:25 CEST — final 2.7.0 quality gate green

- Re-ran the complete `make quality` after the 2.7.0 version, v16 contract, target-migration guard,
  and live-acceptance evidence were committed. All nine gates passed: format-check, lint, mypy over
  168 source files, unit, integration/E2E, validate/version, coverage, packaging-check, and
  docs-check.
- Unit discovery passed 1,597 tests; separate E2E discovery passed 46 tests. Coverage is 83.20% over
  26,492 statements. Packaging built and validated the zero-dependency
  `agent_artifacts-2.7.0-py3-none-any.whl`; version and schema freeze v16 checks passed.
- GitHub prerequisites are available: `gh` 2.92.0 is authenticated as `M1F1` with `repo` and
  `workflow` scopes; repository `M1F1/agent-artifacts` has default branch `main`. Publication now
  proceeds through branch push, draft PR, merge, release-check, tag, wheel attachment, and asset
  verification.

### 04:30 CEST — review, CI, merge, and release-check green

- Pushed checkpoint `f78932da131fc89f6319ecc0c1c2c4dc8caa5474` and opened GitHub PR
  [#93](https://github.com/M1F1/agent-artifacts/pull/93). After making it ready for review, all four
  required quality jobs passed: Python 3.10 and 3.14 for both the branch-push and pull-request runs.
- Merged PR #93 into `main` as
  `7fc12863772dad14da6605f21b19298020d3f7b6`, then verified the published branch head is its
  ancestor and fast-forwarded the local `main` to `origin/main`.
- Cloned the approved registry from its exact HTTPS origin into a fresh directory. Its clean
  `origin/HEAD` was `f25eba97bf71c4e6a4b224f2b081a6bb7c7327f9`.
- `make release-check REGISTRY=/tmp/aart-270-live-87e56b8.0JrujN/release-registry` passed all 11
  release gates: repository, schema-freeze, system-matrix, package, registry-origin,
  registry-format, registry-validate, registry-lock, registry-build, registry-audit, and
  registry-compatibility. No gate or branch protection was bypassed.

### 04:33 CEST — `v2.7.0` released and asset independently verified

- Created and pushed annotated tag `v2.7.0`; tag object
  `f534286e0fba8580c319003fb5688d8a25e251f2` resolves to merge commit
  `7fc12863772dad14da6605f21b19298020d3f7b6` locally and on `origin`.
- Rebuilt the final wheel from the detached tagged commit. The published 569,169-byte
  `agent_artifacts-2.7.0-py3-none-any.whl` has SHA-256
  `6673ae24be9894ea9310c6331521ff613815768a5a50e36b622bf3de425be2da`.
- Published the non-draft, non-prerelease GitHub release
  [`v2.7.0`](https://github.com/M1F1/agent-artifacts/releases/tag/v2.7.0) with that exact wheel and
  its digest in the release notes. Downloaded the asset again through GitHub into a fresh
  directory; its SHA-256 matched the tagged build exactly.

### 04:35 CEST — public install matrix 9/9 and stream complete

- Exercised every README installation cell against the public release in isolated environments.
  `pip`, `pipx`, and `uv tool` each passed for the freshly downloaded wheel, the GitHub release
  URL, and `git+https://github.com/M1F1/agent-artifacts.git@v2.7.0`. Every resulting executable
  returned exactly `agent-artifacts 2.7.0`; result: 9/9 pass.
- Live acceptance is green across maintainer publication, consumer lifecycle, repeatable setup,
  real 2.6.1-to-2.7.0 migration, remote-origin freshness, reporting, Tabnine project/user scope,
  and shared memory ownership. The machine receipts are named in the entries above.
- Final adoption disposition: all 27 findings `AD-01` through `AD-27` are closed. Fifty-six
  unrelated findings remain recorded (one `major`, two `high`, 32 `medium`, and 21 `low`); none
  blocks this adoption-stream release. The immutable release is public, its asset is reproducible
  and independently verified, and there is no remaining work in the requested stream.

### 08:13 CEST — `AD-04` reopened; shipped regression and override hazard recorded

- Operator review corrected the evidence hierarchy used for `AD-04`. The company Tabnine build
  reported a server from `.tabnine/agent/settings.json` as `disconnected`, which proves that it
  parsed the entry and reached a downstream runtime failure. The 2.7.0 repair wrongly demoted that
  measurement below current documentation and a different machine's user-scope file.
- Reopened `AD-04`. Filed `AD-28` for the released 2.7.0 migration onto the unproven file and the
  test that required the proven file to be absent. Filed `AD-29` for the pre-existing profile
  override loader behavior: a partial same-name override replaces the complete builtin profile.
- Audited every code change from the adoption-stream baseline `6c85451` through `v2.7.0`. No other
  builtin profile target moved. The other hard public-identifier substitution was
  `com.m1f1.runtime-requirements` to `aart.runtime-requirements`; unlike Tabnine, no contradicting
  live observation was found. The generic retired-effect update guard is wider than Tabnine but
  does not move data by itself and prevents an old owned destination from being orphaned.
- Repair scope is now explicit: restore project and user MCP files to `settings.json`, retain the
  new user scope and `mcpServers` merge shape, reverse the pinning tests and current normative docs,
  then run focused tests, complete quality, live acceptance, and a 2.7.1 patch release.

### 08:16 CEST — measured Tabnine target restored; `AD-04` reclosed

- The builtin Tabnine profile again merges project MCP entries into
  `.tabnine/agent/settings.json` and user entries into `~/.tabnine/agent/settings.json`, both at
  `mcpServers`. The 2.7.0 user-scope capability remains; no skill, guideline, hook or memory target
  changed. The generic retired-effect guard remains but its comment no longer calls the 2.7.0 move
  a correction.
- Reversed the real CLI E2E rather than relaxing it: it requires the two settings files, checks the
  entry and status at both scopes, requires both standalone files to be absent, and removes each
  scope independently. Profile and install-scope tests pin the same project/user filenames and say
  that the company-build measurement outranks documentation for other builds.
- Corrected the two current tutorials, `DESIGN-memory.md`, `DESIGN-install-scope.md`, and their plans.
  They preserve the published-doc discrepancy as an unmeasured verify item and keep the live
  `disconnected` server out of this file-target repair. Historical 2.7.0 release/progress documents
  remain descriptions of the regression that release actually shipped.
- Focused verification passed: 83 tests and 27 subtests across builtin profiles, overrides, install
  scope, real marketplace CLI Tabnine lifecycle, and canonical lifecycle. Ruff format/check,
  focused mypy, docs-check and diff whitespace checks are green. `AD-04` is closed on corrected
  evidence; released-regression `AD-28` stays open through cross-version live acceptance and the
  patch release. `AD-29` remains an explicitly separate loader finding.
