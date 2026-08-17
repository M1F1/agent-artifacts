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
