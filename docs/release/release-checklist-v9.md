# AART 2.1.0 release checklist and evidence

This minor release closes the source subscription lifecycle. `2.0.0` shipped an executable that
could subscribe to a source and refresh it, but could not unsubscribe from one or follow it through
a declared identity change. Live acceptance found the dead end that follows from that gap; this
release removes it without loosening the check that produced it.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.1.0
python -m build --wheel
```

The release check must pass repository/version evidence, schema freeze v9, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit.

## Registry precondition

**None.** Unlike `2.0.0`, this release requires no registry to be re-authored first. A registry
already published on the `2.0.0` contract — window `>= 2.0.0, < 3.0.0`, setup recipes at `2`/`2` with
a package-root `SETUP.md` — satisfies `registry test --compatibility all --latest-version 2.1.0`
unchanged. The executable and the registries can be released in either order, and registry CI may be
repointed at the released tag whenever convenient.

## Acceptance

The lifecycle is complete:

- a subscription can be ended, and ending it owns the configuration entry, the managed snapshot, and
  the `default_registry` pointer when it named that alias;
- a declared identity change at an unchanged origin and ref is adoptable under the same alias, with
  alias, kind, location, ref, and the default-registry flag preserved;
- the 2026-08-13 reproduction recovers using shipped commands only — no hand-edited `config.json`,
  no directory deleted from the data root;
- no refusal in the source area is a dead end: every `aart …` command named in a remediation is
  parsed by the real `cli.build_parser()`, so the text cannot drift from the shipped surface.

Nothing was loosened:

- `source sync` still refuses a changed declared identity; adoption is explicit, reviewed, and never
  implied;
- adoption authorizes a transition, not a destination — an origin that moves between review and
  finalize is refused rather than absorbed;
- resubscribing an unchanged identity is refused, naming the refresh command;
- without `--yes` neither new command writes configuration, store, or project bytes.

Project isolation holds:

- every source operation runs against a project holding an installed payload and a durable manifest,
  and the project tree is compared byte for byte including `st_mtime_ns` before and after;
- a managed symlink still resolves after its source is removed, because the object store is not the
  snapshot store;
- a durable manifest outlives its subscription and reconciles as `source-unavailable`.

One role model, two front-ends:

- `remove` and `resubscribe` reach the curses Sources stage on `r` and `i` through the same
  application request values the CLI dispatches;
- the TUI carries no implementation of either operation, only its rendering and its confirmation.

Protocol and packaging:

- the v9 schema freeze is byte-identical to v8 in every declared input, which is the machine-checked
  claim that no protocol boundary moved;
- the built wheel reproduces the checkout's typed diagnostics byte for byte;
- the wheel declares zero runtime dependencies and installs under `pip --no-deps`;
- the complete unit, integration, type, lint, docs, and packaging suites remain green.

## Evidence

Design: [DESIGN-source-subscription-lifecycle.md](../design/DESIGN-source-subscription-lifecycle.md).
Plan and work-package record:
[PLAN-source-subscription-lifecycle.md](../plan/PLAN-source-subscription-lifecycle.md).
The originating residue `LAF-28` and its closure are recorded in
[PROGRESS-live-acceptance.md](../testing/PROGRESS-live-acceptance.md); that ledger is appended to,
never rewritten. Merged as [#78](https://github.com/M1F1/agent-artifacts/pull/78).
