# Running these workflows on GitHub Enterprise Server

This project's workflows, and the workflow `aart registry init` writes into every registry it
creates, are built so that a fork on a company GitHub Enterprise Server runs them by **setting
repository variables**, not by rewriting YAML. Every default reproduces the public github.com run,
so an unconfigured fork behaves exactly as this repository always has.

**The runbook is the ordered version** — mirror the tool, configure it, then create a registry.
The numbered sections after it are the reference: every variable, and what each one does.

Section 5 names the three things a variable cannot express. Read it before assuming the move is
a settings change only.

## The runbook, in order

Two repositories, and the order between them is not free: **the tool first, a registry second**. A
registry's CI fetches AART, so a registry created before AART has a home on the instance has
nowhere to fetch it from.

Nothing below edits a file in a fork. Every step is a mirror, a variable, or a command.

### Step 1 — Put AART on the instance

A fork through the web UI works where the instance can reach github.com. Where it cannot, mirror:

```bash
git clone --mirror https://github.com/M1F1/agent-artifacts.git
```

```bash
git -C agent-artifacts.git push --mirror https://ghe.corp/platform/agent-artifacts.git
```

`--mirror` is what carries the **tags**, and tags are load-bearing: the git arm clones `v` followed
by the pin, so a mirror without tags leaves that arm unable to find any version.

### Step 2 — Configure the fork itself

Set these under **Settings → Secrets and variables → Actions → Variables**, on the **organisation**
where you can. Section 2 is the full table; on a private runner with no egress the short list is:

| Variable | Set it to |
|---|---|
| `AART_RUNNER` | your runner labels, as JSON: `["self-hosted","linux","x64"]` |
| `AART_PIP_INDEX_URL` | the internal mirror, for `ruff`, `mypy` and `coverage` |
| `AART_GH_HOST` | the instance hostname, so `gh` does not talk to github.com |
| `AART_PYTHON_VERSIONS` | one entry, e.g. `["3.11"]`, if you also set `AART_CI_IMAGE` |
| `AART_IMAGE_USERNAME_SECRET`, `AART_IMAGE_PASSWORD_SECRET` | the **names** of your existing image-registry secrets, if the image needs a login |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | the **name** of the secret holding `user:pass`, if the index needs a login |

### Step 3 — Decide how registries will fetch AART

This is the only design decision on the page, and it is reversible: the arms are ordered so a later,
more governed answer takes over without unsetting the earlier one. Pick what the instance already
has.

| You have | Do this once | Registries then set |
|---|---|---|
| An internal package index | Publish the wheel to it | `AART_PACKAGE` = `agent-artifacts=={version}` |
| Releases with attached files | Tag `v2.8.5`; `release.yml` builds the wheel and attaches it | `AART_WHEEL_URL` = `https://ghe.corp/platform/agent-artifacts/releases/download/v{version}/agent_artifacts-{version}-py3-none-any.whl` |
| A custom runner image | Bake a checkout into it | `AART_TOOL_PATH` = `/opt/aart` |
| Only the mirrored repository | Nothing — Step 1 is the whole setup | `AART_TOOL_URL` = `https://ghe.corp/platform/agent-artifacts.git` |

The last row always works. It is the row to start on, because it needs nothing that does not exist
after Step 1, and moving up later is one variable set.

### Step 4 — Prove the fork is green before going further

Run the fork's own `validate` workflow. It is the same nine gates as `make quality`. A red run here
is a runner or index problem, and every later step would inherit it.

### Step 5 — Install AART on your own machine

You need it locally only to *create* the registry. CI fetches its own copy.

```bash
pipx install --python python3.11 "git+https://ghe.corp/platform/agent-artifacts@v2.8.5"
```

Where `pipx` is unavailable, an unzipped wheel is a working installation on its own — Section 1.

### Step 6 — Create the registry

Make an empty repository on the instance, clone it, and run `init` inside the checkout:

```bash
aart registry init --source . --source-id corp-registry --display-name "Corp Registry" --yes
```

That writes `.aart-version` with the version you just ran, a generated `README.md`, the three
workflows, and the JSON markers. Commit them.

