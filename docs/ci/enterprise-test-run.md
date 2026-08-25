# Test-driving this branch on a GitHub Enterprise Server instance

[`enterprise-fork-v1.md`](enterprise-fork-v1.md) is the reference: every variable, and the three
things a variable cannot express. This page is the shorter thing — a checklist for standing the
whole setup up **once**, on a real company instance, before the design is trusted.

Everything below is a mirror, a variable, or a command. If you have to edit a file to make this
work, that is the finding, not the workaround.

## One setting that exists only until this merges

This branch is not on `main` and carries no tag of its own. The tag `v2.8.5` points at `main` and
does **not** contain this work. So the registry needs telling where to look:

| Where | Set | Why |
|---|---|---|
| The registry | `AART_REF` = `docs/ghe-ci-portability` | so its CI fetches this code instead of the tag the pin names |

`AART_REF` is the escape hatch written for exactly this: it overrides the pin, switches the version
check off, and says so in the run log rather than disagreeing quietly with a file still in the
repository. Delete it once a tag exists.

Nothing else about the walk is temporary. The fork's own CI runs on any branch it is pushed to, so
the fork needs no version of this note at all.

## Part A — the tool

### 1. Put AART on the instance

Which of these two you do depends on whether the instance already holds a copy.

**No repository there yet.** A fork through the web UI works where the instance can reach
github.com. Where it cannot, mirror:

```bash
git clone --mirror https://github.com/M1F1/agent-artifacts.git
```

```bash
git -C agent-artifacts.git push --mirror https://ghe.corp/platform/agent-artifacts.git
```

`--mirror` is what carries the tags and every branch. Tags are load-bearing: the git arm clones `v`
followed by the pin, so a mirror without tags leaves that arm unable to find any version.

**A repository is already there.** Do not point `--mirror` at it. `--mirror` makes the remote match
your local copy exactly, which means it force-updates every branch and **deletes remote refs your
copy does not have** — someone else's branch, a tag added on the instance. Push the one branch
instead:

```bash
git remote add ghe https://ghe.corp/platform/agent-artifacts.git
git push ghe docs/ghe-ci-portability
```

A branch name the remote does not hold yet is a new ref, so this cannot fast-forward-reject and
cannot overwrite anything. Add `git push ghe v2.8.5` if the existing copy has no tags and you also
want to walk the git arm without `AART_REF`.

**The default branch is not part of this.** `validate.yml` triggers on `push` with no branch
filter, so the push above starts a `quality` run on its own, and the registry reaches this code
through `AART_REF` rather than through whatever `main` says. Changing the default branch is
optional — worth avoiding on a repository other people are already using.

### 2. Set the fork's variables

**Settings → Secrets and variables → Actions → Variables.** On the organisation where you can.
Section 2 of the reference is the full table; the short list for a private runner with no egress:

| Variable | Set it to |
|---|---|
| `AART_RUNNER` | your runner labels, as JSON: `["self-hosted","linux","x64"]` |
| `AART_CI_IMAGE` | the company image, if jobs run in one |
| `AART_PYTHON_VERSIONS` | one entry, e.g. `["3.11"]`, whenever `AART_CI_IMAGE` is set |
| `AART_PIP_INDEX_URL` | the internal mirror, for `ruff`, `mypy` and `coverage` |
| `AART_GH_HOST` | the instance hostname, so `gh` does not talk to github.com |
| `AART_IMAGE_USERNAME_SECRET`, `AART_IMAGE_PASSWORD_SECRET` | the **names** of your existing image-registry secrets, if the image needs a login |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | the **name** of the secret holding `user:pass`, if the index needs a login |

A variable cannot hold a credential, so three of these hold a secret's *name*. The secrets
themselves live in the Secrets tab. Leave `AART_IMAGE_USERNAME_SECRET` unset for a public image —
naming a credential switches the job to the shape that runs `docker login`, and an anonymous pull
then fails on a login it never needed.

### 3. Prove the fork is green

**Actions → quality.** It runs on every push, so the mirror should already have triggered it. Same
nine gates as `make quality`. A red run here is a runner or index problem and every later step
inherits it.

Read the job name — it says which shape the variables selected:

| Job name | Means |
|---|---|
| `quality (Python 3.11)` | no image credentials named. Byte-for-byte the job this project always ran |
| `quality (Python 3.11, private image)` | `AART_IMAGE_USERNAME_SECRET` is set |

Exactly one of the two runs. The other reports as skipped, which is correct.

### 4. Install AART on your own machine

You need it locally only to *create* the registry. CI fetches its own copy.

```bash
pipx install --python python3.11 "git+https://ghe.corp/platform/agent-artifacts@docs/ghe-ci-portability"
```

AART has no runtime dependencies, so a checkout is a working installation on its own where `pipx`
is unavailable:

```bash
git clone https://ghe.corp/platform/agent-artifacts.git
PYTHONPATH=$PWD/agent-artifacts python3 -m agent_artifacts --version
```

Either way it should say `agent-artifacts 2.8.5`. That number returns in step 8.

## Part B — the registry

The order between the two repositories is not free: **the tool first, a registry second.** A
registry's CI fetches AART, so a registry created before AART has a home on the instance has
nowhere to fetch it from.

### 5. Create the registry

Make an empty repository on the instance, clone it, and run `init` inside the checkout:

