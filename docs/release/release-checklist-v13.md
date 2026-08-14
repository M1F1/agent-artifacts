# AART 2.5.0 release checklist and evidence

This minor release makes one artifact shape expressible that was not: a package that carries its own
`Dockerfile`, builds a local image from its own bytes during setup, and trusts a corporate CA that
exists only on the installing machine. Two modules and one capability were added for it —
`docker.build@1`, `trust-store.export-certificates@1`, `trust-store` — along with the primitive both
need, a private writable copy of a package-relative subtree, and the module reference AART had never
written.

The live acceptance run then found that none of it could be reached: a compiled index published the
author's declared capabilities while the consumer recomputed the policy vocabulary and demanded the
two be equal, so setup planning refused every recipe beyond a keychain-only one — in `2.4.0` and in
every release that had the check (`LAF-51`). That is fixed here, and the guided route was re-run on
an unpatched wheel to prove it.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.5.0
python scripts/build_wheel.py
python scripts/release.py wheel-digest
```

The release check must pass repository/version evidence, schema freeze v13, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit, and
compatibility gates. The GitHub release must attach the wheel produced from the tagged commit, and
the release notes must carry the `sha256:<hex>  <wheel filename>` line
`python scripts/release.py wheel-digest` prints at the tag.

## Registry precondition

**None for the contract**, and two for content. A registry published on the `2.0.0` contract —
window `>= 2.0.0, < 3.0.0`, setup recipes at `2`/`2` with a package-root `SETUP.md` — satisfies
`registry test --compatibility all --latest-version 2.5.0` unchanged, and every recipe that parsed on
`2.4.0` parses here with the same meaning.

1. **Re-run `registry build` on `2.5.0`.** An index compiled earlier publishes capabilities in the
   declared vocabulary, which a `2.5.0` consumer refuses to match — the same artifacts it already
   refused, so nothing regresses, but nothing improves either until the index is rebuilt. It also
   refreshes assessment evidence recorded under `baseline-v1`, which now resolves as stale.
2. **Do not publish an artifact using the new modules until consumers have upgraded.** An older
   executable refuses the *whole source*: `source add` fails on the unknown module, and a subscriber
   already on `2.4.0` fails `source sync` on the unknown capability and freezes at last-known-good.
   `requires_aart` does not help — the recipe is parsed before any artifact-level bound is read. Both
   are stated in [compatibility-v13.md](compatibility-v13.md) under *Upgrade notes*.

## Acceptance

A recipe can name the package it ships in, and gets a copy:

- a context is one name directly below the package root; `..`, an absolute path, a nested path, and a
  non-string are each refused with the field named, and a name that would escape the package is
  refused after resolution as well;
- resolution happens at **plan time**, against the queue item's source root, so the review already
  names what will be read;
- the copy holds exactly the declared subtree, is `0o700`, keeps the executable bit, and lives under
  the run root and nowhere else; a symlink in the subtree — or a symlinked source — is refused and
  leaves nothing behind;
- the store is not written to, and the proof is a digest rather than a file-tree comparison: a run
  that materialized a context, wrote a certificate bundle into it, and built from it leaves the
  package's object digest unchanged, and that digest notices a changed mode and not only changed
  bytes;
- the copy is gone when the run ends — after success, after a failed build, and after a declined
  setup, which calls no `docker` at all.

`docker.build@1` owns what it created and nothing else:

- the tag is derived from identity and version, `aart/<type>/<name>:<version>`; a recipe that
  declares its own tag is refused, and a record carrying no version cannot be planned, because a tag
  that cannot be derived is a review that cannot be shown;
- the reviewed argv is what executes — `docker build --tag … --file Dockerfile .` — with the
  materialized copy as `.`;
- a recipe with two build steps is refused at parse time, which is what makes "the context" a
  definite article; a build that does not declare `network`, `process`, or the `docker` required tool
  is refused at parse time too;
- a missing `docker` is reported as a missing prerequisite, not as a build failure;
- the receipt records the context digest, the tag, the local image id, and whether the tag
  pre-existed; rollback removes a tag this run created and leaves a tag that existed before it;
- nothing is pushed, and AART has no code path that could push.

`trust-store.export-certificates@1` reads certificates and says so:

- the capability is `trust-store`, not `keychain`, and the review lists it separately from credential
  store access;
- the substring is the tool's own filter — `security find-certificate -c` — so the reviewed argv is
  the whole filter and no X.509 parsing enters AART;
- an export without a build, an export ordered *after* the build, and an `output` escaping the
  context are each refused at parse time; an export that does not require the `security` tool is
  refused;
- matching nothing fails and names the substring, rather than writing an empty bundle; a failing
  export leaves no half-written file;
- the export will not overwrite a file the package ships, so a maintainer's own `company-ca.pem` is
  never silently replaced by whatever the machine held after the assessment read the shipped one;
- the bundle reaches the build and never the package, and nothing outside the run directory is
  written.

The assessment reads the file the installation is about to execute:

- `RUN` instructions are extracted and rejoined across `\` continuations before the shell rules read
  them, which is the difference between seeing `curl … | sh` and seeing two halves of it; an
  instruction that is not `RUN` describes the resulting container and stays ordinary text;
- a build file's embedded token, plaintext `http`, and unpinned package install are each seen; a
  pinned install is not reported; `Containerfile` and `*.dockerfile` are read too;
- the two new capabilities have their own rules rather than falling into
  `setup-capability-unknown`, which would have discarded exactly the distinction the release draws;
- the ruleset revision is `baseline-v1.1`, so evidence recorded under the old rules is reported stale
  rather than silently reused;
- the acceptance artifact's own Dockerfile raises `unpinned-package-install`, and the test asserts
  the finding rather than weakening the rule: the pins live in `requirements.txt`, and
  `--require-hashes` is the remedy.

The review says what a build does, and the organization sees it:

- no effect falls through to the generic identity; the new modules' details say more than "nothing
  runs", while `restart.notice@1` keeps the generic detail because it genuinely runs nothing;
- the rendered review names the tag, the required tools, and both capabilities, and offers the manual
  route **before** any effect is listed;
- recovery is claimed only where it is true;
- a build declares `docker-build`, `network`, and `process` to policy; an export declares
  `trust-store`; a recipe with neither declares neither.

The documentation is executable, not decorative:

- `docs/protocol/setup-recipe-v2.md` is the first module reference AART has had; a test asserts that
  every module in `_MODULES` and every capability in `_CAPABILITIES` appears there, so neither can
  grow silently;
- every module carries a manual equivalent or states why it has none;
- the worked recipe in the reference is extracted and fed to the parser a consumer uses, so a
  documented example that would not validate fails the suite;
- the three limits are stated rather than hidden: `FROM` reaches the network, a private base image
  will not authenticate under the setup environment, and an artifact using these modules must raise
  its `requires_aart` floor while knowing what that floor does and does not protect.

The vocabulary bridge, which is what makes the rest reachable:

- one function, `planned_capabilities`, decides what a recipe needs; the index compiler and the
  consumer both call it, so the equality gate compares like with like and detects a tampered index
  instead of refusing everything;
- for a recipe using every module, what the index publishes equals what the consumer recomputes,
  asserted through the real `index_artifact_from_package`;
- a recipe that *declares* much and does nothing publishes nothing, and the two vocabularies are
  asserted to be different on purpose, so the next reader learns why the bridge exists rather than
  deleting it;
- `allowed_setup_capabilities` is documented as the policy vocabulary, with its values listed.

Live acceptance, on a real machine, both routes:

- `docs/testing/PROGRESS-live-acceptance-setup-build.md` records the run as it happened — scenario
  map, transcripts, and eleven findings, written live and analysed as clusters at the end rather than
  fixed mid-run;
- route A (guided) and route B (manual `SETUP.md`) both reach a working artifact: the same derived
  tag, byte-identical certificate and `server.py` inside both images, a byte-identical managed
  `~/.zshrc` block, the same keychain item attributes, and the same `.mcp.json` entry. Route B needed
  one command the reference did not carry (`chmod -R u+w`, `LAF-56`, now written down), and the two
  images have different **ids** for identical contents (`LAF-57`, filed rather than smoothed over);
- the certificate that only ever existed in the working copy is inside the built image — verified by
  running `openssl x509` in the container and matching the fingerprint of the CA generated for the
  run — while `setup-runs/` is empty afterwards and no `company-ca.pem` exists anywhere under the
  registry checkout or the object store;
- the failure paths were rehearsed deliberately: no `docker` on `PATH` (refused as a missing
  prerequisite before any effect ran), an unreachable daemon (a shim pointed at a dead socket, rather
  than stopping the maintainer's Docker Desktop), a `subject_contains` matching nothing (refused
  before the build starts, naming the substring), and a `RUN` that exits non-zero
  (`apply-failed-rolled-back`, no image left behind);
- after the vocabulary fix, `LAB-A-01`..`LAB-A-06` were re-run on an **unpatched** wheel in a fresh
  sandbox and recorded as a new section; the same `context_digest sha256:d7d44e24…` appears across
  three runs and two executables;
- the agent typed no secret and drove no interactive prompt. The keychain step therefore ran
  unattended, which is how `LAF-55` was found: `security add-generic-password -w` with no terminal
  exits 0 having stored an empty value. `LAB-C-03` is recorded as **pass (weakened)**, and the
  real-token pass remains the maintainer's.

Protocol and packaging:

- the v13 schema freeze carries protocol versions identical to v12 and differs in exactly one input,
  `agent_artifacts/setup.py`, which holds the module catalog and is not a parsed field;
- no document format, field, command, or flag is added, and no install effect changes;
- two builds of one commit at different wall-clock times produce byte-identical wheels;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

What was **not** loosened:

- `shell.run@1` still does not exist. Every new module is a named operation with a reviewed argv;
  arbitrary shell was refused at the start of the plan and is refused at the end of it.
- Setup process steps still run under a minimal environment with no `HOME`. The design warned that
  this might strand the Docker CLI; probed directly, buildx resolves system-wide and builds without
  `HOME`. The limitation is narrower than feared — registry credentials, not building — and it is
  recorded as a residue rather than fixed by widening what a setup step can see.

## Evidence

Design: [DESIGN-setup-build-context.md](../design/DESIGN-setup-build-context.md). Plan and
work-package record, including what each package found that the plan did not anticipate:
[PLAN-setup-build-context.md](../plan/PLAN-setup-build-context.md). The maintainer's path is
[the setup recipe reference](../protocol/setup-recipe-v2.md), with the vendoring case in
[the vendoring tutorial](../tutorials/vendoring-v1.md).

The live acceptance ledger is
[PROGRESS-live-acceptance-setup-build.md](../testing/PROGRESS-live-acceptance-setup-build.md):
`LAF-51`..`LAF-61`, the transcripts that produced them, what was mocked and what that cost, and the
five clusters they fall into.

## Residues shipped open

One cluster was fixed (`LAF-51`) and two documentation findings landed with it (`LAF-56`, the manual
route's missing `chmod -R u+w`; `LAF-60`, what an older executable actually does to a subscriber).
The rest are recorded against no package because none owns them, and the compatibility matrix lists
them for consumers:

- **Setup is not reversed by anything a consumer can invoke** (`LAF-53`), while every effect's review
  line promises `removes only changes created by this run`. Rollback exists only inside a failing
  run; `marketplace uninstall` reports `setup skipped`.
- **The setup review is not printed by any CLI path** (`LAF-54`) — complete under `--json`, invisible
  otherwise. Setup failures are reported as counts (`LAF-52`), and a failing build's transcript is
  truncated from the front, cutting off the instruction that failed (`LAF-59`).
- **An unattended keychain step stores an empty secret and reports success** (`LAF-55`).
- **A pre-existing tag keeps its name and loses its binding** after a rollback (`LAF-58`).
- **A killed run leaves its working copy** under `setup-runs/`, certificates at mode `0600`, and
  nothing sweeps it (`LAF-61`).
- **The two routes agree on contents and not on image identity** (`LAF-57`).
- Plan-level residues that own no finding: `inputs` accepts only `type: "secret"`, so a username must
  be prompted for by `SETUP.md`; setup steps see no `HOME`, so a private base image cannot
  authenticate; the recipe format has no comment convention, and every `_comment` in the real
  artifact was refused; a package cannot carry an auxiliary script or a second document at its root.
- Carried forward and still open from `2.4.0`: `LAF-45`, `LAF-47`, `LAF-43`, `LAF-49`, an owned
  non-vendored `mcp` package with a wrongly-shaped descriptor being unchecked, and
  `commands/registry.py` stamping dead `1.0.0`/`2.0.0` AART bounds on every non-`init` curation
  request. Also open: four "will not be there" wordings shipped in `2.4.0`
  (`DESIGN-vendored-copy-integrity.md`, `native-source-v1.md`, `vendoring-v1.md`,
  `curation/runtime.py`) that state a future certainty the code does not guarantee.
