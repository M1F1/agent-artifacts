# Splitting the PR check from the release check

**Status: built.** `.github/` matches this page. It records what was duplicated, the shape that
removed it, the two decisions taken, and the three things that are repository settings rather than
files — those are still Michał's to set, on every instance separately.

The whole design rests on one assumption: **`main` is protected and is reached only through a pull
request.** Everything below follows from that. If direct pushes to `main` are ever allowed again,
this shape stops holding, because nothing would then prove the source of a release.

## What ran before, counted

One commit that became a release set the full ten-gate suite going **four times**, on seven
interpreter passes:

| When | Workflow | What runs |
|---|---|---|
| push to the PR branch | `validate.yml` (`on: push`, no branch filter) | 10 gates × 2 interpreters |
| the same push, seen as a PR | `validate.yml` (`on: pull_request`) | 10 gates × 2 interpreters |
| merge lands on `main` | `validate.yml` (`on: push`) | 10 gates × 2 interpreters |
| the release button | `cut-release.yml` | 10 gates × 1 interpreter |

The first two are the same commit, checked twice, minutes apart. That is the classic double run:
`on: push` with no filter and `on: pull_request` both fire for a branch pushed inside the same
repository.

The eleven release checks run **twice per button press**. `scripts/cut_release.py` runs them as a
precondition, and the release action it then calls runs them again.

`release.yml` does not run at all in the button flow. The tag is pushed with the repository
token, and GitHub raises no workflow event for anything done with that token.

There was also a naming collision, now ended. Three different things were called *quality*: the
`validate.yml` workflow's `name:`, its jobs, and two more jobs inside `release.yml`. Nothing is
called that any more.

## The principle

**Each thing is proven once, by the run whose job it is.**

| What is being proven | Which run proves it |
|---|---|
| the source is correct | PR check |
| merging is safe | branch protection, not a run |
| the release may be cut | cut-release preconditions |
| the artefact is sound | the release job |

## The shape

| File | Name | Trigger | What it runs |
|---|---|---|---|
| `pr-check.yml` | `pr-check` | `pull_request` | all ten gates, on 3.10, 3.11 and 3.14 |
| `release.yml` | `release` | tag push, release published | release checks only |
| `cut-release.yml` | `cut release` | `workflow_dispatch` | gates, checklist, tag, release, wheel, index |

`validate.yml` was renamed, not merely retriggered: the file name, the workflow name, the job
names and the required check are all now one word, so a required status check can be named
without ambiguity.

### What the release run keeps

Only what has the release as its subject:

* the source version equals the tag (`version.py check-tag`)
* the tagged commit is an ancestor of `main`
* reviewed release notes exist and are not empty
* the eleven-item release checklist (`release.py check`)
* `packaging-check` — the one quality gate whose subject is the wheel rather than the source
* build, attach, publish

Everything else is dropped from the release path. A release is cut from a commit that reached
`main`, and nothing reaches `main` except through a PR that passed all ten gates.

### What the button stops doing twice

`cut_release.py` keeps the checklist, because it must run **before** the tag exists: the run
either produces a tag and a release or produces neither. The release action therefore needs a way
to be told the checklist has already run — an input, not a guess.

## Three things that are settings, not files

None of these can be committed. Each is set per repository, on every instance separately.

1. **Protect `main`.** Require a pull request; forbid direct pushes. Our own flow never pushes to
   `main` — the button pushes a *tag*, which branch protection does not block.
2. **Require the PR check.** Name the check that must pass before merge.
3. **Decide on "require branches to be up to date".** See the open decision below.

## Traps

**A renamed check silently blocks every merge.** Branch protection stores the check by *name*.
Rename the workflow without updating the required check and every PR waits forever for a job that
no longer exists. Rename and re-point in one sitting.

**The two-arm job pattern has no single name to require.** Every workflow here emits its job
twice — once plain, once with a `container.credentials` block — because that block cannot be made
conditional. Only one arm runs, so a required check naming one arm never passes on a fork that
uses the other. The fix is an aggregating job: one final job with `needs:` on both arms and
`if: always()`, which fails unless the arm that ran succeeded. That job's name is the one to
require, and it is the same name on every instance.

**Dropping gates from the release loses an interpreter.** The quality matrix was 3.10 and 3.14;
the release job runs 3.11, so the release run was the only thing that ever exercised 3.11.
Dropping the gates there would have taken that coverage with them, so 3.11 is now in the PR
matrix. A fork that sets `AART_PYTHON_VERSIONS` chooses its own list and this note does not
apply to it.

**Removing `on: push` means an unmerged branch gets no CI.** That is the intent, and it is worth
saying out loud: a branch pushed without a pull request is checked by nothing. Open the pull
request early if you want the branch checked while you work on it.

**Only Poetry builds the wheel now.** The packaging gate moved into the release run, and it
builds a wheel. An image without Poetry fails there. Name it in `AART_POETRY` if it is off
`PATH`; see docs/release/wheel-reproducibility-v1.md.

## The two decisions, taken

1. **No run on `main`, and branches must be up to date before merging.** Two pull requests can
   each be green and still break `main` together. The setting removes that at the source: a
   branch behind `main` cannot merge until it is brought up to date and checked again. The cost
   is re-running the check after every intervening merge, which is worth paying while merges are
   as infrequent as they are here. Revisit if that changes.
   **This is a setting, not a file.** Turn on "require branches to be up to date before merging"
   next to the required check. Without it there is no post-merge run to catch the pair, because
   `pr-check.yml` triggers on `pull_request` only.
2. **`cut-release` keeps its own gate run.** It is the second full run of a commit that is
   already green, and it is also the last check before something irreversible. It stays, and it
   is the run that covers the release interpreter.
   Because it runs them, the release action it then calls must not run them again: one input,
   `preconditions: "false"`, turns off both the eleven-item checklist and the packaging gate for
   that one caller. The default is `"true"`, so a path that has *not* run them cannot skip them
   by accident.

## What to require, exactly

One check name: **`pr-check`**. It is the aggregating job, and it is the same name on every
instance, which is the point — the two arms are named `gates` and `gates-private-image`, only one
of them ever runs, and requiring either by name would hang every pull request on the fork that
uses the other. The aggregator fails when the arm that ran failed, and also when *neither* arm
ran, which is what a mistyped `AART_IMAGE_USERNAME_SECRET` looks like.

## Not changing

The two-arm job pattern, the Enterprise variables, the composite actions, and the rule that the
button finishes the job itself rather than waiting for an event that never comes.
