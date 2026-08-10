# Canonical Copy installation boundary v1

INS01 introduces the AART 1.0 installation application boundary without switching the legacy CLI
or TUI to it prematurely. Consumer surfaces can now prepare and finalize source-aware installs over
the federated marketplace and immutable object store. INS02 and LIFE01 build Symlink and lifecycle
commands on the same plan/state contract.

## Prepare, review, finalize

`prepare_install` performs the non-mutating part of the flow:

```text
qualified resolve -> trust/policy -> compatibility -> verified CAS object
                  -> Copy projection -> destination/state snapshots -> immutable review digest
```

The request defaults to Copy and identifies the artifact, optional source/version qualification,
harness profile/version, platform, project or user scope, force decision, and offline intent. An
unqualified collision is never resolved by source order. User-scope minimum trust comes from the
effective organization policy. Compatibility uses the shared compiler decision for profile,
platform, scope, mode, and effect support.

Offline preparation succeeds only when `read_object` returns the exact verified content-addressed
object. The planner reparses `artifact.json` and optional `provenance.json`, recomputes manifest and
payload digests, and checks identity/version/compatibility/install/primary-payload semantics against
the index. A missing, corrupt, or evidence-mismatched cache never falls back to mutable source
files.

The frozen plan binds:

- requested and resolved qualified coordinates;
- source alias, declared ID, kind, credential-free origin, exact Git commit or explicit local
  revision, and subscription ref;
- artifact version plus manifest, payload, object, trust-evidence, and policy digests;
- normalized credential-free upstream provenance when present;
- the exact CAS root/candidate, destinations, requested/actual Copy effects, desired content
  digests, and observed destination preconditions;
- the complete replacement manifest-v2 digest, state precondition, lock path, and installed-object
  reference owner.

Changing bound content, a destination, the state replacement, or the CAS location invalidates the
review digest. `finalize_install` also requires the digest explicitly supplied by the reviewing
caller and a current marketplace/effective-configuration projection. It rejects policy, trust,
source health/revision/snapshot, artifact, or provenance changes after Review.

## Copy effects and drift

Canonical payloads project through the established harness profiles and legacy pure planners. The
adapter converts their output into the new immutable effect algebra:

| Artifact | Copy projection |
| --- | --- |
| skill | complete payload tree |
| guideline | standalone Markdown file |
| MCP | managed JSON key merge |
| hook | payload tree plus managed JSON registration |
| memory | managed instruction block or standalone file target |

The application layer contains no filesystem access. The local adapter uses bounded no-follow
inspection and rejects links, special files, unsafe parents, invalid JSON, and paths outside the
explicit project/user target policy.

An exact desired destination is current. Differing unowned content or drift is a conflict unless
the request was reviewed with force. JSON merge planners retain unrelated configuration, reject
non-object path crossings and differing key/list identities without force, and permit distinct
managed identities to share one configuration path. A later source sync cannot alter copied bytes.

## Transaction and state

Finalize rechecks the immutable object and every destination/state snapshot, then repeats those
checks after acquiring the scope state lock. Any difference returns a structured `conflicted`
outcome without writes.

Before the first effect, the adapter retains a transaction reference to the CAS object so
concurrent garbage collection cannot remove it. It then applies tree, file, and merge effects,
writes canonical manifest v2 last, installs the durable `installed` object reference, and releases
the temporary reference.

If an effect, state write, or installed-reference update fails, the adapter restores every
attempted destination and the prior state snapshot in reverse order. The outcome records each
effect as `changed`, `current`, `failed`, `rolled-back`, or `skipped`; it never reports a partial
installation as successful. A stale transaction reference is safe over-retention and is reported
as pending cleanup rather than weakening the installed reference.

Manifest v2 retains the qualified source subscription, exact source revision, artifact version and
digests, profile/version, scope, requested mode, and effect proof. It stores neither trust labels,
credentials, raw setup output, CAS host paths, nor copied payload bytes.

## Deferred boundaries

- Managed Symlink and explicit atomic retarget are defined in
  [`canonical-symlink-v1.md`](canonical-symlink-v1.md).
- Status, update, check, uninstall, and reference release belong to LIFE01.
- Setup recipe execution remains a separate post-payload result and belongs to SET01.
- CLI/TUI adoption occurs only after the lifecycle services are complete, so legacy commands are
  not silently reinterpreted during this slice.
