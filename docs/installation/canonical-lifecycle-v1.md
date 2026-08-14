# Canonical installation lifecycle v1

LIFE01 completes the source-aware lifecycle boundary built on manifest v2, immutable marketplace
objects, Copy, and durable managed Symlink. The functional core plans or classifies work from
explicit state and snapshots; local filesystem and reference-store mutation remains behind an
adapter.

## Selection and terminal outcomes

A selection is restricted to one `project` or `user` scope and may be narrowed by exact qualified
coordinates and profiles. Status and check return exactly one terminal item for every selected
installation. Update and uninstall operate on one exact recorded installation plan at a time, so a
caller processing a basket can preserve one terminal result per item even when another item
conflicts or fails.

Terminal statuses are explicit: `current`, `update-available`, `changed`, `removed`,
`removed-upstream`, `source-unavailable`, `identity-changed`, `missing`, `drifted`, `broken`,
`retargeted`, `replaced`, `conflict`, `failed`, and `skipped`. A zero-change selection is represented
by current/missing/source outcomes rather than an ambiguous successful return.

`source-unavailable` and `identity-changed` divide what used to be one status. The recorded
subscription — alias, kind, origin, ref — is what resolution follows; the source identity the origin
declares is evidence carried inside it. A subscription that is gone, disabled, unhealthy, or now
points somewhere else is `source-unavailable`. A subscription that is intact while its origin
declares a different identity than the installation was made under is `identity-changed`, and
`update` acts on it: the review states both identities and finalizing rebinds the record.

## Status and check do not fetch

Status is fully local. It inspects only manifest-v2 destinations and reports:

- exact digest agreement for copied files and trees;
- current, broken, retargeted, replaced, or missing managed links;
- the recorded identity value inside shared JSON instead of hashing unrelated foreign entries; and
- the named owned marker block inside shared memory files.

Check compares installed evidence with an already built marketplace snapshot. It never invokes
Git, source sync, HTTP, or a moving ref. Fetch/sync is a separate source operation; passing a newer
validated snapshot to check or update does not itself mutate an installation.
Per-destination inspection failures become explicit `failed` terminal status items, so one local
read failure cannot silently erase another selected artifact from the result.

## Recorded-subscription update

Update resolves only the source subscription recorded by the installation:

- source alias and declared source ID;
- source kind and credential-free origin;
- configured Git ref, or the explicit local-source identity; and
- qualified artifact type/name and installed profile/scope/mode.

Memory updates also retain the recorded composition mode (`replace`, `prepend`, `append`, or
`skip`); schema-v2 memory records written before LIFE01 use the compatible `prepend` fallback.

A missing, disabled, unhealthy, renamed, re-pointed, or identity-mismatched source returns
`source-unavailable`. A same-named artifact from another source is never considered. If the exact
healthy source no longer contains the artifact, update returns `removed-upstream` and preserves the
installation. Only an explicit reviewed `prune` converts that fact into an uninstall plan.

Available replacements reuse canonical Install prepare/review/finalize. Copy drift follows the
conflict/force rule; managed links retarget only during Finalize; merge effects remain copied; and
the new object/state/reference evidence is committed by the installation transaction. Source sync
alone never changes installed bytes or link targets.

## Proven-effect uninstall

Uninstall derives every mutation from manifest-v2 ownership evidence and exact destination/state/
reference preconditions:

- unchanged Copy files and trees are removed; drift conflicts unless force was reviewed;
- expected or broken managed links are removed without following them; retargeted/replaced links
  conflict unless force was reviewed; special files always fail closed;
- managed JSON removes only the key/list element matching digest-bound identity evidence and keeps
  foreign configuration, including when force removes a locally modified owned value; and
- managed memory blocks remove only their balanced name-scoped markers and preserve surrounding
  user text.

Missing proven effects are safe no-ops whose state ownership can be released. Invalid JSON,
ambiguous identities, incomplete markers, unsafe path types, or unprovable legacy merge ownership
produce a conflict rather than a guessed deletion.

Effect mutations are serialized with the scope state lock. Finalize revalidates all reviewed
snapshots, applies effects, writes replacement state last, then releases only the exact installed
object reference owner. Every mutation is read back before the next phase. A filesystem/state/
reference failure compensates changed effects and state and verifies the restoration; project and
user state/reference owners remain isolated.

## Merge identity evidence

New canonical installs store immutable `identity_evidence` beside its matching `identity_digest` for
every merge effect. Key merges record their owned key; list merges record the projected identity
fields and values. The state parser keeps the field optional so already-written schema-v2 records
remain readable. A record without this proof can be displayed, but lifecycle removal fails closed;
MIG01 may explicitly enrich legacy records when trustworthy migration input exists.

## Compatibility boundary

The existing 0.1 command implementations remain compatibility adapters until MIG01 removes silent
legacy reinterpretation. New 1.0 consumer/TUI composition uses this canonical lifecycle service;
TUI01/TUI02 add source acquisition and multi-item presentation without weakening its review or
ownership rules.
