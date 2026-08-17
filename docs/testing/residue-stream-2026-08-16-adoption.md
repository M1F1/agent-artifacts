# Adoption stream — 2026-08-16

Findings raised by Michal while preparing to publish AART inside the company. They are **not** from
a live acceptance walk. They come from the reader's side: someone who has never run `aart` meeting
the documents and the first commands.

**These take priority over the register's open rows, including when they are cosmetic.** A finding
here is not competing with `LAF-15` on severity. It is competing on a different question — whether
the first hour with AART is pleasant enough that there is a second one. Adoption is the goal of this
stream and polish is the work.

Rules for this stream, same as every other:

- One id per finding, allocated here, `AD-nn`, never reused and never renumbered.
- Every id gets a row in [`residue-register.md`](residue-register.md), which stays the single place
  that says what is open. This file says where the finding came from; the register says its state.
- Nothing is repaired in the same pass that records it.

## Findings

| ID | Severity | Raised | What was seen |
|---|---|---|---|
| `AD-01` | low | `2026-08-16` | The Quick start offers exactly one way to install AART, and it is a developer's way: `python -m pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts`. A colleague who wants to *use* the tool has to clone the repository first, and then holds an editable install pointing at a checkout they will forget they are on. `pipx` and `uv` are how a Python CLI is installed today, and neither appears. Asked for: `pipx` and `uv` beside the `pip` line, **and the sources an installer can actually name** — a wheel already on disk, a wheel fetched from a GitHub release, and the repository URL directly — not only a path to a clone. Widened by the raiser the same day. |
| `AD-02` | medium | `2026-08-16` | The README never says what vendoring is. The word *vendor* does not occur in it — zero times in 219 lines — while `registry vendor` and `registry revendor` are shipped commands, `provenance.json` is a shipped document, and two designs exist for the mechanism. *Maintaining a registry* teaches `promote-native` instead, and `promote-native` is the one that requires the upstream repository to already declare `aart-source.json` — the precondition most repositories cannot meet, and the exact barrier vendoring was built to remove. A maintainer reading only the README concludes AART cannot take content from a repository that knows nothing about AART. Asked for: an explanation of vendoring in the README. |
| `AD-03` | medium | `2026-08-16` | The README links to no tutorial at all. The word *tutorial* does not occur in it, and `docs/tutorials/` holds four documents including the new [company registry walkthrough for Tabnine](../tutorials/company-registry-tabnine-v1.md). So the one document that answers *how do I actually stand this up* is reachable only by browsing the tree. Asked for: the walkthrough either in the README or linked from it — **linked**, so the README does not grow to the length of a manual. |
| `AD-05` | medium | `2026-08-16` | Vendoring a repository's worth of artifacts is one command per artifact, written by hand. `registry vendor` takes one `KIND NAME` and one `--path`; `VendorOptions.identity` is a single `ArtifactIdentity` and there is no `--all`, no manifest input, and no way to name two subtrees. Onboarding a monorepo of twenty prompts means twenty invocations, each re-cloning the same upstream — walked `2026-08-16`, two artifacts in 3 s, so a shell loop is bearable but the re-clone is per artifact, not per repository. |
| `AD-06` | low | `2026-08-16`, answering *what is a package of artifacts called* | `bundle` is dead vocabulary that still ships. The shipped name is **collection** — `collections/<name>.json`, `collection_roots` in `aart-source.json`, `<source>/collection/<name>` as an install coordinate, `[collection]` in `marketplace list`. But `model.py:243` still defines `Bundle` and `Catalog` with **zero importers anywhere in the package**, `wizard.py:64` still types a row as `Literal["artifact", "bundle", "reference"]`, `tui.py:328` types it `Literal["artifact", "bundle", "profile"]` and builds collection rows with the literal string `"bundle"`, and one operator-visible sentence at `tui.py:290` says *artifacts selected through bundles use copy semantics*. Two names for one thing, one of which the protocol has never heard of. |
| `AD-07` | medium | `2026-08-16`, walking `AD-05`; widened `2026-08-17` | A collection has no authoring command. `registry scaffold` accepts `skill`, `guideline`, `mcp`, `hook`, `memory` and refuses `collection`; the only way to publish one is to write `collections/<name>.json` by hand against a schema documented in `native-source-v1.md` §*Provenance and collections* and nowhere else. Walked `2026-08-16`: hand-written, it validates, locks, builds and installs both members in one consumer command — so the feature works and only the on-ramp is missing. **Widened by the raiser `2026-08-17`**: the ask is not a scaffold template but a maintainer-mode command that builds a collection *out of the artifacts the registry already holds* — available **in the CLI and as a flow in the TUI**, the same way every other maintainer action is. Raised to `medium`: an on-ramp missing in one interface is an inconvenience; a maintainer capability that exists in neither is a feature nobody can reach without a text editor and the protocol document. |
| `AD-10` | low | `2026-08-17`, walking `AD-07`'s stopgap | `registry lock` accepts a collection that `registry build` rejects. Measured `2026-08-17`: a `collections/broken.json` whose selector reads `{"type": "nonsense", "name": "x"}` passes `lock` in review **and** with `--yes`, both exit `0` and neither says anything; `build --yes` then refuses it with `error: selector identity is invalid` and writes no index, and `validate` reports the same. So the malformed collection survives the one step a maintainer performs *before* committing — the documented order is lock, commit the lock, build — and the error arrives after the commit that was supposed to record a good state. Nothing ships broken, because the compiler holds; the cost is the ordering. |
| `AD-08` | high | `2026-08-16`, raised as a proposal | Nothing helps a maintainer find what is worth vendoring in a foreign repository. Asked for: a scan that walks an external checkout, recognises the conventional shapes for the five kinds — `skills/`, `SKILL.md`, `guidelines/`, `hooks/`, `mcp`-ish files — and returns a list of candidate paths a maintainer then accepts or rejects one at a time, feeding the existing `vendor` command. Measured `2026-08-16` against three repositories on the raiser's disk: **69 candidate artifacts** — 14 `SKILL.md` in `upstream-superpowers-v6.2.0`, 20 in `residues-architecture-framework` (plus a `guidelines/` directory), 35 in `upstream-matt-skills-v1.2.3`. At six required arguments per `vendor` invocation that is the manual work the proposal is about. |
| `AD-09` | high | `2026-08-17` | Usage reporting never offers to create an issue, and never says why. Raised after installing a skill; the raiser then confirmed the same silence in the TUI. Measured `2026-08-17`: `registry init` scaffolds the whole registry side — `.github/ISSUE_TEMPLATE/usage-report.yml`, the `aart-usage-dashboard` and `aart-usage-validate` workflows — and writes `"services": {}`. `reporting/destination.py:61` demands exactly one advertised `usage_reporting` service, so `reporting/runtime.py:157-160` skips every source with a bare `continue`. Nothing under `registry_commands/` ever writes that block; the string `usage_reporting` does not occur there. Separately, the consumer-side offer has one caller — `tui.py:821`, in the setup flow only — with `interface="tui"` hardcoded, so `marketplace install` from the CLI has no reporting path at all. |
| `AD-11` | high | `2026-08-17`, raised against the `AD-08` stopgap | `registry vendor` cannot take a single file, and a harness memory document is always a single file at a repository root. `--path DIR` is documented as a directory and refuses anything else — `error: the requested subtree path is not a directory` — while the `memory` payload rule demands *exactly one Markdown document*. Those two are only satisfiable by a directory that holds nothing but that document, which is not how any upstream stores it. Measured `2026-08-17`: `upstream-superpowers-v6.2.0` carries `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` at its root beside 20 other entries; `upstream-matt-skills-v1.2.3` carries `CLAUDE.md`, `AGENTS.md` and `CONTEXT.md`. Under the `tabnine` profile a `memory` artifact installs as project-root `TABNINE.md` (`profiles/builtin.py:179`), so this is the artifact the raiser called indispensable, and it is the one kind the tool cannot import. The only route today is `registry scaffold memory` plus a paste, which produces a copy with no `provenance.json` and no `revendor --check`. The same wall stands in front of every loose `.md` guideline. |
| `AD-12` | high | `2026-08-17`, walking `AD-11`'s adoption | A project can hold only one `memory` artifact, and the design says it should hold several. `DESIGN-memory.md` §3.3 scopes the sentinel by name — `<!-- >>> agent-artifacts memory:<name> >>> -->` — *"so an `memory` block and a same-named guideline block can coexist in one file … without either clobbering the other"*, and two differently-named memory artifacts therefore carry two different markers. Installation refuses anyway. Measured `2026-08-17`: with `memory/superpowers-house-rules` installed into a Tabnine project, installing `memory/test-first-rules` fails with `error: install destinations contain unowned or drifted content; use force: TABNINE.md`, and adding `--force` fails differently with `error: installation state ownership conflict: installation effect ownership must be unique across the manifest`. The cause is that `installation/application.py:847` looks up prior ownership of a destination **by artifact coordinate**, so the second artifact sees a file it does not own and stops; `install_state/model.py:337` then forbids two artifacts owning one destination outright. The block machinery supports coexistence and the ownership model forbids it. |
| `AD-04` | high | `2026-08-16`, walking `AD-03` | Nobody has verified where Tabnine reads MCP servers from, and AART writes them to one of two candidate files. `profiles/builtin.py:139` points the Tabnine `mcp` target at `.tabnine/agent/settings.json` under `mcpServers`, above a comment recording that the published Tabnine documentation puts server *definitions* in a standalone `.tabnine/mcp_servers.json` and uses `settings.json` for a different `mcp` key that is governance only. The comment ends *Verify in-environment* and that verification has not happened. If the documentation is right, every MCP artifact installs successfully, reports success, and Tabnine never sees the server. |