### Step 7 — Configure the registry

One variable from Step 3, plus whatever the instance needs. Set them on the **organisation** and
every registry created later is configured before it exists.

| Variable | When |
|---|---|
| one of the four from Step 3 | always — setting none reaches github.com and fails on the first run |
| `AART_RUNNER`, `AART_CI_IMAGE`, `AART_PYTHON` | same reasons as the fork |
| `AART_PIP_INDEX_URL` | only if you chose `AART_PACKAGE` |
| `AART_GH_HOST`, `AART_REPOSITORY` | the instance hostname and the tool's path on it |
| `AART_IMAGE_USERNAME_SECRET`, `AART_IMAGE_PASSWORD_SECRET` | the image needs a login. Set the **names** of the secrets, not the values |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | you chose `AART_PACKAGE` and the index needs a login |
| `AART_PAGES` = `false` | the instance offers no GitHub Pages. The dashboard is still built and validated, only not published |

### Step 8 — Make the gates pass once

A fresh registry does not pass its own gates until it has a lock and an index. That is correct, not
a fault:

```bash
aart registry lock --source . --yes && aart registry build --source . --yes
```

Commit, open a pull request, and let CI run it.

### Step 9 — Read one line

The `Provide AART` step ends with the whole answer:

```text
AART: agent-artifacts 2.8.5  via wheel https://ghe.corp/…  pinned by .aart-version
```

Which version ran, which arm answered, and whether the pin was honoured. If it says something else,
these are the three ways it fails, all of them non-zero and named:

| Message | Means |
|---|---|
| `no agent_artifacts package under …` | the arm fetched something, but not AART. Wrong URL, wrong path, empty clone |
| `.aart-version pins X but … provided Y` | the arm works and disagrees with the file. A moved tag, an index that resolved elsewhere, or a CI image with a stale AART baked in |
| `pin X overridden by AART_REF` | not a failure. Someone set the escape hatch, and the run says so rather than hiding it |

From here, bumping AART is a pull request against `.aart-version` — the gates run on the new version
before anyone merges it.

## 1. The fact the whole design rests on

AART has **no runtime dependencies**, is standard library only, and ships
`agent_artifacts/__main__.py`. So this is a working installation:

```bash
PYTHONPATH=/path/to/agent-artifacts python3 -m agent_artifacts --version
```

No `pip`. No package index. No build backend. No `setuptools`. A checkout, or a directory baked
into a CI image, is enough.

That removes the step that fails first on a private runner with no egress. It also means a
registry's quality gates need **nothing from the network except the registry itself**.

The one exception is this repository's *own* quality job, which runs `ruff`, `mypy` and
`coverage`. Those are real dependencies and need an index — see `AART_PIP_INDEX_URL`. A registry
repository never installs them.

## 2. Variables a fork of this repository sets

Set under **Settings → Secrets and variables → Actions → Variables**. These drive
`.github/workflows/validate.yml` and `release.yml`.

| Variable | Default | What it does |
|---|---|---|
| `AART_RUNNER` | `["ubuntu-latest"]` | JSON array of runner labels. Must be JSON — `["self-hosted","linux","x64"]`, not a bare word |
| `AART_CI_IMAGE` | unset | Container image for the job. Unset leaves the line inert and the runner's own environment is used |
| `AART_PYTHON` | `python` | The interpreter's name inside that image |
| `AART_PYTHON_VERSIONS` | `["3.10", "3.14"]` | JSON array for the quality matrix. **Pin to one entry when `AART_CI_IMAGE` is set** — one image carries one interpreter, and a two-entry matrix would run the same Python twice under two names |
| `AART_PIP_INDEX_URL` | `https://pypi.org/simple` | Internal mirror for `ruff`/`mypy`/`coverage`. This repository's gates only |
| `AART_RELEASE_PYTHON_VERSION` | `3.11` | Interpreter for the release job when no container is used |
| `AART_ARTIFACT_V4` | `true` | Set to `false` where the instance's artifact backend does not speak the v4 protocol, and the release job uploads the wheel with `upload-artifact@v3` instead. Measured, not guessed — see section 5 |
| `AART_REFERENCE_REGISTRY_URL` | **no default** | The registry the release checklist reconciles against, and the switch for whether it reconciles at all. Unset, the clone is skipped and the seven registry checks report `skipped` — never `passed` — with a warning on every run. See below |
| `AART_GH_HOST` | `github.com` | `gh` talks to github.com unless told the instance hostname |
| `AART_IMAGE_USERNAME_SECRET` | unset | **Name** of the secret holding the image-registry username. Setting it switches the job to the shape that carries a `credentials` block; leaving it unset keeps the job this project always ran |
| `AART_IMAGE_PASSWORD_SECRET` | unset | **Name** of the secret holding the image-registry password |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | unset | **Name** of a secret holding `user:pass` for the index. Combined with `AART_PIP_INDEX_URL`, which stays a bare host |

