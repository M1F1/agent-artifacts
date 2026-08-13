# AART 2.0.0

AART `2.0.0` is one product again.

Until now the binary carried two: a canonical marketplace built on validated sources, compiled
packages, and reviewed plans — and beside it the original 0.1-era catalog, with its own commands,
its own readers, and its own idea of what an artifact is. Live acceptance testing against real
registries and a real consumer project found the seam everywhere. An artifact could pass
publication and fail on consumption. A maintainer command could write legacy-shaped files into a
canonical registry, report success, and have the registry ignore them. A consumer with an empty
checkout could be routed into registry curation because the directory looked like a repository.

This release removes the legacy half rather than adapting to it, and puts one compiler in front of
every boundary that had been guessing.

## Breaking changes

**Nine top-level commands are gone.** `list`, `install`, `status`, `check`, `update`, `uninstall`,
and `setup` move under `aart marketplace`. `migrate` and `upstream` have no replacement: the 0.1
boundary is now refused rather than converted, and canonical packages are authored in a registry
checkout.

**Every `requires_aart` window must be re-authored.** The conventional ceiling of `2.0.0` excludes
this release. Raise the window to `>= 2.0.0, < 3.0.0`, relock, and rebuild. This is the one-step
disruption the `1.4.0` notes warned about; it is accepted here rather than hidden behind a minor
version number that would tell a `1.4.0` user this upgrade is safe.

**A retired 0.1 installation state is rejected**, with one diagnostic naming the only supported
move — remove the state and reinstall from a configured canonical source.

## The 1.4.0 migration that could not be performed

`1.4.0` narrowed setup recipes to revision 2, which requires a package-root `SETUP.md`, and
documented the migration as mechanical: raise both version fields, add the document, relock,
rebuild. Following it produced a registry that `1.4.0` itself refused to validate, because its
canonical package rules did not allow a file named `SETUP.md` at the package root. Publication and
consumption disagreed, and no registry could satisfy both.

`2.0.0` makes `SETUP.md` a valid package-root file, so a setup v2 package is valid end to end. Any
registry that already migrated its recipes needs `2.0.0`; no released `1.x` can read it.

## Also in this release

- **Artifact dependencies are first-class.** A manifest may declare `requires`; the transitive
  closure resolves before review, and an unsatisfied dependency fails without mutation.
- **One reconciliation plan** backs status, update, prune, uninstall, review, and outcome
  rendering, so finalization is never reported independently of durable state.
- **A forced memory replace is reversible again.** The displaced content is preserved as a managed
  sidecar and restored on uninstall; a missing sidecar is a typed conflict, not a silent delete.
- **The index publishes the setup capabilities a recipe actually declares**, so a host missing
  `docker` or `keychain` is refused before any credential is requested.
- **`--memory-mode` is available on the canonical install verb.** The modes were implemented and
  recorded in state, but the only flag that set them lived on a removed command.
- **`registry test --latest-version` and `registry init --minimum-version` follow the running
  release** instead of a literal `1.0.0` frozen in the parser.

See the [2.0.0 compatibility matrix](compatibility-v8.md) and
[release evidence](release-checklist-v8.md).
