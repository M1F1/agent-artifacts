# AART 2.5.0

An MCP server that has to be built on the machine it runs on could not be shipped as an artifact.
The pieces were all there — a package can carry any files, `docker.pull@1` can fetch an image, the
recipe format has a review and a manual route — and none of them let a recipe say *build the bytes
in this package*. So a maintainer either published an image to a registry every consumer could
reach, or wrote a `SETUP.md` and hoped.

This release makes that artifact expressible: a package carries its own `Dockerfile`, setup builds a
local image from the package's own bytes, and a corporate CA that exists only on the installing
machine is exported into the build so the build can get through the proxy in front of it. Nothing is
pushed, and AART has no code path that could push.

## A recipe can name the package it ships in

```json
{
  "use": "trust-store.export-certificates@1",
  "subject_contains": "Example Corp Root CA",
  "output": "company-ca.pem"
},
{
  "use": "docker.build@1",
  "context": "payload",
  "dockerfile": "Dockerfile"
}
```

`context` is a package-relative name — one segment, directly below the package root, resolved when
the plan is made rather than when it runs, so the review already states what will be read. AART
copies that subtree into a private directory under the data root, lets the export write into the
copy, builds there, and removes it when the run ends: after success, after failure, and after a
consumer declines.

**The package itself is never written to.** The proof in the suite is not a file comparison but the
store's object digest, unchanged by a run that materialized a context, wrote a certificate into it,
and built an image from it.

The tag is derived, never authored: `aart/<type>/<name>:<version>`. That is what lets
`payload/mcp.json` name the image before the image exists, keeps two versions of one artifact from
colliding, and gives rollback a rule it can hold — remove a tag this run created, leave one that was
already there.

## A certificate is not a secret

Reading the machine's trust store is its own capability, `trust-store`, deliberately not `keychain`.
Reading a public certificate list is a materially smaller claim than credential-store access, and
conflating the two would teach a reviewer to discount the word. This is what the two effects look
like in the review a consumer approves:

```
1. Export certificates into the build context
   target      company-ca.pem inside the build context
   capability  trust-store
   recovery    removes only changes created by this run
   details     required tool: /usr/bin/security; reads public certificates from the login and
               System keychains, exports no private key, and writes only into the build context
2. Build a local Docker image from this package
   target      aart/mcp/atlassian:1.4.0
   capability  docker
   recovery    removes only changes created by this run
   details     required tool: docker; runs the instructions in Dockerfile with network access,
               from a copy of /registry/mcp/atlassian/payload; the image stays on this machine
```

A substring that matches nothing is a failure that names the substring, not an empty bundle and a
build that fails four steps later at `COPY` with a message about a cache key. An export that would
overwrite a file the package ships is refused, so a maintainer's own `company-ca.pem` is never
silently replaced by whatever the machine held after the assessment had already read the shipped
one. The export must come before the build; a recipe that inverts them is refused at parse time
rather than quietly producing an image without the CA.

## The assessment reads the file the installation executes