### The one variable with no default

Every other variable defaults to the public run, so an unconfigured fork behaves the way this
repository always has. `AART_REFERENCE_REGISTRY_URL` cannot: a default naming a github.com
repository reproduces nothing on an instance that cannot reach github.com. It guarantees a failed
clone, which is worse than no default at all.

So presence is the switch — the same shape `AART_IMAGE_USERNAME_SECRET` already uses:

| Set to | What a release does |
|---|---|
| a registry URL | clones it and runs all eleven checks, seven of them against that registry |
| unset | skips the clone, runs four checks, reports the other seven as `skipped` |

Actions cannot tell an unset variable from an empty one, which is why a default and an opt-out
cannot both exist here. One of them had to go, and a default that only ever produces a failed
clone is the one worth losing.

The release checklist is an acceptance test, not a publication step: it runs the version being
released against a real catalogue to prove the tool still operates one. A fork that keeps no
catalogue has nothing to reconcile against, and the proof it cannot run is a proof it does not
need. What it must not do is claim it ran — hence `skipped`, a `registry_reconciliation` field in
the receipt, and a warning on stderr every time.

**This repository sets the variable explicitly.** Clearing it would not fail anything; it would
quietly verify seven checks fewer, which is the whole reason the warning is loud.

### What a container image has to carry

`AART_CI_IMAGE` is the one variable that moves work into an environment this project does not
build, so it is the one place where the image, not a variable, is the thing that has to be right.
The list is short, because it was made short on purpose:

| Needed | Why |
|---|---|
| A Python interpreter, named by `AART_PYTHON` | setting `AART_CI_IMAGE` skips `actions/setup-python`, which downloads from github.com and is the first thing to fail on a runner with no egress |
| `git` | the gates read the working tree through `git ls-files`, and the tool's own tests build real repositories |

Ownership is handled for you. `actions/checkout` writes the workspace as the runner's uid and a
container job usually runs as another, so git answers every command with `detected dubious
ownership`. Both composite actions mark the workspace trusted before anything else runs. Nothing
to set, and nothing to rebuild an image for.

**Not** GNU Make. The gates are run as `scripts/quality.py`, and the release checklist as
`scripts/release.py check` — both are what the Makefile targets always wrapped. `make` stays for
people typing at a keyboard; CI never needed it, and an image is easier to supply without it.

## 3. Variables a registry sets

`aart registry init` writes **three** workflows itself, all already parameterised — the quality
gate `aart-registry.yml`, and the usage-reporting pair `aart-usage-validate.yml` and
`aart-usage-dashboard.yml`. A registry created inside the company is configured by setting these
variables; the files are not edited.

The first four choose **how AART reaches the runner**, and they are tried in the order listed —
first one set wins, never combined. §3.1 explains why that order and not another.

