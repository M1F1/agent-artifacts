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

**Editing that file is worse than it looks.** `registry init` refuses to overwrite a template whose
content differs from the one it ships, so a hand-edited workflow puts the registry permanently out
of step with the command that manages it. Configuration belongs in variables.

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

If the AART fork is private and the runner holds no credential for it, use `AART_TOOL_PATH` and
bake the tree into the image. AART carries no credentials of its own and this workflow invents
none; a clone succeeds only where the runner could already clone.

## 4. Two different meanings of "latest"

They are unrelated and easy to conflate.

- **`AART_REF`** chooses *which AART* runs the gates. The shipped default is `main`.
- **`--compatibility minimum|latest`** chooses which end of *the registry's own declared
  compatibility window* is exercised. Both ends always run; that is the matrix.

`main` as a default means a registry's CI can turn red with no change to the registry, because
something moved in the tool. For a company registry, prefer pinning `AART_REF` to a release tag and
moving it deliberately. This project has been bitten from the other side too: a registry ran an
AART three releases behind for weeks while a merged pull request titled *Move the CI pin* had moved
it to the wrong version. The `Provide AART` step prints the version that answered, and that printed
line is what a reviewer should read.

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
