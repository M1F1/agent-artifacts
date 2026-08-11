# Marketplace graph compiler v1

C02 supplies the IO-free source/compatibility/effects graph used by the C01 phase framework. Its
inputs are already validated native or registry index records; acquisition, trust calculation,
content-addressed storage, policy, install planning, and human coordinate parsing remain separate
bounded contexts.

## Qualified records

Every `GraphSource` has both a configured `SourceAlias` and a source-authored `SourceId`. Artifact
identity is qualified by the configured alias, so equal `skill/name` identities from distinct
sources remain distinct. Duplicate aliases, duplicate source IDs, duplicate qualified artifacts,
source-ID mismatches, and missing required compiler capabilities fail before a graph is returned.

An external artifact referenced through a registry remains qualified by the registry alias while
its pinned origin URL, commit, and path remain in the normalized provenance projection. C02 never
dereferences an external ref or assigns trust; P03 must already have resolved it through committed
lock data.

## Collections

Protocol-v1 collection references are source-local. Compilation qualifies them with the source
alias, rejects dangling artifacts/collections, rejected version bounds, duplicates, and cycles,
then stores the fully expanded member coordinates. Expansion is sorted and deduplicated, and the
same `expand_collection` result is consumed by selection now and by later bundle, security, and
installation tasks.

## Compatibility and selection

Compatibility evaluates these independent dimensions and retains every reason:

- harness profile and platform;
- project/user scope and Copy/Symlink mode;
- install effects supported by the selected harness projection;
- setup platform and setup capabilities.

An optional artifact `requires_aart` range is payload compatibility evaluated against the running
executable version. It is checked per selection: an unsupported artifact is reported with
`aart-version-unsupported` without changing unrelated artifacts' compatibility. An absent range is
unbounded. Producers maintain the range explicitly from capabilities used by the artifact; the
compiler never substitutes or auto-bumps the current AART version.

Setup compatibility is distinct from payload compatibility. A caller may set `require_setup=False`
to allow a compatible payload while still exposing missing setup reasons for later policy/review.
Broad selection returns incompatible or removed records as `skipped` items with stable reasons.
Explicit selection fails with `artifact-incompatible` or `artifact-not-found`; it never silently
drops a requested item or version.

## Previous-snapshot rules

C02 compares each qualified current artifact with the previous marketplace snapshot:

- version precedence regression fails;
- unchanged SemVer precedence plus any changed manifest, payload, object, or projected-semantic
  digest fails with `artifact-version-unchanged` (build metadata alone cannot hide a change);
- increased version precedence with an unchanged projected semantic digest succeeds with the
  reviewable warning `artifact-version-without-content`;
- an artifact absent from the current graph becomes a `removed` tombstone and cannot be selected.

The projected semantic digest covers payload identity, profile/platform compatibility, scopes,
modes, install effects, and setup recipe/platform/capabilities. The full object/manifest/payload
checks make same-version comparison fail closed even when a changed byte is outside that projection.

## Deterministic phase output

`marketplace_graph_bytes` emits canonical payload-free JSON sorted by qualified coordinates.
`compile_marketplace_graph_phase` binds those bytes and all warning diagnostics into a typed C01
`PhaseOutput`. Equal normalized inputs therefore produce an equal graph, equal bytes, and equal
phase digest without filesystem, network, clock, locale, or host-path access.
