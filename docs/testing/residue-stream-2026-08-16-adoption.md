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
| `AD-01` | low | `2026-08-16` | The Quick start offers exactly one way to install AART, and it is a developer's way: `python -m pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts`. A colleague who wants to *use* the tool has to clone the repository first, and then holds an editable install pointing at a checkout they will forget they are on. `pipx` and `uv` are how a Python CLI is installed today, and neither appears. Asked for: both added beside the `pip` line. |
| `AD-02` | medium | `2026-08-16` | The README never says what vendoring is. The word *vendor* does not occur in it — zero times in 219 lines — while `registry vendor` and `registry revendor` are shipped commands, `provenance.json` is a shipped document, and two designs exist for the mechanism. *Maintaining a registry* teaches `promote-native` instead, and `promote-native` is the one that requires the upstream repository to already declare `aart-source.json` — the precondition most repositories cannot meet, and the exact barrier vendoring was built to remove. A maintainer reading only the README concludes AART cannot take content from a repository that knows nothing about AART. Asked for: an explanation of vendoring in the README. |

## Notes on `AD-01`

The finding is filed as `low` because nothing is broken. It is at the top of this stream anyway,
because it is the first code block a colleague meets.

Two things to settle when it is fixed, not now:

1. **What the command installs from.** There is now a published wheel on a tag
   (`v2.6.1`), so `pipx install`/`uv tool install` can name a Git ref or a release asset rather than
   a local path. Which one is offered decides whether a reader needs a clone at all.
2. **Whether the editable line stays.** It is the right line for someone hacking on AART and the
   wrong one for someone adopting it. The likely shape is two labelled blocks — *install it* and
   *work on it* — rather than three commands in a row with no explanation of which is which.

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
