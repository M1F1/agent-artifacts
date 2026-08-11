# Federated marketplace and effective trust v1

This document records the implemented MKT01 boundary. It refines
[`SPEC-aart-1.0.md` section 15](../design/SPEC-aart-1.0.md) without adding CLI/TUI or installation
orchestration, which are later tasks.

## Domain boundary

The marketplace is a pure runtime projection over three already-validated inputs:

1. the qualified C02 marketplace graph;
2. the effective CFG01 user configuration and organization policy;
3. one SRC01 health/current state for every enabled source.

`build_marketplace` performs no filesystem, process, environment, or network access. Source
acquisition and snapshot validation happen before this boundary. The result retains qualified
artifacts, qualified collections, source health/freshness, provenance, content digests, and a local
effective-trust decision. It does not copy payload bytes or mutate the compiled graph.

The runtime projection is bounded to 1,000 enabled sources and 100,000 artifacts or collections.
Malformed, missing, extra, duplicate, or identity-mismatched runtime source states fail closed with
typed diagnostics instead of producing a partial catalog.

## Deterministic union and resolution

Sources and artifacts are sorted by:

1. optional default-registry rank;
2. configured display order;
3. source alias;
4. artifact type, name, and version.

The default registry affects presentation only. It never shadows another source and never resolves
an identity collision. An unqualified artifact query succeeds only when exactly one available item
matches. A collision returns `artifact-ambiguous` with every valid qualified coordinate, for
example `company/skill/review@1.0.0`. A source-qualified query selects only that source. Removed
history can be included in explicit list/search projections but can never resolve for use.

Search and list operations are stable, source-aware projections. Collections remain qualified and
may reference only catalog items from the same source.

## Effective trust

Trust is derived locally and is never accepted as an artifact self-claim:

| Source/evidence | Effective class |
| --- | --- |
| Mutable configured local source | `local` |
| Configured direct Git source | `direct-source` |
| Registry entry with a valid approved review | `registry-reviewed` |
| Approved registry entry whose exact source identity is organization-designated | `company-reviewed` |
| Registry entry with absent, incomplete, pending, or rejected review | `unverified` |

An exact company identity consists of declared `source_id`, normalized Git host, and normalized
repository path. It applies only to `registry-git` sources. Alias names, display order, default
registry status, and review metadata on direct sources cannot elevate trust.

Every decision includes a deterministic evidence digest bound to artifact manifest, payload, and
object digests; normalized/redacted provenance; source kind, origin, declared ID, resolved revision,
and snapshot digest; entry review; and the complete canonical organization policy. Changing any of
that evidence invalidates the prior decision. Effective trust is runtime data and is not serialized
into an artifact package.

## Output contract

Canonical JSON includes:

- schema version, source health/age/origin/revision/snapshot digest, and diagnostics;
- qualified artifact coordinate, lifecycle, summary, provenance, manifest/payload/object digests,
  effective trust, and trust-evidence digest;
- qualified collection coordinate, summary, and members.

The human renderer exposes the same operational identity: source, health, qualified coordinate,
trust, summary, object digest, and provenance. Common credentials and query/assignment secrets are
redacted defensively from untrusted output text.

MKT01 does not enforce installation scope, setup capabilities, or minimum-installation-trust
policy. Those decisions belong to the installation and setup application services, which consume
this marketplace evidence without re-deriving source trust.

Artifact runtime requirements are a later advisory projection documented in
[`runtime-requirements-v1.md`](runtime-requirements-v1.md). They remain in namespaced artifact
manifest metadata rather than the compiled marketplace index, so they do not change protocol-v1
reader compatibility or participate in artifact resolution and installation compatibility.
