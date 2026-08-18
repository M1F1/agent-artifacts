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

The repair work is briefed separately in [`adoption-stream-repair-brief.md`](adoption-stream-repair-brief.md), which groups every open
`AD-*` into clusters and says which order to take them in.

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
| `AD-13` | medium | `2026-08-17` | `registry init` writes no `.gitignore`, and the one that exists cannot be reached. Measured `2026-08-17`: `registry init` creates exactly six files — `aart-registry.json`, `aart-source.json` and four under `.github/` — and nothing else. No `.gitignore`, no `README.md`, no `LICENSE`, no `SECURITY.md`. All four *are* written, as byte templates, by `PublicRegistryPolicy.repository_files` at `registry_publication.py:169-179` — a module with **zero importers in the package**, referenced only by `tests/public_registry_publication_test.py`. So the code exists and no command runs it, which is `AD-06`'s pattern in a second place. And the template's ignore list is Python-toolchain only — `.coverage`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `build/`, `dist/`, `htmlcov/`, `usage-dashboard/` — with not one harness directory in it, though AART's own built-in profiles write `.claude/`, `.tabnine/`, `.opencode/`, `.vibe/` and `.mcp.json` into a project root, and installation writes `.agent-artifacts/` and `.agent-artifacts-bak/`. A maintainer who tests one install inside their registry checkout has all of that staged by the next `git add -A`. |
| `AD-14` | medium | `2026-08-17` | Publishing a registry is four commands in a fixed order plus a commit, and nothing in the product runs the sequence. `lock`, `build`, `validate`, `audit`, then `git add -A && git commit` — six things typed by hand every time anything changes, with an order that produces confusing errors when got wrong: `build` before `lock` refuses, `validate` before `build` reports the index as stale. The raiser's words: remembering these commands and typing them out is a nightmare and slows the work down. Asked for: one command that takes the registry source, runs the sequence, and **lists every file it is about to commit**. |
| `AD-15` | low | `2026-08-17`, building `AD-14`'s stopgap | `registry build` says its precondition is a *committed* lock, and the precondition is a lock that exists. The message is `error: registry build requires a committed aart.lock.json`, and its remediation reads *"`aart registry lock --yes`, commit the lock it writes, then `aart registry build --yes`"*. The check at `registry_commands/planning.py:1244` is `files.value.get("aart.lock.json")` — presence in the snapshot, nothing about history. Measured `2026-08-17` in a fresh registry: with `aart.lock.json` untracked (`git status` → `?? aart.lock.json`), `build` compiled the index and exited `0`. The cost is one unnecessary commit per publishing cycle for anyone who believes the diagnostic, and this stream's own walkthrough believed it and documented it as a required step until this finding corrected it. |
| `AD-04` | high | `2026-08-16`, walking `AD-03` | Nobody has verified where Tabnine reads MCP servers from, and AART writes them to one of two candidate files. `profiles/builtin.py:139` points the Tabnine `mcp` target at `.tabnine/agent/settings.json` under `mcpServers`, above a comment recording that the published Tabnine documentation puts server *definitions* in a standalone `.tabnine/mcp_servers.json` and uses `settings.json` for a different `mcp` key that is governance only. The comment ends *Verify in-environment* and that verification has not happened. If the documentation is right, every MCP artifact installs successfully, reports success, and Tabnine never sees the server. |
| `AD-16` | high | `2026-08-17` | A source that has fallen behind its origin says `current`. Health never contacts the origin: it is `now - published_at` against `sync.max_age_seconds`, so `healthy` means *the snapshot is recent* and not *the snapshot matches the origin*. Measured `2026-08-17`: a source synchronized at one artifact, its registry then advanced by a commit adding a second, reported `healthy; 8s` from `source health`, `[healthy]` from `marketplace list` and `current` from the TUI projection, with the new artifact absent from the listing and nothing said about why. The inverse holds too — a snapshot identical to its origin reports `stale` once the clock passes. There is no state at all for *the check could not run*: `OFFLINE` exists in the enum and no code path attempts the network at read time. The raiser has been caught by this repeatedly while testing an artifact just added to a registry. Asked for: a visible not-synchronized state on entering `aart`, and a distinct failed-to-check state when the comparison itself cannot be made. |

| `AD-17` | medium | `2026-08-17`, porting an MCP server | A setup recipe prompts for secrets and for nothing else. `inputs[].type` accepts `"secret"` and refuses everything else, so a per-user value that is not a secret — an account e-mail, a board key — has nowhere to go. Found porting `company-atlassian`, whose POC declared the Atlassian e-mail as `type: "text"`. The working route is to keep it in the Keychain with the API token, which means the colleague types their own e-mail address into a prompt with no echo and approves a Keychain access for it. The restriction is deliberate and it is what lets the parser refuse secret interpolation everywhere else, so the ask is a second non-secret input type, not a loosening of this one. |

| `AD-18` | low | `2026-08-17` | The only artifact-manifest extension AART ships is namespaced to a personal account: `com.m1f1.runtime-requirements`, reverse-DNS of the repository owner `github.com/M1F1`. A namespace exists to say who defines a key, and this key is defined and read by AART itself, so it names the wrong party. Every company `artifact.json` that declares a runtime requirement carries it. Seven files mention it. Renaming a published protocol key is the cost, not the edit. |

| `AD-19` | medium | `2026-08-17`, vendoring an MCP server | `error: registry mutation requires a writable local Git checkout` arrives with no remediation line, and the precondition it names is not the one it enforces. The check needs `.git` at the `--source` path itself, so a registry sitting one level inside a Git repository is refused while `git rev-parse --is-inside-work-tree` prints `true` from that same directory. Read commands never touch the check, so it appears at the first publish, after the package is finished. |

| `AD-20` | medium | `2026-08-17`, vendoring an MCP server | `a vendored mcp needs payload/mcp.json; the taken subtree does not contain it, so the maintainer supplies it` says what is missing and who supplies it, never where. It goes at `artifacts/mcp/<NAME>/payload/mcp.json`, authored before the command runs, in a directory the command is about to create. And if upstream happens to ship a file of that name, authoring your own is refused instead as a collision — the right move inverts on upstream content, and the message hints at neither branch. |

| `AD-21` | high | `2026-08-17`, installing an MCP server from the TUI | No artifact with a real setup recipe can be selected in the TUI, by anyone. The row refuses with `setup capabilities are unavailable: …` listing everything the recipe needs. The TUI builds its compatibility target without setup capabilities at all — the argument is simply not passed and defaults to empty — then evaluates against it with `require_setup=True` hard-coded. The organization field that would have filled it is read as *everything permitted* by the setup engine and as *nothing permitted* here. The CLI is unaffected. |

| `AD-22` | medium | `2026-08-17`, setup declined on an installed MCP server | Setup refused on trust and offered the manual route instead. The URL it printed drops the package path and 404s: the web root is the repository at a commit, the path appended is package-relative `SETUP.md`, and nothing supplies `artifacts/mcp/<name>/` in between. The local path in the same message is right, because there the relative path is joined onto the package root. The link fails exactly when it is the only thing the reader has left. |

