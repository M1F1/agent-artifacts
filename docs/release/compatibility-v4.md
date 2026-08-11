# AART 1.2.0 compatibility matrix

This document freezes the supported executable boundary for AART `1.2.0`. Earlier release evidence
remains immutable in the v1–v3 compatibility documents.

| Boundary | Supported in 1.2.0 | Gate |
|---|---|---|
| Python | CPython 3.10–3.14 | Full `make quality` matrix on 3.10 and 3.14 |
| Runtime dependencies | Python standard library only | Import and wheel metadata audit |
| Platforms | macOS and Linux | Protocol/store/install fixtures; setup effects are macOS-only |
| Harness profiles | Claude, OpenCode, Tabnine, Vibe | Built-in profile loading and registry compatibility |
| Source transport | Local directories and Git repositories | Local/Git acquisition and immutable snapshot tests |
| Registry | Optional; zero, one, or many | Direct-only and public/company/team system scenarios |
| Installation scopes | Project and user | Canonical state, path, lifecycle, and migration tests |
| Installation modes | Copy and immutable managed Symlink | Distribution/environment recreation smoke |
| Native Source/Registry Protocol | v1, unchanged | Strict parsers, canonical writers, frozen schema evidence |
| Runtime requirement metadata | Advisory namespaced artifact extension v1 | Parser/evaluator and lifecycle E2E |
| Installation state | v2, unchanged | 0.1 migration/apply/rollback fixtures |
| Configuration/source store | schema v1 / layout v2, unchanged | Round-trip and migration tests |
| Executable delivery | Local editable checkout or local wheel | Index-free distribution smoke |

## Collection lifecycle selection

`marketplace install`, `update`, `uninstall`, `status`, and `setup` accept a qualified
`<source>/collection/<name>` selector. A collection has no independent version; it expands before
Review to the exact member versions already compiled by that source. Artifact selectors and the
Review/Finalize boundary are unchanged.

This is an executable convenience, not a registry compatibility floor. AART `1.1.1` still sees the
collection and can install each visible member coordinate individually. A registry or artifact must
not add `requires_aart >=1.2.0` unless its payload itself invokes the collection command contract.

## Advisory runtime health

Artifacts may use the existing namespaced-extension boundary to publish
`com.m1f1.runtime-requirements`. The compiled index schema does not gain a field, so protocol-v1
readers remain compatible. AART `1.1.1` preserves/ignores the extension and continues to browse and
install the artifact.

`aart marketplace health --environment PATH` reads a repository-owned JSON inventory and reports
per-requirement `satisfied`, `unsatisfied`, or `unknown`. It does not inspect the process environment,
execute probes, install interpreters/packages, or maintain a dependency catalogue. A successfully
computed report exits zero even when observations are unhealthy; JSON states `advisory: true` and
`installation_blocking: false`.

Install, Update, and Setup do not call the runtime-requirement evaluator. The consuming repository
owns environment provisioning, runtime execution, and any CI policy it chooses to apply to the JSON
report.

## Version-floor policy

The executable moves to `1.2.0` because it adds public CLI/TUI capability. This release does not
automatically rewrite source, registry, collection, or artifact version ranges. The public registry
can remain readable/installable at its existing `>=1.1.1,<2.0.0` floor while using a newer AART in
its own quality workflow.
