# agent-artifacts (`aart`)

AART installs reviewed **skills, guidelines, MCP servers, hooks, and memory** from canonical,
validated registry snapshots into a selected harness. It uses only the Python standard library and
has zero runtime dependencies.

## One current contract

AART is one product with one interface: `source`, `marketplace`, and `registry`. It does not
support or convert legacy catalogs, former top-level consumer commands, old installation state, or
retired setup recipes. Input outside the current contract is rejected with a migration diagnostic;
there are no compatibility flags or silent fallbacks.

The names `native-source-v1` and `registry-v1` identify the current document families. They are
not legacy modes. **Setup v1 is retired**: setup v2 is the only accepted recipe. The same compiler
validates it at both publication and consumption boundaries.

See the [native source contract](docs/protocol/native-source-v1.md),
[registry contract](docs/protocol/registry-v1.md), and the accepted
[remediation design](docs/design/DESIGN-post-live-acceptance-remediation.md).

## Install and quick start

Python 3.10 or later is required.

**The exact commands are on this repository's [Releases page](../../releases).** Every release
carries them, filled in with the address of the repository you are reading them in -- so a fork on
a company instance shows its own host, and nobody has to guess or substitute anything. That link is
relative on purpose: it resolves inside whatever repository this file lives in, which is why this
page can point at a release without naming an address that would be wrong in a fork, and would
conflict on every merge from upstream.

From a checkout, the same commands print here:

```sh
python scripts/install_commands.py
```

The shapes are below, if you want them before you look. `<repository>` is the address of the
repository you are reading this in; the command above prints it filled in.

| Source | `pip` (inside your environment) | `pipx` | `uv` |
|---|---|---|---|
| Tagged Git repository, no clone | `python -m pip install --no-deps "git+<repository>.git@v2.8.6"` | `pipx install "git+<repository>.git@v2.8.6"` | `uv tool install "git+<repository>.git@v2.8.6"` |
| Downloaded wheel | `python -m pip install --no-deps ./aart_cli-2.8.6-py3-none-any.whl` | `pipx install ./aart_cli-2.8.6-py3-none-any.whl` | `uv tool install ./aart_cli-2.8.6-py3-none-any.whl` |
| Release wheel by URL | `python -m pip install --no-deps <the wheel's address on the release>` | `pipx install <the wheel's address on the release>` | `uv tool install <the wheel's address on the release>` |

The Git row leads because it is the only one that needs nothing arranged first: `git+https://` goes
through git, and git uses the credentials you already push with.

`pipx` and `uv tool` create an isolated tool environment. AART has no runtime dependencies. The
release wheel is byte-reproducible from its tag and its digest is published in the release notes.

### On a private Enterprise instance

A fork on a GitHub Enterprise Server instance is normally private, and that changes which of those
sources work at all.

| Source | Works on a private instance |
|---|---|
| Tagged Git repository, no clone | **Yes.** git authenticates, so this row needs nothing set up |
| Downloaded wheel | Yes, once the file is on disk -- see below for getting it there |
| Internal index, once the wheel is published to it | Yes. Add `--index-url <your index>` (`--default-index` for `uv`) and ask for `"aart-cli==2.8.6"` |
| Release wheel by URL | **No.** See below |

The last row is the one that surprises people. `pip`, `pipx` and `uv` send no token when they fetch
a URL, so a release asset on a private repository answers with a sign-in page. The installer then
fails on a corrupt archive rather than on a refusal, and the message names neither cause nor fix.
Use that row only where the address answers without a login.

To get the wheel onto disk instead, download it with something that does authenticate -- your
instance's own UI, or a CLI you already have signed in -- and install from the file.

Keep a reviewed tag rather than following a moving branch. Where `pipx` is unavailable, an unzipped
wheel is a working installation on its own -- AART has no runtime dependencies, so a directory on
`PYTHONPATH` is enough.

The editable install is for working on AART itself, not for a colleague adopting it:

```sh
git clone <repository>.git
cd agent-artifacts
python -m pip install --no-index --no-deps --no-build-isolation -e .
```

Then, in a consumer project:

```sh
cd /path/to/consumer-project
aart source add \
  --alias company \
  --kind registry-git \
  --location https://github.example.com/company/agent-artifacts-registry.git \
  --ref main \
  --default \
  --json
aart marketplace list --json
```