```bash
aart registry init --source . --source-id corp-registry --display-name "Corp Registry" --yes
```

Nine files appear:

| File | What it is |
|---|---|
| `.aart-version` | the AART version CI runs. One line. Yours to edit |
| `README.md` | generated, and yours to edit. Names the variables to set |
| `aart-registry.json`, `aart-source.json` | the registry markers. Managed |
| `.github/workflows/aart-registry.yml` | the quality gate. Managed |
| `.github/workflows/aart-usage-validate.yml`, `aart-usage-dashboard.yml` | the usage-reporting pair. Managed |
| `.github/ISSUE_TEMPLATE/usage-report.yml`, `.gitignore` | managed |

Review the diff and commit. `init` refuses to overwrite a managed file whose content differs, so
hand-editing one puts the registry out of step with the command that manages it.

### 6. Set the registry's variables

One decision first: **how AART reaches the runner.** Four arms, tried in this order, never
combined — the first one set wins.

| # | Variable | Choose it when |
|---|---|---|
| 1 | `AART_PACKAGE` | the company mirrors AART in Nexus or Artifactory. Value: `agent-artifacts=={version}` |
| 2 | `AART_WHEEL_URL` | releases carry attached files. Put `{version}` where the number goes |
| 3 | `AART_TOOL_PATH` | a tree is baked into the CI image, e.g. `/opt/aart`. Needs neither git nor the network |
| 4 | `AART_TOOL_URL` | **start here.** Step 1 is the whole setup: `https://ghe.corp/platform/agent-artifacts.git` |

The order runs from the most governed supply chain to the least, so standing up an index later is
one variable set — nothing has to be unset first, and registries created before the index existed
pick the change up without being regenerated.

Set none of them and the registry reaches github.com, which an Enterprise instance cannot. That is
a loud failure on the first run, not a silent one weeks later.

Then `AART_REF` = `docs/ghe-ci-portability`, for the reason at the top of this page. Then whatever
the instance needs — `AART_RUNNER`, `AART_CI_IMAGE`, `AART_PYTHON`, `AART_GH_HOST`,
`AART_REPOSITORY`, the secret-name variables, and `AART_PAGES` = `false` where the instance offers
no Pages. Section 3 of the reference is the full table.

Set them on the **organisation**. GitHub resolves repository variables over organisation ones, so
one organisation variable configures every registry a company has, and a single registry can still
override it.

### 7. Make the gates pass once

A fresh registry does not pass its own gates until it has a lock and an index. That is correct, not
a fault:

```bash
aart registry lock --source . --yes && aart registry build --source . --yes
```

Commit, open a pull request, and let CI run it. All seven gates — `format --check`,
`validate --strict --frozen`, `lock --check`, `build --check`, `audit`, and `test` at both
`minimum` and `latest` — exit `0` on a registry created this way.

### 8. Read one line

The `Provide AART` step ends with the whole answer: which version, which arm, and whether the pin
was honoured.

```text
AART: agent-artifacts 2.8.5  via git https://ghe.corp/… (pin 2.8.5 overridden by AART_REF)
```

If it says something else, these are the three ways it fails, all non-zero and named:

| Message | Means |
|---|---|
| `no agent_artifacts package under …` | the arm fetched something, but not AART. Wrong URL, wrong path, empty clone |
| `.aart-version pins X but … provided Y` | the arm works and disagrees with the file. A moved tag, an index that resolved elsewhere, or a CI image with a stale AART baked in |
| `pin X overridden by AART_REF` | not a failure. On this walk it is the expected line |

From here, bumping AART is a pull request against `.aart-version` — the gates run on the new
version before anyone merges it.

## What this walk is actually testing

Everything above was walked locally and on github.com. Three claims were not, because they cannot
be: they need the instance. They are the reason this page exists.

**1. Action versions.** `uses:` cannot contain an expression, so no variable can redirect where an
action comes from. An Enterprise Server instance carries its own bundled copies and they can lag.
Check the instance has all five:

| Action | Used by |
|---|---|
| `actions/checkout@v4` | the fork and the registry |
| `actions/setup-python@v5` | the fork |
| `actions/upload-artifact@v4` | the fork, release job |
| `actions/upload-pages-artifact@v3` | the registry, dashboard |
| `actions/deploy-pages@v4` | the registry, dashboard |

A missing version is the one hand edit in this whole page — and for the registry workflow it is an
edit `init` will then refuse, so it belongs in the template, not in one registry.

**2. Pages.** The dashboard was split into `aggregate` and `deploy` jobs and `configure-pages` was
dropped. Both follow GitHub's own documented two-job pattern; neither was run. `AART_PAGES=false`
is the escape where the instance has no Pages at all.

**3. `GH_HOST`.** It is derived from `GITHUB_SERVER_URL` by stripping `https://` and nothing else.
An instance served on a path or a non-default port needs `AART_GH_HOST` set explicitly.

## What to report back

Four things make a failure diagnosable:

- The `AART: agent-artifacts …` line from the `Provide AART` step.
- The job name that ran, which says which branch of every `if:` the variables selected.
- The log of the step that failed, and its exit code.
- The variables you set — names and non-sensitive values.

And separately: **if you had to edit any file to make this run, name the file and the line.** A
fork needing zero hand-edits is the claim this design makes, and an edit is the evidence against it.
