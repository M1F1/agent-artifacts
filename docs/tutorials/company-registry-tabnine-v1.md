# Standing up your first company registry, for Tabnine

From an empty Git repository to a colleague running `aart marketplace install` and finding the
skill in their `.tabnine/` directory. Every command below was executed against AART `2.6.1` before
this document was written; the outputs quoted are real. Where something was not walked, it says so.

The examples use `company` as the registry id and `tabnine` as the profile throughout. Substitute
your own registry id; keep the profile.

**What you need**

- AART `2.6.1` or later on your machine. `aart --version` must print it.
- A Git host you can push to — GitHub Enterprise, GitHub, anything reachable over HTTPS or SSH.
- Somewhere to put a new repository, and permission to create it.
- The URL of at least one existing company repository that holds material worth sharing. It does
  **not** need to know anything about AART. That is the point of most of this document.

**What AART will never do**

It never commits and never pushes. Every command below writes files into your checkout and stops.
You review the diff and commit it yourself, through whatever review your company already has. AART
also never handles credentials: it runs system Git, so if `git clone` works at your prompt, AART
works, and if it does not, fix it in Git.

---

## 1. Create the registry repository

Create an empty repository on your Git host — call it `agent-artifacts-registry` — then clone it:

```sh
git clone https://ghe.company.example/platform/agent-artifacts-registry.git
cd agent-artifacts-registry
```

If you would rather start locally and add the remote later:

```sh
mkdir agent-artifacts-registry && cd agent-artifacts-registry
git init -b main .
```

**The directory must be a Git checkout before the next step.** Run `aart registry init` anywhere
else and it refuses:

```text
error: registry mutation requires a writable local Git checkout
```

## 2. Initialize the registry

Every mutating AART command runs twice: once to show you what it would do, once with `--yes` to do
it. Look at the first output before you type the second.

```sh
aart registry init --source . --source-id company --display-name "Company AART Registry"
```

```text
Review canonical Maintainer action: init
  Workspace: /path/to/agent-artifacts-registry
  Review digest: sha256:209d2da8…
  Mutation: yes, only on Finalize
  - added: .github/ISSUE_TEMPLATE/usage-report.yml
  - added: .github/workflows/aart-registry.yml
  - added: .github/workflows/aart-usage-dashboard.yml
  - added: .github/workflows/aart-usage-validate.yml
  - added: aart-registry.json
  - added: aart-source.json
  AART will not commit or push; review the working-tree diff afterward.
```

```sh
aart registry init --source . --source-id company --display-name "Company AART Registry" --yes
```

`--source-id` is the identity every artifact coordinate starts with — your colleagues will type
`company/skill/release-evidence`. It is stable; changing it later changes every coordinate.

The marker it writes declares which AART versions may read this registry:

```json
{"requires_aart": {"min_inclusive": "2.6.1", "max_exclusive": "3.0.0"}, …}
```

The default is derived from the AART you ran, so it always contains it. Widen it with
`--minimum-version` if colleagues are on older builds — but only to a version that can actually read
what you publish.

Commit this before going further. It is the point where an empty repository becomes a registry.

```sh
git add -A && git commit -m "Initialize the company AART registry"
```

## 3. Vendor an artifact out of a repository that knows nothing about AART

This is the step that matters for adoption. Your company already has useful material — a prompt
somebody keeps pasting into Slack, a checklist in a platform-team repo, a monorepo of MCP servers.
None of it declares `aart-source.json`, and none of its owners want to be told to add one.

`registry vendor` copies a subtree of any Git repository into your registry as a package **your
registry owns**, pinned to the exact commit it was taken from, with a `provenance.json` recording
where the bytes came from.

Suppose `https://ghe.company.example/platform/shared-tools.git` has a directory
`packages/release-evidence` holding a `SKILL.md`. Review first:

```sh
aart registry vendor skill release-evidence --source . \
  --url https://ghe.company.example/platform/shared-tools.git \
  --ref main \
  --path packages/release-evidence \
  --artifact-version 1.0.0 \
  --summary "Evidence checklist for a release." \
  --profile tabnine \
  --platform darwin \
  --review-policy manual-review-v1
```