| `AD-23` | high | `2026-08-17`, installing an MCP server from a script | `marketplace install` prints `Install outcome: succeeded`, writes the payload, and exits `1`. The setup queue is folded into the exit code, and for any source the trust gate blocks it is all failures — while the two flags that would authorize it exist only on `marketplace setup`, never on `install`. Measured: exit `1` with `.mcp.json` correctly written. Under `set -e` a correct install aborts the adoption script, and `\|\| true` would swallow every real failure with it. |

| `AD-24` | high | `2026-08-17`, running setup on an MCP server | The Keychain steps hand the terminal to `security`, which prints `password data for new item:` and `retype password for new item:` — twice in a row, identically, for two different values — while AART prints nothing. It has the service, the account and a human-readable summary in hand and shows them in the review, not at the prompt. Type the two values in the wrong order and both steps report success; the first sign of trouble is an Atlassian authentication error much later. |

| `AD-25` | medium | `2026-08-17`, the same setup run | `setup state persistence failed; applied effects were compensated` replaces five distinct causes with one sentence. `persist_setup` returns a specific diagnostic; `finalize_setup` checks only whether it is an error and never reads it. Re-run it, re-review it, check the disk, or investigate a partial rollback — the message supports none of those, and it arrives after every effect has been compensated and the credentials already typed. |

| `AD-26` | high | `2026-08-17`, running setup on an MCP server | A symlinked `~/.zshrc` — the normal result of keeping dotfiles in a repository — makes the managed-block step impossible. The refusal is correct; the timing is not. Planning is a pure function with no filesystem access, by design, so the review lists `~/.zshrc` as the target of a write that cannot succeed, and nothing stats it before the first effect. The reader pays for the image build and types two credentials blind before reaching a step one `lstat` would have ruled out. There is no follow option and no alternative target. |

| `AD-27` | high | `2026-08-17`, iterating on a setup recipe | An artifact's setup succeeds exactly once. Any change to the package bytes leaves the object-store `setup` reference pointing at the superseded digest, and persistence requires it to match, so every later run applies its effects, fails, and compensates — for good. The version is not part of the check, so re-vendoring at the same `1.0.0` trips it just as surely as a bump. No command recovers it: `receipt undo` finds no record, and uninstall plus install leaves both the stale reference and an orphaned state file behind. |
| `AD-30` | high | `2026-08-18`, wiring a setup-collected secret into an MCP server | An MCP descriptor's `${VAR}` is copied into the harness file as those literal characters. The hook path twenty lines away substitutes `${SCRIPT_DIR}`; the MCP path substitutes nothing. A recipe can collect a secret and a descriptor has no way to name it |
| `AD-31` | high | `2026-08-18`, the same install | Install, setup and the recipe's own verify step all reported success on a server running with the strings `ATLASSIAN_USERNAME` and `ATLASSIAN_API_TOKEN` as its credentials. Confluence answered anonymously and made it look configured; Jira returned 401 |

| `AD-32` | medium | `2026-08-18`, defining the Keychain entries for the Atlassian MCP server | A setup recipe can carry the link a reader needs and nothing ever shows it. `inputs[].help_url` and the recipe-level `help_urls` are parsed, single-line checked and HTTPS-validated by `setup.py:563-615`, stored on `SetupInstaller` (`model.py:89`, `:106`) — and then read by nothing. Measured `2026-08-18`: `help_url` occurs in exactly two modules of the package, the model and the parser, and `.help_url`/`.help_urls` attribute reads outside the parser number **zero**. No renderer, no review output, no prompt, no `--json` payload, no generated `SETUP.md`. Both shipped recipes declare them — `mcp/github-docker` names three URLs including where to create the token, `mcp/atlassian` names the API-token page as the input's own `help_url` — so the data is authored, validated, published in the registry, and invisible at every consumer surface. It matters most at the one moment `AD-24` already describes: the Keychain step hands the terminal to `security`, which asks `password data for new item:` twice with no context, and the field designed to say *here is where you get this value* is the field that is dead. The raiser looked for the Atlassian ID link while filling the Keychain and concluded it was missing; it is present in the recipe and unreachable from the flow Widened `2026-08-18` while probing a fresh recipe: `help_urls` is not optional — a setup v2 installer omitting it is refused outright with `invalid setup installer for mcp/<name>: missing field(s): help_urls`. So the protocol **compels** every recipe author to supply the link, validates it, publishes it, and then shows it to nobody. |

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

## Notes on `AD-14`

The third finding in this stream with the same shape — `AD-07` for collections, `AD-08` for
discovery, this one for publishing. A capability the product has, in pieces, with nothing that runs
the pieces in the order they require.

The order is the part that costs. `build` before `lock` refuses outright; `validate` before `build`
reports the compiled index as stale, which reads like a broken registry rather than a step not yet
taken. So a maintainer who mistypes the sequence spends time debugging a state that is merely
incomplete. Four commands is not many, but four commands *whose order produces plausible-looking
errors* is a memory test run several times a day.

**A stopgap exists and the finding stays `open`.** `scripts/registry_publish.py`, `2026-08-17`,
`git` and `aart` its only dependencies. Preview by default: `lock` and `build` run in their own
review mode, `validate` and `audit` are read-only anyway, and the files that would be committed are
listed. `--yes` runs the four for real and commits.

Two decisions in it worth naming. It lists **every file** rather than the directories Git collapses
by default — `git status --porcelain` alone would print `artifacts/` on a first publish, and the
raiser asked to see what is being committed, so `--untracked-files=all` is the point rather than a
detail. And it **commits but never pushes**: AART deliberately does neither, ending every maintainer
command by telling you to review the diff, so a script that commits is already taking something the
tool withholds. Printing the full file list before doing it is what keeps that honest. Pushing is
the step that makes a change other people's problem, and it stays a human's.

Walked `2026-08-17` against a registry initialised from scratch: preview listing ten paths and
writing nothing; `--yes` running the four and committing exactly those ten; an unchanged re-run
reporting nothing to commit; and a deliberately malformed collection stopping it at `build` with
`HEAD` unmoved.

Left for a design: whether the real verb commits at all. It might reasonably stop at the audit and
print the `git` commands, which keeps AART's no-commit line intact — but that is most of the typing
the raiser objected to, so the honest options are a verb that commits behind an explicit flag, or an
admission that the line has moved.

## Notes on `AD-15`

A one-word defect, found because the `AD-14` stopgap had to decide whether to commit between `lock`
and `build`. The walkthrough written earlier in this stream said it must, and quoted AART's own
error message as the reason. Both were wrong.

`registry_commands/planning.py:1244` reads:

    lock_file = files.value.get("aart.lock.json")
    if lock_file is None or lock_file.kind is not SnapshotEntryKind.FILE:
        return _error("registry build requires a committed aart.lock.json", _LOCK_FIRST)

The condition is presence in the workspace snapshot. Nothing consults Git. Measured `2026-08-17` in
a registry initialised from scratch: `build` with no lock at all fails as documented; `lock --yes`
then leaves `aart.lock.json` untracked, `git status` reporting `?? aart.lock.json`; `build --yes`
compiles the index and exits `0`.

Why it matters more than a wording slip: the remediation string is an instruction, and following it
costs a commit per publishing cycle that records a half-published state — lock without index — in
history forever. The word *committed* does belong somewhere near here, which is probably where it
came from: `validate --strict` genuinely does require committed generated outputs
(`cli.py:861`). Moving the claim to the command that makes it would fix both halves.

