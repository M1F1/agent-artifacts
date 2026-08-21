# Running these workflows on GitHub Enterprise Server

This project's workflows, and the workflow `aart registry init` writes into every registry it
creates, are built so that a fork on a company GitHub Enterprise Server runs them by **setting
repository variables**, not by rewriting YAML. Every default reproduces the public github.com run,
so an unconfigured fork behaves exactly as this repository always has.

Section 5 names the two things a variable cannot express. Read it before assuming the move is a
settings change only.

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
| `AART_REFERENCE_REGISTRY_URL` | this project's public registry | The registry the release checklist reconciles against. A fork publishes to its own |
| `AART_GH_HOST` | `github.com` | `gh` talks to github.com unless told the instance hostname |

## 3. Variables a registry sets

`aart registry init` writes **three** workflows itself, all already parameterised — the quality
gate `aart-registry.yml`, and the usage-reporting pair `aart-usage-validate.yml` and
`aart-usage-dashboard.yml`. A registry created inside the company is configured by setting these
variables; the files are not edited.

**You do not set most of these by hand.** `registry init` stamps what the AART running it knows
about itself into the three workflows it writes — see §3.1. The variables below stay available to
override the stamp, which is what makes a stamped registry retargetable without editing a file.

| Variable | Default | What it does |
|---|---|---|
| `AART_TOOL_PATH` | unset | An agent-artifacts tree already on the runner, usually baked into the CI image. **Wins when set, and needs neither git nor the network.** The recommended enterprise route |
| `AART_REPOSITORY` | `M1F1/agent-artifacts` | `owner/name` of the AART fork. Combined with the instance's own URL, so on GHES this alone points the registry at the internal fork |
| `AART_TOOL_URL` | derived from `AART_REPOSITORY` | Full Git URL, for when AART does not live on the same instance as the registry |
| `AART_REF` | `main` | Tag, branch or commit to run the gates with. See §4 |
| `AART_RUNNER` | `["ubuntu-latest"]` | As above |
| `AART_CI_IMAGE` | unset | As above |
| `AART_PYTHON` | `python3` | As above |
| `AART_PAGES` | unset | Set to `false` where the instance offers no GitHub Pages. The usage dashboard is still built and still validated; only its publication is skipped |

All three workflows share one `Provide AART` step, so they cannot drift apart. That step also sets
`GH_HOST` from `GITHUB_SERVER_URL`, because `gh issue list --repo owner/name` otherwise talks to
github.com — from inside an Enterprise instance that is the wrong server, and it fails quietly
rather than loudly.

### 3.1 The stamp

The two defaults in that table you would otherwise have to change — `AART_REPOSITORY` and
`AART_REF` — are written for you. `registry init` reads the origin and the current ref of the AART
checkout it is running from, and puts them in the generated workflows:

```
TOOL_URL: ${{ vars.AART_TOOL_URL || format('{0}/{1}.git', github.server_url, vars.AART_REPOSITORY || 'platform/agent-artifacts') }}
TOOL_REF: ${{ vars.AART_REF || 'main' }}
```

The command says out loud what it wrote, so the value is read at the moment it is chosen rather
than found later in a red run:

```
warning: CI workflows stamped to fetch AART from platform/agent-artifacts@main; set the
AART_TOOL_PATH, AART_REPOSITORY or AART_REF repository variable to override without editing the
files
```

**Why the tool answers this and not you.** The alternative is editing the literal inside your fork
of this repository. That line would then conflict on every later sync from upstream — permanently,
on the one line nobody wants to resolve by hand. Stamping keeps the fork byte-identical to what it
tracks and moves the difference into generated files, where a difference belongs.

**What it stamps is what the checkout is on.** A branch stamps a branch, a detached tag stamps that
tag, a detached commit stamps that commit. The tool records the shape it was run from; it does not
have an opinion about whether you should pin. §4 is where that decision lives.

Three things it will not do:

- **An origin with no host is not stamped.** `/srv/mirrors/agent-artifacts` and `../aart` are
  places a runner cannot fetch from, so they are treated as no answer.
- **AART installed from a wheel has no checkout to read.** The workflows keep the shipped defaults
  and the command says so, rather than guessing.
- **A cross-host fetch is not derived.** The stamp names `owner/name` and lets
  `github.server_url` supply the host, which is right while the tool and the registry share an
  instance. When they do not, set `AART_TOOL_URL`.

| Flag | What it does |
|---|---|
| `--aart-repository OWNER/REPOSITORY` | State the repository instead of reading it |
| `--aart-ref REF` | State the tag, branch or commit instead of reading it |
| `--no-aart-stamp` | Write the shipped defaults and configure the registry with variables |

**A stamped file is still a generated file.** `registry init` refuses to overwrite a template whose
content differs from what it would write, so hand-editing a stamped workflow puts the registry out
of step with the command that manages it. Use the variables, or re-run `init` on an empty
workspace.

If the AART fork is private and the runner holds no credential for it, use `AART_TOOL_PATH` and
bake the tree into the image. AART carries no credentials of its own and this workflow invents
none; a clone succeeds only where the runner could already clone.

## 4. Two different meanings of "latest"

They are unrelated and easy to conflate.

- **`AART_REF`**, and the stamp behind it, choose *which AART build* runs the gates.
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

1. **Action versions may need a one-time edit.** A GitHub Enterprise Server instance carries a
   bundled copy of the common actions, and its versions can lag github.com's. If your instance has
   `actions/checkout@v3` but not `@v4`, that is a hand edit, once — and for the registry workflow
   it is an edit `registry init` will then refuse, so raise it as a change to the template rather
   than to one registry.
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
- The composite action in `.github/actions/aart/`: the same two routes, plus the commit-sha
  fallback to a full clone, plus both refusals — no input given, and a path with no package under
  it.
- A registry scaffolded from scratch by the shipped code, and its three emitted workflows read
  back and parsed.

**Not walked: any of it on a GitHub Enterprise Server instance, or on a self-hosted runner.** Four
claims are therefore unverified and should be checked on the first real run:

1. That `container: ${{ vars.AART_CI_IMAGE }}` with the variable unset means *no container* rather
   than an error. If it errors on your instance, drop the `container:` line — a self-hosted runner
   usually already runs in the intended image.
2. That your instance carries `actions/checkout@v4`, `actions/setup-python@v5`, and
   `actions/upload-artifact@v4` for the release job.
3. That splitting the dashboard into `aggregate` and `deploy` jobs still deploys, and that dropping
   `configure-pages` changes nothing for a static output. Both follow GitHub's own documented
   two-job Pages pattern, but neither was run.
4. That `GH_HOST` derived from `GITHUB_SERVER_URL` is what your `gh` expects. The derivation strips
   `https://` and nothing else, so an instance served on a path or a non-default port needs
   `AART_GH_HOST` set explicitly.
