# Triage brief — what is broken, and whether 2.6.0 should ship

Derived from [`residue-register.md`](residue-register.md) on `2026-08-15`. The register says *what is
open*; this brief says *what it costs you and what to do about it*. When the two disagree, the
register is right and this file is stale.

## Verdict on 2.6.0

**Hold it for three fixes.** Not because the release is unsound — 1528 tests pass, nine gates are
green, and the schema freeze proves no boundary moved — but because all three land on the exact
feature the release is named after, and each is small.

| | Finding | Why it blocks *this* release specifically |
|---|---|---|
| 1 | `LAF-63` | A credential in free text is persisted unredacted, and `receipt show` is the command that prints it |
| 2 | `LAF-66` | `receipt verify` answers `true` about a directory it never looks in |
| 3 | `LAF-65` | The receipt tells the operator no command reverses a setup, in the release that ships one |

Releasing without them ships a reader that can print a secret, a verifier that passes what it cannot
see, and a record that contradicts its own executable. Every one of those is a claim about
trustworthiness, which is the only thing this release sells.

Two further facts belong in the decision, and neither is a reason to hold:

- **Two of the design's seven acceptance criteria were never walked** against published content
  (`LAF-67`). They were accepted against a local fixture in a unit test. That is a known, stated gap,
  not a suspected one.
- **No registry and no consumer repository has met this code** (`LAF-70`, `LAF-71`, `LAF-68`).
  Registry A's CI gates at `2.5.0`; Registry B and the acceptance repo are still at `2.0.0` with
  their moves sitting in unmerged PRs; the machine that authors registry content runs `2.0.0`.

## How to read the two numbers

**Severity** is what it costs when it bites — a property of the defect.

| | Meaning |
|---|---|
| **high** | A secret escapes, state is lost, or a command reports success or `true` when the opposite is true |
| **medium** | The product promises something in its own UI or docs that the code does not do; a human can recover by hand |
| **low** | Friction, dead code, or an undocumented limit; nothing is wrong, something is unhelpful |

**Priority** is when to spend on it — severity plus how likely it is to be met and how much it costs
to fix.

| | Meaning |
|---|---|
| **P1** | Before the next release. Lands on a feature that release advertises |
| **P2** | Next stream. Real, met by real users, but not on the current release's face |
| **P3** | When that area is next opened. Correct to fix, wrong to open the file for |

A **high/P3** is not a contradiction: it means the blast radius is large but the path there is narrow
and nobody is standing on it.

---

## By feature

Each section names the feature a user would say is broken, so you can decide per feature rather than
per finding.

### Credential handling — *"my token does not leave this machine"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-63` | high | **P1** | Redaction anchors on `\b(token\|password\|secret\|api_key)`, and in `GITHUB_TOKEN` there is no word boundary before `TOKEN`. Measured: `TOKEN=ghp_x` redacts, `GITHUB_TOKEN=ghp_x` does not; `secret=` redacts, `AWS_SECRET_ACCESS_KEY=` does not. The prefixed forms are the ones real recipes use |
| `RS-12` | medium | P2 | Setup process steps run without `HOME`, so Docker reads no `config.json` and a private base image cannot authenticate at all |

**On `LAF-63`.** Mapping *keys* are safe — that path matches by substring and catches `GITHUB_TOKEN`.
The gap is free text: a step `detail`, a build transcript, an error message. Those go through
`redact_text` to `dump_setup_state`, so the secret reaches **disk**, not only a terminal. 2.5.0 wrote
them. 2.6.0 adds `receipt show`, which renders `detail` (`setup_render.py:156`) — a second exposure
surface on a file that already had the problem.

The fix is the regex plus its tests, and
`tests/setup_render_test.py::test_laf63_a_prefixed_credential_name_is_not_redacted_today` already
holds the gap visible, so the change is small and its acceptance already exists. Tracked as `RR-2C`.

**Already written records are not cleaned by fixing the pattern.** Whatever is on disk stays there.
That is a second decision — a `receipt` action that rewrites, or an advisory in the release notes.