## Notes on `AD-13`

Raised as *a registry created by `aart` should come with a `.gitignore` listing the harness
directories*. Checking it turned up something more specific than a missing default.

**The file is written; nothing writes it.** `PublicRegistryPolicy.repository_files`
(`registry_publication.py:169-179`) returns `.gitignore`, `LICENSE`, `README.md`, `SECURITY.md`, the
registry CI workflow and the reporting templates, as byte literals ready to drop into a checkout.
`registry init` emits the workflow and the templates and none of the other four. Searching the
package for an importer of `registry_publication` returns nothing; the only reference anywhere is
`tests/public_registry_publication_test.py`. This is exactly `AD-06`'s shape — `Bundle` and
`Catalog` shipped with zero importers — and exactly `AD-09`'s: an apparatus fully built and
unreachable from any command.

**And the ignore list is for the wrong repository.** It reads as a Python project's ignore file:
`.coverage`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `build/`, `dist/`,
`htmlcov/`, `usage-dashboard/`. Only the last of those can appear in a registry a maintainer runs
`aart` in. What actually appears is what AART itself writes: `.agent-artifacts/` and
`.agent-artifacts-bak/` from installation, and the project-scope roots the built-in profiles target
— `.claude/`, `.tabnine/`, `.opencode/`, `.vibe/`, `.mcp.json`. A maintainer who tests a single
install inside their own registry checkout, which is the obvious thing to do before publishing, has
all of that in front of the next `git add -A`.

Two judgements a fix has to make, neither obvious. Whether a harness directory belongs in a default
ignore list at all is a real question for a *consumer* project — some teams commit `.claude/`
deliberately, and `.mcp.json` is often checked in on purpose. In a *registry* checkout the answer is
easier, because those paths can only be test residue. So the default probably differs by repository
role, which is a thing `init` knows and the current template does not express. And `.agent-artifacts/`
holds both a `manifest.json` recording what is installed and a `state.lock`; the second is never
committable, the first is arguably worth committing in a consumer repo. Ignoring the directory
wholesale settles that question by accident rather than on purpose.

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

## Notes on `AD-16`

Raised by the raiser from their own habit: add an artifact to the registry, switch to a project,
install it to see whether it works — and forget the `aart source sync` in between. It has happened
several times. What makes it cost time rather than a second is that nothing on the screen is wrong.
The source is listed. It says `current`. The artifact is simply not there, and the obvious reading of
that is *the artifact is broken*, not *you are looking at yesterday's copy*.

### What health actually measures

`assess_source_health` (`sources/model.py:254-281`) is four lines of arithmetic:

```
age = max(0, now - current.published_at_epoch_seconds)
STALE if age > max_age_seconds else HEALTHY
```

`max_age_seconds` defaults to `900`. So `healthy` means **the snapshot on this disk was published
less than fifteen minutes ago**. It does not mean the snapshot matches the origin, and nothing in the
codebase claims it does — the reading is entirely the operator's, and the interface invites it by
printing the word `current`.

The origin is never contacted. `source_status` (`application/sources.py:516-534`) calls
`read_current_source` and returns; on failure it passes that read's own diagnostics through. Every
consumer path uses it: `consumer/runtime.py:779` and `:876` for the marketplace,
`commands/source.py:673` for `source health`, `tui.py:954` for the TUI's source stage. One clock
reading, four surfaces.

### Measured, both directions

In an isolated `HOME`, a local registry with one guideline, synchronized:

```
company [source-local@local] healthy; 0s
company/guideline/first@1.0.0 [local] [healthy]
```

A second guideline scaffolded into that registry and committed — the origin has moved, the snapshot
has not:

```
company [source-local@local] healthy; 8s
source company [healthy] source-local …/synclab/registry
company/guideline/first@1.0.0 [local] [healthy]
```

Still `healthy`. `guideline/second` does not appear and nothing accounts for its absence. The TUI
agrees, asked directly through its own projection:

```
TUI row: company -> current age 40
```

Then the inverse. Synchronized again, so the snapshot is byte-identical to the origin, with
`sync.max_age_seconds` set to `1`:

```
company [source-local@local] stale; 15s        exit=1
source company [stale] source-local …/synclab/registry
```

`stale`, and `source health` exits non-zero, for a source that is exactly correct.

So the two words the interface has do not mean what they say. `current` does not mean up to date and
`stale` does not mean behind. Both are the same clock reading with a threshold between them.

### The state that does not exist

The raiser asked for a second thing: when the check cannot be made — no network, a dead origin — say
that, rather than saying nothing.

`SourceDisplayHealth.OFFLINE` is already in the enum (`tui_sources.py:48`). It is unreachable for
this purpose. `_display_health` (`tui_sources.py:345-362`) selects it from `source-unavailable` or
`source-auth-failed` in `health.diagnostics`, and those diagnostics can only come from
`read_current_source` failing — a local file, a store lease. No code path attempts the network while
building any of these four views, so *the origin could not be reached* has no way to be true. The
state to add is not `OFFLINE`; it is the one that follows from actually trying.

### A third piece of dead configuration

`sync.mode` defaults to `SyncMode.AUTO`, is validated by `configuration/schema.py:329`, written back
by `:442`, and carried through `configuration/policy.py:132` into the effective configuration. **No
code reads it to decide anything.** There is no automatic synchronization; `auto` is a word in a file.

`refresh_sources=True` — the parameter that would make a command re-fetch before reading — has one
caller in the entire package: `commands/marketplace.py:284`, inside `marketplace health`, which is
about runtime requirements and not about freshness at all. `marketplace list` and `marketplace
install` never pass it.

This is the third instance of the pattern in this stream. `AD-06`: `Bundle` and `Catalog`, defined,
imported by nothing. `AD-13`: `PublicRegistryPolicy.repository_files`, written, run by no command.
Now `sync.mode`, configured, obeyed by nothing. Each one alone is a loose end. Three of them is a
habit of building the mechanism and not wiring the switch — the same habit `AD-09` describes for
usage reporting.

### Why `high`

The failure is silent and it points the operator at the wrong thing. A maintainer testing their own
new artifact loses minutes. A colleague installing from the company registry gets last week's
content, is told the source is `current`, and has no reason to doubt it — and the maintainer, looking
at the same `current`, has no way to tell them otherwise. In a rollout the whole value of a shared
registry is that everyone has the same thing, and this is the one check that would say whether they
do.

## Notes on `AD-17`

Found doing the work rather than reading the code: porting the `company-atlassian` MCP POC to the
current recipe format. The POC declared two inputs, an API token and an account e-mail. The token
went through unchanged. The e-mail did not:

```
error: inputs[0].type must be 'secret'
```

`setup.py:584` allows one value and no other. There is no `text`, no `choice`, no default, no
optional flag.

### Why the restriction exists

It is not an oversight, and the protocol document says so. Secrets-only is what makes the rest of the
model hold. A declared input can be interpolated by exactly one module — `macos-keychain.store@1` —
and `_contains_secret_interpolation` (`setup.py:366`) walks every other step's configuration to
refuse a recipe that mentions one anywhere else. The value itself never passes through AART at all:
the planned argv ends `-w` with nothing after it, so `security` does the prompting and the value goes
from the keyboard into the Keychain. That is a good design and this finding is not asking for it to
be relaxed.