| Variable | Default | What it does |
|---|---|---|
| `AART_PACKAGE` | unset | A requirement for an index, normally `agent-artifacts=={version}` — `{version}` is replaced with the pin. Installed with `pip --no-deps --target`. The most governed route, and the one to use once the company mirrors AART in Nexus or Artifactory |
| `AART_PIP_INDEX_URL` | `https://pypi.org/simple` | The index `AART_PACKAGE` is fetched from |
| `AART_WHEEL_URL` | unset | URL of a released wheel, downloaded with `curl` and unzipped. Use `{version}` where the version appears and the pin fills it in |
| `AART_TOOL_PATH` | unset | An agent-artifacts tree already on the runner, usually baked into the CI image. Needs neither git nor the network |
| `AART_REPOSITORY` | `M1F1/agent-artifacts` | `owner/name` of the AART fork. Combined with the instance's own URL, so on GHES this alone points the registry at the internal fork |
| `AART_TOOL_URL` | derived from `AART_REPOSITORY` | Full Git URL, for when AART does not live on the same instance as the registry |
| `AART_REF` | `v` + the pin | Escape hatch: a branch or commit instead of `.aart-version`. Overrides the pin and switches the version check off. See §4 |
| `AART_RUNNER` | `["ubuntu-latest"]` | As above |
| `AART_CI_IMAGE` | unset | As above |
| `AART_PYTHON` | `python3` | As above |
| `AART_PAGES` | unset | Set to `false` where the instance offers no GitHub Pages. The usage dashboard is still built and still validated; only its publication is skipped |
| `AART_IMAGE_USERNAME_SECRET` | unset | **Name** of the secret holding the image-registry username. As above: it selects the job shape, and a name is not a secret |
| `AART_IMAGE_PASSWORD_SECRET` | unset | **Name** of the secret holding the image-registry password |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | unset | **Name** of a secret holding `user:pass` for the index. Only the `AART_PACKAGE` arm reaches an index at all |

All three workflows share one `Provide AART` step, so they cannot drift apart. That step also sets
`GH_HOST` from `GITHUB_SERVER_URL`, because `gh issue list --repo owner/name` otherwise talks to
github.com — from inside an Enterprise instance that is the wrong server, and it fails quietly
rather than loudly.

### 3.1 Two questions, two homes

`registry init` writes the same bytes for every registry. It detects nothing about how the AART
running it was installed. What a registry ends up with is split by a single test: **is this a
decision about the registry, or a fact about the instance it happens to run on?**

**Which AART version — a decision — is pinned in Git.** `registry init` writes `.aart-version`
holding one line, the version of the tool that created the registry. That is the same number it
already writes as `requires_aart.min_inclusive`, and it needs no inference: AART knows its own
version, which is exactly what the origin stamp this replaced could not say about its own
repository.

```
.aart-version
2.8.5
```

Bumping it is a pull request. The gates run against the new version *before* it merges, `git blame`
says when the registry moved, and a bad bump is one revert away. A version living in a settings page
has none of those: it changes silently, takes effect everywhere at once, and is never tested first.

The pin is also **proved rather than claimed**. After fetching, the step compares `aart --version`
with the file and fails if they differ — catching a tag that moved, an index that resolved to
something else, and a CI image with a stale AART baked in. That last one is invisible today.

**Where this deployment fetches it from — a fact — stays in variables.** The same registry stood up
at two companies runs the same version through a different supply chain, and nothing about that
belongs in its Git history. Four arms; the first variable that is set wins, never combined:

```
1. AART_PACKAGE     pip install from an index      most governed
2. AART_WHEEL_URL   curl a released wheel
3. AART_TOOL_PATH   a tree already on the runner
4. AART_TOOL_URL    git clone                      least governed
```

`{version}` inside `AART_PACKAGE` or `AART_WHEEL_URL` is replaced with the pin, and the Git arm
clones `v` + the pin. So the version is written **once**, in the repository, and the variables carry
no version at all.

Two things follow from that order, and both are deliberate.

**Maturity first, so migration is additive.** A company that clones the repo today and stands up an
internal index tomorrow sets `AART_PACKAGE` and it takes over. Nobody has to unset
`AART_TOOL_URL` first, and a registry created before the index existed picks up the change without
being regenerated.

**Git last, because it is the only arm with a shipped default.** `AART_TOOL_URL` falls back to a
literal, so that arm is *always* set and anything below it would be unreachable. This is structural
rather than agreed — it is the `else` of the chain, and an `else` cannot be moved. What the tests
guard is the part that *is* a convention: which of the first three wins.

Set none of them and the registry reaches `github.com`, which an Enterprise instance cannot. That is
a loud failure in the first run, not a silent one weeks later.

