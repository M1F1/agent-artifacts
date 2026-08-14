# AART 2.5.0 compatibility matrix

AART `2.5.0` is a minor release over `2.4.0`. It adds two setup modules — `docker.build@1` and
`trust-store.export-certificates@1` — one capability, `trust-store`, and the primitive both need: a
recipe can now name something in its own package to *read*, and AART hands it a private writable
copy. Every `2.0.0`…`2.4.0` configuration, source store, object store, installation record,
registry, and artifact is read and written exactly as before.

It is minor rather than patch for one reason: **a registry index compiled by `2.4.0` publishes setup
capability evidence in a vocabulary `2.5.0` no longer recomputes.** Nothing that worked stops
working — the affected recipes are exactly the ones that could never be planned at all — but a
registry should re-run `registry build`. The case is under *Upgrade notes*.

| Boundary | Supported in 2.5.0 | Change from 2.4.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | unchanged | none | native tree and registry gates |
| Provenance document | v1 with `aart.vendor` | none | vendoring and integrity tests |
| Configuration schema | v1 | none — `allowed_setup_capabilities` accepts two new values | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | **two modules and one capability added**; no field, no version | setup parser and canonical setup tests |
| Setup receipts | unchanged shape | two module receipts added | setup runtime tests |
| Index setup evidence | unchanged shape | **capabilities now name what the steps need, not what the author declared** | index and vocabulary tests |
| Registry maintainer gates | unchanged commands | **a committed index is valid under `2.5.0` or under `≤2.4.0`, not both** | registry validate/build gates |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1, ruleset `baseline-v1.1` | **build files are read**; two rules added | security tests |
| Install effects | unchanged | none | installation tests |
| CLI surface | unchanged | none | CLI and e2e tests |
| Maintainer text front-end | unchanged | none | TUI parity tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is minor and not a protocol move

No document gains a field. A recipe using the new modules is a `schema_version: 2`,
`protocol_version: 2` recipe, and a `2.5.0` executable reads every existing recipe unchanged.

The v13 schema freeze differs from v12 in **one input and no protocol version**:
`agent_artifacts/setup.py`, which holds the module catalog. `schema-freeze-v13.json` and
`schema-freeze-v12.json` carry identical `protocol_versions`, and every other hashed input —
configuration, install state, capabilities, native and registry models and schemas, reporting,
security, and both protocol documents — is byte-identical. That is the machine-checked statement
that this release moves no protocol boundary.

## Added

### `docker.build@1` — an image built from the package's own bytes

A recipe may build one image locally. Nothing is pushed and AART has no way to push. The context is
a **package-relative source path** — one name directly below the package root, resolved at plan time
so the review already states what will be read — and AART copies that subtree into a private
directory under the data root, builds there, and deletes it when the run ends. The package is never
written to.

The tag is derived, not authored: `aart/<type>/<name>:<version>`. Two versions of one artifact
cannot collide, `payload/mcp.json` can name the image before it exists, and rollback knows exactly
what it is allowed to remove — a tag this run created, never one that was already there.

### `trust-store.export-certificates@1` and the `trust-store` capability

Writes the machine's matching public certificates into the build context as a PEM bundle, so a build
can trust an interception proxy that exists only on this network. Certificates only; no private key
is read and nothing is prompted for. The capability is deliberately not `keychain`: reading a
public certificate list is a materially smaller claim than credential-store access, and conflating
them would teach reviewers to discount the word.

### Build files are assessed