## Notes on `AD-01`

The finding is filed as `low` because nothing is broken. It is at the top of this stream anyway,
because it is the first code block a colleague meets.

**The ask is two-dimensional, and that is what makes it more than a missing line.** There is the
installer — `pip`, `pipx`, `uv` — and there is what it is pointed at. The README covers one cell of
that grid, and it is the cell a colleague adopting AART is least likely to be in:

| Pointed at | Covered today |
|---|---|
| a local clone, editable | **yes** — the only line there is |
| a wheel already downloaded | no |
| a wheel on a GitHub release | no |
| the repository URL, no clone | no |

The three empty rows are the ones that matter for adoption, because none of them needs a checkout.
`v2.6.1` published a wheel and the repository is public, so all three are reachable today.

Four things to settle when it is fixed, not now:

1. **Every command in the README must have been run.** An install line that does not work is worse
   than an absent one — it is the first thing a colleague tries and the first thing that fails.
   Candidate commands are drafted below and **none of them has been executed**; the fix walks each
   one in a throwaway environment and the README carries only what passed.
2. **Which host the URL names.** The public repository is one thing; a company install may point at
   an internal mirror or GHE, where `pipx install git+https://…` needs credentials AART itself never
   handles. The README should show the shape and say plainly where the host goes.
3. **Whether a version is pinned.** `git+https://…@v2.6.1` gives a colleague a known executable;
   the bare URL gives them whatever `main` is that morning. For adoption the tag is almost certainly
   right, and then the README has a version number in it that has to be maintained.
