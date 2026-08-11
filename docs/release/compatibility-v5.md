# AART 1.3.0 compatibility matrix

This document freezes the supported executable boundary for AART `1.3.0`. Earlier release evidence
remains immutable in the v1–v4 compatibility documents.

| Boundary | Supported in 1.3.0 | Gate |
|---|---|---|
| Python | CPython 3.10–3.14 | Full `make quality` matrix on 3.10 and 3.14 |
| Runtime dependencies | Python standard library only | Import and wheel metadata audit |
| Platforms | macOS and Linux | Protocol/store/install fixtures; setup effects are macOS-only |
| Harness profiles | Claude, OpenCode, Tabnine, Vibe | Built-in profile loading and registry compatibility |
| Source transport | Local directories and Git repositories | Local/Git acquisition and immutable snapshot tests |
| Registry | Optional; zero, one, or many | Direct-only and federated reporting scenarios |
| Installation scopes | Project and user | Canonical state, path, lifecycle, and migration tests |
| Installation modes | Copy and immutable managed Symlink | Distribution/environment recreation smoke |
| Native Source/Registry Protocol | v1, unchanged | Strict parsers, canonical writers, frozen schema evidence |
| Reporting protocol | v1, unchanged serialized payload | Schema, routing, destination, CLI, and TUI tests |
| Installation state | v2, unchanged | 0.1 migration/apply/rollback fixtures |
| Configuration/source store | schema v1 / layout v2 | Round-trip, migration, and downgrade-boundary tests |
| Executable delivery | Local editable checkout or local wheel | Index-free distribution smoke |

## Consent default and compatibility

When a new configuration omits `reporting`, AART now resolves the mode to `prompt`. An explicit
`disabled` remains fully silent. Existing explicit `prompt` and `automatic` settings keep their
meaning, and organization policy can still deny public destinations.

Prompt mode no longer requires one central destination. This is an additive `1.3.0` configuration
form, but AART `1.2.0` rejects it because that client required `destination` for every non-disabled
mode. Therefore configuration compatibility is intentionally one-way: every accepted `1.2.0`
configuration remains accepted by `1.3.0`, while a prompt-without-destination configuration must be
given a destination or changed to explicit `disabled` before downgrading.

## Federated registry routing

Without an explicit central destination, AART groups installed-artifact results by the configured
registry source that advertised each artifact. Each registry receives only results for its own
artifacts. Two aliases or refs advertising the same GitHub Issues endpoint produce one report, and
direct sources or registries without a valid `usage_reporting` service produce none.

The source alias is local routing state. It is never serialized into reporting protocol v1, whose
payload and schema remain unchanged. Discovery uses only enabled registry sources and their current
local snapshots; preparing a report never fetches or executes registry content.

The human TUI lists the proposed endpoints and retains two default-No confirmations per Issue: one
before showing the exact payload and one before submission. An explicit destination continues to
produce one combined central report. `automatic` reporting still requires that explicit destination
and can never be activated by a registry advertisement.

## Version-floor policy

The executable moves to `1.3.0` because its public configuration default and routing behavior
change. This release does not automatically rewrite source, registry, collection, or artifact
version ranges. A publisher adds or raises `requires_aart` only when its artifact payload actually
depends on a newer executable capability; client-side analytics behavior alone is not such a
dependency. The public registry therefore retains its existing `>=1.1.1,<2.0.0` floor.
