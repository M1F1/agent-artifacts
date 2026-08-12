# AART 1.4.0 compatibility matrix

AART `1.4.0` is a minor release over the frozen `1.3.1` boundary. It delivers the typed
wizard-error track and the transparent setup review. Exactly one boundary moves: the setup-recipe
protocol now supports a single revision and rejects the superseded one.

| Boundary | Supported in 1.4.0 | Gate |
|---|---|---|
| Python | 3.10+ | package and system matrix |
| Runtime dependencies | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1, unchanged | schema freeze and registry gates |
| Installation state | v2, unchanged | lifecycle tests |
| Setup recipe | **v2 only; v1 rejected** | setup parser and canonical setup tests |
| Reporting | v1, unchanged | reporting tests |
| CLI surface | backward compatible | CLI and e2e tests |

## Why this is minor and not major

The executable's own surface is unchanged: no command, subcommand, or flag was removed or renamed,
and the consent semantics are identical. The breaking change belongs to the setup-recipe protocol,
which this project versions independently of the executable.

That separation is load-bearing rather than cosmetic. Registries and artifacts conventionally
declare `requires_aart` with `max_exclusive: "2.0.0"`, so an executable major would make every
artifact — including those with no setup recipe at all — incompatible in one step. Keeping the
executable in the `1.x` line confines the disruption to the artifacts that actually declare a
superseded recipe.

## The breaking change

A `setup/installer.json` must declare `schema_version: 2` and `protocol_version: 2`, and its
package must contain a regular, contained, non-empty UTF-8 `SETUP.md` at its root. A recipe
declaring the superseded `1`/`1` pair is refused when the catalog is read:

```text
invalid setup installer for <artifact>: schema_version and protocol_version must both be 2;
a superseded recipe is migrated by raising both to 2 and adding the package-root SETUP.md route
```

The migration is mechanical: raise both fields to `2`, add the document, then relock and rebuild
the registry. There is no compatibility branch and no automatic upgrade — only the newest revision
of the protocol is maintained.

A custom entrypoint must begin, after an optional shebang, with
`# AART manual setup: see ../SETUP.md`, so the manual route is visible when reading the script.

**Scope of the impact.** Only artifacts that declare a setup recipe are affected. Artifacts without
one install, update, and uninstall exactly as before. A registry that publishes a `1`/`1` recipe
will have those specific artifacts rejected at discovery until it is rebuilt against this release.

## What is explicitly not migrated

Rejecting an old *input* is not rewriting existing *state*. Installation state stays at v2 and is
never migrated, rewritten, or deleted automatically. Recognized AART 0.1 state is reported with an
explicit `aart migrate state --from 0.1 … --dry-run` preview that a person chooses to run; `--apply`
and `--rollback` remain separate explicit steps. A setup receipt recorded by an earlier run stays
readable exactly as written, including its stored version fields.

## Consent semantics

Unchanged. `--yes`, `--approve-setup-effects`, `--authorize-untrusted-source`,
`--authorize-custom-entrypoint`, trust authorization, and per-effect approval behave exactly as in
`1.3.1`. Per-effect consent still defaults to No. Declining setup never rolls back an installed
payload, and following the manual `SETUP.md` route is never recorded as consent to the automation.
