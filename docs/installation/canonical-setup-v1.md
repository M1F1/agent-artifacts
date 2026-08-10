# Canonical setup boundary v1

SET01 keeps the existing declarative macOS setup modules, but moves their authority behind the
same immutable-object and Review/Finalize boundary as canonical installation. It does not replace
payload installation: setup starts only from a matching installation-manifest-v2 record and always
reports payload and setup status separately.

## Prepare, Review, Finalize

`prepare_setup` resolves the exact qualified installed coordinate and verifies all of the following
without applying an effect:

1. the selected source, commit, artifact version, manifest/payload/object digests still match the
   installation record and current marketplace;
2. the setup recipe and optional executable custom entrypoint are regular files inside that exact
   immutable CAS object;
3. the recipe's artifact identity, recipe hash, custom hash, ordered effect plan, target paths,
   semantic capabilities, profile, platform, scope, trust evidence, and organization-policy digest
   agree;
4. direct, local, and unverified sources have explicit setup authorization;
5. every semantic capability is allowed when policy supplies an allowlist, and custom code has
   explicit authorization and is not policy-denied.

The resulting `CanonicalSetupPlan` is frozen. Its Review digest binds all of that evidence plus the
per-installation setup-state path and current setup object-reference precondition. `finalize_setup`
re-resolves and rechecks the evidence. A trust downgrade, policy change, replaced object, changed
installed record, stale state, or mismatched Review digest produces a terminal conflict/error before
the Keychain, filesystem, process, Docker, or custom-code adapter runs.

Policy capability names describe effects rather than implementation mechanisms:

| Recipe effect | Policy capability |
|---|---|
| macOS Keychain store | `keychain` |
| owned file, shell, JSON, or directory mutation | `managed-file` |
| fixed-argv verification | `verify-command` |
| digest-pinned Docker pull | `docker-pull`, `network` |
| copied custom protocol entrypoint | `custom-code` |

An older compiled index may omit its capability projection; the exact recipe is then authoritative.
If an index advertises capabilities, they must equal the derived plan.

## Custom-code boundary

Custom entrypoints remain trusted code, not a sandbox. The source executable is read with
no-follow semantics, bounded to 1 MiB, verified against the recipe hash, copied into a newly created
mode-`0700` run directory under the AART data root, and executed only from that copy with fixed argv,
`shell=False`, and the existing minimal environment. Plan/apply/verify share the same copied bytes.
The receipt records their source and copied paths plus hashes, never stdout, stderr, environment, or
secret values.

## State, references, retry, and rollback

Every attempted item receives two terminal fields:

- `payload_status=installed`, proving setup did not reinterpret or undo payload installation;
- an independent setup status such as `configured`, `already-configured`, `cancelled`,
  `verification-failed`, `rollback-incomplete`, `conflicted`, or `skipped`.

Canonical non-secret setup evidence is written to
`<data-root>/state/setup/<setup-state-ref>.json`. The installation record receives the same
`setup_state_ref`, and `ReferenceKind.SETUP` retains the exact object digest. The state key includes
the qualified coordinate, profile, scope, and installation-state path, so two projects cannot share
one setup receipt accidentally. Persistence is compensated on failure; successfully applied effects
are rolled back when their state cannot be made durable.

Queue execution is sequential. Earlier successes remain durable after a later failure. With
stop-on-failure, every remaining item is explicitly `skipped`; `retryable_plans` selects only
incomplete identities for a newly prepared Review. `rollback_setup` accepts only receipts whose
canonical Review, object digest, setup-state reference, current durable state, and every mutation
locator still match the reviewed plan, then uses the existing ownership-aware reverse-order
compensation.

Legacy `aart setup` remains available during the staged 0.1.x migration. The source-aware TUI and
CLI will consume this application boundary in TUI02/MIG01 rather than reconstructing authority from
command output or a mutable checkout.

## Secret and reporting boundary

Secret inputs stay in the existing prompt/Keychain channel. They are never accepted by
`SetupRequest`, plan data, argv, or environment. Setup diagnostics and durable receipts are redacted;
canonical evidence is an all-or-nothing set of strict SHA-256/trust/state identifiers. The
`setup_outcome_event` function is a bounded allowlist projection and intentionally excludes receipts,
raw setup output, process fields, and secret material.
