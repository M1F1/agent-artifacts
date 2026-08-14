# AART 2.0.0 compatibility addendum — removed subcommands

[`compatibility-v8.md`](compatibility-v8.md) records the nine **top-level** commands `2.0.0`
removed. It does not record the subcommands removed with them, and a user migrating from `1.x`
reads that table expecting it to be complete. This addendum closes that gap. It is written during
`2.2.0` and changes nothing about `2.0.0`; it states what was already true.

Live acceptance v2 is why it exists: AART itself was still telling operators to run
`aart source doctor`, more than two releases after that command stopped existing. Nothing recorded
the removal, so nothing contradicted the message.

## Removed subcommands

| Removed | Canonical replacement |
|---|---|
| `aart source doctor` | `aart source sync --alias <alias>` |
| `aart setup run` | `aart marketplace setup <coordinate> --profile <name>` |
| `aart setup retry` | `aart marketplace setup <coordinate> --profile <name>` — re-running the recipe is the retry |
| `aart setup status` | `aart marketplace status --profile <name>`, which reports each item's setup state |
| `aart setup rollback` | none — see below |
| `aart registry migrate` | none — recorded in `compatibility-v8.md`, repeated here for one complete list |

`aart source doctor` reported and applied rebinds for the legacy source-store layout. `2.0.0`
removed the legacy layout together with the command; a managed snapshot whose state cannot be read
is republished by synchronizing it, which is what the diagnostics now say.

## `aart setup rollback` has no replacement

The rollback verb has no CLI surface in `2.0.0`, `2.1.0`, or `2.2.0`. The engine reverses its own
effects when an apply fails — that path is exercised and is what produces the `rolled-back` and
`rollback-incomplete` statuses — but a *completed* setup cannot be reversed by any command.
`setup_engine.rollback_setup` exists and is reachable only from library code.

Until a surface exists, AART says so instead of naming the removed command: the `rollback` field of
a setup outcome names the artifact, profile, and scope to undo from the recorded receipt, and does
not offer a command to run. Exposing the verb is a CLI addition, not a wording fix, and is left as
its own decision.

## What keeps this table honest

`tests/source_remediation_test.py` parses every `aart …` command AART shows an operator — in
diagnostics, in rendered fields, in TUI reasons — against the shipped parser. It reads the removed
names from the tables in this directory, so a message naming a command removed here fails the build
rather than reaching a user.