**Set them on the organisation, not the repository.** GitHub resolves repository variables over
organisation ones, so one organisation variable configures every registry a company has, and a
single registry can still override it.

`AART_REF` remains as an escape hatch: set it and it overrides the pin, the version check is
switched off, and the run log says so — because at that point you asked for a different build on
purpose.

**Which arm answered is printed by the run:**

```
AART: agent-artifacts 2.8.5  via index https://nexus.corp/pypi/simple (agent-artifacts==2.8.5)  pinned by .aart-version
```

**Generated files, and files you own.** The workflows and the two JSON markers are managed —
`registry init` refuses to overwrite one whose content differs, so hand-editing puts the registry out
of step with the command that manages it. `.aart-version` and `README.md` are written only when
absent and never compared: they are the two files a maintainer is meant to edit.

If the AART fork is private and the runner holds no credential for it, use `AART_TOOL_PATH` and bake
the tree into the image. AART carries no credentials of its own and this workflow invents none; a
clone or a download succeeds only where the runner could already reach that host.

## 4. Two different meanings of "latest"

They are unrelated and easy to conflate.

- **`.aart-version`** chooses *which AART build* runs the gates, and `AART_REF` overrides it.
- **`--compatibility minimum|latest`** chooses which end of *the registry's own declared
  compatibility window* is exercised. Both ends always run; that is the matrix.

They are not two settings of one thing. `--latest-version` defaults to the version of the AART that
is executing, on purpose — a frozen default would test a release that is not there. So "latest"
already means *whatever ran*, and `AART_REF` is what decides what ran.

The deliberate-upgrade decision you might expect the pin to carry is carried somewhere else: the
window in `aart-registry.json`. `registry init` writes `min_inclusive` as the AART that created the
registry and `max_exclusive` as the next major. An AART past that ceiling fails the `latest` check
until someone edits the registry — which is the decision, recorded in a diff, in the registry's own
repository.

**The window is a version range, not a promise about behaviour.** A 2.9.0 that changes what
`registry lock` writes turns a registry's CI red with no change to the registry and no help from
the ceiling. `required_capabilities` catches a missing feature; nothing catches a changed one. So:

- **Stamp a branch** when you want the gates to follow the tool, and accept that upstream can turn
  a registry red. The ceiling still stops a major.
- **Stamp a tag**, or set `AART_REF` to one, when a registry's CI must only change when someone
  changes it.

This project has been bitten from the pinned side too: a registry ran an AART three releases behind
for weeks while a merged pull request titled *Move the CI pin* had moved it to the wrong version.
The `Provide AART` step prints the version that answered, and that printed line is what a reviewer
should read.

## 5. What a variable cannot express

**`uses:` cannot contain an expression.** GitHub Actions requires a literal action reference, so no
variable can redirect where an action comes from. Two consequences:

1. **A version can be present and still unusable.** This was written as a guess about instances
   carrying older bundled actions. A real Enterprise run says the guess was the wrong shape. The
   instance downloaded `actions/upload-artifact@v4` without complaint and then failed at run time:

   ```text
   GHESNotSupportedError: @actions/artifact v2.0.0+, upload-artifact@v4+ and
   download-artifact@v4+ are not currently supported on GHES.
   ```

   The action was there. The instance's artifact backend does not speak the protocol that version
   uses. So the thing to check is not "does the instance have `@v4`" but "does `@v4` work here",
   and only a run answers that.

   Because `uses:` takes no expression, the release job carries **both** upload steps and picks one
   with `if:` — the same move `container.credentials` forced. `AART_ARTIFACT_V4=false` selects the
   v3 step. Nothing about the github.com run changes.

   For the registry workflow the same situation would be an edit `registry init` refuses, so raise
   it as a change to the template rather than to one registry.
2. **An instance without the bundled actions needs `run:` steps instead.** The registry workflow is
   already down to one action, `actions/checkout`, which can be replaced with a plain `git clone`
   using `${{ github.server_url }}` and `${{ github.token }}`.