### What it costs

Three homes exist for a non-secret per-user value, and each is wrong in its own way.

**Author it into the recipe.** Right for the Jira and Confluence URLs, which are the same for
everyone in the company and now sit in `payload/mcp.json` as literal arguments. Wrong for anything
that differs per person.

**Read it from the environment.** Only works if the company already exports it, which is a fact about
the fleet, not about the artifact.

**Put it in the Keychain with the secrets.** What the port does, because it is the only one that
works everywhere. The colleague is then asked for their own e-mail address at a prompt with no echo,
grants macOS a Keychain access for it, and sees the step reported as not automatically reversible.
Nothing breaks. It just describes an e-mail address as a credential, and the person doing it can tell.

### The ask

A second input type with the same review and the same refusal to interpolate into arbitrary places —
prompted, echoed, and usable by the modules that write managed files. `shell.env-from-keychain@1`
would then have a sibling that exports an authored value, and the Keychain would hold only the things
that belong in it.

Until then the pattern to copy is the one in
[`../tutorials/mcp-servers-into-the-registry.md`](../tutorials/mcp-servers-into-the-registry.md) §5.4:
put it in the Keychain, and say plainly in `SETUP.md` that the prompt is hidden. The friction is
small. Discovering it alone, mid-install, is what makes it a finding.

## Notes on `AD-18`

Raised by the raiser reading the `artifact.json` this stream had just written for their own company
MCP server: they did not like seeing `m1f1` in it.

The name comes from the repository owner. `pyproject.toml` gives
`Homepage = "https://github.com/M1F1/agent-artifacts"`, and `com.m1f1.` is that owner in reverse-DNS
form. So it is consistent rather than arbitrary. It is also personal, and it is in a published
protocol key.

### Why the namespace is the wrong one

A namespaced extension key exists to answer one question: **who defines this field, so that two
parties can add fields to the same document without colliding.** `com.example.thing` means
*example.com owns the meaning of `thing`*.

This key is not a third party's. `RUNTIME_REQUIREMENTS_EXTENSION` is a constant in AART
(`consumer/runtime_requirements.py:31`); AART parses it, AART evaluates it, `aart marketplace health`
is the only thing that reads it. It is a first-party field wearing a third-party namespace, and the
party it names is a person rather than the project.

`docs/marketplace/runtime-requirements-v1.md` explains at length why the data lives in an *extension*
rather than a core field — older readers preserve namespaced extensions, so the addition breaks no
protocol-v1 consumer. That reasoning is sound and unaffected. It simply never says anything about the
`m1f1` half.

### Where it shows

Seven files in the repository mention the string, of which one is the constant, one a test, one a
fixture and the rest documentation. That is not the cost.

The cost is that it appears in **every `artifact.json` that declares a runtime requirement**, which
means every company package that needs Docker or a particular Python. The raiser met it while
reading their own registry's manifest, and *company package declaring a personal namespace* is a
reasonable thing to object to when the point of the exercise is to publish AART inside a company.

It is also the field most likely to outlive the choice: if the repository ever moves to an
organization, the key stays behind as the one place the old account name is frozen into other
people's files.

### What renaming costs

Not the edit. Renaming a published protocol key is the cost, and this project's standing rule is that
there is one live revision of any protocol — a superseded one is rejected with a migration error, not
read alongside the new one. So the change is: rename the constant, reject the old key with a
diagnostic naming the new one, update the fixture, the test, the two protocol documents, the
changelog and the tutorial. A registry that carries the old key rebuilds; nothing installed breaks,
because the data was never load-bearing.

Suggested replacement: **`aart.runtime-requirements`**. It satisfies the extension pattern
(`^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$`), it names the party that actually defines the field, and
it does not encode where the repository happens to be hosted this year.

## Notes on `AD-19`

### What was being done

Publishing the ported `company-atlassian` package: authoring the payload, then running
`aart registry vendor mcp company-atlassian --source . …`. The command stopped with one line:

```
error: registry mutation requires a writable local Git checkout
```

No remediation, no path, no second line.

### The two ways to earn it

Both were measured on `2026-08-17`, each on a copy of the working lab registry.

**A registry that is not a Git checkout.** Copy the registry, delete `.git`. Read commands still
work — `registry validate` runs and reports on the lock and index as usual. `registry vendor … --yes`
prints the line above and stops.

**A registry inside a Git checkout, one level down.** Put the registry at `<repo>/registry/` and
`git init` at `<repo>/`. From inside `registry/`, `git rev-parse --is-inside-work-tree` prints
`true`. The same mutation is refused with the same line.

The second one is the interesting one, because the message is then simply false as read: it *is* a
writable local Git checkout, and the tool says it is not.

### What the check actually requires

`_writable_checkout` (`agent_artifacts/io/registry_workspace.py`, lines 200-232) has three parts, in
order:

1. `--source` resolves to a real directory that is not a symlink;
2. `os.stat(self.root / ".git")` succeeds and yields a directory or a regular file that is not a
   symlink;
3. only then, `git -C <root> rev-parse --is-inside-work-tree` prints `true`.

Step 2 is the one nobody guesses. It requires `.git` **at the `--source` path itself**, so the
registry has to be the repository root. Step 3, the part that would accept a subdirectory, is never
reached in that case.

The rule is defensible — a registry that owns its own history is easier to review, and it keeps a
mutation from writing into a repository whose root is somewhere unexpected. It is not the rule the
message states.

### Why there is no remediation line

`_error` in that module is:

```python
def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))
```

It takes no remediation and no call site in the file supplies one, so **every** diagnostic raised by
the registry workspace is bare. Its neighbours in `registry_commands/planning.py` all carry
remediation, which is why the absence reads as an omission rather than a style.

### When it is met

At the first publish, and not before. `registry init`, authoring the payload, writing
`setup/installer.json`, `registry validate` — none of them touch the check. The wall appears after
the package is finished, which is the worst moment to discover that the directory layout was wrong.

### The workaround, for now

If the registry is meant to be its own repository:

```
git init
```

in the registry root, then re-run the vendor command. If it lives inside a larger repository, it has
to be split out — there is no flag for it.

### Asked for

One remediation line that separates the two causes: *initialise a repository here with `git init`*,
versus *the registry must be the repository root; `<path>` is inside a checkout rooted at `<root>`*.
The second half is cheap — the code already knows, because `rev-parse` would tell it.

## Notes on `AD-20`

### What was being done

Vendoring the ported MCP server. `AD-19` was cleared by putting the registry in its own Git
checkout, the same command was re-run, and it stopped again:

```
error: a vendored mcp needs payload/mcp.json; the taken subtree does not contain it,
so the maintainer supplies it
```

The sentence is correct and complete about the problem. It says nothing about the remedy beyond
naming the person responsible for it.

### Why *where* is the hard part

Three things make the location non-obvious, and the message addresses none of them.

The path is **package-relative, not registry-relative**. `payload/mcp.json` as printed is relative to
`artifacts/mcp/<NAME>/`, so the file goes at `artifacts/mcp/<NAME>/payload/mcp.json`. Read as a path
from the registry root — the directory the command is being run in — it is wrong.