4. **Whether the editable line stays.** It is the right line for someone hacking on AART and the
   wrong one for someone adopting it. The likely shape is two labelled blocks — *install it* and
   *work on it* — rather than a row of commands with no explanation of which is which.

### Candidate commands — drafted, not verified

Recorded so the fix starts from a list rather than a blank page. Each is a claim to be tested, not a
result.

```sh
# from a wheel already on disk
pipx install ./agent_artifacts-2.6.1-py3-none-any.whl
uv tool install ./agent_artifacts-2.6.1-py3-none-any.whl
python -m pip install ./agent_artifacts-2.6.1-py3-none-any.whl

# from a wheel on the GitHub release, without downloading it first
pipx install https://github.com/M1F1/agent-artifacts/releases/download/v2.6.1/agent_artifacts-2.6.1-py3-none-any.whl

# from the repository, no clone
pipx install "git+https://github.com/M1F1/agent-artifacts@v2.6.1"
uv tool install "git+https://github.com/M1F1/agent-artifacts@v2.6.1"
```

Two properties AART has that make these unusually safe to recommend, and that the fixed README
should probably say out loud: there are **no runtime dependencies**, so nothing is resolved from an
index at install time, and the published wheel is **byte-reproducible from the tag** with its digest
in the release notes — so a colleague who wants to check what they installed can.