```text
  - added: artifacts/skill/release-evidence/artifact.json
  - added: artifacts/skill/release-evidence/payload/LICENSE
  - added: artifacts/skill/release-evidence/payload/SKILL.md
  - added: artifacts/skill/release-evidence/payload/references/verification-checklist.md
  - added: artifacts/skill/release-evidence/provenance.json
  - added: security/attestations/3dbd79bb….json
  - check vendor-assessment: passed
      installation risk: medium
      findings: 2
      install-effect-copy-tree (low): Installation copies a directory tree into a harness destination.
      review-missing (medium): No registry review decision is attached to this artifact.
  - check vendor-license: passed
      discovered: LICENSE: MIT
      recorded: MIT
  - check vendor-origin: passed
      origin: https://ghe.company.example/platform/shared-tools.git
      ref: main
      resolved commit: 3706c2a5a679f17a3c3d4979b840fa86bc2a13e5
      subtree: packages/release-evidence
      target: artifacts/skill/release-evidence
      declared version: 1.0.0
      payload files: 3
  warning: Vendoring copies upstream bytes into this registry and pins them to a commit; a successful vendor reports what was copied, and is not a safety claim.
  warning: This registry now owns the copy: upstream fixes do not reach consumers until it is vendored again.
```

Read the three checks before you finalize. `vendor-license` discovered `MIT` from a `LICENSE` file
in the subtree; had it found nothing, you would have to state one with `--license`. `vendor-origin`
is the pin — that resolved commit is what `provenance.json` records, and what a drift check later
compares against.

Then finalize:

```sh
aart registry vendor skill release-evidence --source . \
  --url https://ghe.company.example/platform/shared-tools.git \
  --ref main --path packages/release-evidence \
  --artifact-version 1.0.0 --summary "Evidence checklist for a release." \
  --profile tabnine --platform darwin --review-policy manual-review-v1 --yes
```

A guideline works the same way, with `guideline` as the kind:

```sh
aart registry vendor guideline branch-conventions --source . \
  --url https://ghe.company.example/platform/shared-tools.git \
  --ref main --path packages/branch-conventions \
  --artifact-version 1.0.0 --summary "How we name and merge branches." \
  --license MIT --profile tabnine --platform darwin --review-policy manual-review-v1 --yes
```

### Four things about vendoring that will bite you otherwise

1. **The URL must be HTTPS or SSH.** A local path or a `file://` URL is refused —
   `Git source location must be credential-free HTTPS/SSH`. You cannot rehearse this against a
   repository on your own disk; point it at the real remote.
2. **`--artifact-version` is yours, not upstream's.** Upstream declares no version AART can trust,
   so you state the version your registry publishes the copy under. It has nothing to do with any
   tag upstream may carry.
3. **You now own the copy.** Upstream fixing a typo changes nothing for your colleagues until you
   re-vendor. That is the trade: they get bytes that cannot move under them, you get the job of
   moving them deliberately. Section 7 is how.
4. **`--profile tabnine` is a declaration, not a filter.** It says this artifact targets Tabnine.
   List every profile the artifact genuinely supports, comma-separated
   (`--profile tabnine,claude`); an artifact that does not declare a profile cannot be installed
   into it.

### When *not* to vendor

If the upstream repository already is an AART native source — it has `aart-source.json` and its
packages sit at `<root>/<kind>/<name>` — use `registry promote-native` instead. That records a
reference and pins the commit without copying bytes, so upstream keeps ownership and your registry
stays small. `promote-native` refuses any repository that does not meet that precondition, which is
why almost everything in a normal company gets vendored.

## 3a. Vendoring a whole repository's worth of artifacts

There is no bulk vendor. `registry vendor` takes one kind, one name and one `--path`, so a monorepo
of twenty prompts is twenty invocations. Write the list down and loop over it — that keeps the list
reviewable in Git, which hand-typed commands never are.

`vendor.tsv`, tab-separated, one artifact per line:

