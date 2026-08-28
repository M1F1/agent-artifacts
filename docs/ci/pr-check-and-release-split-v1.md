# Splitting the PR check from the release check

**Status: proposed, not built.** Nothing in `.github/` has changed. This page records what is
duplicated today, the shape that removes it, and the decisions that are Michał's rather than mine.

## What runs today, counted

One commit that becomes a release sets the full ten-gate suite going **four times**, on seven
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

There is also a naming collision worth ending. Three different things are called *quality*: the
`validate.yml` workflow's `name:`, its jobs, and two more jobs inside `release.yml`.

## The principle

**Each thing is proven once, by the run whose job it is.**

| What is being proven | Which run proves it |
|---|---|
| the source is correct | PR check |
| merging is safe | branch protection, not a run |
| the release may be cut | cut-release preconditions |
| the artefact is sound | the release job |

## The target shape

| File | Name | Trigger | What it runs |
|---|---|---|---|
| `pr-check.yml` | `PR check` | `pull_request` | all ten gates, full interpreter matrix |
| `release.yml` | `release` | tag push, release published | release checks only |
| `cut-release.yml` | `cut release` | `workflow_dispatch` | preconditions, tag, release, wheel, index |

`validate.yml` is renamed, not merely retriggered: the file name, the workflow name and the job
names all become one word, so that a required status check can be named without ambiguity.

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

**Dropping gates from the release loses an interpreter.** The quality matrix is 3.10 and 3.14;
the release job runs 3.11. Today the release run is the only thing that ever exercises 3.11. Drop
the gates there and that coverage goes with them — so 3.11 belongs in the PR matrix instead.

**Removing `on: push` means an unmerged branch gets no CI.** That is the intent, and it is worth
saying out loud: a branch pushed without a PR will be checked by nothing.

## Open decisions

1. **Is a post-merge run on `main` still wanted?** Two PRs can each be green and still break
   `main` together. Requiring branches to be up to date before merging removes that, at the cost
   of re-running the check after every intervening merge. Recommendation: require up-to-date
   branches and keep no `main` run. Revisit if merges become frequent enough to thrash.
2. **Does `cut-release` keep its own gate run?** It would be the second full run of a commit that
   is already green. It is also the last check before something irreversible. Recommendation:
   keep it, and let it be the run that covers the release interpreter.

## Not changing

The two-arm job pattern, the Enterprise variables, the composite actions, and the rule that the
button finishes the job itself rather than waiting for an event that never comes.