## Notes on `AD-02`

`medium`, not cosmetic. This one hides a capability rather than presenting it awkwardly: the
README's *Maintaining a registry* section documents `promote-native` and stops, and the sentence
under it — *keeps reviewed subscriptions and updates easy without adapting a foreign legacy layout*
— reads as though that command already solves the foreign-repository case. It does not. It refuses
any upstream without `aart-source.json`.

The material to write from already exists and does not need inventing:
[`DESIGN-registry-vendoring.md`](../design/DESIGN-registry-vendoring.md) opens with the barrier and
what removes it, and [`DESIGN-vendored-copy-integrity.md`](../design/DESIGN-vendored-copy-integrity.md)
covers what keeps a copy honest afterwards.

Three things to settle when it is fixed, not now:

1. **Where it goes.** Beside `promote-native` under *Maintaining a registry*, or its own section.
   The two commands answer the same question with different preconditions, so a reader meeting one
   without the other is the defect; whatever shape is chosen has to put the choice in front of them.
2. **What the explanation has to contain.** At minimum: it copies the content into your registry, it
   records where the copy came from in `provenance.json`, `revendor` is how it is refreshed when
   upstream moves, and the copy is checked for drift. Anything less and a maintainer cannot tell
   vendoring from copy-and-paste.
3. **Whether the `promote-native` sentence is corrected at the same time.** It is currently the only
   thing the README says about foreign content, and it overstates its reach.

## Notes on `AD-03`

The walkthrough now exists — [`company-registry-tabnine-v1.md`](../tutorials/company-registry-tabnine-v1.md)
— and every command in it was executed against a `2.6.1` wheel in a throwaway venv before it was
written. The finding is about reaching it, not writing it.

The raiser's constraint is explicit and shapes the fix: **link, do not inline.** The README is 219
lines and covers a product with three command families; a full standing-up guide inside it would
bury the parts a reader needs in the first minute.

Two things to settle when it is fixed, not now:

1. **Whether the other three tutorials get linked too.** `company-registry-v1.md`,
   `direct-source-v1.md` and `vendoring-v1.md` are equally unreachable. Note that the first two are
   `1.0.0`-era: `company-registry-v1.md` opens *Tutorial: AART 1.0.0* and tells the reader to
   *open `aart`*. Linking them from the README without reading them first would advertise stale
   instructions to exactly the audience this stream is for. That is its own finding if it turns out
   to be true of more than one.
2. **Where the link goes.** *Quick start* gets a reader to their first command; the walkthrough is
   what a platform team follows for half a day. Those are different moments and probably different
   places in the README.

## Notes on `AD-08`

The largest item in this stream, and the only one that asks for something the product does not have
at all. Everything else is a document, a default, or a name.

**The design already sanctioned this shape, and named the condition.**
[`DESIGN-registry-vendoring.md`](../design/DESIGN-registry-vendoring.md) §10 lists batch discovery
as a deliberate non-goal, and then says exactly how it may come back: *"If it returns, it returns as
an orchestration layer over this primitive, never as a replacement for it."* §9 records why the old
`aart upstream import` was removed — GitHub REST, `GITHUB_API_URL`, a `GITHUB_TOKEN` in the
environment — and the reason it produced *"results a maintainer had to audit line by line"*. So the
proposal is not fighting the design; it is the re-entry the design described. What must not come
back with it is the credential handling and the idea that discovery decides anything.

**Prior art sits in one of the raiser's own repositories.** `residues-architecture-framework` carries
`agent-artifacts.import.json`: 14 entries, each with `type`, `name`, `path`, `description` — and
`bundle`, the dead word from `AD-06`. It is read by **nothing** in AART; it is a leftover of the
removed importer. It is also, near enough, the manifest a crawler would emit and `vendor-all.sh`
would consume. Whatever gets built should be able to produce that file, and reading a hand-written
one is most of the value on its own.

