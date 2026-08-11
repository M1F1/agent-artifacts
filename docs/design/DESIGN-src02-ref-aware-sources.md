# Design: ref-aware source storage and source maintenance commands (SRC02)

- **Status:** active; follows `CB01` and `LIFE02`
- **Plan:** [PLAN-post-v1-catalog-boundary.md](../plan/PLAN-post-v1-catalog-boundary.md) § SRC02
- **Problem:** the v1 source store is keyed by `(kind, location)`, so one Git origin cannot be
  configured at two refs. `CB01` closed the hole by *rejecting* that configuration; this design
  makes it representable.

## 1. Why the v1 key is wrong

`source_instance_id` hashes `(kind, location)` and the store lives at
`<data_root>/sources/<instance_id>/`, holding one `mirror.git`, one `snapshots/` tree, and one
`current.json` pointer. Two configured sources at different refs of the same origin would resolve
to the same directory and silently overwrite each other's `current.json` — the second sync would
retarget the first source's installed content.

`CB01` therefore made `UserConfiguration` reject a duplicate Git origin outright. That is correct
but restrictive: tracking a registry's `main` and a pinned `release` ref simultaneously is a
legitimate, common request.

## 2. The v2 key

The instance identity becomes `(kind, location, ref)`, where `ref` is the configured ref (`None` for
local sources, and for Git sources the recorded ref rather than the resolved revision).

**Identity hashes the literal `location`, and deliberately continues to.** Origin normalization
(`git_origin_key`: HTTPS/SSH/SCP spellings, host case, optional `.git`) lives in the
`UserConfiguration` uniqueness invariant, not in the store key — and that is enough, because the
invariant already makes it impossible to configure two spellings of one origin at the same ref. So
two spellings can never race for one directory. Moving normalization into the identity would change
the directory name of every source whose configured location is not already in canonical form,
widening the migration for no correctness gain.

Consequences:

- every existing Git source's directory name changes;
- the `UserConfiguration` uniqueness invariant moves from *origin* to *(origin, ref)*;
- two refs of one origin get independent mirrors, snapshots, and pointers, so neither can retarget
  the other.

Local sources keep a `ref` of `None` and therefore keep their current identity.

## 3. Store versioning

`<data_root>/sources/store.json` records the layout:

```json
{"schema_version": 2}
```

An absent file means a v1 layout. The file is written **only after** every planned rebind has
succeeded, so an interrupted migration is never recorded as complete.

## 4. Migration

Migration is planned as a pure function over `(configuration, existing directory names)` and applied
separately, so the plan can be reviewed — including as JSON — before anything moves.

For each configured Git source:

| Old directory | New directory | Action |
|---|---|---|
| exists | absent | `rebind` — atomically rename old → new |
| exists | exists | `conflict` — refuse; both pointers are real data |
| absent | exists | `current` — already migrated |
| absent | absent | `absent` — nothing stored yet; the next sync creates it |

**The ambiguity rule.** A v1 configuration could hold only one ref per origin, so each legacy
directory maps to exactly one configured source and migration is unambiguous. A *hand-authored* v2
configuration may legitimately declare two refs for one origin while a single legacy directory still
exists. That legacy directory cannot be attributed to either ref — its `current.json` records a
resolved revision, not the ref it was configured from. Migration refuses to guess: it emits an
explicit diagnostic naming every candidate alias and leaves the directory untouched. The remedy is
to sync the sources, which creates correct per-ref directories, and then remove the legacy one.

**Recovery and idempotence.** Rebinding uses an atomic directory rename. If the process dies
mid-migration, every completed rename is already durable and `store.json` is still absent, so a
re-run replans from what is actually on disk and finishes. Re-running after a complete migration is
a no-op. A rename is never attempted onto an existing directory, so no pointer is ever clobbered.

Migration never fetches, never writes user configuration, and never publishes objects.

## 5. Maintenance commands

Re-adding an existing alias is the wrong way to refresh it — `source add` is for onboarding and
carries addition semantics. SRC02 adds three explicit commands:

- `aart source sync [--alias A]` — re-synchronize configured sources through the existing
  `sync_source` path. Fails closed on policy, honours `--offline`, and never changes source
  identity or policy defaults.
- `aart source health [--json]` — per-source health: pointer presence, resolved revision, snapshot
  age against the configured `max_age_seconds`, and staleness.
- `aart source doctor [--json] [--apply]` — report layout version, legacy directories, planned
  rebinds, conflicts, and ambiguity. Read-only unless `--apply` is passed.

None of the three may create, rename, or delete a configured source, or alter policy.

## 6. Out of scope

- Concurrent-writer isolation for configuration writes — that is `CFG02`.
- Any change to the object store or installed state.
- Automatic removal of legacy directories: after a conflict or ambiguity the operator decides.
