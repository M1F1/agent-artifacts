# Public reference-registry publication boundary v1

The AART tool and operational registries are independently versioned products. The tool wheel
contains compiler/runtime code, schemas, profiles, importers, and templates; it does not contain,
export, or bootstrap the public reference registry or another operational artifact catalog.

The first public reference instance has one approved identity:
`M1F1/agent-artifacts-registry`, with `PUBLIC` visibility. A different owner, name, existing
repository, or unverifiable visibility is a stop condition rather than an invitation to select a
different destination.

## Independent registry lifecycle

Registry content is maintained and reviewed in its own Git checkout. AART never derives it from
the tool checkout and has no command that copies an embedded seed catalog into it. An empty
registry starts with the explicit maintainer workflow:

```bash
git init agent-artifacts-registry
aart registry init --source agent-artifacts-registry \
  --source-id reference-registry --display-name "AART Reference Registry"
```

An existing external 0.1 catalog is converted explicitly with `aart registry migrate`; the source
checkout, public origin URL, ref, destination, and selected profiles are reviewed inputs. The
migration never changes or deletes the legacy checkout. See
[`maintainer commands v1`](maintainer-commands-v1.md#migration) for the exact preview and apply
commands.

Before publishing a registry revision, maintainers run the same checks in the registry checkout:

```bash
aart registry format --source . --check
aart registry validate --source . --strict --frozen
aart registry lock --source . --check
aart registry build --source . --check
aart registry audit --source .
aart registry test --source . --compatibility all --latest-version <current-aart-version>
```

The tool repository's `make validate` is intentionally different: it validates the code-only
repository boundary and rejects embedded `skills/`, `guidelines/`, `mcp/`, `hooks/`, `memory/`,
and `bundles/` roots as well as canonical `artifacts/`, `collections/`, source/registry markers,
and dangling root symlinks. It is not a registry validator.

## Publication review

Publication may proceed only after a human reviews the registry checkout's file list, diff,
lock/index changes, audit result, compatibility result, and intended visibility. Registry CI must
repeat the checks for both its declared minimum and current compatible AART versions.

The audit rejects, among other things:

- missing or non-allowlisted artifact licenses;
- missing, malformed, or mismatched source commit/path/digest provenance;
- credentials and high-confidence token/private-key patterns;
- local user paths, local/private endpoints, or non-public source URLs;
- symlinks, special files, binary/non-UTF-8 files, and unsafe paths;
- caches, build outputs, dashboards, and paths outside the reviewed registry contract;
- a changed or absent minimum/latest registry CI workflow.

## Provenance and ownership

Each materialized artifact retains the source repository, exact 40-character commit, source path,
and content input digest. Registry history belongs to the registry repository; artifact provenance
lives in its canonical documents rather than through an unaudited history transfer from the AART
tool repository.

Security evidence is bounded evidence, not a safety certificate. Usage reporting remains inert
unless the registry advertises a compatible service and local user/organization policy explicitly
selects it.