Six things to settle in a design, none of them settled here:

1. **Where the scan runs.** On a local checkout the maintainer already cloned, or on a URL AART
   acquires the way `vendor` does? The second is friendlier and keeps one acquisition path; the
   first makes the whole feature a read-only local walk with no network story at all.
2. **What a rule is, and whether a maintainer can add one.** `SKILL.md` at a directory root is
   nearly unambiguous. `guidelines/*.md` is a guess. `mcp` is the hardest — there is no file whose
   presence means *this is an MCP server*. A fixed rule set is honest and small; a configurable one
   is a second format to specify.
3. **What the output is.** A JSON manifest (feeding a loop, reviewable in Git, diffable when
   upstream moves) or an interactive one-by-one prompt. The raiser asked for the second; the first
   composes with `AD-05`'s loop and survives being re-run six months later. They are not exclusive
   — the prompt can write the manifest.
4. **What it fills in and what it refuses to.** `--summary` could be read from a `SKILL.md` front
   matter `description`; `--artifact-version` **must not** be guessed — §10 already forbids parsing
   `package.json` or tags for a version, and the vendor command deliberately makes the maintainer
   state it.
5. **How a candidate becomes a decision.** *Accept* has to end in the same reviewed
   `registry vendor` invocation an operator would have typed, with the same three checks. If the
   crawler can vendor something the primitive would have refused, the feature is a hole.
6. **Whether it reports what is already vendored.** Run against a repository half of which is
   already in the registry, the useful answer is *these five are new, these nine you already have,
   two of them have moved since*. `provenance.json` and `revendor --check` hold everything needed
   to say that.

**A stopgap exists, and the finding stays `open`.**
[`scripts/vendor_scan.py`](../../scripts/vendor_scan.py), written `2026-08-16` at the raiser's
request, so a company registry can ship before the design is settled. It is not the feature: it is a
script in `scripts/`, outside the wheel, outside the schema, with `git` and `aart` as its only
dependencies. It answers four of the six questions above provisionally — local checkout *or* URL
(1); a fixed rule set, no configuration (2); a JSON manifest that the interactive review writes back
into (3); summary read from the document, version never guessed (4) — and it answers (5) by not
being able to violate it: every acceptance ends in a real `aart registry vendor` invocation, and
`--yes` is required before anything is finalized. It does not answer (6) beyond skipping artifacts
already present by path.

The one thing the stopgap taught that the proposal did not anticipate: **in a repository that does
not speak AART, the `mcp` and `hook` rules find nothing.** `mcp.json` and `hook.json` are AART's own
payload filenames. Foreign repositories carry `.mcp.json`, `mcp_servers.json`, servers declared
inside `package.json`, and `hooks/` directories full of scripts — none of which `vendor` can take,
because a payload must be a directory in the shape the compiler enforces. So the script reports
those as *hints* naming the wrapper a maintainer would have to author, never as candidates. Question
2 above is therefore sharper than it was written: for `mcp` and `hook` the problem is not
recognition, it is that recognition alone does not produce something vendorable. Whatever is
eventually designed has to say what it does about the gap between the two.

Measured on the three repositories in the row above: **73 candidates** — 69 skills, matching the
row's count exactly, and 4 guidelines the row's manual count had missed — and 1 hint. Walked end to
end against a real `2.6.1` wheel on `2026-08-16`, into a throwaway registry: scan → review → vendor
→ lock → commit → build → `validate` passed, `audit` warning only about a missing upstream license.

## Notes on `AD-11`

Raised by the raiser against the `AD-08` stopgap — *it did not detect `TABNINE.md`, kind `memory`,
which is an indispensable part of superpowers* — and the scan was indeed silent about it. Fixing the
scan turned out to be the small half. The large half is that **the thing it was silent about cannot
be vendored at all.**