```text
skill	release-evidence	packages/release-evidence	1.0.0	Evidence checklist for a release.
guideline	branch-conventions	packages/branch-conventions	1.0.0	How we name and merge branches.
```

`vendor-all.sh`:

```sh
#!/usr/bin/env bash
set -euo pipefail
URL="$1"; REF="${2:-main}"

while IFS=$'\t' read -r kind name path version summary; do
  [ -z "${kind:-}" ] && continue
  case "$kind" in \#*) continue ;; esac
  echo "== vendoring $kind/$name from $path"
  aart registry vendor "$kind" "$name" --source . \
    --url "$URL" --ref "$REF" --path "$path" \
    --artifact-version "$version" --summary "$summary" \
    --profile tabnine --platform darwin \
    --review-policy manual-review-v1 --yes >/dev/null
done < vendor.tsv

aart registry lock --source . --yes >/dev/null
echo "now commit the lock, then: aart registry build --source . --yes"
```

```sh
./vendor-all.sh https://ghe.company.example/platform/shared-tools.git main
```

Two artifacts took three seconds, and `validate --strict --frozen` passed afterwards. **Each
invocation clones the upstream again** — the clone is per artifact, not per repository — so budget
roughly a clone per line on a large repository.

`--yes` inside a loop skips the review step, which is the whole point of a loop and also its risk.
Run the script once without `--yes` first if the upstream is one you have not vendored before.

### Filling that list without reading the repository yourself

Writing `vendor.tsv` by hand is the slow part: on three repositories on a maintainer's disk it is
73 lines and six fields each. [`scripts/vendor_scan.py`](../../scripts/vendor_scan.py) writes it for
you. It depends on nothing but `git` and `aart`, it decides nothing, and it vendors through the real
`registry vendor` — with its review step and its three checks — one artifact at a time.

```sh
scripts/vendor_scan.py scan https://ghe.company.example/platform/shared-tools.git --out cand.json
scripts/vendor_scan.py review cand.json
scripts/vendor_scan.py vendor cand.json --source . --yes
```

`scan` clones read-only and reports directories `vendor` can take today: a directory holding
`SKILL.md` is a skill, a directory holding exactly one Markdown file is a guideline, `mcp.json` and
`hook.json` are an MCP server and a hook. It reads the summary out of the document — front-matter
`description` first — instead of inventing one, and names a lone guideline after the document rather
than the directory it happens to sit in.

Anything else it recognises it reports as a **hint** rather than a candidate: a `.mcp.json` in the
upstream's own layout, a `hooks/` directory of scripts, guidance split across several Markdown files
in one directory. These are real artifacts that `vendor` cannot take as they stand, because a
payload must be a directory in exactly the shape AART compiles. A hint says what the obstacle is and
what you would have to author. It never becomes a command that would fail.

**Project memory is the hint that will annoy you most.** `CLAUDE.md`, `AGENTS.md`, `TABNINE.md` and
their kin are the `memory` kind — under the tabnine profile a `memory` artifact installs as
project-root `TABNINE.md` — and they live at a repository root beside twenty other files. `vendor
--path` takes a directory, and a `memory` payload must be exactly one Markdown document, so a
root-level memory file satisfies neither. `upstream-superpowers-v6.2.0` carries three of them and
not one can be vendored. The scan has a command for exactly this case:

```sh
scripts/vendor_scan.py adopt candidates.json --source . --yes
```

It walks the loose documents the scan found, asks what you want to call each one, runs `aart
registry scaffold memory <name>`, and writes the upstream document in as the payload. Then lock,
commit, build, commit as usual, and it installs like anything else:

```sh
aart marketplace install company/memory/superpowers-house-rules --profile tabnine --yes
```

which lands it in project-root `TABNINE.md` inside a managed block. Under a different profile it
goes wherever that profile says — that is the point of the `memory` kind: upstream's filename is
irrelevant, the installing profile decides the destination.

**One memory artifact per project, though.** Installing a second one fails with `install
destinations contain unowned or drifted content: TABNINE.md`, and `--force` fails too with
`installation effect ownership must be unique across the manifest`. That is `AD-12`. So if you want
the upstream's house rules *and* your own, merge them into one document before you adopt it.

