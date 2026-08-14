# AART 2.0.0 compatibility matrix

AART `2.0.0` is a major release over the frozen `1.4.0` boundary. It is the canonical remediation:
AART becomes a single, current-protocol product, and the legacy catalog product that shared the
binary with it is gone.

| Boundary | Supported in 2.0.0 | Gate |
|---|---|---|
| Python | 3.10+ | package and system matrix |
| Runtime dependencies | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1, extended with `requires` | schema freeze and registry gates |
| Canonical package tree | `SETUP.md` allowed at the package root | native tree and registry gates |
| Installation state | v2, unchanged | lifecycle tests |
| Setup recipe | v2 only; v1 rejected | setup parser and canonical setup tests |
| Reporting | v1, unchanged | reporting tests |
| CLI surface | **nine top-level commands removed** | CLI and e2e tests |
| 0.1 installation state | refused, never converted | install-state tests |

## Why this is major and 1.4.0 was not

`compatibility-v7.md` argued that `1.4.0` stayed minor because "no command, subcommand, or flag was
removed or renamed". That criterion is exactly what this release fails, and deliberately: `list`,
`install`, `status`, `check`, `update`, `uninstall`, `setup`, `migrate`, and `upstream` are removed
from the top level. What remains is one canonical command family — `marketplace`, `source`,
`registry`, `security`, `reporting`, `upgrade`.

The v7 note also warned that an executable major makes every artifact declaring the conventional
`requires_aart` ceiling of `2.0.0` incompatible in one step. That consequence is real and is
accepted here rather than deferred. It is the same disruption the remediation asks of every other
boundary, and pretending the removal of nine public commands is a minor release would misinform
exactly the clients least able to absorb it — a `1.4.0` user would be offered `1.5.0` as compatible
and lose half the CLI on upgrade.

## The 1.4.0 contradiction this release resolves

`1.4.0` required a package-root `SETUP.md` for every setup v2 recipe, while its own canonical
package validation refused any file at the package root other than `artifact.json`, `README.md`,
`provenance.json`, `payload/`, and `setup/`. A registry that followed the documented `1.4.0`
migration — "raise both fields to `2`, add the document, then relock and rebuild" — was then
rejected by `registry validate` with:

```text
error: unexpected canonical package path: SETUP.md
```

The `1.4.0` migration was therefore unsatisfiable: the recipe could not be valid and publishable at
the same time. `2.0.0` adds `SETUP.md` to the allowed package roots, so publication and consumption
agree on one rule. Any registry that migrated its recipes to setup v2 requires `2.0.0` or later; no
released `1.x` executable can validate it.

## Breaking changes

### Removed commands

| Removed | Canonical replacement |
|---|---|
| `aart list` | `aart marketplace list` |
| `aart install` | `aart marketplace install` |
| `aart status` | `aart marketplace status` |
| `aart check` | `aart marketplace status` |
| `aart update` | `aart marketplace update` |
| `aart uninstall` | `aart marketplace uninstall` |
| `aart setup` | `aart marketplace setup` |
| `aart migrate` | none — the 0.1 boundary is refused, not converted |
| `aart upstream` | none — author canonical packages in a registry checkout |
| `aart registry migrate` | none — the legacy catalog reader is removed |

The canonical verbs take a `<source>/<kind>/<name>[@<version>]` coordinate. An unqualified
`<kind>/<name>` resolves only when it is unique; otherwise the diagnostic names every valid
coordinate. Legacy `--source`/`--repo` are not accepted anywhere.

This table lists top-level commands only. The subcommands removed with them —
`aart source doctor` and the `aart setup` verbs — are recorded in
[`compatibility-v8-addendum.md`](compatibility-v8-addendum.md), added during `2.2.0`.

### `requires_aart` windows must be re-authored

A registry or artifact declaring the conventional `max_exclusive: "2.0.0"` excludes this release.
Raise the window to `min_inclusive: "2.0.0"`, `max_exclusive: "3.0.0"`, relock, and rebuild. A
registry that also publishes setup v2 recipes or a package-root `SETUP.md` **must** declare the
`2.0.0` floor, because no `1.x` executable can validate that content.

### Retired 0.1 installation state

A recognized 0.1 state file is rejected at the boundary with one typed diagnostic naming the only
supported move: remove the retired state and reinstall from a configured canonical source. There is
no conversion, no compatibility flag, and no automatic upgrade.
[`migration-v1.md`](migration-v1.md) is retained as released `1.0.0` evidence and is marked
historical; every command it names is removed.

### Artifact dependencies

An artifact manifest may declare `requires`. A runnable artifact cannot be installed without its
declared required artifacts; the transitive closure is resolved before review, and an unsatisfied
dependency fails without mutation. A `1.x` executable reports `unknown field 'requires'` and
refuses the registry, which is the correct one-way outcome.

## What did not change

Installation state stays at v2 and is not migrated. The reporting protocol, the security assessment
protocol, the configuration schema, and the registry/native source protocol revision are unchanged.
Consent semantics are unchanged: without `--yes` every action stops after Review and changes
nothing. Copy and managed Symlink layouts, the object store, and existing installation records are
read and reconciled exactly as before.