The directory **does not exist yet**. A first vendoring creates the package, so the natural reading
is that the file should end up in the upstream subtree, or be passed by a flag. Neither is true:
`plan_artifact_vendor` adopts whatever the maintainer has already placed at the target path
(`registry_commands/planning.py`, lines 705-725) and no flag can carry file bytes.

The ordering is **author first, then vendor**, which is the reverse of what building a package feels
like. This stream's own tutorial had it backwards until testing corrected it.

### Five projections

Measured `2026-08-17` by calling `project_vendored_package` directly over one synthetic upstream
subtree holding `launcher.sh`, `README.md` and `server.py`.

| Authored at the package path | Upstream subtree | Result |
|---|---|---|
| nothing | three files | `a vendored mcp needs payload/mcp.json …` |
| `payload/mcp.json` | three files | accepted; six files written |
| `mcp.json` at the package root | three files | `authored file is not canonical package content: mcp.json` |
| `payload/mcp.json` | three files **plus** its own `mcp.json` | `authored file collides with the taken subtree: payload/mcp.json` |
| nothing | three files **plus** its own `mcp.json` | accepted; upstream's copy is shipped |

The last two rows are the trap. Whether authoring `payload/mcp.json` is the fix or the error depends
on whether upstream happens to ship a file of that name — something the maintainer has no reason to
have checked, because the wrapper is the part they expect to write themselves. The refusal that
sends them to author it does not mention that the opposite case exists.

The collision rule itself is right: overwriting a taken byte would mean reviewing upstream content
that is not the content the registry ships. It is stated in the code and nowhere the maintainer
reads.

### Same omission as `AD-19`, one module over

```python
def _error(message: str, path: str | None = None) -> Err:
    return Err((Diagnostic(ARTIFACT_INVALID, Severity.ERROR, message, SourceLocation(path=path)),))
```

No remediation parameter, and the `path` that is available is passed by no call site in the file.
Every refusal `registry_maintenance/vendoring.py` can raise — and there are around thirty — arrives
bare. `AD-19` found the same thing in `io/registry_workspace.py`. Two modules on the publishing path
lost their remediation lines while their neighbours in `registry_commands/planning.py` kept theirs.

### Asked for

The package-relative path in the message, so it reads *author it at
`artifacts/mcp/<name>/payload/mcp.json` before vendoring*. And a second clause on the collision
refusal saying that upstream already provides this file and the authored copy should be dropped —
which turns two dead ends into two instructions.

## Notes on `AD-21`

### What was being done

Installing the finished `mcp/company-atlassian` from the TUI — the interface the walkthrough tells a
colleague to start with. The row would not select:

```
cannot select this row: setup capabilities are unavailable:
docker-build, keychain, managed-file, network, process, trust-store, verify-command
```

The first reading is that the package asks for too much, or that the machine lacks something. Both
are wrong. The machine is never consulted.

### The list is proof the package is correct

Those seven names are not what the recipe declares. An author writes `keychain`, `filesystem`,
`docker`, `network`, `process`, `trust-store` — the author's vocabulary. Policy speaks a different
one, and `_PLANNED_CAPABILITIES` (`agent_artifacts/setup.py`, lines 115-128) translates module by
module:

| Step in `installer.json` | Module | Planned capabilities |
|---|---|---|
| `docker_running` | `command.verify@1` | `verify-command` |
| `company_ca` | `trust-store.export-certificates@1` | `trust-store` |
| `image` | `docker.build@1` | `docker-build`, `network`, `process` |
| `store_username`, `store_token` | `macos-keychain.store@1` | `keychain` |
| `shell_env` | `shell.env-from-keychain@1` | `managed-file` |
| `restart` | `restart.notice@1` | none |

Sorted, that set is `docker-build, keychain, managed-file, network, process, trust-store,
verify-command` — character for character what the TUI printed. Computed `2026-08-17` from the table
itself. The package is well-formed and the recipe compiles; what the message reports is the whole of
what the recipe needs, because the side it is compared against is empty.

### The empty side

`tui.py`, lines 1775-1780, is the only place in the codebase that builds a `MarketplaceTarget`:

```python
MarketplaceTarget(
    tuple(sorted(session.profiles)),
    "darwin" if sys.platform == "darwin" else "linux",
    scope,
    session.install_mode,
)
```

Four positional arguments. The fifth field, `setup_capabilities`, is not passed, and its dataclass
default is `()` (`tui_marketplace.py`, line 59).

`_compatibility` (`tui_marketplace.py`, lines 228-239) hands that empty tuple straight into
`evaluate_compatibility` together with `require_setup=True`, hard-coded. `compiler/graph.py`, lines
837-849, then lists every declared capability as missing, and `compatible` is

```python
self.payload_compatible and (self.setup_compatible or not self.setup_required)
```

so with `setup_required` forced true, the row is unselectable. **Any recipe using any module except
`restart.notice@1` — the one module that needs nothing — fails this.** It is not specific to this
package or this machine.

### One unset field read two opposite ways

The field that should have filled the target exists: `allowed_setup_capabilities`
(`configuration/model.py`, line 177), an organization-policy list, default `None`.

The setup engine reads it correctly (`setup_engine/application.py`, lines 279-287):

```python
allowed = effective.policy.allowed_setup_capabilities
if allowed is not None:
    ...
```

`None` means *no organization restriction*, so everything is permitted. That is the right reading of
an unset policy.

The TUI never reads it at all, and its own default — an empty tuple — means *nothing is permitted*.
So the same absence of an organization policy means everything on the half that actually performs
setup, and nothing on the half that lets you choose it. The gate does not enforce a policy; it
enforces the absence of one.

### The CLI is unaffected

`installation/application.py`, lines 1012-1020, builds its target with `require_setup=False`, so the
setup capabilities never enter the install decision there. `marketplace install --yes` installs the
same artifact, and `setup run` then applies real policy through the engine above.

That is the workaround and it is also what makes the finding `high` rather than `blocking`: the
capability is reachable, just not from the interface a newcomer is pointed at. Under `AD-09` the TUI
is already the only place usage reporting is offered, so *use the CLI instead* costs more than it
sounds.

### Asked for

Pass the effective policy's `allowed_setup_capabilities` into the target, with `None` meaning
*everything*, exactly as `setup_engine/application.py` reads it. And when the gate does fire, say
which side is empty — a message naming seven capabilities the recipe needs, without a word about
what the target offers, sends the reader to audit their own package.

## Notes on `AD-22`

### What was seen

`marketplace install … --yes` succeeded from the CLI, as `AD-21` predicted it would, and setup then
declined:

```
Setup not planned: registry/mcp/atlassian@1.0.0#tabnine/project
  reason  setup from unverified requires explicit source authorization
  manual instructions  SETUP.md
  manual source        https://github.dev.…/agent-artifacts-registry/
                       blob/fd491ca5033d806d4d9f456694d81392479ef5f8/SETUP.md
```

The refusal itself is correct behaviour and not the finding. The link is.

### Two roots, one relative path

`_manual_source_url` (`setup_engine/application.py`, lines 247-256) builds a web root from
installation provenance:

```python
return f"https://{host}/{repository}/blob/{source.resolved_commit}"
```