**What adoption costs is the provenance.** The package has no `provenance.json`, so `revendor
--check` will never tell you upstream moved and the audit's drift pass cannot see it. There is
nowhere to record the origin — `artifact.json` rejects an unknown field — so `adopt` prints an
origin line for your commit message, and that is the only place it lives until `AD-11` is settled.
If the document *is* alone in its own directory upstream, the scan picks it up as a real `memory`
candidate instead and ordinary vendoring works, provenance and all.

`review` shows one candidate at a time and takes `y`/`n`, `r` to rename, `e` to rewrite the summary,
`v` to set the version. Your answers are written back into the manifest, so the review is resumable
and lands in Git as a reviewable list — the same property the hand-written `vendor.tsv` has.

`vendor` runs `aart registry vendor` per keeper, skips what is already in the registry, and reviews
without finalizing until you add `--yes`. Scanning a checkout you already have on disk works too; it
reads the working tree but pins the vendoring to your `--ref` on `origin`, and it says so.

This is a stopgap for `AD-08`, and it lives in `scripts/` rather than in `aart` on purpose: batch
discovery that guesses on your behalf is exactly what `DESIGN-registry-vendoring.md` §10 leaves
open, and a script you can read in one sitting is the honest form of it until that is settled.

## 3b. Grouping artifacts so a colleague installs them in one command

The word for a group of artifacts is a **collection**. (If you have used AART before under a
different name: `bundle` still appears in some internal type names, but nothing in the protocol,
the registry format, or the CLI uses it. `collection` is the shipped word.)

A collection is one file under `collections/` — `registry init` already declared that root in
`aart-source.json`. There is **no `registry scaffold collection`**; write the file:

`collections/platform-baseline.json`

```json
{
  "schema_version": 1,
  "name": "platform-baseline",
  "summary": "What every platform-team repository starts with.",
  "artifacts": [
    {"type": "skill", "name": "release-evidence"},
    {"type": "guideline", "name": "branch-conventions"}
  ]
}
```

Four fields are required — `schema_version`, `name`, `summary`, `artifacts` — and `name` must be a
lowercase slug. A member selector needs only `type` and `name`.

**Then lock, commit, build, commit.** A collection is compiled into the index like everything else,
so until you do, `validate` says:

```text
error: compiled index does not match registry inputs
  remediation: resolve the authored entries again with `aart registry lock --yes`, then `aart registry build --yes`
```

```sh
aart registry lock --source . --yes
git add -A && git commit -m "Add the platform-baseline collection"
aart registry build --source . --yes
git add -A && git commit -m "Rebuild the index"
aart registry validate --source . --strict --frozen
```

### Pinning a member, and building on another collection

A selector may carry half-open version bounds, and a collection may include other collections.
Walked — this one validates, builds, and installs all three members it resolves to:

```json
{
  "schema_version": 1,
  "name": "platform-pinned",
  "summary": "The baseline, pinned to the 1.x line.",
  "artifacts": [
    {"type": "skill", "name": "release-evidence",
     "version": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}}
  ],
  "collections": ["platform-baseline"]
}
```

The compiler rejects duplicate selectors, direct self-reference, dangling members, and cycles, and
refuses a collection with no members at all. Those are compile-time failures, so a broken collection
never reaches a consumer.

Your colleague now installs the whole set with one coordinate:

```sh
aart marketplace install company/collection/platform-baseline --profile tabnine --yes
```

```text
Install outcome: succeeded
  Selected: 2; changed=2
  - company/guideline/branch-conventions@1.0.0#tabnine/project: changed
  - company/skill/release-evidence@1.0.0#tabnine/project: changed
```

Collections show up in `marketplace list` with their members spelled out, so nobody has to install
one to find out what is in it:

```text
company/collection/platform-baseline [collection] What every platform-team repository starts with. members=company/guideline/branch-conventions@1.0.0,company/skill/release-evidence@1.0.0
```

