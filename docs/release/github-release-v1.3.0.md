# AART 1.3.0

AART `1.3.0` makes consent-based usage reporting the default for new configurations and supports
federated reporting when a user installs artifacts from several registries.

If no central reporting destination is configured, prompt mode partitions results by the registry
that advertised each artifact. Every registry receives only its own artifact results. Aliases or
refs pointing to the same GitHub Issues endpoint are deduplicated, direct sources are omitted, and
source aliases never enter the reporting payload.

The human flow remains deliberately conservative: every proposed Issue has two default-No
confirmations, including a review of the exact payload. Users can explicitly choose `disabled` for
complete silence. `automatic` remains available only with one explicit central destination and
cannot be enabled by registry metadata.

Reporting protocol v1 and its JSON schema are unchanged. All configurations accepted by `1.2.0`
remain accepted, but `1.2.0` cannot read the new prompt-without-destination form; add a destination
or set explicit `disabled` before downgrading.

The executable version changes because this is public client behavior. Registry and per-artifact
`requires_aart` floors are not raised automatically, so artifacts that do not depend on a new AART
capability remain installable with their existing version bounds.

See the [`1.3.0` compatibility matrix](compatibility-v5.md) for the exact boundary.