Two rules meet and leave nothing between them. `registry vendor --path DIR` takes a directory: point
it at a file and it answers `error: the requested subtree path is not a directory`. And
`native_tree.py:274-283` requires a `memory` or `guideline` payload to be *exactly one Markdown
document*. Both are satisfied only by a directory holding that document and nothing else. No
upstream stores a memory document that way, because to its own harness it is a root-level file:
`CLAUDE.md` for Claude Code, `AGENTS.md` for the common convention, `GEMINI.md`, `TABNINE.md`.

Measured `2026-08-17`. `upstream-superpowers-v6.2.0` has all three of `CLAUDE.md`, `AGENTS.md`,
`GEMINI.md` at its root, among 20 other entries. `upstream-matt-skills-v1.2.3` has `CLAUDE.md`,
`AGENTS.md`, `CONTEXT.md`. Not one is vendorable.

**The kind itself is fine.** Vendored from a directory that does hold exactly one document,
`aart registry vendor memory house-rules … --path packages/branch-conventions --yes` compiles,
writes `artifacts/memory/house-rules/payload/branch-conventions.md` and a `provenance.json`, and
passes `vendor-assessment`, `vendor-license` and `vendor-origin`. So this is not a defect in
`memory`. It is the file/directory boundary in `vendor`.

**What it costs.** The only route today is `registry scaffold memory <name>` and a paste. That
produces a package with no `provenance.json`, therefore outside `revendor --check`, therefore
invisible to `registry audit`'s upstream-drift pass — and `AD-02`'s whole argument for vendoring is
that a copy without provenance is the thing AART exists to replace. For a Tabnine shop it is the
worst possible kind to lose: `profiles/builtin.py:179` installs a `memory` artifact as project-root
`TABNINE.md`, which is the file that makes a skills repository do anything at all.

Not decided here, and the choice is real: teach `--path` to accept a file and synthesise the
single-document payload, or add something narrower like `--payload-file`. The first is a smaller
surface and reads as what a maintainer meant; the second cannot be confused with taking a subtree.
Either way the provenance record has to keep meaning the same thing, since `revendor --check` reads
it.

Meanwhile the scan reports every one it finds as a hint, naming the scaffold command and the
provenance it costs — a maintainer who never learns the file is there cannot decide anything about
it. And when a memory document *is* alone in a directory, the scan now classifies it as a `memory`
candidate rather than a `guideline`, which is what it was doing before.

**The stopgap now performs the adoption**, on the raiser's instruction: *detect these files, let the
maintainer name one at vendoring time, put it into the registry as a `memory` artifact, and let it
install into whichever file the harness reads.* `vendor_scan.py adopt` asks for a name per document,
runs `aart registry scaffold memory <name>`, and writes the upstream document in as the payload.

Walked end to end `2026-08-17` against the real `2.6.1` wheel. `CLAUDE.md` from
`github.com/obra/superpowers.git` adopted as `memory/superpowers-house-rules`, 115 lines carried
across intact; locked, committed, built, committed; `registry validate: passed`; installed into a
throwaway consumer with `--profile tabnine` and it landed as project-root `TABNINE.md`, 117 lines —
the two extra being the managed-block markers. Cursor's `.cursorrules` adopts the same way, into a
Markdown payload, which is the whole point: the upstream filename is a harness's business, the
destination is the installing profile's, and the name in between is the maintainer's.

Installing a *second* memory artifact into the same project turned out to be refused. That is
`AD-12`, found here.

So the *outcome* the raiser described is reachable today. What is still missing, and what keeps
`AD-11` `high` and `open`, is the provenance: the adopted package has no `provenance.json`, so
`revendor --check` will never notice upstream moving and the audit's drift pass cannot see it. The
origin goes in the commit message because `artifact.json` rejects an unknown field — verified
`2026-08-17`, `error: unknown field 'x-adopted-from'` — and inventing a provenance record for bytes
that were never vendored would be a lie every later audit would repeat.

## Notes on `AD-12`

Found by installing a second adopted memory artifact into the same project, which is the first thing
a company will do: upstream's house rules, plus its own.

The design intended this. `DESIGN-memory.md` §3.3 chose HTML-comment sentinels over `#` headings so
the markers stay invisible in the document a model reads every turn, and made the marker
**type-scoped and name-scoped** — `memory:<name>` — with the stated reason that blocks must coexist
in one file *"without either clobbering the other on install/uninstall"*. §7.1 repeats it for Mistral
Vibe, where `memory` and `guideline` both target `AGENTS.md`. Two memory artifacts, two names, two
markers: nothing about the file format stops them.