This is the piece worth building first if you want adoption. *Run one command and you have the
team's baseline* is a much easier thing to put in an onboarding document than a list of seven
coordinates.

### Writing the collection without writing the JSON

[`scripts/collection_new.py`](../../scripts/collection_new.py) composes one out of what the registry
already holds. `aart` is its only dependency, and it only runs it to check what it wrote.

```sh
scripts/collection_new.py platform-baseline --source . --summary "What every repo here starts with."
```

With no `--include` it lists every artifact in the registry — type, name, version, summary, and
whether it was vendored or written here — and asks about each one. With `--include skill/foo
--include guideline/bar` it takes your list and asks nothing. `--pin` bounds each member to its
current version up to the next major, which is what you want for a baseline and not what you want
for a topic, so it is never the default. `--nest other-collection` includes another collection whole.

Re-running with a name that already exists **edits** it: current members come back pre-selected, so
adding one artifact is a run through with one answer changed, and existing version bounds are kept
even if you leave `--pin` off. Unpinning a baseline should take a decision, not a re-run.

It reads `artifact_roots` and `collection_roots` out of your `aart-source.json` rather than assuming
the layout, and refuses a member that is not in the registry rather than writing a collection that
will fail to build. Afterwards it runs `aart registry validate` and separates the three complaints
that just mean *you authored something and have not built yet* from anything that is actually wrong.

Then publish it the normal way — lock, commit, build, commit — exactly as above.

Two caveats worth knowing. This is a stopgap for `AD-07`; the real thing is a maintainer-mode
command in the CLI and a flow in the TUI, and it does not exist yet. And `registry lock` does not
check collections at all (`AD-10`) — a malformed one passes `lock --yes` silently and is only caught
by `build`, which runs after the commit. If you hand-write a collection, run `validate` before you
commit the lock.

## 4. Write an artifact of your own

For material that has no upstream, scaffold a package and fill it in:

```sh
aart registry scaffold skill onboarding --source . \
  --summary "How we onboard a new engineer." \
  --profile tabnine --platform darwin --yes
```

```text
  - added: artifacts/skill/onboarding/artifact.json
  - added: artifacts/skill/onboarding/payload/SKILL.md
  warning: Review and complete the generated starter payload before publication.
```

Edit `artifacts/skill/onboarding/payload/SKILL.md`. The starter is a placeholder, and the warning
means it.

## 5. Lock, commit, build — in that order

This sequence has one non-obvious step, and skipping it produces the only confusing error in this
document.

```sh
aart registry lock --source .          # review
aart registry lock --source . --yes    # writes aart.lock.json
```

Then build:

```sh
aart registry build --source . --yes   # writes aart.index.json
```

**Without a lock at all, `build` refuses**, and its wording is worth reading carefully:

```text
error: registry build requires a committed aart.lock.json
  remediation: `aart registry lock --yes`, commit the lock it writes, then `aart registry build --yes`
```

It says *committed*, and it does not mean it. Measured `2026-08-17` in a fresh registry: with
`aart.lock.json` present but **untracked** — `git status` reporting `?? aart.lock.json` — `build`
compiles the index and exits `0`. The precondition is that the file exists
(`registry_commands/planning.py:1244`), not that it is in history. That is `AD-15`, and it means one
commit is enough for the whole cycle rather than the two this guide used to tell you to make.

The lock resolves what you authored; the index is what consumers read. Commit both together once the
checks in the next section pass — `validate --strict` is the one that requires committed generated
outputs, so that is where history starts to matter.

## 6. Check it before anyone else sees it

```sh
aart registry validate --source . --strict --frozen
aart registry audit --source .
```

```text
registry validate: passed
registry audit: passed
  warning: no per-object installation-risk evidence was supplied to registry audit
  warning: registry contains no external references; provenance coverage is partial
```

Both warnings are informational and expected for a young registry. The second one is not a defect:
a registry whose artifacts are all vendored copies has no external references, so there is no
external provenance to check.

Run these two in CI on every pull request. `--frozen` is what makes the check meaningful: it fails
if the committed lock and index do not match the authored content, which is exactly the mistake a
reviewer cannot catch by reading a diff.

