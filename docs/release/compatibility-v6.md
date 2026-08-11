# AART 1.3.1 compatibility matrix

AART `1.3.1` is a patch release over the frozen `1.3.0` boundary. It changes only how the
agent-facing marketplace setup command builds its read-only Review outcome.

| Boundary | Supported in 1.3.1 | Gate |
|---|---|---|
| Python | 3.10+ | package and system matrix |
| Runtime dependencies | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1, unchanged | schema freeze and registry gates |
| Installation state | v2, unchanged | lifecycle tests |
| Setup recipe | v1, unchanged | setup parser and canonical setup tests |
| Reporting | v1, unchanged | reporting tests |

## Setup Review behavior

Without `--yes`, `aart marketplace setup` remains non-mutating. For each reviewed item that declares
setup, it creates a bounded synthetic terminal projection with `setup_status=pending`; canonical
`prepare_setup` must still prove a matching installed record, object, recipe, trust decision, and
policy before a plan is returned. Items without setup are projected as `not-required`.

The projection contains no credential, receipt, environment value, or authorization. The command
does not call payload Finalize or setup Finalize in Review mode. `--authorize-untrusted-source` and
`--authorize-custom-entrypoint` remain explicit, while effect execution still additionally requires
`--yes` and the setup-effect approval decision.

## Directional compatibility

Artifacts and registries do not need to raise `requires_aart` for this patch. Older AART releases
can still browse and install the same payloads and use existing human/legacy setup paths; they only
lack the corrected complete CLI/JSON setup preview. Configuration written by `1.3.1` is identical
to `1.3.0` configuration and retains the same downgrade constraint documented in compatibility v5.