`source add` acquires, compiles, and validates the exact snapshot before it saves configuration.
With automatic synchronization (the default), source-bearing marketplace and TUI entry points
compare with the origin and publish a validated changed snapshot first. Manual mode reports
`not-synchronized` or `could-not-check` without moving the local pointer.
## Consumer lifecycle

Every mutation uses the same review and finalize boundary. Without `--yes`, a command renders its
reviewed plan only; `--yes` finalizes that exact plan. `--json` changes only rendering, never
selection, consent, effects, or exit semantics.

```sh
# Explicit source refresh
aart source sync --alias company --json

# Review, then finalize
aart marketplace install company/skill/code-review --profile claude --json
aart marketplace install company/skill/code-review --profile claude --yes --json

aart marketplace status --profile claude --json
aart marketplace update --profile claude --yes --json
aart marketplace update --profile claude --prune --yes --json
aart marketplace uninstall company/skill/code-review --profile claude --yes --json
```

An empty `marketplace update` selects every installed artifact in the given profile and scope.
After `source sync`, status distinguishes `current`, `update_available`, `removed_upstream`,
`source_unavailable`, and `local_drift`. `--prune` removes only the reviewed items outside the
authoritative selected set.

An artifact can declare `requires`. Direct install and update calculate a deterministic transitive
closure before review; an unavailable or conflicting dependency cannot create a partial install.

## MCP setup and credentials

A v2 recipe and its package-root `SETUP.md` are compiled before AART plans an installation effect.
Review shows effects, capabilities, entrypoint, trust, and the manual route without secrets.

A human supplies credentials in an approved interactive session. AART never writes them to a
registry, state, JSON output, or logs. Registries may use safe placeholders such as
`${GITHUB_PERSONAL_ACCESS_TOKEN}`; container images should be pinned by digest.

## Reading, checking, and undoing a setup

Every setup run writes a complete account of itself — the plan hash, the installer hash, when it ran,
how it exited, and one receipt per step. Three actions read that account after the run is over.

```sh
# What did the run actually do?
aart marketplace receipt show company/mcp/github --profile claude --json

# Is any of it still true?
aart marketplace receipt verify company/mcp/github --profile claude

# Reverse it — review first, then finalize
aart marketplace receipt undo company/mcp/github --profile claude
aart marketplace receipt undo company/mcp/github --profile claude --yes
```

`show` renders the persisted record. `verify` asks this machine whether each receipt's claim still
holds: does the image tag exist and still resolve to the recorded id, does the managed block still
carry the text that was installed, does the Keychain item exist **and hold a non-empty value**. A
claim it cannot ask is reported `unknown` rather than `true`, and `verify` exits non-zero when any
claim is false, so it is usable from CI. It reports and never repairs — an orphaned run directory is
named and left where it is.

`undo` is a mutation, so it follows the same boundary as everything else: without `--yes` it prints
the effects it would reverse and changes nothing. `--expect <digest>` binds the decision to the exact
undo that was read.

The review names what it will **not** reverse, and why, before you approve it:

```text
Review undo: company/mcp/github#claude/project
reverses: Keychain item service='aart-github' account='token'
  step    3
  module  macos-keychain.store@1
  reason  deletes the Keychain item this run created
reverses: /Users/you/.zshrc
  step    2
  module  file.managed-block@1
  reason  restores the file to the block it held before this run
keeps: aart/mcp/github:1.0.0
  step    1
  module  docker.build@1
  reason  the tag named an image before this run, so it is not removed — but it now points
          at what this run built, and the receipt never recorded the earlier image id, so
          the undo cannot restore the original binding (LAF-58)
Undo: reverses=2, keeps=1
Reviewed only; re-run with --yes to apply this exact undo.
```

Steps are numbered in the order the rollback runs them, which is the reverse of the order they were
applied — so the review reads top to bottom in the order you will watch it happen.

A step whose receipt no longer matches the reviewed plan is reported and skipped, never forced. On
partial success the record is written back as `rollback_incomplete`.

All three are also reachable from `aart` with no arguments, under **Action → receipt**.

## Maintaining a registry

A registry is an ordinary Git checkout. Maintainer mutations prepare reviewed files and stop. The
explicit `registry publish --yes` flow runs every publisher gate and creates the listed commit; AART
never pushes. An empty Git repository is not a registry until its `aart-registry.json` marker exists.

