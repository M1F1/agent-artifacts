# Public reference-registry publication boundary v1

The AART tool and operational registries are independently versioned products. The tool wheel
contains compiler/runtime code, schemas, profiles, importers, and templates; it does not contain
the public reference registry or another operational artifact catalog.

The first public reference instance has one approved identity:
`M1F1/agent-artifacts-registry`, with `PUBLIC` visibility. A different owner, name, existing
repository, or unverifiable visibility is a stop condition rather than an invitation to select a
different destination.

## Deterministic export

The export consumes one exact committed Git tree. It never reads working-tree-only catalog files
and never transfers source history:

```bash
python scripts/prepare_reference_registry.py \
  --source-checkout /absolute/path/to/agent-artifacts \
  --source-commit "$(git rev-parse HEAD)" \
  --destination /absolute/path/to/new-empty-registry \
  --json
```

The exporter performs the legacy-to-canonical migration with an explicit `MIT` artifact license,
canonical formatting, lock and index generation, strict frozen validation, audit, and
minimum/latest compatibility checks. It then audits every publishable byte and emits a stable tree
digest. The destination is a fresh local Git repository, but the exporter never creates a remote,
commits, or pushes.

The allowlist fixes ten artifact identities, two collection identities, the public source URL and
commit, the registry ID, repository metadata, and the exact registry CI/reporting templates. The
audit rejects:

- missing or non-allowlisted artifact licenses;
- missing, malformed, or mismatched source commit/path/digest provenance;
- credentials and high-confidence token/private-key patterns;
- local user paths, local/private endpoints, or non-public source URLs;
- symlinks, special files, binary/non-UTF-8 files, and unsafe paths;
- caches, build outputs, dashboards, and every path outside the reviewed allowlist;
- a changed or absent minimum/latest registry CI workflow.

Publication may proceed only from the exact audited destination tree and only after a human reviews
its file list, diff, receipt digest, and intended visibility. Registry CI is present in the first
published tree and must pass for both the minimum and latest compatible AART versions.

## Provenance and ownership

Each materialized artifact retains the source repository, exact 40-character commit, legacy source
path, and content input digest. The fresh registry starts with new history; source provenance lives
in the canonical documents rather than through an unaudited history transfer.

Security evidence is bounded evidence, not a safety certificate. Usage reporting remains inert
unless the registry advertises a compatible service and local user/organization policy explicitly
selects it.
