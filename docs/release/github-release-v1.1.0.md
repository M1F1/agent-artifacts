# AART 1.1.0

AART `1.1.0` gives agents a canonical non-interactive surface over configured sources, and makes the
managed source store ref-aware. It is a minor release: no protocol, artifact, registry, or
installation-state schema changed, and every `1.0.0` configuration continues to load unchanged.

## Added

**A canonical JSON lifecycle for agents.** `aart marketplace install`, `update`, `uninstall`,
`status`, and `setup` run over the same configured sources the TUI uses. Artifacts are addressed as
`<source>/<kind>/<name>[@<version>]`; a shorter `<kind>/<name>` resolves only when exactly one
configured source provides it, and otherwise fails naming every valid coordinate rather than picking
one.

Two properties carry the safety of running this unattended:

- **Review before Finalize.** Without `--yes` a command prints the exact plan it would apply and
  changes nothing. With `--yes` it finalizes the digest of the review computed in the same process,
  so a plan cannot drift in between.
- **Authorizations are never implied.** `--authorize-untrusted-source`,
  `--authorize-custom-entrypoint`, and `--approve-setup-effects` are each required explicitly.
  Omitting one denies; it never prompts and never assumes.

**Source maintenance commands.** `aart source sync`, `health`, and `doctor` — so refreshing a source
no longer means re-adding an existing alias. None of them can change source identity, configuration,
or policy.

**One Git origin at several refs.** The managed source store is now keyed by
`(kind, location, ref)`, so tracking a registry's `main` alongside a pinned release ref gives each
its own mirror, snapshots, and pointer. `1.0.0` rejected this configuration because both sources
would have shared one pointer.

## Changed

**Reviewed configuration writes are lock-guarded.** Source management reads the configuration, syncs
over the network, and then writes. A writer landing in that window was previously overwritten
silently; it is now refused with `config-write-conflict` and a retry diagnostic.

**The legacy `--source`/`--repo` compatibility warning** now names `aart marketplace` as well as the
TUI.

## Upgrading from 1.0.0

**Your sources will read `missing` on the first run**, because the ref-aware layout resolves them to
new directory names. Nothing is lost. Run either:

```shell
aart source doctor          # review the exact rebinds
aart source doctor --apply  # perform them
```

or `aart source sync` to republish. `aart source health` reports `pending_store_migration` and names
the remedy. Migration is never implicit — moving user data is not a side effect of a read — and it
refuses to guess when a legacy and a ref-aware directory both exist, or when one legacy directory
could belong to either of two configured refs.

**Downgrading** to `1.0.0` is safe only if you have not added a second ref for an origin: `1.0.0`
rejects such a configuration. See [`compatibility-v2.md`](compatibility-v2.md).

Migration from 0.1.x is unchanged: `migration-v1.md`.
