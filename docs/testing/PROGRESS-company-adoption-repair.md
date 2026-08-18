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
