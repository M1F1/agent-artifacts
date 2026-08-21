# Running these workflows on GitHub Enterprise Server

This project's workflows are written so that a fork on a company GitHub Enterprise Server runs
them by **setting repository variables**, not by rewriting YAML. Every default reproduces the
public github.com run, so an unconfigured fork behaves exactly as this repository always has.

Two things a variable cannot express are named in §4. Read that section before assuming the fork
is a settings change only.

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

## 2. Variables

Set under **Settings → Secrets and variables → Actions → Variables**.

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

For a registry repository, `docs/ci/templates/registry-quality.yml` adds three more:
`AART_TOOL_PATH` (a tree baked into the image), or `AART_TOOL_URL` plus `AART_TOOL_REF` (the fork
and the tag to pin).

## 3. Which file goes where

- **A fork of this repository** keeps `.github/workflows/validate.yml` and `release.yml` as they
  are, and sets the variables above.
- **A registry repository** copies `docs/ci/templates/registry-quality.yml` to
  `.github/workflows/aart-registry.yml` and sets `AART_TOOL_*`. That file is self-contained: one
  marketplace action, no pip, no index.
- `.github/actions/aart/action.yml` is a local composite action that puts an `aart` command on
  PATH. `./`-prefixed actions resolve without reaching a marketplace, which is the point.

## 4. What a variable cannot express

**`uses:` cannot contain an expression.** GitHub Actions requires a literal action reference, so
no variable can redirect where an action comes from. Two consequences:

1. **Action versions may need a one-time edit.** A GitHub Enterprise Server instance carries a
   bundled copy of the common actions, and its versions can lag github.com's. If your instance
   has `actions/checkout@v3` but not `@v4`, that is a hand edit in each workflow, once. It cannot
   be a variable.
2. **An instance without the bundled actions needs `run:` steps instead.** The registry template
   is already down to one action — `actions/checkout` — and that one can be replaced with a plain
   `git clone` using `${{ github.server_url }}` and `${{ github.token }}` if your instance carries
   no actions at all.

The rule of thumb this leads to: **the fewer `uses:` lines a workflow has, the more portable it
is.** That is why the registry template resolves AART with fifteen lines of `bash` rather than an
action, even though an action would read more nicely.

## 5. Many registries, one pin

Copying the template into five registry repositories means five places to move a version pin. This
project has already been bitten by exactly that: a registry ran an AART three releases behind for
weeks while a merged pull request titled *Move the CI pin* had moved it to the wrong version.

When there is more than one registry, promote the template to a **reusable workflow** in an
internal repository, and let each registry call it:

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

The pin then moves in one file. Note that a reusable workflow's `uses:` is a literal too, so the
`@v1` above is the one line each registry still owns.

## 6. What was walked, and what was not

Walked locally on 2026-08-21, against the real reference registry with a source copy carrying no
`.git`, no `pip`, no `setuptools` and no index:

- All seven registry gates — `format --check`, `validate --strict --frozen`, `lock --check`,
  `build --check`, `audit`, and `test` at both `minimum` and `latest` — exit `0` when run as
  `PYTHONPATH=<copy> python -m agent_artifacts …`.
- The composite action's script, run with `RUNNER_TEMP`, `GITHUB_PATH` and `GITHUB_OUTPUT` set by
  hand: the baked-path branch, the shallow tag clone, the commit-sha fallback to a full clone, and
  both refusals — no input, and a `path` with no package under it.
- The registry template's inline script, then all seven gates through the `aart` shim it puts on
  PATH.

**Not walked: any of it on a GitHub Enterprise Server instance, or on a self-hosted runner.** Two
specific claims are therefore unverified and should be checked on the first real run:

1. That `container: ${{ vars.AART_CI_IMAGE }}` with the variable unset means *no container*
   rather than an error. If it errors on your instance, delete the two `container:` lines in the
   fork — the runner's own image is then what the job uses, which for a self-hosted runner is
   usually what was wanted anyway.
2. That your instance carries `actions/checkout@v4` and `actions/setup-python@v5`, and that
   `actions/upload-artifact@v4` exists for the release job.