AART reaches every remote by running system Git, with an allowlisted environment rather than the
operator's. If a repository clones at a shell prompt but not through AART, the environment is where
to look: [the environment AART gives Git](docs/configuration/git-environment-v1.md) lists what is
passed, what is dropped, and what to configure instead — `https_proxy` is dropped, and behind a
proxy that is the whole failure.

`registry init` turns an empty checkout into a registry: the two JSON markers, a `.gitignore`,
three GitHub workflows, a `README.md` describing the registry it just made, and a `.aart-version`
pinning the AART that created it. Those last two are written only when absent — they are the files
you own afterwards, and AART never compares or overwrites them. The workflows and the JSON are
managed: hand-edit one and `init` refuses the registry.

The generated workflows need no configuration to run on github.com. To run them inside a company,
set the variables in [Repository variables](#repository-variables) — no file in the registry
changes.

```sh
# Create a registry
aart registry init --source . --source-id company --display-name "Company Registry" \
  --usage-reporting-repository acme/agent-artifacts-registry
aart registry init --source . --source-id company --display-name "Company Registry" \
  --usage-reporting-repository acme/agent-artifacts-registry --yes

# Author a package, or review a native package from another repository
aart registry scaffold skill code-review --source . --summary "Review code." \
  --profile claude --platform darwin
aart registry promote-native skill code-review --source . \
  --url https://github.com/acme/skills.git --ref main \
  --path artifacts/skill/code-review

# Or copy foreign content the upstream has not packaged for AART
aart registry vendor skill code-review --source . \
  --url https://github.com/acme/prompts.git --ref main --path prompts/code-review \
  --artifact-version 1.0.0 --summary "Review code." \
  --profile claude --platform darwin

# Review, then finalize lock + build + validate + audit + one commit
aart registry publish --source .
aart registry publish --source . --yes
```

`promote-native` records a reference to an external repository, pins its resolved commit in the
lock, and leaves ownership upstream. It requires the upstream to already be a native AART source.
`vendor` is the foreign-repository path: it copies a file or subtree into this registry, records the
origin and pinned commit in `provenance.json`, and makes this registry the copy's owner. `revendor`
compares that copy with upstream and plans an explicit versioned refresh; validation and audit reject
a copied payload that drifts from its provenance.

For the complete path, use the [walked company-registry tutorial for Tabnine](docs/tutorials/company-registry-tabnine-v1.md).
The [vendoring tutorial](docs/tutorials/vendoring-v1.md) covers provenance and re-vendoring, and
[porting an MCP server](docs/tutorials/mcp-servers-into-the-registry.md) covers setup recipes.

## Repository variables

Every knob in this project's CI, and in the workflows `registry init` writes, is a GitHub
repository variable with a default that reproduces the public run. **A fork configures itself from
its settings page and never edits a file.** That matters on sync: an edited literal is a permanent
conflict on the line every later merge from upstream touches.

Set variables under *Settings → Secrets and variables → Actions → Variables*. Set them on the
**organisation** where you can: GitHub resolves a repository variable over an organisation one, so
one organisation variable configures every repository, and any single repository can still
override it.

### A fork of this repository

| Variable | Default | What it does |
|---|---|---|
| `AART_RUNNER` | `["ubuntu-latest"]` | JSON array of runner labels. Must be JSON — `["self-hosted","linux","x64"]`, not a bare word |
| `AART_CI_IMAGE` | unset | Container image for the jobs. Unset means the runner's own environment |
| `AART_PYTHON` | `python` | The interpreter's name inside that image |
| `AART_PYTHON_VERSIONS` | `["3.10", "3.14"]` | JSON array for the quality matrix. Pin to one entry when `AART_CI_IMAGE` is set |
| `AART_PIP_INDEX_URL` | `https://pypi.org/simple` | Internal mirror for `ruff`, `mypy` and `coverage` |
| `AART_RELEASE_PYTHON_VERSION` | `3.11` | Interpreter for the release job when no container is used |
| `AART_REFERENCE_REGISTRY_URL` | this project's registry | The registry the release checklist reconciles against |
| `AART_GH_HOST` | `github.com` | `gh` talks to github.com unless told the instance hostname |
| `AART_IMAGE_USERNAME_SECRET` | unset | **Name** of the secret holding the image-registry username |
| `AART_IMAGE_PASSWORD_SECRET` | unset | **Name** of the secret holding the image-registry password |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | unset | **Name** of a secret holding `user:pass` for that index |

### A registry created by `aart registry init`

A registry splits its configuration by one test: **is this a decision about the registry, or a fact
about the instance it runs on?**

*Which* AART version is a decision, so `registry init` pins it in Git, in a one-line `.aart-version`
at the registry root. Bump it in a pull request and the gates run against the new version before it
merges; `git blame` says when the registry moved; a bad bump is one revert away. After fetching, CI
compares `aart --version` with that file and fails if they differ — so a moved tag, an index that
resolved elsewhere, or a stale AART baked into a CI image is caught rather than assumed.

*Where this deployment fetches it from* is a fact about the instance, so it stays in variables. Four
ways in; the first variable that is set wins, and they are never combined:

| Order | Variable | Example | How it fetches |
|---|---|---|---|
| 1 | `AART_PACKAGE` | `aart-cli=={version}` | `pip` from `AART_PIP_INDEX_URL` |
| 2 | `AART_WHEEL_URL` | `https://host/…/v{version}/aart_cli-{version}-py3-none-any.whl` | `curl`, then unzip |
| 3 | `AART_TOOL_PATH` | `/opt/aart` | Already on the runner |
| 4 | `AART_TOOL_URL` | `https://ghe.corp/platform/agent-artifacts.git` | `git clone` at `v` + the pin |

`{version}` is replaced with the pin, so the version is written **once**, in the repository, and no
variable carries one. `AART_REF` overrides the pin for a single registry — the run says so and the
version check switches off, because you asked for a different build deliberately.

The order runs from the most governed supply chain to the least, so migration is additive: stand up
an internal index later, set `AART_PACKAGE`, and it takes over without unsetting anything. Git is
last because it carries the only shipped default — an arm below one that is always set would be
unreachable.

Set none of them and CI reaches `github.com`. Inside a GitHub Enterprise instance that fails on the
first run, loudly, rather than silently pointing at the wrong tool. Which arm answered is printed by
the run: `AART: aart-cli 2.8.6  via wheel https://…`.

The registry also reads `AART_RUNNER`, `AART_CI_IMAGE`, `AART_PYTHON`, `AART_PIP_INDEX_URL`,
`AART_REPOSITORY`, `AART_GH_HOST`, and `AART_PAGES` — set the last to `false` where the instance
offers no GitHub Pages, and the usage dashboard is still built and validated, only not published.

### Registries and images that need a login

A private image needs a `credentials` block, and that block cannot be made conditional: an empty one
and a `null` one are both rejected before the job starts, and a placeholder makes an anonymous pull
fail a `docker login` it never needed. So every containerised job is written twice and `if:` picks
one. **You name the secrets rather than copying them**, because a secret's name is not a secret:

| Variable | Holds |
|---|---|
| `AART_IMAGE_USERNAME_SECRET` | the name of your existing username secret, e.g. `NEXUS_USER` |
| `AART_IMAGE_PASSWORD_SECRET` | the name of your existing password secret |
| `AART_PIP_INDEX_CREDENTIALS_SECRET` | the name of a secret holding `user:pass` for the index |

Setting `AART_IMAGE_USERNAME_SECRET` is what flips the switch. Leave it unset and the job that runs
is the one this project always ran, unchanged. An organisation therefore keeps its own naming and
creates no new secrets, and the index URL stays a bare host — the credential is assembled in the
step, with both halves re-masked first, because GitHub masks the whole `user:pass` it was given and
neither half after a split.

[The Enterprise fork contract](docs/ci/enterprise-fork-v1.md) is the full page. Its runbook is the
ordered version of everything above — mirror this repository onto the instance, set its variables,
choose how registries will fetch it, and only then run `registry init` — followed by every
variable in reference form, what was walked, and what was not.

## Canonical package

A package lives at `<artifact-root>/<type>/<name>/` and contains `artifact.json` and `payload/`.
Its manifest defines SemVer, compatibility, installation, optional `setup`, `requires_aart`, and
`requires`. When it declares setup, `setup/installer.json` must be v2 and `SETUP.md` must be at
the package root; the modules a recipe may use are listed in the
[setup recipe reference](docs/protocol/setup-recipe-v2.md). An invalid hook, setup, dependency, symlink, or unknown file fails compilation
before lock, index, or installation.

```json
{
  "requires": [
    {"type": "skill", "name": "using-residues"}
  ]
}
```

`aart.lock.json` binds references to commits and digests. `aart.index.json` is a deterministic,
payload-free consumer projection. Both are generated and must pass their gates before publication.

## Interface

```text
aart source add|list|sync|health
aart marketplace list|health|install|update|uninstall|status|setup
aart registry init|scaffold|collection|discover|vendor|vendor-batch|revendor|promote-native|refresh-native|lock|build|validate|audit|publish|diff
aart security scan|show|verify|analyzers|suites
aart reporting validate-event|validate-issue|aggregate
aart upgrade --wheel FILE | --source-checkout DIR
```

Running `aart` without a subcommand on a TTY opens the human-oriented TUI (curses or text
fallback). The TUI submits the same canonical requests as flag mode; it is not a second command
engine.

## Verification

```sh
python -m unittest
git diff --check
```

The historical first live-acceptance record remains in
[`docs/testing/PROGRESS-live-acceptance.md`](docs/testing/PROGRESS-live-acceptance.md). The new
remediation run is documented separately and does not rewrite that evidence.

## Development dependencies and what the quality gates run

**The installed runtime has no dependencies.** `dependencies = []` in `pyproject.toml`, standard
library only — that is a design rule, not an accident, and the gates below exist partly to keep it
true. Everything in this section is developer and CI tooling that a user of `aart` never installs.

Install them into a virtual environment, so nothing lands in the system interpreter:

```sh
python3 -m venv .venv
```

```sh
source .venv/bin/activate
```

```sh
python -m pip install -e ".[dev]"
```

`.venv/` is already in `.gitignore`. Activate it in every new shell before running the gates or
`scripts/prepare_release.py`; `deactivate` leaves it. Behind an internal package index, add
`--index-url <your index>` to the install, or set `PIP_INDEX_URL` first. If `python3 -m venv` fails
with an `ensurepip` error, that interpreter's venv support is broken — use another one, for example
`python3.11 -m venv .venv`.

Without these tools six of the ten gates cannot run. `scripts/quality.py` says so before it starts,
names the ones that are missing, and prints the install command; the other four — `unit`,
`integration`, `validate`, `docs-check` — need nothing but Python and can be run on their own.

| Package | Constraint | Used for |
|---|---|---|
| `ruff` | `>=0.6` | formatting and linting — the `format-check` and `lint` gates |
| `mypy` | `>=1.11` | the `typecheck` gate |
| `coverage` | `>=7.6` | the `coverage` gate, branch coverage with `fail_under = 82` |
| `setuptools` | `>=61` | the editable install and the `build-system` backend. Named explicitly because newer Python versions no longer bundle it in `venv`/`ensurepip` |
| `wheel` | `>=0.44` | present in the environment for `pip wheel --no-build-isolation`, which the `packaging-check` gate uses so the build fetches nothing |

Tests are **stdlib `unittest`** — there is no test-runner dependency. The wheel is built by
`scripts/build_wheel.py`, also stdlib, so the offline release path needs neither `setuptools` nor
`build`.

### The ten gates

`python scripts/quality.py` runs all ten, each in a temporary cache directory with
`PYTHONDONTWRITEBYTECODE=1`, stopping at the first failure. `make quality` is a wrapper around
the same script; CI calls the script directly, because a CI image is not obliged to carry GNU Make
and a real one did not. Run a single gate with `make <gate>`.

| Gate | Command | Depends on |
|---|---|---|
| `format-check` | `ruff format --check agent_artifacts tests scripts` | `ruff` |
| `lint` | `ruff check agent_artifacts tests scripts` | `ruff` |
| `typecheck` | `mypy` | `mypy` |
| `unit` | `unittest discover -s tests -p "*_test.py"` | stdlib |
| `integration` | `unittest discover -s tests -p "*e2e_test.py"` — drives the real CLI over real trees | stdlib |
| `validate` | `scripts/validate.py`, then `scripts/version.py check` | stdlib |
| `coverage` | `coverage run --branch --source=agent_artifacts` over the unit suite, then `coverage report` | `coverage` |
| `packaging-check` | `scripts/packaging_check.py` — builds the wheel and inspects it | stdlib |
| `docs-check` | `scripts/docs_check.py` | stdlib |
| `secret-shape-check` | `scripts/secret_shape_check.py` — refuses credential-shaped literals anywhere in the tracked tree, so the repository stays pushable to an instance with push protection on | stdlib |

Four of the ten — `unit`, `integration`, `validate`, `docs-check` — need nothing installed beyond
Python itself.

## Releasing

**Actions → cut release → Run workflow → type the version.** That is the release.

Two things are decided before you press it, and they are the two a machine cannot decide: which
version, and what the notes say. Both arrive on `main` through an ordinary reviewed change.

### What you do

```sh
python scripts/prepare_release.py
```

It asks which version and what the release does in one line, then runs everything local in the
only order that works: the version into the six files that carry it, the four documents into their
places, the ten gates, the eleven checklist checks. It stops at the first refusal and says which
step refused.

One thing it deliberately leaves you: the prose. The documents arrive with their headings and a
visible `TODO(2.9.0)` line wherever a human has to write something, and the script will not
continue while one stands. A change record, a compatibility statement and a checklist entry are
what someone reads to decide whether to upgrade; no command can write them, and a release that
ships without them is a release nobody can assess.

When it finishes, three things are left and none of them is a gate:

1. Commit, push, open the pull request.
2. Merge to `main`.
3. **Actions → cut release → Run workflow → type the version.**

### The same script, driven by an agent

Pass what a person would have typed and read a receipt instead of prose:

```sh
python scripts/prepare_release.py 2.9.0 --summary "One line about the release." --json
```

Both callers take the same path through the same steps — a JSON mode running different code is a
JSON mode reporting a run nobody had. `stdout` carries exactly one document; everything the steps
print goes to `stderr`. It never prompts where there is no terminal to prompt at, and never
substitutes a default for an answer it could not get: a guessed version would set six files to a
number nobody chose.

Three exit codes, and the middle one is the interesting one:

| Code | Meaning | What to do |
|---|---|---|
| `0` | prepared | commit, merge, press the button |
| `3` | documents still hold placeholders | the receipt lists them by file and line — write them, run again |
| `2` | a step failed | read `reason`; nothing already written was undone |

`3` is separate from `2` on purpose. An unwritten changelog is a retry after work; a failing gate
is a stop. One code for both teaches a caller to treat them the same.

### What the button does### What the button does

In this order, writing nothing until every check has passed:

| Step | Refuses when |
|---|---|
| Preconditions | the worktree is dirty, the source version does not match the tag, the notes are missing or empty, the tag already exists, or `HEAD` is not in `origin/main` |
| Ten quality gates | any gate fails |
| Eleven checklist checks | any check fails — four cover this repository, seven reconcile against the reference registry |
| Tag and publish | — |

A run therefore produces a tag and a release, or it produces neither. There is no half-published
state to unpick by hand.

Publishing the release fires `release.yml`, which builds the wheel and attaches it. That keeps one
builder of release artifacts rather than two that can disagree. The release body carries the
wheel's `sha256`, computed from the same tag, so a downloaded asset can be checked against it.

### The same thing from a terminal

The button is a trigger; the sequence lives in a script, so it runs anywhere:

```sh
python scripts/cut_release.py 2.9.0 --registry /path/to/agent-artifacts-registry
```

With no registry checkout to hand:

```sh
python scripts/cut_release.py 2.9.0 --without-registry
```

The seven registry checks are then reported `skipped`, never `passed`, and the run says so. Typing
the flag out is the point: a release that verifies less can only happen on purpose. In CI the same
choice is made by one repository variable, `AART_REFERENCE_REGISTRY_URL` — set, the registry is
cloned and reconciled against; unset, those checks are skipped. It has no default, because a
default naming a github.com repository reproduces nothing on an instance that cannot reach it.

### The workflow is read from the tag, not from `main`

This is the part that catches people, and it caught us. GitHub loads workflow files from the ref
that triggered the run, so a release runs `release.yml` **as it was at the tag**. A fix merged to
`main` after tagging is not in that run, and re-running the failed job replays the same commit
rather than picking the fix up. Move the tag and publish again:

```sh
git tag -f v2.9.0 main && git push -f origin v2.9.0
```

Re-publishing is safe: the attach step replaces an asset of the same name instead of colliding
with it.

## License

AART is released under the [MIT License](LICENSE). Free for any use, including commercial, with no
obligation beyond keeping the copyright notice and the warranty disclaimer. The software is provided
as is, with no warranty and no liability on the author.

Copyright (c) 2026 Michał Filek. From Poland with <3
