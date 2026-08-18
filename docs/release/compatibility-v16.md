# AART 2.7.0 compatibility matrix

AART `2.7.0` is a minor release over `2.6.1`. It adds public registry-maintenance commands and a
reporting option, extends setup recipe v2 with a `text` input, and repairs the complete company
adoption stream. Protocol version numbers and persisted document shapes do not change.

| Boundary | Supported in 2.7.0 | Change from 2.6.1 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | no version change | schema freeze and registry gates |
| Configuration schema | v1 | no shape change | configuration tests |
| Source store | v2 | freshness compares validated origin identity, revision, and digest | source runtime tests |
| Installation state | v2 | distinct named memory blocks may share one destination | lifecycle and schema tests |
| Setup recipe | v2 only | adds `text` input and `shell.env-from-input@1` | setup parser/runtime tests |
| Setup state | unchanged shape | stronger update preconditions, compensation evidence, and target preflight | setup lifecycle tests |
| Registry maintainer CLI | `collection`, `discover`, `vendor-batch`, `publish` | commands added | registry command tests |
| Registry initialization | optional `--usage-reporting-repository` | service can be enabled with its templates | init/reporting tests |
| Reporting | v1 | finalized CLI joins TUI routing and consent behavior | reporting and lifecycle tests |
| Runtime-requirements extension | `aart.runtime-requirements` | personal namespace retired with diagnostic | runtime-requirements tests |
| Tabnine project MCP | `.tabnine/mcp_servers.json` | was written to the CLI settings document | Tabnine real CLI E2E |
| Tabnine user MCP | `~/.tabnine/mcp_servers.json` | unchanged | Tabnine real CLI E2E |
| Security assessment | v1, ruleset `baseline-v1.1` | none | security tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging and release checks |

## Upgrade direction

Every `2.6.1` configuration, source, object, registry, artifact, installation record, and setup state
remains readable by `2.7.0`; there is no bulk data migration and existing registries are not
rewritten. Registry maintainers only need to rebuild when they choose to author content that uses a
new 2.7.0 capability.

Three boundaries require an explicit operator or author action:

- Rename authored `com.m1f1.runtime-requirements` metadata to `aart.runtime-requirements`. The old
  spelling is deliberately rejected rather than accepted as a second live dialect.
- A package using the new setup `text` input must set `requires_aart.min_inclusive` to `2.7.0` or
  later. AART 2.6.1 rejects that recipe construct.
- For a Tabnine project MCP artifact installed by 2.6.1, run `marketplace uninstall` and then
  `marketplace install` under 2.7.0. Update detects the changed owned destination and refuses with
  those exact commands rather than dropping the old ownership proof and orphaning its entry.

## Downgrade direction

Most 2.7.0 state is readable by 2.6.1 because schemas stay at the same revisions. Two new semantics
are intentionally not downgrade-safe:

- 2.6.1 rejects installation state in which two distinct memory artifacts own blocks in the same
  destination. Uninstall one of the shared memories before downgrading.
- 2.6.1 cannot consume a setup recipe using the `text` input. Keep that artifact's compatibility
  floor at 2.7.0.

Tabnine MCP entries written to the standalone documented file are ordinary Tabnine configuration;
2.6.1 AART does not manage that project target correctly. Upgrade rather than downgrade when AART
owns such an entry.

## Registry protocol and release classification

The commands added in 2.7.0 produce the same registry v1, native-source v1, artifact manifest v1,
lock, index, and provenance documents already accepted at the boundary. The schema freeze therefore
retains every protocol number. This is nevertheless a minor release because operators can point to
new commands, a new flag, and a new recipe capability.

Compared with v15, v16 changes exactly one normative schema input: `agent_artifacts/setup.py`. That
file contains the setup-recipe parser and the setup-reference/persistence rules repaired here. All
other stream changes are command, application, profile, rendering, or documentation behavior outside
the frozen protocol inputs.