### Setup receipts: show, verify, undo — *the whole of 2.6.0*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-66` | high | **P1** | The orphan-run-directory probe scans `<project_root>/.agent-artifacts/setup-runs`; runs are created under `<data_root>`. The claim answers `true` in every scope without looking |
| `LAF-65` | medium | **P1** | The `rollback` line the record itself carries says *no command reverses a completed setup*. `receipt undo` is in the same executable that prints it |
| `LAF-61` | medium | P2 | A killed run leaves its working copy under the data root and nothing sweeps it. Was recorded `visible`; `LAF-66` took that back — nothing sees it |
| `LAF-58` | medium | P2 | An image tag that existed before a run keeps its name through an undo and points at what the run built. The earlier binding was never recorded, so nothing can restore it. The undo review does say so before consent |
| `LAF-67` | medium | P2 | No published artifact uses `docker.build@1`, so the `preexisting`-tag criterion and the failing-build criterion cannot be walked against published content at all |

**`LAF-66` is the one to care about.** The design's own §3.2 says *a verifier that quietly passes what
it cannot see is worse than no verifier*, and the three-status mechanism was built for exactly that.
It protects against **asking and failing**. It does nothing against **asking the wrong question
confidently**, which is what this is. Fix is the path the probe is handed; `LAF-61` becomes genuinely
visible the moment it lands.

**`LAF-65` is cheap and embarrassing.** A field this release *writes* carries a sentence this release
falsifies. Every record created from now on carries it. An operator who reads the receipt rather than
the release notes is told to do by hand what one command does.

**`LAF-67` is not a code defect** — it is the acceptance surface being assumed rather than derived. It
belongs here because it is why two criteria have no live evidence behind them, which you should know
before deciding what "tested" means for this release.

### Install and uninstall hygiene — *"uninstall leaves nothing behind"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-47` | medium | P2 | Uninstall leaves the `.mcp.json` it created, reduced to `{"mcpServers": {}}` |
| `RS-10` | medium | P2 | The same shape for any merge effect: the last uninstall leaves the merge file behind |
| `LAF-57` | low | P3 | The two installation routes agree on content and disagree on image identity |

These two are one defect. `DESIGN-readable-receipt.md` §5 claimed `receipt verify` would make them
observable; it does not — both are **install** effects and `verify` reads a **setup** record, whose
only claim for `json.managed-merge@1` is that the path exists, which is `true` for an emptied file
exactly as for a full one. That correction is recorded in the register rather than edited into the
design.

### Registry and source acquisition — *"I can vendor from any upstream"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-62` | medium | P2 | A `≤2.4.0` consumer cannot `source add` a registry rebuilt on `2.5.0`; it fails before any artifact is named. Deferred to the index-version boundary stream |
| `RS-03` | medium | P3 | A repository containing *any* symlink cannot be acquired at all — a bound stricter than the design rule states. Deferred |
| `LAF-43` | medium | P3 | Vendoring refuses a `file://` upstream, so `changed` and the symlink refusal cannot be rehearsed live. Deferred |
| `RS-01` | medium | P2 | An owned, non-vendored `mcp` package with a wrongly-shaped descriptor is never checked |
| `RS-08` | medium | P2 | A snapshot carrying a *malformed* `aart-registry.json` skips the identity comparison entirely |
| `RS-04` | low | P3 | `vendor` is create-only and its refusal cannot name `revendor`, the command that does adopt movement |

**`LAF-62` and `RS-03` bear directly on what you asked for next.** If the acceptance repo becomes an
upstream that registries vendor from, `RS-03` decides whether it may contain a symlink anywhere, and
`LAF-62` decides who can still read the registries afterwards.

### Diagnostics and reporting — *"when it refuses, it tells me what to do"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `RS-09` | medium | P2 | No `registry` refusal carries remediation at all — the field is empty in both renderers |
| `RS-07` | medium | P2 | `marketplace status` under a removed sole subscription refuses `no-source-configured` instead of reporting `source-unavailable` |
| `LAF-45` | medium | P2 | `audit --check-upstream` prints nothing when everything is current, so success is indistinguishable from a dropped flag |
| `LAF-49` | low | P3 | The allowlisted Git environment drops `https_proxy`, undocumented — behind a corporate proxy this fails with no hint |

`LAF-45`'s lesson was applied to the three new commands — a path with nothing to report says it
checked. `audit --check-upstream` itself is untouched, which is why the row is still open.

