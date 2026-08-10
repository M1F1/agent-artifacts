# TUI source management and health v1

TUI01 inserts **Sources** between Role and Harness in both the text and curses state machines. The
stage is a policy-aware configuration editor and health snapshot. Ordinary checkbox selection is
not a network fetch or an artifact installer; the explicit **Add source** action has its own
review, synchronizes one immutable snapshot, then saves the reviewed origin. Its functional core
is [`tui_sources.py`](../../agent_artifacts/tui_sources.py), and its durable boundaries are
[`application/source_management.py`](../../agent_artifacts/application/source_management.py).

## Read model

At runtime AART loads the effective user configuration and organization policy through the CFG01
application service. Each configured source is joined with its durable SRC01 current pointer and
projected into one immutable row. Git origins are normalized to credential-free `host/repository`
text. Rows distinguish:

- enabled or disabled configuration;
- current, stale, offline, invalid, incompatible, or missing managed health;
- registry, direct Git, or mutable local kind;
- default-registry presentation rank;
- organization-required or recommended aliases;
- exact company-reviewed registry identity.

Recommendation and review are intentionally separate. A recommended alias without configuration is
listed as needing setup. A source is labelled company-reviewed only when its current declared
source ID plus normalized Git host/repository exactly matches local organization policy. Alias,
default rank, or source-authored metadata cannot grant that label.

An existing managed snapshot may support last-known-good operation while its source is offline. The
row still says `offline`; it is never rewritten as current. Invalid and incompatible rows are not
selectable. Direct/local sources become unavailable when organization policy denies direct
sources.

## First run and optional registries

No registry is intrinsically required. With no configured source, the Sources screen offers
**Add source** plus, unless policy declares required aliases, **Continue without sources**. Add
asks for an alias, origin, and Git ref (or a local directory), shows a credential-free review, then
downloads and validates one immutable source snapshot before saving the configuration. A registry
must have a valid current compiled lock/index; a direct/local source must satisfy the native source
protocol. Sync failure leaves user configuration untouched. Continue without sources exits
successfully and states that no registry was forced and no changes were made. Missing
required/recommended policy aliases remain visible instead of being invented from an alias or URL
guess.

When policy requires more than one alias, **Add source** may save each policy-allowed source in a
separate reviewed/synchronized operation. The intermediate configuration is usable only to return
to Sources and add the remaining aliases; it cannot enter the canonical marketplace or install
content until all required aliases are enabled. This does not relax direct-source, Git-origin,
reporting, or default-registry policy checks.

For the current store format, one Git kind/origin may be configured once. Add rejects a second
alias pointing at the same Git origin, even with a different ref, rather than let two refs share a
managed pointer. Ref-aware multi-source support requires its own versioned store migration.

The executable checkout is never *implicitly* treated as an artifact source. Explicit `--source`
and `--repo` arguments remain isolated legacy choices and never rewrite global configuration; an
explicit tool checkout is simply an empty legacy source after the repository-boundary change.

## Deferred request and policy gate

Confirming Sources creates a frozen `SourceManagementRequest` containing exact before/after user
configuration, local policy, and a deterministic operation list:

```text
disable aliases -> enable aliases -> clear/use default registry
```

The request invariant permits changes only to source `enabled` flags and `default_registry`.
Origins, refs, kinds, aliases, sync settings, and reporting settings cannot be smuggled through this
operation. The desired configuration is evaluated against organization policy before Review.
Required sources, direct-source restrictions, reporting destination constraints, and default
registry validity therefore fail closed.

Adding an origin uses a separate `SourceAdditionRequest`, not an overloaded toggle request. It
preserves every existing source/settings field, adds exactly one enabled schema-valid source, and
makes only a new registry the default. The runtime synchronizes and validates that source before
the atomic configuration write; it rechecks configuration/policy drift after synchronization.
Only missing required aliases are temporarily tolerated by this source-management write. Ordinary
source toggles and every content operation retain the full required-source gate.

The wizard stores selected aliases, default registry, no-source decision, the inert request, and a
health snapshot. Backspace (or `b`/`back`) returns exactly one applicable stage while preserving
that value plus existing profiles, basket, cursor, and scroll state. Changing Sources unconfirms
the applicable downstream stages. It does not perform a write.

`Finalize` revalidates the reviewed desired configuration and invokes one injected save port. A
no-op request performs no write. Save failure prevents artifact command dispatch and is rendered as
an explicit failure. Text applies this boundary only after the Review answer; curses tears down the
full-screen UI before applying it.

## Consumer boundary

The TUI hands the reviewed effective configuration to the canonical consumer marketplace. It
combines enabled current registry/direct/local sources by their qualified coordinates and preserves
source trust/health facts. A missing, stale, invalid, or policy-denied source is rendered explicitly
rather than being silently reinterpreted as the executable checkout or an old catalog layout.