That is the **repository** at a commit. `manual_reference` (`setup.py`, lines 1042-1055) then appends
`item.installer.manual_path`, and `_manual_path` (lines 322-327) derives that as exactly `"SETUP.md"`
for the canonical `setup/installer.json`. It is **package-relative**. Nothing between the two
contributes `artifacts/<kind>/<name>/`.

Reproduced `2026-08-17` against the raiser's own output:

| | |
|---|---|
| `_manual_path("setup/installer.json")` | `SETUP.md` |
| origin matches `_PINNED_SOURCE_URL` | yes |
| composed | `…/blob/fd491ca…/SETUP.md` |
| the file is at | `…/blob/fd491ca…/artifacts/mcp/atlassian/SETUP.md` |

The composed line is character-for-character what the command printed.

The local branch of the same function is right. `_contained_manual_path` joins the same relative path
onto `item.source_root`, and that root *is* the package root, so the on-disk route resolves. One
relative path, two different roots, one of them wrong — and the wrong one is the branch that fires
for a real Git-backed registry, which is every company installation.

### Why it matters more than a broken link usually does

This message appears only when the automated route has just refused. The reader has nothing else at
that point. Handing them a 404 at the exact moment their fallback is the only route left is worse
than printing no URL at all, because a missing URL sends them to the repository to look, and a
present one sends them to a page that says the file does not exist.

### The third remediation-free module

```python
def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, _redact(message)),))
```

`setup_engine/application.py`, lines 104-105. No remediation parameter, no call site naming a flag.
So `setup from unverified requires explicit source authorization` never says
`--authorize-untrusted-source`, which is the flag that resolves it — and it is not a flag anyone
guesses, because it reads as a security override rather than the ordinary answer to *this registry
has no approved review record yet*.

`AD-19` found this in `io/registry_workspace.py`, `AD-20` in `registry_maintenance/vendoring.py`, and
this is the third. All three sit on the path from authoring a package to running it. It is worth
treating as one repair rather than three.

### Asked for

Compose the manual URL from the package root, not the repository root — the installation record
already knows where the package sits, because the local branch of the same function uses it. And a
remediation line on the trust refusal naming `--authorize-untrusted-source`, together with the
durable alternative: an approved review record on the registry entry raises trust to
`registry-reviewed`, which the gate at `setup_engine/application.py:272-278` lets through without any
flag at all.

## Notes on `AD-23`

### What was measured

`2026-08-17`, isolated `HOME`, a registry configured as a local source holding the ported MCP server:

```
$ aart marketplace install company/mcp/company-atlassian --profile claude --scope project --yes
Install outcome: succeeded
  Selected: 1; changed=1
  - company/mcp/company-atlassian@1.0.0#claude/project: changed · setup pending
Setup not planned: company/mcp/company-atlassian@1.0.0#claude/project
  reason  setup from local requires explicit source authorization
Setup: planned=0, failures=1
$ echo $?
1
```

`.mcp.json` and `.agent-artifacts/` were both written. The install is real and correct. The exit code
says it failed.

### Where the exit code comes from

`commands/marketplace.py`, lines 616-626:

```python
setup_ok = True
if action == "setup" or any(item.setup_status == "pending" for item in outcome.items):
    setup_payload, setup_ok = _run_setup_queue(request, service.value, review, outcome)
    ...
if outcome.session_status in {"failed", "partial"} or not setup_ok:
    return _common.ERROR
```

So any installed artifact with a pending setup drags the setup queue's verdict into the install's
exit code. `_run_setup_queue` (lines 436-437) returns `not queue.failures`, and the trust gate at
`setup_engine/application.py`, lines 272-278, refuses `unverified`, `local` and `direct-source`
outright unless `authorize_untrusted_source` is set.

### The part that makes it unavoidable

`marketplace setup` accepts `--authorize-untrusted-source`, `--authorize-custom-entrypoint` and
`--approve-setup-effects`. `marketplace install` accepts none of them — checked against
`install --help`, whose only match for *authorize* is `--force`, which is about overwrites.

`_run_setup_queue` reads `request.authorize_untrusted_source` regardless, and from `install` that
value can only ever be false. So the command runs a queue it is not equipped to authorize, and
returns its failure.

Three trust classes hit this, and they are the three a company registry passes through on its way to
being trusted: a local checkout while the maintainer tests, a direct Git source, and a registry whose
entry has no approved review record yet. Only `registry-reviewed` and `company-reviewed` avoid it.

### Why `high`

This stream exists to produce adoption scripts whose only dependencies are `aart` and `git`. Such a
script runs under `set -e`, and a correct install now aborts it at the first artifact that declares
setup — which is every artifact worth scripting, since the ones with no setup need no script.

The obvious repair is worse than the defect. `aart marketplace install … || true` restores the flow
and simultaneously discards every genuine install failure: a missing coordinate, an incompatible
platform, a digest mismatch. The alternative, matching on stdout text, makes the script depend on
message wording.

There is a correct workaround and it is not obvious: install and set up as two commands, and let only
the second one's exit code mean anything.

```
aart marketplace install <coord> --profile <p> --scope <s> --yes
aart marketplace setup   <coord> --profile <p> --scope <s> \
     --authorize-untrusted-source --approve-setup-effects --yes
```

The first still exits `1`. The script has to tolerate it and check the second — which is exactly the
reasoning a colleague should never have to reconstruct.

### Asked for

An install's exit code should report the install. A setup queue this command has no flags to
authorize is a **pending** state, already printed as `setup pending` in the very same output, and
reporting it twice — once as a status and once as a failure — is what makes the two disagree.

## Notes on `AD-24`

### What was seen

Setup reached the two Keychain steps and the terminal showed, with nothing else on it:

```
password data for new item:
retype password for new item:
```

and then the same two lines again.

Four prompts, two values, no labels. The person typing has to remember, from a review they read
several minutes and one Docker build ago, that the first pair is an Atlassian e-mail address and the
second is an API token.

### AART knows and does not say

`setup.py`, lines 743-770, builds both of these at plan time:

```python
target = f"Keychain generic password service={service!r} account={account!r}"
...
summary = f"Store {target}; the security tool prompts without echo{replacement}"
```

They appear in `setup review`. At apply time, `_keychain_apply` (`setup_runtime.py`, line 246) does:

```python
result = runtime.process(effect.argv, env=env, cwd=None, timeout=120, capture=False)
```

`capture=False` hands the terminal to `security`, which prints its own generic prompt. Nothing of
AART's own is printed first. The string that would answer the reader's question is computed, stored
on the effect, rendered in one place, and withheld in the only place it is needed.

### Why this is `high` rather than cosmetic

Getting the order wrong is silent and it is not recoverable by observation.

Both steps succeed — `security` accepts any bytes. `setup receipt` records two stored items. The
shell block exports both variables. Everything reports green. The e-mail is now in the service named
`…/api-token` and the token in `…/username`, and the first symptom is an authentication failure from
Atlassian, far enough away that nobody connects it to two anonymous prompts.

Undoing it requires knowing which service holds which value — the thing the prompts declined to say.

It also lands on the exact person this stream is about. The maintainer who wrote the recipe knows the
order. The colleague running it has never seen the recipe.

### Relation to `AD-17`