The ownership model does. `installation/application.py:847` asks `_previous_effect(state, request,
coordinate, destination)` — prior ownership is resolved **by artifact coordinate** — so the second
artifact looks at `TABNINE.md`, finds content no effect of *its own* produced, and reports a
conflict. That is the guard working as designed for the case it was designed for: a file a human
edited. It cannot tell that apart from a file another AART artifact owns a different block of.
`--force` does not get past it either, because `install_state/model.py:337` raises outright when two
artifacts claim one destination.

Measured `2026-08-17` in a project already holding `memory/superpowers-house-rules`:

    install memory/test-first-rules        → install destinations contain unowned or drifted
                                             content; use force: TABNINE.md
    install memory/test-first-rules --force → installation state ownership conflict: installation
                                             effect ownership must be unique across the manifest

Two things a fix has to keep, and they are why this is not a one-line change. The uniqueness rule
protects uninstall: `setup_undo` has to know whose bytes to remove. And the drift guard protects a
human's own edits to `TABNINE.md`. Making ownership per-block rather than per-destination satisfies
both in principle, since the sentinels already delimit exactly the bytes each artifact owns — but it
moves the unit of ownership through the install state, the undo path and the verify path together.

Until then a company that wants upstream's memory *and* its own merges the two documents by hand
before adopting, and the walkthrough says so.

## Notes on `AD-07`

Raised `low` on `2026-08-16` as a missing scaffold template, and widened by the raiser on
`2026-08-17` into something larger: **a maintainer-mode command that composes a collection out of
the artifacts the registry already holds, in the CLI and as a flow in the TUI.** The distinction
matters. A `scaffold collection` verb would hand a maintainer an empty file and the same schema
problem they had before. What is actually wanted is the operation a maintainer performs: *show me
what is in this registry, let me pick, write the collection.* Every input that command needs is
already on disk — `artifact.json` carries the type, name, version and summary of each package.

Raised to `medium` on the widening. `low` was defensible while the gap was one missing template; a
maintainer capability absent from **both** interfaces is not an on-ramp problem, it is a feature
that requires a text editor and `native-source-v1.md` to use at all. Compare `AD-09`: the same
shape, where an apparatus that scaffolds and validates cleanly cannot be switched on by any command.

**A stopgap exists and the finding stays `open`.** `scripts/collection_new.py`, written
`2026-08-17`, outside the wheel, `aart` its only dependency and only to check what it wrote. It
reads the registry's own `artifact_roots` and `collection_roots` rather than assuming the layout,
lists every artifact from its manifest, and asks one at a time; `--include` skips the asking.
Re-running on an existing name edits it, with current members pre-selected and **their version
bounds preserved** — unpinning a company baseline is a decision, and a re-run is not one. Walked end
to end into a throwaway registry on `2026-08-17`: authored, locked, committed, built, committed,
`registry validate: passed`, and the collection is in `aart.index.json`.

What the stopgap cannot answer, and a design must: whether the TUI flow reuses the review-then-
finalize contract every other maintainer action has (it should), and whether editing an existing
collection is the same verb or a different one.

## Notes on `AD-10`

Found while deciding what the `AD-07` stopgap should run to check its own output. The obvious
choice was `registry lock` without `--yes`, which reviews and mutates nothing. It turned out to
accept anything.

Measured `2026-08-17`. A `collections/broken.json` containing the selector
`{"type": "nonsense", "name": "x"}` — a type that does not exist — passes `registry lock --source .`
with exit `0` and no diagnostic, and passes `registry lock --source . --yes` the same way, writing
`aart.lock.json`. `registry build --source . --yes` then refuses it: `error: selector identity is
invalid`, and `aart.index.json` keeps `"collections": []`. `registry validate` reports the same
error.