3. **The dashboard's Pages actions are the least portable thing here.** `upload-pages-artifact` and
   `deploy-pages` need Pages, and Pages needs an instance that offers it. `AART_PAGES=false` is the
   escape. `configure-pages` was dropped: it computes a base path for static-site generators, and
   `aart reporting aggregate` writes plain files that do not need one.

The rule this leads to: **the fewer `uses:` lines a workflow has, the more portable it is.** That
is why the registry workflow resolves AART with a dozen lines of `bash` rather than an action, even
though an action would read more nicely.

**A variable cannot hold a credential, and a credentials block cannot be made conditional.**
Both were measured on real runs rather than reasoned about, because the documentation states
neither. What the runs established:

| Tried | Result |
|---|---|
| `secrets[vars.NAME]` — a secret named by a variable | **works**, in `env:` and inside `container.credentials` alike |
| `secrets` anywhere in the `container:` expression itself | `Unrecognized named-value: 'secrets'` |
| `credentials:` with empty values | `Unexpected value ''`, before the job starts |
| `credentials: ${{ fromJSON('null') }}` | the same rejection — `null` is not *absent* |
| `credentials:` filled with a placeholder | `Docker login for '' failed`, so an anonymous pull breaks |
| `container: ${{ fromJSON(vars.X \|\| 'null') }}` | `null` runs on the host, an object runs in the container |

Two consequences shape every workflow here.

1. **The credential switch lives at `if:`, so each containerised job is emitted twice.** One shape
   carries no `credentials` block at all and is byte-for-byte the job this project always ran; the
   other names both secrets through variables. `AART_IMAGE_USERNAME_SECRET` decides which runs, and
   because it is a *name* rather than a value it is safe in a variable — a secret's name is not a
   secret. Naming nothing changes nothing, which is why an existing fork sees no difference.
2. **The index credential is assembled, never stored.** `AART_PIP_INDEX_URL` holds the bare host and
   `AART_PIP_INDEX_CREDENTIALS_SECRET` names a secret holding `user:pass`; the URL is composed in
   the step. Splitting a secret **defeats GitHub's masking** — it masks the whole value it was
   given, not the halves — so both halves are re-masked with `::add-mask::` before use, and the log
   line names the bare host so no password reaches it even masked.

The steps of the two shapes live in a composite action rather than in two copies, since a
duplicated gate list is a gate list that drifts. An action cannot read `vars`, so the job reads the
variables and passes the answers down.

## 6. Many registries, one pin

Five registries mean five places to move `AART_REF`. Promote the workflow to a **reusable
workflow** in an internal repository and let each registry call it:

```yaml
name: AART registry quality
on:
  pull_request:
  push:
    branches: [main]
jobs:
  quality:
    uses: platform/ci-workflows/.github/workflows/aart-registry.yml@v1
```

The pin then moves in one file. A reusable workflow's `uses:` is a literal too, so the `@v1` above
is the one line each registry still owns. Note that this replaces the managed template, so
`registry init` will refuse the registry afterwards — a deliberate trade, not an accident.

## 7. What was walked, and what was not

Walked locally on 2026-08-21, against the real reference registry, with a source copy carrying no
`.git`, no `pip`, no `setuptools` and no index:

- All seven registry gates — `format --check`, `validate --strict --frozen`, `lock --check`,
  `build --check`, `audit`, and `test` at both `minimum` and `latest` — exit `0` when run as
  `PYTHONPATH=<copy> python -m agent_artifacts …`.
- The `Provide AART` step, extracted from the bytes `registry init` actually emits and run with
  `RUNNER_TEMP` and `GITHUB_PATH` set by hand: the baked-path route and the tag clone, then the
  gates through the `aart` shim it puts on PATH.
- Re-walked on 2026-08-24 with `.aart-version` in place. All four arms reach the pinned 2.8.5 —
  `{version}` substituted into an index requirement and into a wheel URL, `v2.8.5` derived for the
  clone, and the baked path checked rather than composed. A pin the arm cannot satisfy fails: a
  path holding 2.8.5 against a pin of 2.8.4 exits `2` naming both numbers, and a pin of `9.9.9`
  fails the clone. `AART_REF` overrides the pin and the run says so. With no file at all the
  template behaves as it did before. Then a registry created from scratch, locked, built, and all
  seven gates run through the shim the pinned step puts on PATH.