`AD-17` is that a setup recipe can prompt for a secret and nothing else, so a non-secret per-user
value — the e-mail — has to be stored as one. This is the next problem along: the slot it is forced
into is anonymous. Fixing `AD-17` would remove one of the two prompts here and fixing this would make
both legible; neither subsumes the other.

### Asked for

Print the step's own `summary` immediately before yielding the terminal. It exists, it is already
redacted for review, and it names the service, the account and the purpose.

## Notes on `AD-25`

### What was seen

After the effects ran:

```
setup state persistence failed; applied effects were compensated
```

That is the whole of it. The effects were undone, the run cost stands, and there is nothing in the
message to act on.

### Five causes, one sentence

`persist_setup` (`setup_engine/io.py`, lines 89-187) can fail in five distinct ways, each with its
own diagnostic:

| Diagnostic | What it means | What the reader should do |
|---|---|---|
| `installed payload state is unavailable during setup persistence` | the install record cannot be read | check the install, re-install |
| `installed payload changed before setup persistence` | something re-installed underneath the run | re-run setup; nothing is wrong |
| `setup persistence preconditions cannot be inspected` | a path could not be stat-ed | permissions, disk |
| `setup state or object reference changed after Review` | the plan is stale | re-review and re-run |
| `cannot persist canonical setup state: <OSError>` | the write itself failed | disk, permissions — the real error text is here |

The last one can carry `; rollback incomplete: …`, which is the one case where something is left
behind.

`finalize_setup` (`setup_engine/application.py`, lines 690-708) does this with it:

```python
persisted = ports.persist_setup(plan, applied, expected_record=plan.previous_record)
if isinstance(persisted, Err):
    recovery = rollback_record(applied, runtime) if applied.receipt else applied
    status = ... FAILED or ROLLBACK_INCOMPLETE
    return Ok(_outcome(plan, status, "setup state persistence failed; applied effects were compensated" ...))
```

`persisted.diagnostics` is never read. The only thing that varies the message is whether the rollback
finished, which is a different question from why the persistence failed.

### Why the placement makes it worse

This message arrives *after* every effect has been applied and then compensated. The Docker build ran.
The certificates were exported. The credentials were typed at an unlabelled prompt (`AD-24`). All of
it was undone, correctly. What the reader has to show for it is one sentence that does not
distinguish *run it again, it was a race* from *your disk is full*.

`AD-22` recorded that this module's `_error` takes no remediation. This is the same module discarding
a diagnostic it already holds.

### Asked for

Propagate the diagnostic. It is constructed, it is redacted, and it is thrown away one frame above
where it was made.

### `AD-25`, addendum: the receipt is lost too

`marketplace receipt show` exists precisely for this question — its help reads *print the persisted
setup record … plan hash, timings, exit status, and each step with its module, target and
disposition*. It cannot answer here.

The persistence-failure path returns `state_written=False` (`setup_engine/application.py`, line 705),
so no record is written. The single run whose per-step disposition the reader most needs is the only
run that leaves nothing behind. Both routes to the cause — the discarded diagnostic and the unwritten
receipt — close at the same moment, for the same reason.

Confirmed `2026-08-17` while trying to answer *did it fail on the `~/.zshrc` write?* from the
outside. It cannot be answered from AART's own records; it has to be answered by looking at
`~/.zshrc` itself.

## Notes on `AD-26`

### How it was found

Raised as a hunch — *I think it fails on the `~/.zshrc` write* — while trying to interpret `AD-25`'s
featureless message. The hunch was right and the confirmation was one command on the raiser's own
machine: `ls -l ~/.zshrc` shows an arrow.

That is worth recording on its own. The person running the setup diagnosed it faster from a suspicion
about their own dotfiles than either the diagnostic or the receipt could (`AD-25`), because neither
was able to say anything.

### The refusal is right

```python
def _read_regular_text(path: str) -> tuple[str, bool, Optional[int]]:
    if os.path.islink(path):
        raise RuntimeError(f"refusing to edit symlink: {path}")
```

`setup_runtime.py`, lines 194-196. Writing through a symlink writes to a file the review never named,
possibly outside the home directory entirely. Refusing is the only defensible behaviour and this
finding does not ask for it to change.

Verified `2026-08-17` against the function directly:

| Target | Result |
|---|---|
| symlink | `refusing to edit symlink: …` |
| regular file | accepted, mode preserved |
| missing | accepted, treated as empty |

So the single unsupported shape is the one a dotfiles repository produces — which is how most of the
developers this stream is aimed at keep their shell configuration.

### The timing is not

`plan_setup` (`setup.py`, lines 887-895) is documented as resolving *exact non-secret effects and
binding them to a deterministic plan hash*, and it reads nothing from the filesystem. That is
deliberate and correct: a plan hash that varied with local state could not be compared against a
review, and `--expect` would be meaningless.

The consequence is that the review prints `~/.zshrc` as the target of a write that cannot succeed,
with no qualification. And nothing between the review and the first effect stats it either — the
first contact with the path is the step itself, sixth of seven.

By then the reader has run `docker info`, exported certificates, waited out an image build through a
corporate proxy, and typed two credentials into unlabelled prompts (`AD-24`). All of it is then
compensated. One `lstat` before the first step would have cost nothing and saved all of it.

### There is no way through

The module takes `file` and `variables` and nothing else — no follow-symlink option, no fallback
target, no *write beside it instead*. And the recipe author cannot choose correctly on the reader's
behalf, because whether `~/.zshrc` is a symlink is a property of the person's machine, not of the
artifact.

The shape that works is a file the artifact owns, which the reader sources from their dotfiles
repository once, by hand:

```json
{ "id": "shell_env", "use": "shell.env-from-keychain@1",
  "with": { "file": "~/.aart-atlassian.zsh", "variables": { … } } }
```

`_resolve_target` (`setup.py`, lines 702-709) accepts any `~/…` path, so this needs no code change —
only a recipe that stops assuming it may edit the reader's shell configuration directly. That is
probably the better default for a company registry regardless: an artifact that owns its own file can
be removed cleanly, and it never contends with whatever else manages the dotfiles.

### Asked for

A preflight between the reviewed plan and the first effect that stats every managed-file target and
refuses before anything runs. It sits outside the plan hash, so determinism is untouched, and it
turns a late compensated failure into an immediate one that names the file.

## Notes on `AD-27`

### The loop this breaks

Edit `installer.json`. Delete the files vendoring derives and the files it copied. Re-run `vendor` at
the same version. Publish. Update the consumer. Run setup. Read what happened. Repeat.

That is the ordinary loop for getting a setup recipe right, and it is the loop the raiser was in. It
terminates after the first successful setup. Every iteration after that ends with

```
setup state persistence failed; applied effects were compensated
```

no matter what the recipe says.

### Reproduced without Docker or Keychain

Built `2026-08-17` in an isolated `HOME`: a probe MCP artifact whose whole recipe is one
`file.managed-block@1` step writing `export AART_PROBE=1` into a file it owns. Nothing to prompt for,
nothing to build.

| Step | Result |
|---|---|
| install, then setup | `configured=1, failures=0` |
| setup again, unchanged | `already-configured` — fine |
| change the block content, re-publish, `update --force`, setup | **`setup state persistence failed`** |
| repeat that setup | same, every time |

