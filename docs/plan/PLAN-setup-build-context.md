# Plan: a setup recipe that can build from the package it belongs to

Design: [DESIGN-setup-build-context.md](../design/DESIGN-setup-build-context.md). Target `2.5.0`,
contract v13.

The acceptance case is one real artifact, `mcp/company-atlassian`: two vendored files, an authored
`Dockerfile`, a corporate CA that only exists on the consumer's machine, and an image built locally
and never published. Every package below is judged by whether that artifact gets closer to being
expressible as a recipe — and by whether its `SETUP.md` route stays equally usable.

## Guardrails

- **The object store is never written to.** Every package that touches a path must hold this; the
  test for it is a mismatched object digest, not a code review.
- **The manual route stays equal.** A module that cannot be described as a command a human can paste
  into a terminal is not finished. `SETUP.md` is mandatory and the review renders it before consent.
- **No arbitrary shell.** `shell.run@1` stays unknown at the end of this plan.
- **Stdlib `unittest`, no new dependencies.** `make quality` — all nine gates — green before each
  commit.
- **Commits say what became possible and why**, not which files moved.

## SBC-1 — a recipe can name the package, and AART hands it a copy

**Files:** `agent_artifacts/setup.py`, `agent_artifacts/setup_runtime.py`,
`agent_artifacts/model.py`

1. Add package-relative source-path validation, reusing the `custom_entrypoint` rules: relative, no
   `..`, no absolute path, no traversal. It is a distinct validator with its own error text, because
   its failures point at a different field.
2. Resolve it against the queue item's source root at plan time — never at apply time, so the review
   already names what will be read.
3. Add build-context materialization into the existing per-run directory
   (`<data_root>/.agent-artifacts/setup-runs/<plan-hash>-<random>/`): copy the declared subtree out
   of the store, `0o700`, and remove it when the run ends, including on failure.
4. The copy carries file modes but no symlinks; a symlink in the declared subtree is refused, as it
   is everywhere else in AART.

**Tests:** a path with `..`, an absolute path, and a path with a separator are each refused with the
field named; a materialized context contains exactly the declared subtree; the store's object digest
is unchanged after a run that materialized, wrote into, and removed the context; the directory is
gone after both a successful and a failed run; a symlink in the subtree is refused.

## SBC-2 — `docker.build@1`

**Files:** `agent_artifacts/setup.py`, `agent_artifacts/setup_runtime.py`

1. Register the module: capability set `docker`, `network`, `process`; fields `context` (required,
   package-relative source path) and `dockerfile` (optional, context-relative, default
   `Dockerfile`).
2. Derive the tag from identity and version — `aart/<type>/<name>:<version>` — and refuse a recipe
   that tries to declare its own. Record the derivation in the effect summary so the review shows the
   exact tag.
3. Apply: materialize the context (SBC-1), run `docker build -t <tag> -f <dockerfile> <context>`,
   capture the resulting image id.
4. Receipt: the context digest, the tag, the local image id, and whether the tag pre-existed.
5. Rollback removes the tag **only** when this run created it; a pre-existing tag is left alone and
   the receipt says why.

**Tests:** the tag is derived and a recipe-declared tag is refused; a build whose context digest is
recorded matches the digest of the materialized copy; rollback removes a tag this run created;
rollback leaves a pre-existing tag; a failing build reports the failure and removes the context; the
`docker` tool absence is reported as a missing required tool rather than a build failure.

## SBC-3 — `trust-store.export-certificates@1` and the `trust-store` capability

**Files:** `agent_artifacts/setup.py`, `agent_artifacts/setup_runtime.py`

1. Add the capability `trust-store` to `_CAPABILITIES`, distinct from `keychain` (design §5).
2. Register the module: fields `subject_contains` (required) and `output` (required,
   context-relative). It reads the system keychain via `security find-certificate -a -p`, keeps
   certificates whose subject contains the declared substring, and writes a PEM bundle into the
   materialized context.
3. It can write **only** into a context materialized by SBC-1; a recipe that declares it without a
   `docker.build@1` context is refused at parse time.
4. No match is a failure with the substring named, not an empty bundle.

**Tests:** a matching subject yields a bundle containing only matching certificates; a non-matching
substring fails and names it; `output` may not escape the context; the module is refused without a
context; nothing is written outside the run directory; the capability is reported separately from
`keychain` in the review.

## SBC-4 — a Dockerfile is assessed

**Files:** `agent_artifacts/security/baseline.py`

