# TUI source management and health v1

TUI01 inserts **Sources** between Role and Harness in both the text and curses state machines. The
stage is a policy-aware configuration editor and health snapshot, not a network fetch or an
artifact installer. Its functional core is [`tui_sources.py`](../../agent_artifacts/tui_sources.py),
and the only write boundary is
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

No registry is intrinsically required. With no configured source, the UI gives the exact
`aart source add` setup direction and, unless policy declares required aliases, offers **Continue
without sources**. That path exits successfully and states that no registry was forced and no
changes were made. Missing required/recommended policy aliases remain visible instead of being
invented from an alias or URL guess.

During the alpha transition, a genuinely new configuration with no source policy keeps the
installed checkout as one visible `bundled-legacy` local choice. An explicitly saved empty
configuration does not reactivate that compatibility fallback. Explicit `--source` and `--repo`
arguments remain isolated legacy choices and never rewrite global configuration.

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

The wizard stores selected aliases, default registry, no-source decision, the inert request, and a
health snapshot. Backspace (or `b`/`back`) returns exactly one applicable stage while preserving
that value plus existing profiles, basket, cursor, and scroll state. Changing Sources unconfirms
the applicable downstream stages. It does not perform a write.

`Finalize` revalidates the reviewed desired configuration and invokes one injected save port. A
no-op request performs no write. Save failure prevents artifact command dispatch and is rendered as
an explicit failure. Text applies this boundary only after the Review answer; curses tears down the
full-screen UI before applying it.

## Transitional consumer boundary

TUI01 owns source configuration and health, not the federated artifact union delivered by TUI02.
The existing 0.1 consumer catalog bridge therefore proceeds only with one compatible local source
or one `github.com` direct source tracking `main`; it never silently treats a registry, multiple
sources, another Git host, or another ref as the old catalog shape. Those selections remain valid
source-management domain values, but artifact browsing fails explicitly until the federated
marketplace path can consume them.
