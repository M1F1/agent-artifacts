# Advisory runtime requirements v1

This document defines informational runtime metadata for artifacts and the repository-supplied
environment inventory consumed by `aart marketplace health`. It does not extend installation
compatibility and does not make AART a runtime or dependency manager.

## Responsibility boundary

- AART provides the artifact installation structure.
- Configured registries and sources provide the federated marketplace and may publish advisory
  runtime metadata.
- The consuming repository owns its runtime, dependency installation, and the decision to run an
  installed artifact.

AART never probes interpreters, commands, packages, or the ambient process environment for this
feature. It never installs a declared runtime capability. An absent, unknown, invalid, or
unsatisfied declaration never hides an artifact and never blocks Install, Update, or Setup.

## Artifact declaration

Requirements live in the optional namespaced artifact-manifest extension
`aart.runtime-requirements`. Existing protocol-v1 readers already preserve namespaced
extensions, so older AART versions can continue to browse and install the artifact without
understanding this advisory data.

```json
{
  "aart.runtime-requirements": {
    "schema_version": 1,
    "requirements": [
      {
        "id": "python",
        "version": {"min_inclusive": "3.11.0"},
        "reason": "The artifact uses Python 3.11 stdlib features."
      },
      {"id": "command.git"}
    ]
  }
}
```

Requirement IDs are lowercase dotted or dashed identifiers. A version, when present, uses SemVer
`min_inclusive` and/or `max_exclusive` bounds. Omitting `version` declares presence only. A
declaration is authored by the artifact publisher; AART does not infer it from payload files.

## Repository environment description

The consuming repository generates or maintains a JSON inventory for the exact runtime it wants to
evaluate:

```json
{
  "schema_version": 1,
  "name": "repository-ci",
  "capabilities": [
    {"id": "python", "version": "3.11.9"},
    {"id": "command.git"}
  ]
}
```

The optional name identifies the environment to humans. Capability versions use complete SemVer;
presence-only capabilities omit `version`. How this file is produced is deliberately outside AART:
a Python project can generate it from its lock/toolchain workflow, while another repository can
maintain it directly.

## Health command

```sh
aart marketplace health \
  reference/collection/residuality \
  --environment .agent-artifacts/runtime-environment.json \
  --json
```

Coordinates are optional; omitting them reports every artifact in the local marketplace. Collection
selectors expand to their exact compiled members. Requirement observations are:

- `satisfied`: the supplied capability and, if needed, version match;
- `unsatisfied`: a supplied version is outside the declared bounds;
- `unknown`: the capability or required version is absent from the supplied inventory.

Artifacts with no declaration report `not-declared`. Content that is not locally available reports
`unavailable`, and a malformed advisory extension reports `invalid` without invalidating
installation.

A successfully computed health report exits zero even when it contains `unsatisfied`, `unknown`,
`unavailable`, or `invalid` items. JSON fixes the semantics with `"advisory": true` and
`"installation_blocking": false`. A consuming repository may inspect the JSON and apply its own CI
policy; AART intentionally has no strict mode that could turn these observations into an implicit
installation gate.
