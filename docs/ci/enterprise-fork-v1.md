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

The first four choose **how AART reaches the runner**, and they are tried in the order listed —
first one set wins, never combined. §3.1 explains why that order and not another.

| Variable | Default | What it does |
|---|---|---|
| `AART_PACKAGE` | unset | A requirement for an index: `agent-artifacts==2.8.5`, or a range. Installed with `pip --no-deps --target`. The most governed route, and the one to use once the company mirrors AART in Nexus or Artifactory |
| `AART_PIP_INDEX_URL` | `https://pypi.org/simple` | The index `AART_PACKAGE` is fetched from |
| `AART_WHEEL_URL` | unset | Direct URL of a released wheel, downloaded with `curl` and unzipped. Always a frozen version — a wheel's filename carries it |
| `AART_TOOL_PATH` | unset | An agent-artifacts tree already on the runner, usually baked into the CI image. Needs neither git nor the network |
| `AART_REPOSITORY` | `M1F1/agent-artifacts` | `owner/name` of the AART fork. Combined with the instance's own URL, so on GHES this alone points the registry at the internal fork |
| `AART_TOOL_URL` | derived from `AART_REPOSITORY` | Full Git URL, for when AART does not live on the same instance as the registry |
| `AART_REF` | `main` | Tag, branch or commit the git arm clones. See §4 |
| `AART_RUNNER` | `["ubuntu-latest"]` | As above |
| `AART_CI_IMAGE` | unset | As above |
| `AART_PYTHON` | `python3` | As above |
| `AART_PAGES` | unset | Set to `false` where the instance offers no GitHub Pages. The usage dashboard is still built and still validated; only its publication is skipped |

All three workflows share one `Provide AART` step, so they cannot drift apart. That step also sets
`GH_HOST` from `GITHUB_SERVER_URL`, because `gh issue list --repo owner/name` otherwise talks to
github.com — from inside an Enterprise instance that is the wrong server, and it fails quietly
rather than loudly.

### 3.1 The order the arms are tried in

`registry init` writes the same bytes for every registry. It does not detect how the AART running
it was installed, and it does not write an address into the file. **Where CI fetches AART from is
a repository variable**, which is what makes the whole page's promise — configure by settings, not
by editing — true without exception.

The one `Provide AART` step offers four ways in. The first variable that is set wins, and they are
never combined:

```
1. AART_PACKAGE     pip install from an index      most governed
2. AART_WHEEL_URL   curl a released wheel
3. AART_TOOL_PATH   a tree already on the runner
4. AART_TOOL_URL    git clone                      least governed
```

Two things follow from that order, and both are deliberate.

**Maturity first, so migration is additive.** A company that clones the repo today and stands up
an internal index tomorrow sets `AART_PACKAGE` and it takes over. Nobody has to remember to unset
`AART_TOOL_URL` first, and a registry created before the index existed picks up the change without
being regenerated.

**Git last, because it is the only arm with a shipped default.** `AART_TOOL_URL` falls back to a
literal, so that arm is *always* set. Any arm placed below it would be unreachable. This is the
one rule in the block that is invisible from reading the YAML, and
`tests/enterprise_ci_template_test.py` fails if the order is changed.

Set none of them and the registry reaches `github.com`, which an Enterprise instance cannot. That
is a loud failure in the first run, not a silent one weeks later.

**Set them on the organisation, not the repository.** GitHub resolves repository variables over
organisation ones, so one organisation variable configures every registry a company has, and a
single registry can still override it. This is why the value is not written into the file: an
address in N generated files is N places to edit when the fork moves.

**Which arm answered is printed by the run**, not stored in the file:

```
AART: agent-artifacts 2.8.5  via index https://nexus.corp/pypi/simple (agent-artifacts==2.8.5)
```

The cost of keeping this in settings rather than in the file is that `git log` on a registry does
not say which AART an old run used. The run log does, and every other knob on this page already
works that way.

**A generated file is still a generated file.** `registry init` refuses to overwrite a template
whose content differs from what it would write, so hand-editing a workflow puts the registry out
of step with the command that manages it. Use the variables, or re-run `init` on an empty
workspace.

If the AART fork is private and the runner holds no credential for it, use `AART_TOOL_PATH` and
bake the tree into the image. AART carries no credentials of its own and this workflow invents
none; a clone or a download succeeds only where the runner could already reach that host.

## 4. Two different meanings of "latest"

They are unrelated and easy to conflate.

- **`AART_REF`**, or whichever arm answered ahead of it, chooses *which AART build* runs the gates.
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
- Re-walked on 2026-08-24, after the four arms replaced the stamp. Each arm reached
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