The third row is the finding. Nothing about it depends on Docker, the Keychain, the trust store, or a
symlinked dotfile — the failures this stream chased for two days on a seven-step recipe reproduce on
a one-step one.

### The cause, recovered by instrumenting

`AD-25` throws the diagnostic away, so it had to be read by wrapping `persist_setup`:

```
>>> REAL CAUSE: ['setup state or object reference changed after Review']
>>> owner: sha256:539991e1…  | plan: sha256:be08b1d5…  | match: False
```

`setup_engine/io.py`, lines 139-141:

```python
reference_matches = _owner_digests(references.value, plan) == (plan.object_digest,)
```

And the consumer's reference index at that moment:

```json
{"digest": "sha256:be08b1d5…", "kind": "installed", "owner": "project/lab/mcp/probe/claude"}
{"digest": "sha256:539991e1…", "kind": "setup",     "owner": "setup/setup-aa6f772c…"}
```

`update` moved the `installed` reference to the new object and left the `setup` reference on the old
one. Nothing moves it, and the check treats the mismatch as evidence that something changed
underneath the review rather than as the ordinary consequence of updating an artifact.

**The version appears nowhere in this.** The check compares object digests, so re-vendoring at the
same `1.0.0` with one byte different is indistinguishable from a version bump. There is no way to
edit a recipe that avoids it.

### Nothing gets you out

| Attempt | Result |
|---|---|
| run setup again | identical failure |
| `marketplace receipt undo` | `lab/mcp/probe is installed and no setup run has been recorded for it` |
| `uninstall` then `install` | stale reference survives; setup still fails |

The second row is `AD-25` closing the exit behind itself: the command built to reverse a setup needs
a persisted record, and the runs that fail persistence write none. The third leaves an orphaned
`state/setup/setup-<id>.json` that no installation points at any more, while planning recomputes the
same deterministic owner id and finds it again.

### The escape, and its own trap

Editing consumer state by hand is the only route found:

1. remove the `"kind": "setup"` entry from
   `~/Library/Application Support/agent-artifacts/state/object-references.json`;
2. delete `~/Library/Application Support/agent-artifacts/state/setup/setup-<id>.json`.

Setup then reported `configured=1`.

The trap is in step 1. Rewriting that file re-indented is refused:

```
failed — cannot retain transaction object reference: object reference index is not canonical
```

It has to be written back compact, with sorted keys and a trailing newline. So the only workaround
for a `high` defect requires knowing an unwritten serialization rule, and getting it wrong produces a
different error that says nothing about formatting.

It also costs the record of whatever a previous successful setup applied: any effect that run owned —
a managed block, a Keychain item — stays on disk with nothing claiming it.

### Asked for

Move the `setup` reference with the object, the way the `installed` one already moves. Failing that,
treat a `setup` reference pointing at a superseded digest as replaceable rather than as evidence of
tampering — the digest it points at is one the same run is about to stop using.

### `AD-23`, addendum: `update` is affected the same way

The finding was recorded against `marketplace install`. `marketplace update` shares `_action` and so
shares the defect. Measured `2026-08-17` on the probe artifact with its setup pending:

```
$ aart marketplace update lab/mcp/probe --profile claude --scope project --force --yes
Update outcome: no-op
  Selected: 1; current=1
  - lab/mcp/probe@1.0.1#claude/project: current · setup pending
Setup not planned: lab/mcp/probe@1.0.1#claude/project
Setup: planned=0, failures=1
$ echo $?
1
```

An update that correctly determined there was nothing to do returns a failure code. Neither `install`
nor `update` declares `--authorize-untrusted-source`, so on any source below `registry-reviewed`
every one of these commands exits non-zero for the whole time an artifact's setup is pending — which
is from installation until setup is authorized, the exact window an adoption script runs in.

## Notes on `AD-30` and `AD-31`

### How it looked from the outside

Two days of `disconnected` in Tabnine, chased through four wrong hypotheses in order: the image tag,
the settings file, the environment inheritance, and the flag shape. The server had been starting the
whole time. It was authenticating as nobody.

### What the descriptor said

The vendored `payload/mcp.json` carried the shape every MCP example uses:

```json
"env": {
  "ATLASSIAN_USERNAME":  "${ATLASSIAN_USERNAME_EMAIL}",
  "ATLASSIAN_API_TOKEN": "${ATLASSIAN_API_TOKEN}"
}
```

`installation/application.py:395-407` reads `descriptor["server"]` and hands it to the merge as the
value under `mcpServers.<name>`. Nothing between the registry and `.tabnine/agent/settings.json`
touches it. So those braces reach the harness intact, and whether they ever become a credential is
the harness's business. Tabnine's is not to expand them.

Twenty lines below, `:424-427`, the hook path builds its entry and **does** substitute — it replaces
`${SCRIPT_DIR}` in `command` with the resolved scripts directory. One projection interpolates and
its neighbour does not, in the same function, for the same reason an author would expect both to.

### What the recipe had, and could not give

The setup recipe did its half correctly. It prompted for the token, put it in the Keychain under
`aart/mcp/company-atlassian/api-token`, and wrote a shell block exporting `ATLASSIAN_USERNAME_EMAIL`
and `ATLASSIAN_API_TOKEN`.

The descriptor asked for `ATLASSIAN_USERNAME`.

Nothing compares those two vocabularies, because nothing models them as meeting. The recipe is
validated against the module table; the descriptor is validated as JSON. The name that has to match
between them is checked by neither, and a mismatch is not an error anywhere — it is an empty string
at runtime, inside a container, days later.

### Why it looked like it worked

The final hand-tuned entry passed the credentials as flags:

```
"--username", "ATLASSIAN_USERNAME",
"--api-token", "ATLASSIAN_API_TOKEN",
```

— the variable *names*, unexpanded and undecorated, as literal argument values. The image's
validation is a presence check on the flags, so it accepted them and started.

Confluence worked. Jira did not.

That asymmetry is the whole finding. A company Confluence commonly serves open spaces to anonymous
readers, because being readable is what it is for; a company Jira does not, because its contents are
records about people. One product answered, and answering read as configured.

Proven by substituting deliberate nonsense — `--username nikt --api-token bzdura` — and observing no
change in Confluence. The credential fields had no effect on the outcome, which is the definition of
not being used.

### What AART reported while this was true

`marketplace install`: `changed`. Setup: applied. The recipe's `verify-command` step: passed — it
verifies the setup's own effects, which were all genuinely correct. The Keychain entry was real. The
shell exports were real. Every stage was telling the truth about its own scope, and no stage owned
the question *can the thing we just installed do its job*.

The operator's only signal was one word in the harness, `disconnected` — the same word produced by a
missing image, a stopped Docker daemon, an unexpanded variable and a bad credential. It carries no
information, and it is the only thing the person gets.

### Asked for

`AD-30`: the descriptor needs a way to name a value the recipe collects, and the two vocabularies
need to be checked against each other at build or vendor time, when the author is still there. If
verbatim copying stays, then a `${...}` in an MCP descriptor should at minimum be surfaced in the
install review as *this harness must expand this; AART will not*.

`AD-31`: something has to test the installed server before the operator is told it is configured.
The recipe already has a `verify-command` module — it is pointed at the setup's effects rather than
at the artifact's purpose.
