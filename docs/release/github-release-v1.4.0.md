# AART 1.4.0

AART `1.4.0` makes wizard failures honest and gives every setup installer a manual alternative.

Failures that used to collapse into one loose line are now three distinct, separately actionable
things. Recognized AART 0.1 installation state states the exact path, the detected and required
schema, and previews migration for the project and user scope independently. An unreadable state
file keeps the parser's own line and column and never pretends migration would repair it. A defect
in AART names the stage, the operation, and the exception type only — no message, traceback,
subprocess output, or value typed during setup. Nothing is migrated, rewritten, or deleted on your
behalf; the previews are commands a person chooses to run.

Setup is no longer a wall of terminal-width-dependent lines. Each effect is a bounded record with
its identity, target, capability, and recovery, and every review names the artifact's `SETUP.md` so
you can decline the automation and configure it yourself. Declining is a supported way to finish: it
never rolls back a payload that already installed, and following the manual route is never recorded
as consent.

## Breaking change

Setup recipes now support exactly one revision. `schema_version` and `protocol_version` must both
be `2`, which is what makes the package-root `SETUP.md` mandatory. A recipe declaring the superseded
`1`/`1` pair is refused when the catalog is read, with the migration named in the error.

**A registry that still publishes a `1`/`1` recipe must be rebuilt before those artifacts install
again.** Raise both fields to `2`, add the document, relock, and rebuild. Artifacts without a setup
recipe are unaffected.

Installation state stays at v2 and is not migrated by this release. The CLI surface is backward
compatible: no command or flag was removed or renamed, and consent semantics are unchanged.

See the [1.4.0 compatibility matrix](compatibility-v7.md) and
[release evidence](release-checklist-v7.md).
