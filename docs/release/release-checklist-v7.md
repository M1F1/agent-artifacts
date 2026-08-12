# AART 1.4.0 release checklist and evidence

This minor release delivers the typed wizard-error track and the transparent setup review, and
narrows the setup-recipe protocol to a single supported revision.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v1.4.0
python -m build --wheel
```

The release check must pass repository/version evidence, schema freeze v7, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit.

## Registry precondition

**`make release-check` requires a registry already rebuilt for revision 2.** This is a real
precondition, not a formality: at the time this release was prepared, the public registry's only
setup-capable artifact (`mcp/atlassian`) still declared `1`/`1` with no package-root `SETUP.md`,
and was therefore rejected at discovery. Migrate and relock the registry before running the check,
or the registry gates fail for the expected reason.

## Acceptance

Typed errors:

- recognized 0.1 installation state reports `install-state-legacy` with the exact path, the
  detected and required schema, and an independent migration preview per scope;
- an unreadable state file reports `install-state-invalid` with the parser's own location and never
  offers migration;
- an unexpected exception reports `tui-stage-internal` with stage, operation, and exception type
  only — no message, traceback, subprocess output, or setup input;
- a stage-blocking failure opens the scrollable record with Retry/Back/Quit; a list-local problem
  stays in the fixed pane below a still-usable list;
- no failure path mutates tracked project, configuration, state, or store files.

Setup review and manual route:

- a setup-capable artifact is rejected at catalog validation when its `SETUP.md` is missing, unsafe,
  or unreadable, and when its version pair is not `2`/`2`;
- every setup review and every incomplete setup outcome names the `SETUP.md` route with a
  commit-pinned HTTPS URL or a contained local path;
- at widths 40, 80, 120, and 200 no normal review, effect, or error line exceeds the shared measure;
- declining setup leaves the payload installed and never claims a payload rollback;
- no route or record leaks a credential, setup input, environment value, raw subprocess output,
  script body, or unpinned source URL.

Packaging:

- the built wheel reproduces the checkout's typed diagnostics byte for byte, not merely its imports;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, e2e, type, lint, docs, and packaging suites remain green.
