# Consumer marketplace TUI v1

TUI02 replaces the transitional one-checkout User bridge with a typed application boundary over
the configured federated marketplace. The text and curses frontends collect choices; they do not
parse command output or implement installation rules.

## Runtime composition

At the Sources stage, AART builds the consumer context from the exact reviewed prospective source
configuration. This lets a source enabled in the current wizard participate immediately without
writing configuration early. Finalize first persists that reviewed source selection and then
applies the already-reviewed artifact plans. A source write failure prevents artifact effects.

Current managed source snapshots are compiled into one marketplace. Native packages are
materialized into the shared immutable object store. Registry coordinates remain qualified by the
registry alias while upstream identity remains provenance. AART does not fetch during marketplace
browse and never falls through to a same-named artifact from another source.

Registry-owned packages are materialized directly from the reviewed registry snapshot. An external
native reference is resolved only through a matching committed `aart.lock.json`. At Review, AART
checks the exact selected object in CAS and, only when it is absent, fetches the locked commit into a
managed bare mirror, validates the package against both lock and index, and publishes the verified
object. Unselected references are not fetched. Offline Review uses an already verified object or
returns `offline-object-missing` without touching the network; reference-only registries remain
valid marketplace sources.

Optional committed registry security indexes are accepted only when their canonical documents,
attestation digests, registry identity, and registry-input digest verify. Evidence is then joined
to the exact artifact object and local trust overlay. Missing or invalid optional evidence remains
visible as `not-scanned`/`unknown`; it does not invent a safety verdict or prevent core use by
itself.

## Marketplace and cart

Every artifact row retains its qualified coordinate:

```text
SOURCE/TYPE/NAME@VERSION
```

Rows expose a one-line value description, source alias and health, effective trust, installation
risk, maximum finding severity, coverage, compatibility, and installed/update state. The details
view adds the resolved source revision, manifest/payload/object digests, providers and versions,
evidence age, remediation, and exact incompatibility reasons.

Filtering and basket reconciliation are pure projections. Text, kind, source, trust,
compatibility, and installed-state filters cannot shadow qualified collisions. When an earlier
choice changes, only basket entries that are no longer compatible or available are invalidated;
valid entries, cursor, and scroll positions survive Backspace navigation.

Harness, scope, and mode are part of compatibility. Copy is the default. Symlink targets exact
immutable store objects, while merge/config effects remain copies and are disclosed as mixed
actual modes.

## Review and Finalize

One multi-item application request prepares the cart sequentially so later items observe the
state projected by earlier plans. Review binds:

- qualified coordinate and exact version;
- source revision and effective trust;
- manifest, payload, object, per-plan, and aggregate review digests;
- requested scope/mode and actual mode per effect;
- every resolved destination;
- security status/risk and declared setup recipe/capabilities.

Finalize accepts only the aggregate digest shown in Review. Each canonical install, update, or
uninstall plan revalidates its own preconditions and evidence. A changed destination or state is a
typed conflict/failure for that target; other reviewed targets retain their own terminal results.
Status and fetch-free check results use the same review/outcome model without filesystem mutation.

## Setup queue and outcomes

Setup is a second boundary after successful payload installation. AART prepares the canonical
setup queue from installed state, the exact CAS object, source trust, policy, platform, recipe, and
capabilities. Required untrusted/custom authorization is explicit. The user reviews the queue and
consents to each declared effect before sequential execution.

Payload success is not rolled back when setup is declined or incomplete. The TUI prints exact
retry commands for planning or execution failures.

Every completed path prints selected/item counts and one terminal status per target. Session
status is explicit:

- `no-op` when nothing changed, including already-current selections;
- `succeeded` when all mutations completed;
- `partial` when some targets changed and others conflicted/failed;
- `failed` when every selected target failed;
- offline last-known-good when cached snapshots and objects were intentionally used.

The curses frontend collects and reviews the same immutable values inside the terminal screen, but
performs Finalize only after curses teardown. The text fallback uses the same application service
and produces equivalent evidence and outcomes.