### Recipe format limits — *"I can express my setup"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `RS-11` | low | P3 | `inputs` accepts only `type: "secret"`; a recipe cannot prompt for a username |
| `RS-13` | low | P3 | No `shell.zshrc-managed-block@1`; the convenience module does not exist |
| `RS-14` | low | P3 | The format has no comment convention, and every `_comment` is refused |
| `RS-15` | low | P3 | A package cannot carry an auxiliary script at its root |

All four are the same decision deferred: the recipe format is closed and nothing may be added to it
without a protocol move. Worth opening together, as one format stream, or not at all.

### Front-end — *"the two skins behave the same"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-64` | medium | P2 | `_curses_install_scope` returns a `WizardInput` with `wizard=True` and an `InstallScope` without it. A new caller writing the obvious `isinstance` guard compiles, typechecks, and silently turns every successful selection into a cancel |

This one is worth its priority for a reason the severity does not show: it was found by writing the
*second* caller of a helper that had had one. It cost a debugging session and was caught only by a
test. The next second-caller pays the same cost.

### Release and acceptance process — *"the gates mean what they say"*

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `LAF-69` | high | P2 | `DOC009` fails a document that calls a `closed` finding open, and says nothing about one that calls an `open` finding closed. The dangerous direction is unchecked, and it fired: the register moved `LAF-61` to `open` and `docs-check` stayed green with two release documents still saying `visible` |
| `LAF-70` | medium | P2 | The machine that authors registry content runs AART `2.0.0` (`pipx`, from the v2.0.0 release wheel) while Registry A's CI gates that content at `v2.5.0`. The author's tool is older than its own gate, so content can pass locally and be judged by something else |
| `LAF-71` | medium | P2 | Every version-move is prepared and none lands. Registry B's move to `2.5.0` is open **PR #5**; the acceptance repo's is open **PR #1**. Both were raised, both were left |
| `LAF-68` | medium | P2 | The acceptance repo's `main` pins `2.0.0`, so its CI has never exercised `2.5.0`. The instance of `LAF-71` that a live run met |
| `RS-02` | low | P3 | `commands/registry.py` stamps dead `1.0.0`/`2.0.0` AART bounds on every non-`init` request |

**`LAF-69` is high and P2, which is the combination worth explaining.** Its blast radius is large — it
is the gate that decides whether the release documents can be trusted — but it fired once, was caught
by a human within minutes, and the fix is a design question rather than a predicate change: making
`DOC009` symmetric means teaching it to read a disposition out of prose, which is the thing the
register exists to stop documents doing. Fix it deliberately, not quickly.

**`LAF-70`, `LAF-71` and `LAF-68` are one defect with three faces**, and the version state across the
four repositories is not what a reader would guess:

| Repository | `main` pins | Move to `2.5.0` |
|---|---|---|
| Authoring machine (`pipx`) | `2.0.0` | never attempted |
| Registry A | `v2.5.0` | merged (`c472730`) |
| Registry B | `v2.0.0` | open **PR #5** |
| Acceptance repo | `2.0.0` | open **PR #1** |

Two of the three moves were written and neither was merged, and the one machine that authors content
for all of them is the oldest thing in the table — older than the CI that judges its output. Nothing
here has met `2.6.0` at all.

This is also the first place I got the facts wrong while writing this brief: I read both registries'
pins out of local working trees, and both were sitting on branches that disagreed with `origin/main`
— one seven commits behind, one *on* the unmerged PR. The corrected numbers are above. That mistake
is the reason the skill this brief comes with makes reading remote state a rule rather than advice.

### Dead weight

| ID | Sev | Pri | What actually happens |
|---|---|---|---|
| `RS-05` | low | P3 | `io/cache.py` is unreferenced by shipping code |
| `RS-06` | low | P3 | `DESIGN-upstream.md` carries no superseded banner |

---

## If you only do one thing

`LAF-63`. It is the only finding here where the failure mode is *a secret on disk and on a terminal*,
the fix is a regex and its tests, and the test that proves it is already written and currently
asserting the broken behaviour.

## If you want 2.6.0 out this week

`LAF-63`, `LAF-66`, `LAF-65` — one stream, all three small, all three on the release's own face. Then
re-walk scenarios 3 and 6 of
[`PROGRESS-live-acceptance-receipt.md`](PROGRESS-live-acceptance-receipt.md), which are the two the
fixes change, and ship with `LAF-67`'s two unwalked criteria stated in the release notes rather than
rounded up.
