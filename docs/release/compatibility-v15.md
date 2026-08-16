# AART 2.6.1 compatibility matrix

AART `2.6.1` is a patch release over `2.6.0`. It changes no schema, no protocol version, no document
field, and adds no command. Every `2.0.0`…`2.6.0` configuration, source store, object store,
installation record, registry, artifact, and setup state file is read and written exactly as before.

It is patch rather than minor because nothing an operator can point at is new. What changed is that
fifteen recorded defects stopped happening: a setup step that could not authenticate, a digest that
described a wheel nobody received, refusals that named no next step, a wizard that suggested a
window the executable it ran from is outside of, and a doc gate that only failed in one direction.

| Boundary | Supported in 2.6.1 | Change from 2.6.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | unchanged | none | native tree and registry gates |
| Provenance document | v1 with `aart.vendor` | none | vendoring and integrity tests |
| Configuration schema | v1 | none | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | none | setup parser and canonical setup tests |
| Setup state file | unchanged shape | none | setup runtime tests |
| Setup step environment | **`HOME` and `DOCKER_CONFIG` reach the docker adapters** | a private base image can authenticate | setup runtime tests, live acceptance v4 |
| Index setup evidence | unchanged | none | index and vocabulary tests |
| Registry maintainer gates | unchanged | none | registry validate/build gates |
| Registry compatibility window written by `init` | **derived from the running executable** | was the literals `1.0.0`/`2.0.0` in the wizard | registry CLI tests, live acceptance v13 |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1, ruleset `baseline-v1.1` | none | security tests |
| Install effects | unchanged shape | **a merge file AART created and emptied is removed** | installation tests, live acceptance v11 |
| CLI surface | unchanged | none — no command added, none removed | CLI and e2e tests |
| Refusal and report text | **remediation on registry refusals and report findings** | was empty everywhere | registry command tests, source remediation tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is patch and not minor

The v15 schema freeze differs from v14 in **one input and no protocol version**:
`agent_artifacts/setup.py`. The change there is one function split in two —
`rollback_command(item)` now delegates to `rollback_command_for(type, name, profile, scope)` so a
persisted record can compose the same sentence from its own coordinates. No caller outside the
package can observe it, and nothing it writes changes shape.

Every other change is in code the freeze does not cover: the CLI's refusal text, the curses wizard's
suggested defaults, uninstall's file reclamation, the docs gate, and one documentation fix.

## Both directions

A `2.6.0` data root is fully readable by `2.6.1`, and a `2.6.1` data root is fully readable by
`2.6.0`. A registry built on either validates on the other. There is no migration, no re-lock, and
no obligation for a registry maintainer in either direction.

One behaviour is deliberately *not* symmetric, and it is a repair rather than a break: a
`marketplace uninstall` on `2.6.1` removes a `.mcp.json` or `.claude/settings.json` that AART itself
created and has just emptied, where `2.6.0` left the emptied file behind. A file that existed before
the install is still never removed, on either version — that boundary is what
[`DESIGN-uninstall-file-reclamation.md`](../design/DESIGN-uninstall-file-reclamation.md) exists to
draw, and it is walked in both directions in live acceptance v11.

## What a registry maintainer must do

Nothing.

`registry init` on `2.6.1` writes a narrower default compatibility window than `2.6.0`'s wizard did —
`>=2.6.1,<3.0.0` instead of `>=1.0.0,<2.0.0`. That is the repair: the old pair excluded the
executable that wrote it, so `registry validate` refused the registry its own wizard had just
created. An existing registry keeps whatever window it declares; nothing rewrites it.