1. `_text_like` accepts `Dockerfile`, `*.dockerfile`, and `Containerfile`, so the existing rules read
   `RUN` lines.
2. No new rule in this package: the point is that the rules that already exist stop skipping the
   file.

**Tests:** a `Dockerfile` with `curl … | sh` produces the pipe-to-interpreter finding; one with an
embedded token produces the secret finding; a plain `Dockerfile` produces none; the `company-atlassian`
Dockerfile is scanned and is clean.

## SBC-5 — the review says what a build does

**Files:** `agent_artifacts/setup.py`

1. `_effect_identity` and `_effect_details` entries for both new modules; neither may fall through to
   the generic line (design §7).
2. The build effect's detail states that the Dockerfile's instructions are executed and names the
   required tool; the certificate effect's detail states that certificates are read and no private
   key is exported.
3. Both effects are `reversible` only where they truly are: the build is, the export is (it writes
   into a directory AART removes).

**Tests:** the rendered review for the acceptance recipe names the tag, the required tool, and both
capabilities; no effect renders the generic identity; the manual alternative is rendered before
consent for a recipe containing a build.

## SBC-6 — the worked artifact, and the documentation that makes it copyable

**Files:** `docs/protocol/setup-recipe-v2.md` (**new** — see below),
`docs/tutorials/vendoring-v1.md`, `docs/design/DESIGN-setup-installers.md`

0. **There is no module reference today.** The eight modules are defined only in
   `_MODULES` and described only in `DESIGN-setup-installers.md`, which is a design document and not
   a reference a maintainer can write a recipe from. This package writes
   `docs/protocol/setup-recipe-v2.md` covering all ten modules, not only the two added here —
   otherwise the new ones would be the only documented ones, which is worse than none being
   documented.
1. Document both new modules there: fields, capability, what the review shows, and the manual
   equivalent command for each.
2. A worked section: an artifact whose payload is partly vendored and partly authored, building a
   local image with a corporate CA — the `company-atlassian` shape, with the names generalized.
3. State the three limits from design §9 — `FROM` reaches the network, a private base image will not
   authenticate under the setup environment, and the artifact must raise its `requires_aart` floor.
4. A test asserting every module named in `_MODULES` appears in the reference document, so a module
   cannot be added without being written down.

**Tests:** the docs gate; the module-coverage test; the acceptance recipe parses, plans, and renders
from a fixture built out of the real artifact.

## SBC-7 — live acceptance: both routes, on a real machine

**This package is the completion condition for the whole plan.** Nothing here is hermetic; it runs
the real CLI against a real Docker daemon and a real keychain, and it is the only evidence that the
two routes are equivalent rather than merely both documented.

**Files:** `docs/testing/PROGRESS-live-acceptance-setup-build.md` (findings ledger, written live)

1. **Route A — guided.** `aart marketplace install` the acceptance artifact, answer the setup review,
   let the recipe export the CA, build the image, store the token, and write the shell block.
2. **Route B — manual.** From a clean machine state, follow `SETUP.md` by hand, pasting each command.
3. **Compare.** Same image tag, same image contents, same keychain entry, same managed shell block,
   same `.mcp.json` entry. A difference is a finding against `SETUP.md`, not against the recipe: the
   design claims the routes are equal and this is where that claim is falsified or held.
4. **Rollback and re-run.** Route A, rolled back, leaves no image tag it created, no keychain entry,
   and no shell block; a second install is clean, not "already configured" on top of debris.
5. **Failure paths, rehearsed deliberately:** no `docker` on `PATH`; the daemon stopped; a
   `subject_contains` that matches nothing; a Dockerfile whose `RUN` fails.
6. Findings are **recorded, not fixed mid-run**; they are analysed as clusters at the end.

**Credentials and what is mocked (agreed before the run starts):**

- **The Atlassian API token is a dummy string.** It is stored under a rehearsal-only keychain service
  and deleted afterwards. The server will fail its first real API call, which is the expected and
  recorded outcome — this run tests installation, not Atlassian.
- **The corporate CA is synthetic by default.** The run generates its own CA with `openssl` and a
  `subject_contains` that matches it, so no company certificate is read and the rehearsal is
  repeatable on any machine. A confirming pass against the real company CA is a separate, explicitly
  approved step, because reading the machine's real trust store is the maintainer's call and not a
  default.
- **The agent does not type secrets and does not drive an interactive prompt.** Where the flow
  demands a typed secret, the maintainer performs that step; everything either side of it is
  automated and recorded. If the run turns out to need a real credential, it stops and says so
  rather than improvising.