A `Dockerfile` was ordinary unreadable bytes to the security baseline while being exactly the bytes
setup was about to execute. It is now scanned: `RUN` instructions are extracted and rejoined across
`\` continuations first, so `curl … | sh` is seen as one command rather than two halves of one.
Everything that is not `RUN` describes the resulting container and stays ordinary text.

The ruleset revision is `baseline-v1.1`, so an assessment recorded under the old rules is reported
**stale** rather than silently reused.

## The modules are written down

There was no module reference. The ten setup modules existed in a Python dict and were described in a
design document. [`docs/protocol/setup-recipe-v2.md`](../protocol/setup-recipe-v2.md) is now the
reference a maintainer can write a recipe from — every module, every capability, what the review
shows, and the manual command that does the same thing by hand. A test asserts that every module and
every capability appears there, so neither can grow silently, and the worked recipe in it is fed to
the real parser by another test.

## The part that had never run

This release's live acceptance pass walked both installation routes on a real machine, against a real
Docker daemon and a real keychain. The first scenario failed, and not for anything this release
added.

A registry index publishes a recipe's capabilities so a policy can refuse an artifact's setup without
reading it. It published the *author's* declaration (`filesystem`, `docker`) while the consumer
recomputed the *policy* vocabulary (`managed-file`, `docker-build`) and required the two to be
**equal**. They cannot be. Every recipe beyond a keychain-only one was refused with
`Setup: planned=0, failures=1` and a reason visible only under `--json` — in `2.4.0`, and in every
release that had the check.

Both vocabularies still exist, because they say different things: an author declares what a recipe
touches, an organization decides what it will allow. What changed is that one function now decides
what a recipe's steps need, the index publishes that, the consumer recomputes it from the same bytes,
and the gate compares like with like — so it detects a tampered index instead of refusing everything.

The guided route was then re-run end to end on an unpatched wheel. It reaches `configured`, and the
same `context_digest` appears across three runs and two different executables.

## Upgrading

**Re-run `registry build` on `2.5.0`, and move the AART ref your registry CI pins in the same
change.** An index compiled earlier publishes the old vocabulary, and `registry validate --strict
--frozen` on `2.5.0` reports `compiled index disagrees with owned package …` for every artifact whose
recipe needs more than `keychain`. Rebuilding fixes that and inverts it — the rebuilt index fails the
same check under `2.4.0` and `2.0.0` — so **a committed index is valid under one side or the other,
never both.** Rebuilding also refreshes assessment evidence recorded under `baseline-v1`.

**Consumers are unaffected in both directions**, because a consumer recompiles the index from the
source snapshot rather than trusting the committed one. A `2.4.0` consumer adds a `2.5.0`-rebuilt
registry, lists every artifact `healthy`, and installs one exactly as before. The version split is a
registry maintainer's problem, and it is a one-command problem.

**Do not publish an artifact using the new modules until your consumers have upgraded.** A recipe is
validated when a source snapshot is validated, before any artifact-level bound is read, so a
`requires_aart` floor protects nobody. A `2.4.0` consumer refuses the *whole registry* at
`source add`; one already subscribed fails `source sync` and freezes at its last-known-good snapshot,
keeping everything they already had installable. The degradation is graceful and it is total.

Otherwise nothing moves. No command, no flag, no field, no document format, no install effect.
Contract v13 carries protocol versions identical to v12 and differs in exactly one input,
`agent_artifacts/setup.py` — the module catalog, which is not a parsed field.

## Known defects shipped open

The acceptance run recorded eleven findings. One is fixed above, two were documentation and are
corrected, and the rest ship open because fixing them is a separate decision, not because they are
unimportant:

- **Nothing a consumer can invoke reverses a setup that succeeded**, while every effect's review line
  says `removes only changes created by this run`. `marketplace uninstall` reports `setup skipped`
  and leaves the image tag, the keychain item, and the shell block. The receipt records exactly what
  was done, and undoing it is currently by hand.
- **The setup review is printed by no CLI path.** It is complete under `--json` and invisible
  otherwise, which means `--approve-setup-effects` approves a list the consumer was not shown.
- **An unattended keychain step stores an empty secret and reports success.**
  `security add-generic-password -w` with no terminal exits 0 having stored nothing, and every check
  downstream agrees the item exists. Run setup interactively.
- A failing build's transcript is truncated from the front, so the instruction that failed is cut
  off; a rolled-back build leaves a pre-existing tag pointing at the image the failed run produced;
  a killed run leaves its working copy behind; and the two installation routes agree on image
  contents while disagreeing on image ids.

They are listed with their transcripts in
[the acceptance ledger](../testing/PROGRESS-live-acceptance-setup-build.md) and summarized in
[the compatibility matrix](compatibility-v13.md).

## Verifying this release

The wheel is byte-reproducible from the tagged commit:

```sh
git checkout v2.5.0
make wheel
shasum -a 256 dist/agent_artifacts-2.5.0-py3-none-any.whl
```

Compare the result with the digest published in this release's verification section.

## Not in this release

`shell.run@1` still does not exist, and this release is the case that would most have excused it: a
build is arbitrary code by definition. It is arbitrary code inside a container, from a file the
assessment reads, under a tag AART derives — which is a different thing from a recipe that can run
anything on the host. Every module added here is a named operation with a reviewed argv.

Setup steps still run with no `HOME`, so a private base image will not authenticate. The design
warned this might prevent building at all; it does not — buildx resolves system-wide — but widening
what a setup step can see is a decision about the setup environment, not about builds, and it stays
open.

Start here: [the setup recipe reference](../protocol/setup-recipe-v2.md). See also the
[2.5.0 compatibility matrix](compatibility-v13.md) and
[release evidence](release-checklist-v13.md).