- Walked earlier the same day, before the pin existed. Each arm reached
  `agent-artifacts 2.8.5` from a different place — a PEP 503 index on disk, a wheel over HTTP, a
  path, and a clone at `v2.8.5`. Then the cascade, which is the part that can actually fail: all
  four variables set resolves to the index, and dropping them one at a time walks down to the
  wheel, the path, and the clone, in that order. All three failure modes exit non-zero and name
  the cause — an unreachable host (`128`), a path holding no package (`2`), a wheel URL that does
  not answer (`7`).
- The composite action in `.github/actions/aart/`: the same two routes, plus the commit-sha
  fallback to a full clone, plus both refusals — no input given, and a path with no package under
  it.
- A registry scaffolded from scratch by the shipped code, and its three emitted workflows read
  back and parsed.
- Walked on GitHub Actions itself on 2026-08-24, because the two questions the container shape
  turns on are not answered anywhere in the documentation. Sixteen throwaway runs, each isolated to
  one question, on a branch since deleted. What they established is the table in §5. Three of the
  early runs were invalid for a reason worth recording: `run: echo "RESULT 9: ..."` is a plain YAML
  scalar containing `": "`, which is a mapping, so those runs failed on the probe rather than on
  the thing being probed. They were re-run inside block scalars and are not counted above.
- The `secrets[vars.NAME]` form and the `if:`-driven switch were then confirmed on the company
  GitHub Enterprise Server instance this work is for, which is the instance that matters.
- The credentialed index walked end to end on 2026-08-24, against a local index that answers `401`
  without credentials and `200` with them. The emitted step, run with the secret set, installs AART
  through it and exits `0`; run without, `pip` prompts for a user and fails. The announced line
  carries the bare host, and the password appears in the output exactly once — inside the
  `::add-mask::` directive, which is the line GitHub consumes and removes.

**Walked on a real GitHub Enterprise Server instance on 2026-08-25**, in a container image on a
company runner, against an internal index. `quality` is green there and `release` builds the wheel.
Five defects came out of that walk, none of them fixable by a variable, all of them fixed here:

| What failed | What it actually was |
|---|---|
| `make: command not found` | CI shelled out to GNU Make for two lines of substitution. It no longer does |
| `git ls-files` exit 128 | `dubious ownership`: `actions/checkout` writes the workspace as one uid, a container job runs as another |
| `Needed a single revision` | git writes `refs/remotes/origin/HEAD` on fetch only since 2.46; older gits fell through to a tag named `HEAD` |
| `registry-origin-invalid` on any fork | the workflow honoured `AART_REFERENCE_REGISTRY_URL` and the checklist compared against a constant |
| two checks "cannot prove" at once | the checklist runs git with global config off, so the workspace-trust the job had written was invisible to it |

Three of the five printed no usable message, because the process that failed had captured the
explanation and discarded it. That is worth more than any single fix: **when a subprocess fails,
print what it said.**

**One claim remains unverified**, and one was answered by the walk:

1. ~~That your instance carries the actions the release job needs.~~ **Answered, and the question
   was wrong.** The instance carried `actions/upload-artifact@v4` and downloaded it without
   complaint, then failed at run time with `GHESNotSupportedError`: its artifact backend does not
   speak the protocol that version uses. Presence is not the test; a run is. The release job now
   carries both upload steps and picks one with `if:`, selected by `AART_ARTIFACT_V4`.
2. That splitting the dashboard into `aggregate` and `deploy` jobs still deploys, and that dropping
   `configure-pages` changes nothing for a static output. Both follow GitHub's own documented
   two-job Pages pattern, but neither was run. `deploy` now waits on both shapes of `aggregate`
   and tolerates the one that stood down; a skipped dependency skips its dependents unless the
   condition says otherwise, which is what `!cancelled()` is doing there.
3. That `GH_HOST` derived from `GITHUB_SERVER_URL` is what your `gh` expects. The derivation strips
   `https://` and nothing else, so an instance served on a path or a non-default port needs
   `AART_GH_HOST` set explicitly.
