# Deterministic compiler pipeline v1

C01 defines the typed functional pipeline used by later source/graph compilers. Domain values live
in `agent_artifacts.compiler`; the application service lives in `agent_artifacts.application` and
can perform effects only through three injected callable ports: source acquisition, immutable
object materialization, and snapshot publication. No durable filesystem, Git, network, clock, or
environment adapter is part of this task.

## Phase contract

Every run returns exactly one ordered report for each phase:

```text
Acquire -> Parse -> Handshake -> Resolve -> Normalize -> Validate
        -> Index -> Materialize -> Publish
```

Each successful pure phase produces a frozen typed value, a canonical SHA-256 digest, and sorted
warning/info diagnostics. An error marks that phase failed and all later phases skipped. Independent
acquisition and object-store failures are all attempted and accumulated deterministically.

Index creates an immutable candidate binding the complete acquired-input digest, exact index bytes,
and sorted object byte/digest plans. Only then may Materialize call the object port. Publish is
unreachable until every object receipt matches its plan and is itself accepted only when the
receipt matches the snapshot digest derived from build key, inputs, index, and objects. Partial
immutable-object writes after adapter failures are unreferenced and cannot become current.

## Frozen consumer builds

A Consumer source request must provide a locked revision and expected snapshot digest, and the
acquisition result must match both. Resolve must additionally return `frozen=True`; a moving ref is
therefore unable to reach Normalize, Index, Materialize, or Publish. Maintainer mode may resolve a
moving input in order to produce a new reviewable lock/index candidate.

After Acquire, pure steps receive a narrowed compiler context containing only stable build key,
mode, options digest, and complete input digest. Source locators—including local absolute paths—are
not visible to those steps and are excluded from compilation identity. Replaying equal snapshots,
revisions, locks/options, and phase functions yields equal candidates, diagnostics, and publication
digests regardless of source request order or host locator.

## C02 extension point

`CompilerSteps` is intentionally generic in C01. C02 supplies the concrete artifact/source graph
types and functions for compatibility, effects, collections, external references, and normalized
marketplace records without changing the effect boundary or publication gate. The graph contract,
selection semantics, history rules, and typed phase bridge are documented in
[`graph-v1.md`](graph-v1.md).