Why it is `low` and not higher: nothing broken can ship, because the compiler holds and the build
is what produces the index a consumer reads. Why it is not nothing: the publishing order this
stream's own walkthrough documents is *lock, commit the lock, build* — `build` requires a committed
lock — so the only command that runs before the commit is the one command that does not look at
collections. A maintainer commits a lock recording a state that will not build. And `lock` reporting
success on input it never examined is the weaker half of the defect: silence about something checked
and silence about something skipped are indistinguishable to the person reading the output.

The stopgap therefore runs `registry validate` instead, and separates the three complaints that mean
*the index is stale because you just authored something* from anything else validate says.

## Notes on `AD-09`

Raised as *analytics does not fire after installing a skill*, and then sharpened by the raiser the
same hour: **the TUI does not offer it either**. That second observation is what makes this a `high`
rather than a missing CLI path, because it rules out the obvious explanation and points at the
registry side.

**The decisive field is one the maintainer is never told about.** `registry init` writes the whole
apparatus — the issue template a consumer would file into, the workflow that validates a filed
report, the workflow that builds the dashboard — and then writes `"services": {}` into
`aart-registry.json`. `reporting/destination.py:61-63` requires *exactly one* advertised
`usage_reporting` service before a destination can be bound at all, so the routing loop at
`reporting/runtime.py:157-160` reaches `continue` for every configured source and returns an empty
tuple of routes. `tui.py:797` then prints its header only `if prepared.value:`, so an empty routing
produces no line of output whatsoever. Nothing is broken; nothing is said either.

**And nothing can write that field.** `usage_reporting` does not occur anywhere under
`registry_commands/`. The only way to advertise the service is to hand-edit `aart-registry.json`,
which means knowing the key, the `github-issues` kind and the `repository` value — a shape
`destination.py:65-66` enforces and no command scaffolds. This is `AD-07`'s pattern again: the
feature works, the on-ramp does not exist. Here it is worse, because a collection you failed to
author is a file that is missing, while reporting you failed to advertise looks exactly like
reporting that ran and found nothing to say.

**The CLI has no reporting path at all**, which is a real second defect and not a symptom of the
first. `usage_report_from_consumer` has exactly one caller outside `reporting/`: `tui.py:821`,
inside `_complete_canonical_consumer_action`, which is reached only from the text wizard
(`tui.py:2177`) and the curses setup (`tui.py:5295`). `aart marketplace install` finishes without
ever constructing a usage report. That the projection already takes an `interface` parameter — and
that both call sites pass the literal `"tui"` — says the CLI interface was anticipated and never
wired.

Not investigated, and worth checking before anything is designed: `runtime.py:147` also skips any
destination on `github.com`, `gitlab.com` or `bitbucket.org` when `deny_public_destinations` is set.
It defaults to `False` (`configuration/model.py:128`), so it is not the cause here, but it is a
third silent `continue` on the same path and a company registry on a public host would hit it.

The shape of a fix is not decided here. What the evidence does settle is that at least two things
have to change together — something must write the service advertisement, and something must say
out loud when reporting was skipped and which gate skipped it — or a maintainer will keep seeing an
apparatus that scaffolds cleanly, validates cleanly, and reports nothing.

## Notes on `AD-04`

Filed `high`, and it is the only finding in this stream that is not about documents. It surfaced
while writing the destination table for `AD-03`'s walkthrough: the table needed a row for `mcp`,
the source had a comment saying the row might be wrong, and there was no evidence either way.

**Why `high`.** The failure is silent. An MCP artifact installs, `marketplace install` reports
success, `marketplace status` reports `current`, and the file it wrote is one Tabnine may never
read. Nothing in AART can detect this, because AART's job ends at writing the file the profile
names. The first person to notice is a colleague whose MCP server does not appear, at which point
the tool they were told to adopt looks broken.

What would settle it, and it is cheap: install one `mcp` artifact into a scratch project with
`--profile tabnine`, open Tabnine, and see whether the server is there. If it is not, move the
`MergeSpec` to `.tabnine/mcp_servers.json` — the comment already says this is a one-line record
change. **Requires a machine with Tabnine on it**, which is the raiser's, not the agent's.

Until it is settled the walkthrough carries the caveat in the open, in the section a reader meets
before rolling MCP artifacts out to a team.