The security baseline now reads `Dockerfile`, `Containerfile`, and `*.dockerfile`, and extracts `RUN`
instructions — rejoined across `\` continuations — so the shell rules see `curl … | sh` as one
command rather than two halves of one. AART was about to execute bytes the assessment had never
read. Two rules are added for the new capabilities, `setup-capability-docker-build` (high: the build
file's instructions execute with network access) and `setup-capability-trust-store` (medium: the
certificates are public and no private key is exported); without them both would have been reported
as `setup-capability-unknown`, discarding exactly the distinction the new capability exists to draw.

The ruleset revision moves to `baseline-v1.1`. The rules changed and their reach changed, so the
rules digest changes, and an assessment recorded under `baseline-v1` is reported **stale** rather
than silently reused — the mechanism the evidence contract already specifies.

## Changed

### Index setup capabilities name what the steps need

A registry index publishes setup capability evidence so that a policy can refuse an artifact's setup
without reading its recipe. Until this release it published the author's declaration (`filesystem`,
`docker`) while the consumer recomputed the policy vocabulary (`managed-file`, `docker-build`) and
required the two to be **equal**. They cannot be, so setup planning refused every recipe beyond a
keychain-only one — in `2.4.0`, and in every release that had the check.

Both vocabularies remain, because they say different things: an author declares what a recipe
touches, an organization decides what it will allow. What changed is that the index now publishes
the second one, the consumer recomputes the same table from the same bytes, and the gate compares
like with like — so it detects a tampered index instead of refusing everything. The mapping is
tabulated in [`setup-recipe-v2.md`](../protocol/setup-recipe-v2.md).

## Upgrade notes

1. **Rebuild the registry index, and move the AART pin that validates it.** An index compiled by
   `2.4.0` or earlier carries declared-vocabulary capabilities.
   `aart registry build --source . --yes` on `2.5.0` republishes it, and setup then plans for recipes
   that never could: `docker.pull@1`, `command.verify@1`, and every managed-file module. Two
   consequences, and they differ by audience:

   - **A registry maintainer must rebuild, and cannot straddle.** `registry validate --strict
     --frozen` on `2.5.0` fails a not-yet-rebuilt index with `compiled index disagrees with owned
     package <identity>` for every artifact whose recipe needs more than `keychain` — a registry that
     passed on `2.4.0` fails here. Rebuilding fixes that and inverts it: the rebuilt index fails the
     same check under `2.4.0` and under `2.0.0`. **A committed index is valid under one side or the
     other, never both.** If your registry CI pins an AART ref, the rebuild and the pin must move in
     one change.
   - **A consumer is unaffected in both directions**, because a consumer recompiles the index from
     the source snapshot rather than trusting the committed one. Verified: a `2.4.0` consumer adds a
     `2.5.0`-rebuilt registry, syncs, lists every artifact `healthy`, and installs one — reaching the
     same `Setup: planned=0, failures=1` it always reached on `2.4.0`. And a `2.5.0` consumer reading
     a stale index refuses that artifact's *setup* with `compiled setup recipe, platform, or
     capability evidence does not match the object`, which is exactly what it did before the upgrade,
     for the same artifacts. Nothing that worked stops working for anyone installing artifacts.

   A keychain-only recipe is unaffected everywhere, because both vocabularies agree there.
2. **Publishing an artifact that uses the new modules withholds the whole registry from older
   consumers.** A recipe is parsed while a source snapshot is validated, before any artifact-level
   bound is read, so a `requires_aart` floor does not protect anyone. On `2.4.0`, `source add`
   refuses the registry (`unknown or unsupported setup module 'docker.build@1'`), and a consumer
   already subscribed keeps their last-known-good snapshot — `source sync` fails with `unknown
   capabilities: trust-store`, and everything they already had stays installable. Plan the rollout
   around consumer upgrades, not around the version window.
3. **Assessment evidence recorded under `baseline-v1` resolves as stale.** The rules digest is part
   of the attestation's cache identity, so a `2.5.0` consumer marks a `2.4.0` registry's attestations
   stale and reports the raised risk that goes with unrefreshed evidence. Nothing is refused for it —
   risk is reported, not gated — and `registry build` on `2.5.0` refreshes it, which is the same
   remedy as note 1. A re-assessed package containing a Dockerfile may now show findings it did not
   before, because the file is now read.

## What did not change

No protocol revision, no schema, no store layout, no on-disk format, no consent semantics, no
install effect, and no command or flag. Without `--yes` every action still stops after Review and
changes nothing; setup effects are still declined unless `--approve-setup-effects` is given; AART
still never commits or pushes a maintainer checkout. Setup process steps still run with a minimal
environment and no `HOME`.

## Known defects shipped with this release

The live acceptance run for this release walked both installation routes end to end on a real
machine and recorded eleven findings, [`PROGRESS-live-acceptance-setup-build.md`]
(../testing/PROGRESS-live-acceptance-setup-build.md). One (`LAF-51`) is fixed above; two
(`LAF-56`, `LAF-60`) were documentation and are corrected. The rest ship open, and a consumer should
know them:

- **Nothing reverses a setup that succeeded** (`LAF-53`), though every effect's review line says
  `removes only changes created by this run`. `marketplace uninstall` removes the harness entry and
  reports `setup skipped`; the image tag, the Keychain item and the shell block remain. Undo them
  from the receipt, which records exactly what was done.
- **A pre-existing tag keeps its name and loses its binding** (`LAF-58`). Rollback does not delete a
  tag that already existed — and does not restore what it pointed at either.
- **The setup review is not printed by any CLI path** (`LAF-54`); it is complete under `--json`.
  Setup failures are likewise reported as counts (`LAF-52`), and a failing build's transcript is
  truncated from the front, so the failing instruction is cut off (`LAF-59`).
- **An unattended Keychain step stores an empty secret and reports success** (`LAF-55`).
  `security add-generic-password -w` with no terminal exits 0 having stored nothing. Run setup
  interactively, or set the value yourself and re-run.
- **A killed run leaves its working copy** (`LAF-61`) under `<data-root>/.agent-artifacts/setup-runs/`.
  Public certificates at mode `0600`; nothing sweeps it.
- **The two routes agree on contents and not on image identity** (`LAF-57`): a hand build and an AART
  build produce the same files and different digests.

## Downgrade

A `2.5.0` data root is fully readable by `2.4.0`…`2.0.0`. The only new thing written is a working
directory that is deleted with the run. The asymmetry is in the registry: a registry that publishes
an artifact using the new modules is refused by older executables, as described above.

## `requires_aart` windows

A registry or artifact declaring `min_inclusive: "2.0.0"`, `max_exclusive: "3.0.0"` admits this
release unchanged. An artifact whose recipe uses `docker.build@1` or
`trust-store.export-certificates@1` should declare `min_inclusive: "2.5.0"` — it is true, and it
documents the requirement — while knowing that the field is not what protects an older consumer.

## Published wheel

`agent_artifacts-2.5.0-py3-none-any.whl` is byte-reproducible: rebuilding the tagged commit anywhere
produces the same sha256, not merely the same member contents. The expected digest is published with
the release artifacts rather than committed, because it is a property of the tagged commit and
cannot live inside it. See [wheel-reproducibility-v1.md](wheel-reproducibility-v1.md).
