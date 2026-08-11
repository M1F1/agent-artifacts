# AART 1.1.0 compatibility matrix

This document freezes the supported executable and protocol boundary for AART `1.1.0`. The
`1.0.0` boundary remains recorded, unedited, in [`compatibility-v1.md`](compatibility-v1.md).

| Boundary | Supported in 1.1.0 | Gate |
|---|---|---|
| Python | CPython 3.10–3.14 | Full `make quality` matrix on 3.10 and 3.14 |
| Runtime dependencies | Python standard library only | Import and wheel metadata audit |
| Platforms | macOS and Linux | Protocol/store/install fixtures; setup effects are macOS-only |
| Harness profiles | Claude, OpenCode, Tabnine, Vibe | Built-in profile loading and registry compatibility |
| Source transport | Local directories and Git repositories | Local/Git acquisition and immutable snapshot tests |
| Registry | Optional; zero, one, or many | Direct-only and public/company/team system scenarios |
| Installation scopes | Project and user | Canonical state, path, lifecycle, and migration tests |
| Installation modes | Copy and immutable managed Symlink | Distribution/environment recreation smoke |
| Native Source/Registry Protocol | v1 (unchanged) | Strict parsers, canonical writers, frozen schema evidence |
| Installation state | v2 (unchanged) | 0.1.x migration/apply/rollback fixtures |
| Configuration schema | v1 document, relaxed uniqueness rule | Round-trip, hand-authored, and multi-ref parser tests |
| Source store layout | **v2, ref-aware** | Migration planning/apply, crash-resume, and conflict tests |
| Setup | Reviewed recipe protocol v1; macOS effects | Fake Keychain/process, partial/retry/rollback tests |
| Security assessment | Baseline/provider/attestation schema v1 | Provider failure and bundle policy matrices |
| Usage reporting | Optional; disabled without destination | Absent/failure-isolation matrix |
| Executable delivery | Local editable checkout or local wheel | Index-free distribution smoke |

## What changed since 1.0.0

`1.1.0` is a minor release: it adds public command surface and relaxes one configuration rule. No
protocol, artifact, registry, or installation-state schema changed.

### Added command surface

Eleven new commands. A registry artifact that documents any of them must declare
`requires_aart >= 1.1.0`, because `1.0.0` does not expose them:

- `aart marketplace install|update|uninstall|status|setup`
- `aart source sync|health|doctor`

### Configuration: one relaxed rule, and its direction

`1.0.0` rejected a configuration that named one Git origin at two refs, because the source store was
keyed by origin alone and the two sources would have shared a mirror and pointer. `1.1.0` keys the
store by `(kind, location, ref)` and therefore accepts it.

**This compatibility is one-directional, and that matters for `requires_aart`:**

| Configuration | Read by 1.0.0 | Read by 1.1.0 |
|---|---|---|
| Single ref per origin (every 1.0.0 configuration) | accepted | accepted |
| Same origin at two refs | **rejected** | accepted |
| Same origin *and* ref twice | rejected | rejected |

A configuration written by `1.1.0` that uses multi-ref sources cannot be read by `1.0.0`. Existing
`1.0.0` configurations continue to load unchanged. Downgrading is therefore safe only if no
multi-ref source was added; there is no automatic downgrade path, and none is claimed.

### Source store layout

The managed source store moves to a ref-aware layout recorded in
`<data_root>/sources/store.json`. The first `1.1.0` run against a `1.0.0` store resolves each
configured source to a directory that does not exist yet, so sources read `missing` until either
`aart source doctor --apply` rebinds them or `aart source sync` republishes them. `aart source
health` reports `pending_store_migration` and names the remedy. Nothing is migrated implicitly:
moving user data is never a side effect of a read.

Migration is refused rather than guessed when a legacy and a ref-aware directory both exist
(conflict), or when one legacy directory could belong to either of two configured refs (ambiguity).

### Configuration writes

Reviewed source-management writes are now guarded by a configuration lock and an expected-digest
compare-and-swap. A concurrent writer is refused with `config-write-conflict` instead of being
silently overwritten. This changes no on-disk format.

## Registry expectations

The public `M1F1/agent-artifacts-registry` declares AART `>=1.0.0,<2.0.0`, which continues to hold.
Registry capability and SemVer handshakes—not an exact executable patch—decide compatibility. An
artifact whose payload documents the commands or multi-ref behaviour added here must raise its own
`requires_aart` minimum to `1.1.0`.
