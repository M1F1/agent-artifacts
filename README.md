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

Python 3.10 or later is required. Pick the installer you use and the source you trust. The `pip`
and `pipx` commands below were exercised against the published `v2.8.0` artifact and tag. The `uv`
column carries the same three sources and was last exercised at `v2.7.1`, because `uv` was absent
from the release host.

| Source | `pip` (inside your environment) | `pipx` | `uv` |
|---|---|---|---|
| Downloaded wheel | `python -m pip install --no-deps ./agent_artifacts-2.8.0-py3-none-any.whl` | `pipx install ./agent_artifacts-2.8.0-py3-none-any.whl` | `uv tool install ./agent_artifacts-2.8.0-py3-none-any.whl` |
| GitHub release wheel | `python -m pip install --no-deps https://github.com/M1F1/agent-artifacts/releases/download/v2.8.0/agent_artifacts-2.8.0-py3-none-any.whl` | `pipx install https://github.com/M1F1/agent-artifacts/releases/download/v2.8.0/agent_artifacts-2.8.0-py3-none-any.whl` | `uv tool install https://github.com/M1F1/agent-artifacts/releases/download/v2.8.0/agent_artifacts-2.8.0-py3-none-any.whl` |
| Tagged Git repository, no clone | `python -m pip install --no-deps "git+https://github.com/M1F1/agent-artifacts.git@v2.8.0"` | `pipx install "git+https://github.com/M1F1/agent-artifacts.git@v2.8.0"` | `uv tool install "git+https://github.com/M1F1/agent-artifacts.git@v2.8.0"` |

`pipx` and `uv tool` create an isolated tool environment. For a company mirror, replace the
GitHub host and repository with the reviewed HTTPS URL your normal Git credentials can reach; keep a
reviewed tag instead of following a moving branch. AART has no runtime dependencies. The release
wheel is byte-reproducible from its tag and its digest is published in the release notes.

The editable install is for working on AART itself, not for a colleague adopting it:

```sh
git clone https://github.com/M1F1/agent-artifacts.git
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
