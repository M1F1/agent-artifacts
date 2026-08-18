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

**What AART does with Git**

Maintainer mutations stop after writing reviewed files. The explicit `registry publish --yes`
workflow is the one exception: it runs the publisher gates and creates the listed commit. It never
pushes. AART also never handles credentials: it runs system Git, so if `git clone` works at your
prompt, AART works, and if it does not, fix it in Git.

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
aart registry init --source . --source-id company --display-name "Company AART Registry" \
  --usage-reporting-repository platform/agent-artifacts-registry
```

```text
Review canonical Maintainer action: init
  Workspace: /path/to/agent-artifacts-registry
  Review digest: sha256:209d2da8…
  Mutation: yes, only on Finalize
  - added: .gitignore
  - added: .github/ISSUE_TEMPLATE/usage-report.yml
  - added: .github/workflows/aart-registry.yml
  - added: .github/workflows/aart-usage-dashboard.yml
  - added: .github/workflows/aart-usage-validate.yml
  - added: aart-registry.json
  - added: aart-source.json
  AART will not commit or push; review the working-tree diff afterward.
```

```sh
aart registry init --source . --source-id company --display-name "Company AART Registry" \
  --usage-reporting-repository platform/agent-artifacts-registry --yes
```

`--source-id` is the identity every artifact coordinate starts with — your colleagues will type
`company/skill/release-evidence`. It is stable; changing it later changes every coordinate.
`--usage-reporting-repository` publishes the GitHub owner/repository coordinate that makes the
generated Issue Form reachable from the default prompt-only consumer flow. AART derives the host
from this registry's configured Git URL. Omit the option to keep reporting disabled; Review says
explicitly that the generated templates are inert and names the option that enables them.

The generated `.gitignore` excludes AART caches, build output, and the project/user harness targets
used by the built-in profiles (`.agent-artifacts/`, `.claude/`, `.tabnine/`, `.opencode/`, `.vibe/`,
and `.mcp.json`), so an acceptance install inside the checkout does not pollute the next publish.

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

Scan a checkout you already have and write the review manifest:

```sh
aart registry discover \
  --checkout ../shared-tools \
  --url https://ghe.company.example/platform/shared-tools.git \
  --ref main \
  --artifact-version 1.0.0 \
  --profile tabnine --platform darwin \
  --output vendor-candidates.json
```

Discovery recognises conservative conventional shapes: `SKILL.md` packages, Markdown below
`guidelines/` or `rules/`, MCP descriptors, hook descriptors, and loose harness-memory documents
such as `CLAUDE.md` and `AGENTS.md`. Every candidate starts with `"accept": false`. Review names,
summaries, versions and paths in the JSON and change only the keepers to `true`; discovery itself
never authors registry content.

Then review the one atomic batch and finalize it:

```sh
aart registry vendor-batch --source . --manifest vendor-candidates.json
aart registry vendor-batch --source . --manifest vendor-candidates.json --yes
```

The command resolves the manifest's URL and ref once, then runs the same provenance, license,
security and delivery checks as `registry vendor` for every accepted item. Either the whole reviewed
plan lands or none of it does. A loose Markdown file is a valid subtree, so project memory keeps its
upstream `provenance.json` and remains visible to `revendor --check`; no copy-and-paste adoption path
is needed.

Under the Tabnine profile a `memory` artifact installs into project-root `TABNINE.md` inside a
name-scoped managed block. Differently named memory artifacts can share that file: status checks
each block independently, and uninstalling one artifact preserves every other managed block.
Section 8 shows the consumer command.
## 3b. Grouping artifacts so a colleague installs them in one command

The word for a group of artifacts is a **collection**. Compose one only from artifacts this registry
already holds:

```sh
aart registry collection platform-baseline --source . \
  --summary "What every platform-team repository starts with." \
  --include skill/release-evidence \
  --include guideline/branch-conventions
```

The review shows the canonical `collections/platform-baseline.json` it will add. Finalize the same
digest with `--yes`, or use the Maintainer TUI's **Author collection** flow for the same name,
summary, and member selection. Both interfaces refuse unknown members before writing anything.

```sh
aart registry collection platform-baseline --source . \
  --summary "What every platform-team repository starts with." \
  --include skill/release-evidence \
  --include guideline/branch-conventions --yes
```

Collections are compiled into the index. `registry lock` validates their selectors before it writes
the lock, so a malformed or hand-written collection is rejected at the first publishing step. A
consumer can then install the baseline in one command:

```sh
aart marketplace install company/collection/platform-baseline --profile tabnine --yes
```
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

## 5. Publish one reviewed cycle

Publishing is one command. First review the exact generated files, publisher checks, commit subject,
and every path Git would include:

```sh
aart registry publish --source .
```

Then finalize the reviewed cycle:

```sh
aart registry publish --source . --yes
```

The command plans `lock` then `build` in memory, validates and audits that exact projected
snapshot, writes the reviewed `aart.lock.json` and `aart.index.json`, and creates one commit. A
failed lock, build, validation, or audit stops before the commit. It never pushes.

The lock file only has to be valid and present for a standalone `registry build`; it does not have
to be committed first. Its diagnostic and remediation say exactly that. `registry publish` removes
the ordering trap entirely and commits the lock and index together.

Every pre-existing Git change is listed alongside the generated files because finalization uses
`git add -A`. Keep unrelated work out of the registry checkout. Use `--message TEXT` to state the
commit subject; otherwise AART derives one from the compiled index. Re-running an unchanged,
already-clean registry reports that there is nothing to commit.

## 6. Check it before anyone else sees it

`registry publish` already runs strict compiled validation and the audit before committing. CI
should independently verify what history contains:

```sh
aart registry validate --source . --strict --frozen
aart registry audit --source .
```

`--frozen` fails when the committed lock or index does not match authored content. Push the commit,
open a pull request, and review it like any other repository.
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

Without `--artifact-version` nothing is planned — deliberately. Then publish the reviewed registry
cycle as in section 5.

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

After a finalized CLI or TUI action, AART offers one redacted report per registry that advertises
`usage_reporting`. Prompt mode defaults to No twice: once before showing the exact payload and once
before opening the prefilled issue. Non-interactive and JSON CLI runs never open a browser; JSON
returns the same bounded plan for automation. If the registry was initialized without the service,
AART now says why no offer appeared and names `--usage-reporting-repository` as the maintainer fix.
Reporting failures are advisory and never change the install result or exit code.

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
| `mcp` | `.tabnine/mcp_servers.json`, key `mcpServers` | yes — project and user filesystem contract |
| `hook` | `.tabnine/agent/hooks/<name>/` plus `hooks.BeforeTool`/`AfterTool`/`SessionEnd` in `.tabnine/agent/settings.json` | no |

`.agent-artifacts/manifest.json` is AART's own record of what it installed. Commit it if you want
the project's artifact set to be reproducible for the next person who clones; it contains no
secrets.

**MCP location is settled.** Current Tabnine documentation names
`.tabnine/mcp_servers.json` for a project and `~/.tabnine/mcp_servers.json` for the user-global
equivalent. The latter also exists on the maintainer's Tabnine machine with the documented
`mcpServers` shape. AART now targets those two files; the real CLI regression installs the same
server into both scopes, reports both current, and uninstalls either without touching the other.
An earlier Tabnine IDE build also surfaced a server from `.tabnine/agent/settings.json`, but that
undocumented fallback is no longer AART's publication contract.

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
