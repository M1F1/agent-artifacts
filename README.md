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

## Quick start

Python 3.10 or later is required.

```sh
python -m pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts

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
`source sync` is the explicit snapshot-refresh operation; `marketplace list` and `status` use the
last local validated snapshot and perform no hidden fetch.

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

## Maintaining a registry

A registry is an ordinary Git checkout. AART can prepare and verify changes, but never commits or
pushes them. An empty Git repository is not a registry until its `aart-registry.json` marker exists.

```sh
# Create a registry
aart registry init --source . --source-id company --display-name "Company Registry"
aart registry init --source . --source-id company --display-name "Company Registry" --yes

# Author a package, or review a native package from another repository
aart registry scaffold skill code-review --source . --summary "Review code." \
  --profile claude --platform darwin
aart registry promote-native skill code-review --source . \
  --url https://github.com/acme/skills.git --ref main \
  --path artifacts/skill/code-review

# Review/finalize generated publication artifacts
aart registry lock --source .
aart registry lock --source . --yes
aart registry build --source .
aart registry build --source . --yes
aart registry validate --source . --strict --frozen --json
aart registry audit --source . --json
```

`promote-native` records a reference to an external repository, pins its resolved commit in the
lock, and validates its package through the same compiler as a locally owned artifact. This keeps
reviewed subscriptions and updates easy without adapting a foreign legacy layout.

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
aart registry init|scaffold|format|promote-native|refresh-native|lock|build|validate|audit|diff
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