Push, open a pull request, get it reviewed like any other repository.

### The whole cycle in one command

Sections 5 and 6 are four `aart` commands in a fixed order plus a commit, and typing them from
memory every time is how the order gets wrong.
[`scripts/registry_publish.py`](../../scripts/registry_publish.py) runs them:

```sh
scripts/registry_publish.py --source .          # shows what would happen, writes nothing
scripts/registry_publish.py --source . --yes    # runs them and commits
```

`lock` → `build` → `validate` → `audit` → `git add -A` → `git commit`. Any step failing stops it
before the commit. Before committing it prints **every file**, one per line, not a collapsed
`artifacts/`:

```text
=== committing 10 paths
  ??  .github/workflows/aart-registry.yml
  ??  aart-registry.json
  ??  aart-source.json
  ??  aart.index.json
  ??  aart.lock.json
  ??  artifacts/guideline/probe/artifact.json
  …
committed f56e56f: Publish registry: 1 artifact
Not pushed — that step is yours.
```

`-m` sets the subject; without it one is derived from the compiled index. If the tree was already
dirty when you started, it says so first and lists what it found — those files land in the same
commit, so stash anything unrelated. `--allow-audit-failure` commits despite an audit finding;
`validate` failing always stops it. It never pushes.

This is `AD-14`'s stopgap: the cycle should be a maintainer verb in the CLI and a flow in the TUI.

## 7. Keeping a vendored copy current

Ask whether upstream has moved. This writes nothing:

```sh
aart registry revendor skill release-evidence --source . --check
```

```text
      disposition: up-to-date
      origin: https://ghe.company.example/platform/shared-tools.git
      ref: main
      recorded commit: 3706c2a5a679f17a3c3d4979b840fa86bc2a13e5
      resolved commit: 3706c2a5a679f17a3c3d4979b840fa86bc2a13e5
      the ref has not moved since this copy was taken
  warning: Nothing was written; re-vendoring compares upstream and reports.
```

Three answers are possible: `up-to-date`, `changed`, or `unreachable`. An upstream AART could not
read is **never** reported as up-to-date, so this is safe to run in a scheduled job.

When it says `changed`, you decide what version the moved copy ships as:

```sh
aart registry revendor skill release-evidence --source . --artifact-version 1.1.0        # review
aart registry revendor skill release-evidence --source . --artifact-version 1.1.0 --yes
```

Without `--artifact-version` nothing is planned — deliberately. Then lock, commit, build, commit,
as in section 5.

## 8. The consumer side — what a colleague runs

They need AART installed and nothing else. In their project:

```sh
cd ~/work/some-project

aart source add \
  --alias company \
  --kind registry-git \
  --location https://ghe.company.example/platform/agent-artifacts-registry.git \
  --ref main \
  --default
```

```text
source added: company; snapshot published; default=yes
```

`source add` clones, compiles and validates the whole snapshot before it saves anything, so a broken
registry fails here rather than halfway through an install.

```sh
aart marketplace list
```

```text
source company [healthy] registry-git https://ghe.company.example/platform/agent-artifacts-registry.git
company/guideline/branch-conventions@1.0.0 [healthy] How we name and merge branches. origin=https://ghe.company.example/platform/shared-tools.git@3706c2a…:packages/branch-conventions
company/skill/release-evidence@1.0.0 [healthy] Evidence checklist for a release. origin=https://ghe.company.example/platform/shared-tools.git@3706c2a…:packages/release-evidence
```

Every row carries the origin it was vendored from, so a colleague can see where a skill actually
came from without opening the registry.

Install — review, then finalize:

```sh
aart marketplace install company/skill/release-evidence --profile tabnine
```

```text
Review consumer action
  Action: Install
  Scope: project
  Requested mode: copy
  Review digest: sha256:1ea04e2e…
  Source freshness: company is healthy; origin matched; snapshot published 7s ago
  - company/skill/release-evidence@1.0.0#tabnine/project
    trust/security: local; unknown (not-scanned)
    digests: manifest=sha256:cf9ac726…; object=sha256:6a944c55…
    destination: /home/you/work/some-project/.tabnine/agent/skills/release-evidence
Reviewed only; re-run with --yes to apply this exact plan.
```