**Exit condition:** both routes complete, the comparison in step 3 holds or every difference is filed,
and the ledger records the failure paths from step 5 with their transcripts.

## SBC-8 — the `2.5.0` release commit

**Files:** `pyproject.toml`, `agent_artifacts/__init__.py`, `agent_artifacts/runtime_contract.py`,
`scripts/release.py`, `docs/release/`, `CHANGELOG.md`, `PROGRESS.md`

1. `python scripts/version.py set 2.5.0 --write`; `EXPECTED_VERSION` and
   `RELEASE_CONTRACT_VERSION = 13`.
2. `docs/release/compatibility-v13.md`, `release-checklist-v13.md`, `github-release-v2.5.0.md`, and
   the v13 schema freeze.
3. The compatibility matrix states that no existing recipe changes meaning, that an artifact using
   the new modules must declare `requires_aart` `min_inclusive: "2.5.0"`, and that an older AART
   fails closed on an unknown module.
4. `CHANGELOG.md` and `PROGRESS.md` record what became expressible and the residues left open.

**Publication is the maintainer's.** This package prepares the commit; it does not tag, push, or
release.

## Dependency graph

```
SBC-1 ──┬── SBC-2 ──┬── SBC-5 ── SBC-6 ── SBC-7 ── SBC-8
        └── SBC-3 ──┘                      │
SBC-4 ──────────────────────────────────────┘
```

`SBC-1` is the primitive everything else waits on. `SBC-3` needs a context to write into, so it
follows `SBC-1` and is independent of `SBC-2` until `SBC-5` renders both. `SBC-4` touches only the
analyzer baseline and can land at any point before `SBC-7`. `SBC-7` is the live acceptance pass and
gates `SBC-8`: the release is not prepared until both installation routes have been walked on a real
machine.

## What the plan did not anticipate

*Amended after each package lands.*

### SBC-1

- **The per-run directory was not a primitive; it was four statements inside `_custom_apply`.** The
  plan says "the existing per-run directory" as though something owned it. Nothing did. Extracting
  `new_run_directory` was a prerequisite, not a refactor, and it is now the one place the run root's
  `0o700` is decided.
- **Two run directories, two lifetimes.** The plan asks that the directory be gone after both a
  successful and a failed run. That is right for a build context and wrong for a custom entrypoint:
  a custom run directory deliberately survives, because `_rollback_receipt` writes
  `custom-receipt.json` back into it and calls the script's `rollback` phase there. So removal is
  the *context*'s contract, not the run directory's, and `materialize_build_context` returns a
  subdirectory rather than taking the run directory over.
- **`context_digest` had to land here, not in SBC-2.** The plan puts the context digest in the
  build's receipt, but the store-is-never-written claim is not testable without it, and a test that
  compares file trees by hand proves less than one digest that must not move. It ignores empty
  directories on purpose: nothing is built from a directory's existence, and counting them would
  make the digest depend on how the walk was written.
- **A one-segment name is stricter than "no traversal".** Reusing `custom_entrypoint`'s rule means a
  context must sit *directly* below the package root, so a package cannot group several contexts
  under one subdirectory. That suits the acceptance artifact, whose context is `payload`, and
  widening it later is additive; narrowing it later would not be.

## Residues this plan records and does not own

- **`inputs` accepts only `type: "secret"`.** The acceptance artifact wants to prompt for a username,
  which is not a secret; `SETUP.md` covers it. A `text` input type is a change to the prompting and
  consent surface, not to the build story.
- **Setup process steps run without `HOME`,** so the Docker CLI reads no `~/.docker/config.json`: a
  private base image will not authenticate, and this already affects `docker.pull@1`. Widening the
  environment is a decision about what AART lets a setup step see.
- **`shell.zshrc-managed-block@1` does not exist.** `shell.env-from-keychain@1` plus
  `file.managed-block@1` cover the acceptance artifact's needs; a single module that writes a shell
  block mixing literal exports and keychain lookups would be a convenience, not a capability.
- **The recipe format has no comment convention.** The real artifact carried `_comment` fields and
  every one of them was refused. Whether a recipe should be annotatable is a format question.
- **A package cannot carry an auxiliary script at its root.** `install.sh` and `TESTING.md` are
  refused by the canonical tree; they live beside the registry instead. Whether a package may ship
  documentation other than `SETUP.md` is a protocol question this plan does not open.