```sh
aart marketplace install company/skill/release-evidence --profile tabnine --yes
aart marketplace install company/guideline/branch-conventions --profile tabnine --yes
```

### Where the files land for Tabnine

Walked, not quoted from a design document:

```text
.tabnine/agent/skills/release-evidence/SKILL.md
.tabnine/agent/skills/release-evidence/LICENSE
.tabnine/agent/skills/release-evidence/references/verification-checklist.md
.tabnine/guidelines/branch-conventions.md
.agent-artifacts/manifest.json
```

| Artifact kind | Where it goes in a project | Walked |
|---|---|---|
| `skill` | `.tabnine/agent/skills/<name>/` | yes |
| `guideline` | `.tabnine/guidelines/` | yes |
| `memory` | `TABNINE.md` at the project root | no |
| `mcp` | `.tabnine/agent/settings.json`, key `mcpServers` | no — **see the caveat below** |
| `hook` | `.tabnine/agent/hooks/<name>/` plus `hooks.BeforeTool`/`AfterTool`/`SessionEnd` in `.tabnine/agent/settings.json` | no |

`.agent-artifacts/manifest.json` is AART's own record of what it installed. Commit it if you want
the project's artifact set to be reproducible for the next person who clones; it contains no
secrets.

**MCP caveat, stated plainly.** AART writes MCP servers for Tabnine into
`.tabnine/agent/settings.json` under `mcpServers`. The profile's own source comment records a
disagreement with the published Tabnine documentation, which puts server *definitions* in a
standalone `.tabnine/mcp_servers.json` and uses `settings.json` for governance instead. Nobody has
verified which one a current Tabnine actually reads. **Install one MCP artifact into a scratch
project and check that Tabnine sees the server before you roll MCP artifacts out to a team.** If it
reads the other file, say so — it is a one-line change in the profile, not a redesign.

### Day-to-day

```sh
aart marketplace status --profile tabnine          # what is installed, and is it current
aart marketplace update --profile tabnine --yes    # pull newer versions from the registry
aart source sync --alias company                   # refresh the snapshot explicitly
aart marketplace uninstall company/skill/release-evidence --profile tabnine --yes
```

`list` and `status` never fetch. The snapshot only moves when someone runs `source sync` or
`update`, so a colleague's environment cannot change under them because a maintainer pushed.

Uninstall removes what it installed and nothing else — walked: after uninstalling the skill,
`.tabnine/agent/skills/release-evidence/` is gone and `.tabnine/guidelines/branch-conventions.md`,
installed separately, is untouched.

---

## What was verified, and how

Every command in sections 1–8 was executed against a wheel built from AART `2.6.1` and installed
into a throwaway virtual environment, with a sandboxed `HOME`, on `2026-08-16`. The registry, the
consumer project and the upstream repository were real Git repositories; nothing was faked,
patched, or mocked. The vendoring examples were walked against a real public repository over HTTPS,
with the same command shapes shown above.

Two things are **not** verified and are marked where they appear:

- The `memory`, `mcp` and `hook` rows of the destination table. They come from the Tabnine profile
  definition in the AART source, not from a walk.
- Everything about your Git host: URLs, credentials, and whether `git clone` works from your
  machine. AART runs system Git with a restricted environment — notably `https_proxy` is **not**
  passed through. If a repository clones at your shell prompt but not through AART, read
  [the environment AART gives Git](../configuration/git-environment-v1.md) first; behind a proxy,
  that is the entire failure.

## Where to read more

- [Registry vendoring, in depth](../design/DESIGN-registry-vendoring.md) — why vendoring exists and
  what it guarantees.
- [Keeping a vendored copy honest](../design/DESIGN-vendored-copy-integrity.md) — what drift
  detection actually checks.
- [The registry protocol](../protocol/registry-v1.md) — the file formats, if you are automating
  against them.
