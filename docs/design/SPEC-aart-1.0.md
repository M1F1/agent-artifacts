# AART 1.0 Technical Specification

- **Status:** Stable
- **Protocol:** AART Source/Registry Protocol v1
- **Executable:** `1.0.0` (after the `1.0.0aN` implementation train)
- **Product requirements:**
  [`docs/product/PRD-aart-1.0.md`](../product/PRD-aart-1.0.md)
- **Tracking issue:** [#27](https://github.com/M1F1/agent-artifacts/issues/27)

## 1. Purpose

This specification defines the technical boundary between:

- the locally installed `aart` compiler/package-manager executable;
- native artifact source repositories;
- optional curated registry repositories;
- foreign upstreams normalized by maintainers;
- the durable managed source/object store;
- project and user-global harness installations.

The words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe normative 1.0 behavior.

## 2. Architecture invariants

1. The AART Python package MUST NOT require an operational artifact catalog beside
   `agent_artifacts.__file__`.
2. A user MAY configure zero or more sources. A registry is optional.
3. Consumer installation MUST operate only on a compiled canonical artifact package.
4. Foreign-format import MUST occur before consumer installation and MUST produce reviewable
   canonical content.
5. Remote refs used by a registry consumer MUST be pinned to a commit and content digest.
6. Sync/fetch MUST NOT silently change installed content.
7. Managed artifact objects MUST be immutable and live outside the Python environment.
8. An invalid/incompatible update MUST preserve the previous validated snapshot.
9. Source identity, origin, trust, and artifact identity MUST remain separate concepts.
10. Trust MUST be assigned by local policy/provenance, not accepted from artifact self-description.
11. Organization policy MUST constrain all user config, CLI flags, and environment overrides.
12. Secrets MUST NOT be stored in manifests, compiled indexes, locks, logs, or usage reports.

## 3. Component model

```text
┌──────────────────────────┐       ┌───────────────────────────┐
│ Native artifact repo     │       │ Foreign upstream repo     │
│ aart-source.json         │       │ harness/project layout    │
│ canonical packages       │       └─────────────┬─────────────┘
└─────────────┬────────────┘                     │ maintainer-only importer
              │                                  v
              │                    ┌───────────────────────────┐
              │                    │ Canonical reviewed copy   │
              │                    │ provenance + warnings     │
              │                    └─────────────┬─────────────┘
              │                                  │
              v                                  v
┌──────────────────────────────────────────────────────────────────┐
│ Optional registry repositories                                  │
│ discovery · native refs · canonical packages · locks · policy   │
└───────────────────────────────┬──────────────────────────────────┘
                                │ configured source union
                                v
┌──────────────────────────────────────────────────────────────────┐
│ AART source compiler                                            │
│ parse · resolve · validate · normalize · index · diagnostics    │
└───────────────────────────────┬──────────────────────────────────┘
                                v
┌──────────────────────────────────────────────────────────────────┐
│ Durable managed store                                           │
│ Git mirrors · validated snapshots · content-addressed objects   │
└───────────────────────────────┬──────────────────────────────────┘
                                │ plan/review/apply
                                v
┌──────────────────────────────────────────────────────────────────┐
│ Harness compilers/profiles                                      │
│ project/user scope · Copy/Symlink/merge · setup · state         │
└──────────────────────────────────────────────────────────────────┘
```

## 4. Repository roles

### 4.1 Tool repository

The current `agent-artifacts` repository owns:

- Python package and entry points;
- JSON schemas and protocol compatibility code;
- compiler, resolver, managed store, install engine, and setup engine;
- built-in harness profiles;
- built-in, versioned source importers;
- scaffolding templates and small test fixtures;
- migration logic and documentation.

It MUST NOT ship the operational public/company marketplace as package data.

### 4.2 Native source repository

A native source is a Git tree/local directory with `aart-source.json`. It contains one or more
canonical packages. It is directly consumable and does not require registry membership.

### 4.3 Registry repository

A registry is a native source plus curation features declared by `aart-registry.json`. It may:

- own canonical packages;
- reference packages from other native Git sources;
- own normalized copies of foreign upstreams;
- define collections;
- commit a deterministic lock and index;
- advertise an optional reporting service;
- run AART quality gates in CI.

The 1.0 public reference instance has the fixed remote identity
`https://github.com/M1F1/agent-artifacts-registry` and `PUBLIC` visibility. SEP01 MUST revalidate
that the name is still available and MUST NOT create or push the repository until the deterministic
export passes secret/credential, local/private path, license, provenance, and registry-CI preflight
checks. An unexpected existing target or inconclusive visibility/audit is a stop condition, not a
reason to choose another public remote silently.

### 4.4 Foreign upstream repository

A foreign upstream has no AART source marker or uses a supported non-canonical layout. It is never
compiled directly in a consumer install. A built-in importer can materialize canonical output into
a maintainer checkout.

## 5. Serialization and canonical hashing

Protocol files MUST be UTF-8 JSON. JSON is chosen over YAML/TOML to retain Python 3.10 stdlib-only
operation and avoid an underspecified custom parser.

Normative JSON rules:

- objects MUST NOT contain duplicate keys;
- protocol integers MUST fit signed 64-bit range;
- floating-point numbers MUST NOT appear in hashed protocol documents;
- unknown keys are rejected unless their schema location explicitly permits namespaced extensions;
- extension keys MUST use reverse-domain or organization namespace syntax;
- normalized hashing serializes with sorted keys, UTF-8, compact separators, and no insignificant
  whitespace, then appends one LF;
- digests use lowercase `sha256:<64-hex>` form.

Tree digests include, in lexical path order:

- normalized relative path;
- entry kind (`file` or `directory`);
- executable bit for files;
- file byte length and SHA-256.

Canonical packages MUST reject absolute paths, `..` traversal, device/FIFO/socket entries, and
filesystem symlinks in protocol v1. Generated installs may create managed symlinks; source payloads
cannot smuggle them into the store.

## 6. Identity and coordinates

Each configured source has a locally unique alias such as `company`, `public`, or `team-a`.

Artifact identity inside one source is:

```text
<type>/<name>
```

The runtime-qualified coordinate is:

```text
<source-alias>/<type>/<name>@<artifact-version>
```

The version suffix MAY be omitted when selecting the source's current compiled version. A manifest
and installation record MUST still store the resolved version and digest.

Examples:

```text
company/mcp/atlassian@2.1.0
public/skill/code-review@1.4.2
team-a/guideline/backend-conventions@3.0.0
```

Aliases are presentation/configuration identifiers, not global trust anchors. State MUST also
record declared source ID, canonical origin URL/path, and resolved commit/snapshot. Renaming an
alias does not change origin identity.

Unqualified selection is allowed only when the query resolves to exactly one enabled artifact.
The default registry MAY affect TUI ranking, but MUST NOT silently resolve an identity collision.

## 7. Source configuration

### 7.1 User configuration

Suggested schema:

```json
{
  "schema_version": 1,
  "sources": [
    {
      "alias": "company",
      "kind": "registry-git",
      "url": "git@github.company.example:agents/company-agent-artifacts-registry.git",
      "ref": "main",
      "enabled": true
    },
    {
      "alias": "personal",
      "kind": "source-git",
      "url": "https://github.com/example/personal-agent-artifacts.git",
      "ref": "main",
      "enabled": true
    },
    {
      "alias": "local-dev",
      "kind": "source-local",
      "path": "/absolute/path/to/artifacts",
      "enabled": false
    }
  ],
  "default_registry": "company",
  "sync": {
    "mode": "auto",
    "max_age_seconds": 900
  },
  "reporting": {
    "mode": "prompt",
    "destination": "company"
  }
}
```

`sources` MAY be empty and `default_registry` MAY be null/absent. A reporting destination MUST NOT
be inferred from an artifact origin. A registry can advertise a reporting repository, but user or
organization configuration must explicitly enable it.

### 7.2 Organization policy

Policy is a separate JSON document provisioned outside the user-writable AART config. It may define:

```json
{
  "schema_version": 1,
  "recommended_sources": ["company"],
  "required_sources": [],
  "allowed_git_hosts": ["github.company.example"],
  "allowed_repository_prefixes": ["agents/", "platform/"],
  "allow_direct_sources": true,
  "minimum_trust_for_user_scope": "direct-source",
  "allowed_setup_capabilities": ["keychain", "managed-file", "verify-command"],
  "allow_custom_setup_entrypoints": false,
  "reporting": {
    "mode": "prompt",
    "destination": "company",
    "deny_public_destinations": true
  }
}
```

Configuration precedence is:

1. built-in defaults;
2. user configuration;
3. environment/CLI request overrides;
4. organization policy validation and locked values.

The final policy layer is a constraint, not another user-overridable default. A disallowed CLI flag
MUST fail before network or filesystem mutation.

### 7.3 First-run behavior

Interactive first use offers:

- a provisioned/recommended registry, if present;
- addition of one or more direct Git/local sources;
- continuation with no source.

Non-interactive content commands with no usable source fail with stable code `no-source-configured`
and direct an agent to `aart source add --help` (or a human to the interactive Sources stage), then
to add each policy-allowed required alias through the reviewed source-management path where
required. Intermediate source configuration never authorizes content: all required aliases must be
enabled before marketplace/install/update/setup operations proceed. The canonical agent browse
command is `aart marketplace list --json`; legacy list/install/update/setup retain their explicit
0.1 compatibility source contract until canonical lifecycle CLI commands land.
`--help`, `--version`, local status, and uninstall do not require a source.

## 8. Platform paths

The resolver MUST support test overrides and at least macOS/Linux.

Suggested defaults:

```text
macOS data:
  ~/Library/Application Support/agent-artifacts/

Linux data:
  $XDG_DATA_HOME/agent-artifacts/
  or ~/.local/share/agent-artifacts/

Linux config:
  $XDG_CONFIG_HOME/agent-artifacts/config.json
  or ~/.config/agent-artifacts/config.json
```

macOS MAY keep `config.json` under the application data root for v1. Test-only environment
overrides MUST redirect config, data, cache, fake home, and policy independently so tests never
touch real user state.

Organization policy locations SHOULD include:

```text
macOS: /Library/Application Support/agent-artifacts/policy.json
Linux: /etc/agent-artifacts/policy.json
```

## 9. Native source protocol

### 9.1 Source root

A native source repository contains:

```text
aart-source.json
artifacts/
  skill/<name>/
  guideline/<name>/
  mcp/<name>/
  hook/<name>/
  memory/<name>/
collections/                  # optional
```

`aart-source.json` example:

```json
{
  "schema_version": 1,
  "protocol_version": 1,
  "source_id": "team-a-agent-artifacts",
  "display_name": "Team A Agent Artifacts",
  "requires_aart": {
    "min_inclusive": "1.0.0",
    "max_exclusive": "2.0.0"
  },
  "required_capabilities": ["artifact-manifest-v1"],
  "artifact_roots": ["artifacts"],
  "collection_roots": ["collections"]
}
```

Artifact roots MUST be explicit. Consumer compilation MUST NOT heuristically crawl an arbitrary
repository. Discovery/scanning of foreign layouts belongs to Maintainer import planning.

### 9.2 Canonical artifact package

Example directory:

```text
artifacts/mcp/atlassian/
  artifact.json
  README.md                   # optional extended documentation
  SETUP.md                    # required whenever setup/ declares a recipe
  payload/
    mcp.json
  setup/
    installer.json            # optional reviewed setup recipe
    install.sh                # optional custom entrypoint; starts with the manual-route header
  provenance.json             # required for imported/curated foreign content
```

Example `artifact.json`:

```json
{
  "schema_version": 1,
  "type": "mcp",
  "name": "atlassian",
  "version": "2.1.0",
  "summary": "Connect supported agent harnesses to reviewed Atlassian tools.",
  "payload": {
    "root": "payload",
    "format": "aart-mcp-v1"
  },
  "compatibility": {
    "profiles": ["claude", "tabnine"],
    "platforms": ["darwin", "linux"]
  },
  "install": {
    "scopes": ["project", "user"],
    "modes": ["copy", "symlink"],
    "effects": ["merge-json"]
  },
  "setup": {
    "recipe": "setup/installer.json",
    "platforms": ["darwin"]
  }
}
```

The manifest MUST NOT contain a trust classification. Optional authorship/license/homepage fields
may inform the user but do not affect trust.

Artifact versions use SemVer. AART 1.0 implements a documented SemVer subset itself and does not
add a packaging dependency. Strict build compares payload/manifest digests with the prior lock and
fails when semantic content changes without a version change. Metadata-only exceptions must be
explicit and reviewable.

### 9.3 Canonical type payloads

Protocol v1 defines these canonical conventions:

- `skill`: `payload/SKILL.md` plus supporting files;
- `guideline`: one Markdown payload document;
- `memory`: one Markdown payload document;
- `mcp`: normalized `payload/mcp.json`, with setup kept separate;
- `hook`: normalized descriptor plus reviewed scripts/resources;
- `collection`: a named set of qualified artifact selectors and optional constraints.

The standard SHOULD reuse stable native formats where semantics already exist. It MUST NOT claim
cross-harness portability for concepts that are profile-specific. Namespaced manifest extensions
may preserve supported harness-specific metadata when the profile capability declares it.

## 10. Registry protocol

### 10.1 Registry layout

```text
aart-registry.json
entries/
  <type>/<name>.json          # external/native references
artifacts/
  <type>/<name>/...           # registry-owned canonical packages
collections/
  <name>.json
aart.lock.json
aart.index.json
```

`aart-registry.json` example:

```json
{
  "schema_version": 1,
  "protocol_version": 1,
  "registry_id": "company-agent-artifacts",
  "display_name": "Company Agent Artifacts",
  "requires_aart": {
    "min_inclusive": "1.0.0",
    "max_exclusive": "2.0.0"
  },
  "required_capabilities": [
    "artifact-manifest-v1",
    "registry-entry-v1",
    "lockfile-v1",
    "setup-recipe-v1"
  ],
  "default_channel": "main",
  "services": {
    "usage_reporting": {
      "kind": "github-issues",
      "repository": "agents/company-agent-artifacts-registry"
    }
  }
}
```

`services` advertises capabilities only. It MAY make a registry eligible for the default
prompt-only, per-registry reporting flow, but MUST NOT enable automatic submission.

### 10.2 Registry entry

A native reference avoids payload duplication:

```json
{
  "schema_version": 1,
  "type": "mcp",
  "name": "atlassian",
  "source": {
    "kind": "git",
    "url": "git@github.company.example:platform/atlassian-agent-tools.git",
    "ref": "main",
    "path": "artifacts/mcp/atlassian"
  },
  "review": {
    "status": "approved",
    "policy": "company-artifact-review-v1"
  }
}
```

The registry lock resolves `ref` to a commit and tree digest. Consumer sync MUST use the committed
lock; only a Maintainer lock/update command may advance a moving upstream ref.

A registry-owned package uses the normal `artifacts/<type>/<name>/artifact.json` layout and does
not need a duplicate `entries` file.

If a registry wants to rename, patch, or semantically alter a native upstream package, it becomes a
fork/materialized canonical package with explicit provenance. A reference cannot silently override
the upstream artifact identity.

### 10.3 Lockfile

`aart.lock.json` contains deterministic resolved records:

```json
{
  "schema_version": 1,
  "registry_inputs_digest": "sha256:<hex>",
  "entries": {
    "mcp/atlassian": {
      "origin_url": "git@github.company.example:platform/atlassian-agent-tools.git",
      "requested_ref": "main",
      "resolved_commit": "<40-hex>",
      "path": "artifacts/mcp/atlassian",
      "manifest_digest": "sha256:<hex>",
      "payload_digest": "sha256:<hex>",
      "object_digest": "sha256:<hex>",
      "artifact_version": "2.1.0"
    }
  }
}
```

`registry_inputs_digest` covers deterministic registry inputs while excluding generated lock/index
files, avoiding a self-referential Git commit/hash. The real schema also records importer
input/version/options digests for normalized copies. Secrets, access URLs containing credentials,
local absolute maintainer paths, and timestamps MUST NOT appear in deterministic lock data.

### 10.4 Compiled index

`aart.index.json` is the deterministic consumer/search projection. It contains normalized metadata,
qualified-in-source identity, descriptions, version/digests, compatibility, supported effects,
setup summary/capabilities, provenance summary, and collection membership.

It MUST NOT contain payload bytes, credentials, arbitrary README content, raw importer logs, or
trust derived from the consumer's local policy. Local compilation overlays effective trust at
runtime.

Registry CI runs `aart registry build --check` to prove the committed index and lock match source.

## 11. Compatibility handshake

Compatibility has independent dimensions:

- AART executable SemVer;
- protocol version;
- document schema versions;
- required compiler capabilities;
- artifact version;
- harness profile version/capabilities;
- setup recipe version/capabilities;
- importer ID/version for normalized foreign content.

The source compiler performs this order:

1. parse root JSON with duplicate-key rejection;
2. check supported protocol version;
3. check `requires_aart` bounds;
4. check every required capability;
5. parse referenced document schemas;
6. compile and validate graph/content;
7. publish the candidate only if every required check passes.

An unsupported optional extension may be ignored only when its schema declares that behavior. An
unknown required capability is fatal. Failure code `source-incompatible` includes required and
available versions/capabilities and retains last known good.

## 12. Compiler pipeline

The same core compiler serves consumers and Maintainer CI.

### 12.1 Inputs

- configured source snapshot(s);
- committed registry locks for frozen consumer builds;
- harness profile capability registry;
- effective organization/user policy;
- optional local working-tree source for Maintainer mode.

### 12.2 Phases

1. **Acquire:** resolve local tree or immutable Git commit.
2. **Parse:** decode strict JSON and canonical package metadata.
3. **Handshake:** validate protocol/AART/capability compatibility.
4. **Resolve:** bind registry entries through committed lock data.
5. **Normalize:** produce canonical in-memory artifact records.
6. **Validate:** check identities, versions, paths, digests, graph references, collections,
   compatibility, effects, setup, and policy.
7. **Index:** emit a deterministic, immutable candidate with its required object plans.
8. **Materialize:** copy only candidate objects into the content-addressed store.
9. **Diagnose:** return structured warnings/errors and human rendering.
10. **Publish:** atomically mark a complete validated and materialized snapshot current.

Index construction precedes materialization so every semantic/compiler failure happens before a
write port is called. Immutable object writes may partially succeed when an adapter reports several
independent failures, but publication remains unreachable until every planned object receipt and
the final snapshot receipt match their digests.

Consumer compilation is frozen: it never advances an external registry ref. Maintainer
`lock/update` may resolve moving refs and then produces a reviewable lock/index diff.

### 12.3 Determinism

Build output MUST be byte-identical for equal source trees, locks, compiler protocol version, and
options. It MUST exclude wall-clock time, host paths, usernames, environment order, locale, and Git
credentials. Diagnostics have stable codes and sorted source/path ordering.

### 12.4 Qualified marketplace graph

The normalized graph qualifies every artifact and collection by the configured source alias while
retaining its source-authored ID. A registry-resolved external artifact remains qualified by the
registry alias and retains its pinned origin/commit/path provenance. Duplicate aliases/source IDs,
source-ID mismatches, duplicate qualified records, unavailable required compiler capabilities,
dangling collection members, excluded versions, and collection cycles fail graph compilation.

Collection references are source-local in protocol v1. Compilation stores their deterministic,
deduplicated transitive membership so selection, bundles, installation-risk aggregation, and
install planning consume the same expansion.

Compatibility evaluates profile, platform, scope, mode, supported install effects, setup platform,
and setup capabilities independently. Every failed dimension remains visible. Broad selection may
skip items with reasons; an explicit incompatible/missing/removed selection fails rather than being
silently filtered. Payload compatibility remains distinct from optional setup compatibility.

Against a previous graph, version regression fails. Equal SemVer precedence plus a changed
manifest, payload, object, or projected-semantic digest fails, so build metadata cannot conceal a
content change. A precedence increase without a projected semantic change emits a reviewable
warning. Missing current artifacts become non-selectable removed tombstones rather than vanishing
from lifecycle feedback.

## 13. Source importers

### 13.1 Boundary

Importers are built into the AART executable for protocol v1. External runtime plugins and
repository-supplied converter code are out of scope.

Each importer declares:

- stable ID and version;
- recognized input markers;
- supported artifact types/layout versions;
- deterministic options schema;
- emitted canonical schema/capabilities;
- loss/ambiguity rules;
- safe warnings and remediation.

### 13.2 Workflow

```text
scan -> select importer -> pin input -> preview plan -> materialize temp output
     -> validate canonical package -> compare -> maintainer apply -> registry build --check
```

The apply result includes `provenance.json`:

```json
{
  "schema_version": 1,
  "origin": {
    "kind": "git",
    "url": "https://github.com/example/upstream.git",
    "resolved_commit": "<40-hex>",
    "path": ".claude/skills/example",
    "input_digest": "sha256:<hex>"
  },
  "importer": {
    "id": "claude-skill-v1",
    "version": "1.0.0",
    "options_digest": "sha256:<hex>"
  },
  "warnings": []
}
```

The importer MUST NOT infer secrets, execute upstream files, follow source symlinks outside the
pinned tree, or discard unknown semantic fields silently. `aart upstream update` reruns the exact
recorded importer and makes changed warnings/provenance part of review.

### 13.3 Initial importer policy

Only broadly used, stable formats SHOULD receive built-in importers. One-off repository mappings
MUST be rejected or handled by first converting that repository to the native AART standard.

Likely initial candidates are existing `SKILL.md` directory layouts and selected MCP descriptor
layouts where the transformation is lossless. Ambiguous monolithic instruction files require the
maintainer to choose artifact type/name/compatibility explicitly.

The first implemented contract is the closed, deterministic
`legacy-catalog-v1` importer. Its mapping, rejection rules,
provenance projection, review/apply boundary, and current limitations are normative for the 0.1.x
catalog conversion.

## 14. Managed source and object store

### 14.1 Layout

Suggested data-root layout:

```text
sources/
  <source-instance-id>/
    mirror.git/
    snapshots/
      <resolved-commit>/
        source/
        compiled-index.json
        validation.json
    current.json
objects/
  sha256/
    <first-two-hex>/<remaining-hex>/
      artifact.json
      payload/
      setup/
      provenance.json
locks/
tmp/
state/
```

`current.json` is a small pointer replaced atomically. A platform symlink MAY implement the pointer
internally, but readers MUST see the old or new complete snapshot, never a partially written tree.

### 14.2 Git acquisition

Remote Git sources require a supported system `git` executable. AART remains free of Python runtime
dependencies; local sources and already-materialized offline operations remain usable without
network access.

Git commands use fixed argv with `shell=False`, bounded timeouts, sanitized environment, and no
credential values in output. Auth is delegated to SSH, Git credential helpers, or existing user Git
configuration. URLs containing embedded credentials are rejected/redacted.

The acquisition algorithm:

1. acquire a per-source lock;
2. create/update a bare mirror;
3. resolve configured ref to commit;
4. materialize into a temporary sibling without source-controlled hooks;
5. compile/validate under effective policy;
6. fsync required files/directories where supported;
7. atomically publish snapshot and pointer;
8. release lock.

Failure leaves mirror diagnostics and the previous current snapshot usable.

### 14.3 Content-addressed objects

Canonical packages are copied into `objects/sha256/...` only after digest verification. Publication
uses stage-then-rename and handles concurrent identical writers. Published objects are treated as
read-only and MUST never be edited in place.

Install manifests pin object digests. Garbage collection retains objects referenced by:

- any project/user manifest registered with the local state index;
- current source snapshots;
- configured retained/rollback snapshots;
- active setup transactions.

`aart store gc` defaults to dry-run, acquires a global GC lock, and never follows user symlinks.
The implemented envelope, publication, reference, transaction, verification, repair, and rollback
contract is documented in
[`content-addressed-store-v1.md`](../store/content-addressed-store-v1.md).

### 14.4 Sync policy

`aart registry sync`/`aart source sync` force synchronization. Bare TUI, list, install, and update MAY
perform best-effort sync when configured `max_age_seconds` expires. `status`, `uninstall`,
`--version`, and `--help` do not implicitly fetch.

Offline/network failure returns a visible warning and uses last known good when the requested
artifact is available. It is an error only when the operation requires uncached content.

## 15. Marketplace merge and trust

The compiled marketplace is sorted deterministically by configured display order, source alias,
artifact type, name, and SemVer. Display order affects presentation only.

Effective trust classes:

- `company-reviewed`: exact source identity is designated by organization policy and entry review
  is valid;
- `registry-reviewed`: entry is reviewed by its registry, but the registry is not organization
  designated;
- `direct-source`: native remote source configured directly;
- `local`: mutable local source;
- `unverified`: provenance/review requirements are incomplete.

Trust is recalculated when URL, declared source/registry ID, resolved commit, lock, entry review,
object digest, or policy changes. It is not serialized into the artifact package.

The implemented pure runtime projection, qualification rules, exact organization source identity,
trust-evidence digest, and JSON/human output contract are recorded in
[`federated-marketplace-v1.md`](../marketplace/federated-marketplace-v1.md).

Duplicate `<type>/<name>` entries remain visible as distinct qualified rows. An unqualified CLI
request that matches more than one row fails with `artifact-ambiguous` and lists valid qualified
coordinates.

## 16. Installation engine

### 16.1 Plan boundary

Install follows:

```text
resolve -> compatibility/policy -> materialize object -> plan -> review -> apply -> state -> setup
```

The immutable plan records:

- request and qualified coordinate;
- source alias/ID/kind/origin/resolved commit;
- registry entry and origin provenance when applicable;
- artifact version, manifest digest, and object digest;
- effective trust and policy decisions;
- harness profile/version, scope, destination;
- requested/actual install mode per effect;
- ordered filesystem/config actions;
- setup recipe/capabilities/plan digest.

Finalize executes exactly the reviewed plan or fails if any precondition changed.

### 16.2 Copy

Copy is default. Pure file/tree effects copy from the immutable object into the harness destination.
Existing drift follows the established keep/conflict/force policy. Copy remains independent when a
source later syncs or its object becomes non-current.

### 16.3 Symlink

Managed Symlink targets the immutable content object, never `site-packages`, a virtualenv, a Git
worktree snapshot scheduled for deletion, or a moving `current` pointer.

Pure file/tree effects may symlink. Merge/config effects remain managed copies/merges, producing a
visible mixed-mode plan. Explicit local developer mode may link directly to a selected checkout;
the manifest records `mutable-local` trust/link semantics.

`aart update` materializes and validates the replacement object, then atomically replaces managed
destination symlinks. Source sync alone does not retarget them. Live-to-moving-current links are out
of scope for 1.0.

### 16.4 State

Project state remains under `<project>/.agent-artifacts/`. User-global state moves through a tested
migration into the platform data root. Manifest schema v2 records, per installed artifact:

```json
{
  "coordinate": "company/mcp/atlassian",
  "source": {
    "alias": "company",
    "declared_id": "company-agent-artifacts",
    "kind": "registry-git",
    "origin": "<redacted-safe-git-identity>",
    "resolved_commit": "<40-hex>"
  },
  "artifact": {
    "type": "mcp",
    "name": "atlassian",
    "version": "2.1.0",
    "manifest_digest": "sha256:<hex>",
    "payload_digest": "sha256:<hex>",
    "object_digest": "sha256:<hex>"
  },
  "profile": "tabnine",
  "profile_version": 1,
  "scope": "user",
  "requested_mode": "symlink",
  "effects": [],
  "setup_state_ref": "<non-secret-state-key>"
}
```

Actual schema stores complete effect proof needed for status/update/uninstall. It MUST NOT store
credentials, credential-bearing origins, raw setup output, or mutable trust labels without their
derivation inputs.

### 16.5 Update and uninstall

Update uses the recorded source subscription and qualified identity. Missing/disabled sources yield
actionable `source-unavailable` state and do not fall through to a same-named artifact elsewhere.

Update reports selected, changed, current, skipped, conflicted, failed, removed-upstream, and setup-
pending counts/items. Uninstall removes only proven managed effects; retargeted/replaced symlinks and
user-edited merges require the established force/conflict handling.

## 17. Setup engine

The existing reviewed static setup recipe model remains the default. Setup identity binds:

- artifact object digest;
- recipe digest/version;
- harness profile and scope;
- source/provenance identity;
- capability plan digest.

The setup queue begins after payload effects reach terminal state. Each selected item receives a
terminal payload and setup outcome even when an earlier item fails or the remaining queue is
stopped.

Initially supported macOS modules include Keychain, owned file/shell blocks, owned JSON values,
directories, fixed-argv verification, digest-pinned Docker pulls, and restart guidance. Custom
entrypoints remain explicitly reviewed, policy-gated, hash-bound, executed from a private copied
run directory with minimal environment and `shell=False`; they are trusted code, not a sandbox.

Direct/local/unverified sources do not automatically inherit permission to run setup. Policy and
interactive review can deny unsupported capabilities while still allowing payload installation.

### 17.1 Manual route

Setup recipes carry a matching `schema_version`/`protocol_version` pair, and exactly one revision
is supported: both fields MUST be `2`. Any other pair, including the superseded `1`/`1`, MUST be
rejected at parse time with an error naming the required pair and the document it implies. No
compatibility path for a superseded revision exists in validation, review, or the runtime.

Every valid recipe therefore requires a package-root `SETUP.md`: a contained regular file,
non-empty safe UTF-8, never a symlink. Catalog discovery validates it before setup planning and
never parses its prose as commands. The route is derived from the recipe path, not declared by the
author, so a package cannot advertise a document it does not own — and every validated installer
resolves to exactly one route, so there is no "documentation unavailable" state to render.

A custom entrypoint MUST begin, after an optional shebang, with the exact line:

```sh
# AART manual setup: see ../SETUP.md
```

so that reading the script directly also reveals the manual route. The runtime preamble stays
authoritative regardless of what a script contains.

Presentation resolves the route to a commit-pinned HTTPS blob URL when the reviewed source has
one, and otherwise to the contained absolute local path. It is shown before setup consent and
again after any outcome that is not complete. Following it is never treated as consent, and it
grants no capability that automated setup would not have needed.

## 18. Security assessment subsystem

### 18.1 Evidence model

Security assessment describes evidence and installation risk for one immutable artifact object. It
MUST NOT expose a boolean `safe`/`secure` result.

```json
{
  "schema_version": 1,
  "object_digest": "sha256:<hex>",
  "status": "partial",
  "installation_risk": "high",
  "max_finding_severity": "medium",
  "coverage": {"completed": 2, "expected": 3},
  "findings": {"critical": 0, "high": 0, "medium": 2, "low": 3},
  "providers": [
    {
      "id": "aart-baseline",
      "version": "1",
      "rules_digest": "sha256:<hex>",
      "status": "complete"
    }
  ]
}
```

Valid assessment status values are `not-scanned`, `complete`, `partial`, `failed`, and `stale`.
Valid normalized risk/severity values are `unknown`, `low`, `medium`, `high`, and `critical`.
Provider/rules/object changes make cached evidence stale.

### 18.2 Zero-dependency baseline

`aart-baseline` is pure stdlib analysis over the canonical object and compiled metadata. It covers:

- source/lock/provenance/review completeness and moving/unpinned inputs;
- declared install/setup effects and sensitive capabilities;
- embedded credential patterns and unsafe MCP JSON values;
- Python syntax/AST patterns using stdlib `ast`;
- bounded, explicitly heuristic shell patterns such as dynamic evaluation, pipe-to-shell, privilege
  escalation, destructive broad paths, and unpinned remote execution;
- insecure transport/unpinned package/image references;
- importer warnings and custom setup entrypoints.

Baseline diagnostics MUST state the observed fact/rule and remediation. The baseline does not claim
general SAST, malicious-package detection, or runtime-behavior coverage.

### 18.3 Optional provider protocol

External analyzers install independently and expose `security-analyzer-v1` over JSON stdin/stdout.
AART invokes a fixed executable argv with `shell=False`, timeout, minimal environment, immutable
input path, no secrets, and declared network requirement. An analyzer process is trusted optional
code, not a sandbox.

The handshake includes provider ID/version, protocol/capabilities, supported artifact/file types,
ruleset digest, network requirement, and maximum input constraints. Output includes normalized
findings with stable provider rule ID, severity, safe message, relative location, fingerprint, and
coverage/skips. AART rejects malformed/oversized output and deduplicates only identical normalized
fingerprints; it does not hide disagreements between providers.

Initial built-in command adapters SHOULD cover separately installed tools for Python static rules,
secret detection, Python dependency advisories, and shell analysis. MCP/IaC/multi-language adapters
remain optional capability extensions. AART MUST NOT auto-install providers or add them to its own
Python environment.

### 18.4 Cache and registry attestations

Assessment cache identity includes object digest, provider ID/version, rules digest, normalized
options digest, and effective policy inputs. Registry CI may publish a deterministic assessment
attestation/index for a pinned object. Consumer trust in that result derives from registry identity
and local policy, not from the attestation's self-assertion. Consumers may re-scan locally.

### 18.5 Bundle aggregation and policy

Nested collections are expanded/deduplicated before aggregation. Bundle summary exposes:

- worst installation risk and maximum finding severity;
- minimum/maximum risk range;
- arithmetic mean numeric risk as secondary context only;
- severity counts;
- complete/partial/failed/stale/not-scanned coverage counts;
- worst artifact coordinate(s).

Install policy MUST use worst risk/severity and unknown/stale coverage. A favorable mean cannot
override a critical/high/unknown member. Policy may warn, require confirmation, or block by scope,
trust, provider suite, severity, or coverage.

## 19. TUI state machine

The wizard state contains:

- visited/current stage;
- role;
- enabled source view/filter and health snapshot;
- profile/harness selection;
- action, scope, install mode;
- basket of qualified artifact selections;
- cursor/scroll position per selector;
- compiled plan and invalidation reasons;
- setup queue and trust/policy warnings.

Backspace transitions to the previous applicable stage without discarding valid state. Editing an
earlier choice invalidates only dependent selections/plans. Finalize is the only state allowed to
dispatch mutations.

Suggested consumer stages:

```text
How it works -> Role -> Sources -> Harness -> Action -> Scope -> Mode
             -> Artifacts -> Review -> Finalize -> Outcome
```

Source rows show enabled/current/stale/offline/invalid/incompatible health. Artifact rows show
source alias, trust, type/name, version, summary, compatibility, installed state, and update state.

If no sources are configured, User mode offers source setup or exits cleanly; it does not force a
registry. Maintainer mode requires an explicit writable local source/registry checkout for mutation.

## 20. CLI surface

Implemented canonical agent commands in this release slice:

```text
aart source add|list
aart marketplace list [--json]
```

The remaining target command groups are design targets, not aliases for the retained legacy
`list/install/update/setup` compatibility commands:

```text
aart source remove|enable|disable|use|sync|health|doctor|path
aart compile [--source <alias-or-path>] [--frozen] [--json]

aart registry init|validate|format|lock|build|audit|test|diff|migrate
aart registry add|remove|list|use-default|sync|health|doctor|path

aart artifact scaffold|validate|import|promote
aart upstream add|check|update

aart list|install|update|uninstall|status|check
aart setup run|status|retry|rollback
aart security scan|show|analyzers|suites|verify
aart store status|verify|gc
aart config show|set|doctor
```

`registry` is a specialized source with curation/lock/index commands. Shared acquisition and health
logic MUST live below both command groups.

Legacy `--source DIR`, `--repo`, and package-catalog behavior receive explicit alpha deprecation or
migration handling. They MUST NOT silently reinterpret an old request against a different source.

## 21. Structured outcomes and errors

Core operations return typed results; the TUI does not parse human stdout. JSON output includes:

- `schema_version`;
- operation and session outcome;
- source/snapshot metadata;
- selected/changed/current/skipped/conflicted/failed counts;
- per-item terminal result;
- stable warning/error codes;
- safe remediation commands.

Initial stable error codes include:

```text
no-source-configured
source-unavailable
source-auth-failed
source-incompatible
source-invalid
source-policy-denied
artifact-not-found
artifact-ambiguous
artifact-incompatible
lock-stale
digest-mismatch
import-lossy
import-stale
install-conflict
setup-policy-denied
offline-object-missing
```

Human messages may improve without breaking JSON consumers; code meanings and schema changes follow
versioning policy.

## 22. Security requirements

- Never execute Git hooks from cloned sources.
- Never execute artifact payloads during parse/build/list.
- Reject source symlinks and path traversal before materialization.
- Never interpolate source metadata into shell commands.
- Use fixed argv and `shell=False` for Git/setup subprocesses.
- Redact credentials from URLs, Git errors, outcomes, and state.
- Validate lock commit/digest before using external content.
- Treat registry index/lock, README, artifact metadata, and GitHub issues as untrusted input.
- Bound file counts, individual file sizes, total object size, JSON depth, string length, and setup
  diagnostics.
- Do not let registry-declared trust override local policy.
- Require explicit review/consent for setup effects and user-global writes.
- Preserve last known good on parse, compatibility, policy, fetch, digest, or build failure.
- Do not delete objects/snapshots while referenced by install/setup state.
- Never render security evidence as a guarantee that an artifact is safe.
- Never auto-install or in-process import optional analyzer packages.
- Bind every assessment/attestation to object, provider, and rules digests and expose stale/unknown
  coverage explicitly.

Protocol v1 does not require cryptographic signing. Commit identity plus digest/provenance and
organization Git controls provide the initial trust boundary. A future signature capability may be
added without changing artifact identity.

## 23. Concurrency and atomicity

Use separate locks for:

- each source mirror/snapshot;
- each content object publication;
- project/user manifest transaction;
- setup state transaction;
- global garbage collection.

Locks include bounded stale-owner recovery based on process/host-safe metadata without exposing it
in telemetry. All writes use a temporary sibling, validation, fsync where appropriate, and atomic
rename/replace. Readers never observe half-written JSON, snapshots, objects, or manifests.

Concurrent identical fetch/materialize operations converge on one object. Concurrent conflicting
install/update operations on the same manifest serialize and revalidate preconditions before apply.

## 24. Reporting integration

Reporting configuration is independent from source configuration. A registry service declaration
is a prompt-only endpoint for results selected through that registry. An explicit user or
organization destination centralizes reporting and is mandatory for automatic submission.

The default unconfigured mode is prompt. Results are partitioned by artifact registry before
serialization, aliases for the same endpoint are deduplicated, and each destination receives a
separate default-No consent flow. Registries without an advertisement and direct sources receive no
report. Explicit `disabled` performs no source read, prompt, preview, queue, browser, or network
operation.

When configured, session results use a versioned allowlist event, preview in interactive prompt
mode, and target only the configured GitHub/GitHub Enterprise repository. Browser prefill is the
tokenless path. Automatic creation requires explicit authenticated configuration. Reporting failure
never changes installation exit status.

Registry-owned GitHub workflows validate, label, close, aggregate, and render reports. They MUST
follow the untrusted-input and privacy constraints retained from superseded issue #24.

## 25. Migration from 0.1.x

### 25.1 Catalog content

Use built-in importer `legacy-catalog-v1` for an external 0.1 checkout with this top-level
layout:

```text
skills/ guidelines/ mcp/ hooks/ memory/ bundles/ upstreams.json
```

The AART tool checkout intentionally contains none of these operational roots. The importer
produces a canonical native source root with `aart-source.json`, `artifacts/`, `collections/`, and
provenance. IMP02/REG01 add promotion, registry lock, and compiled index workflows. Migration runs
in a new/explicit output directory and never deletes the source tree without a reviewed apply.

### 25.2 Installation state

Migration command:

```text
aart migrate state --from 0.1 --dry-run
aart migrate state --from 0.1 --apply
aart migrate state --from 0.1 --rollback
```

It MUST:

- create a timestamp-independent deterministic backup name plus collision suffix;
- parse and validate legacy state before writing;
- map package/local/GitHub subscriptions to configured source identities or request resolution;
- retain existing targets and actual Copy/Symlink state;
- retain enough legacy proof for rollback/uninstall;
- never guess between multiple same-named source artifacts;
- leave the 0.1 state usable on failure.

Ambiguous identities are resolved with repeatable
`--source-map TYPE/NAME@PROFILE=ALIAS`. A completed journal plus its exact backup is sufficient for
rollback in a later process. Legacy `--source`/`--repo` inputs remain a disclosed compatibility
path and are never treated as canonical aliases; an absent legacy source no longer falls back to
package contents.

### 25.3 Executable version transition

The code version stayed `0.1.48` until implementation started the alpha train. Documentation alone
did not bump the package. The first breaking implementation commit used `1.0.0a1`; stable `1.0.0`
was finalized only after all release gates passed.

## 26. Local installation and future Nexus readiness

Supported initial delivery remains explicit and local:

```text
pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts
pip install --no-index --no-deps /path/to/agent_artifacts-1.0.0-py3-none-any.whl
```

The hermetic distribution smoke executes both forms in isolated tool environments from outside the
checkout. It syncs a native source, installs Copy and immutable managed Symlink targets, deletes
and recreates the executable environment, resumes status/uninstall/reinstall, and verifies that
managed links survive both environment removals. The wheel contains:

- executable Python package;
- schemas;
- built-in harness profiles;
- built-in source importers;
- scaffold templates;

Package resources are allowlisted to schemas/profiles/importers/templates. Operational registries,
artifact payloads, unexpected package data, duplicate/unsafe archive paths, and unconditional
runtime dependencies fail the packaging gate.

The wheel MUST NOT contain the public/company operational registry. Runtime config, mirrors,
snapshots, CAS objects, and state MUST live outside the environment. Deleting and recreating the
Python environment MUST NOT break managed object symlinks.

`aart upgrade` requires exactly one reviewed local `--wheel FILE` or `--source-checkout DIR` and
constructs a fixed index-free pip invocation. It never infers a repository/version or contacts an
index. Editable replacement also disables build isolation. Local source state accepts the legacy
`local` revision and the canonical snapshot-bound `local:<sha256>` revision during migration.

Future Nexus/PyPI work may add indexed install/upgrade documentation and publication credentials.
It MUST NOT require changing the protocol, source config, managed store, or install manifest model.

## 27. Verification strategy

### Unit tests

- strict JSON and duplicate-key rejection;
- SemVer bounds and capability negotiation;
- coordinate parsing/ambiguity;
- canonical JSON/tree digests;
- policy calculation/trust derivation;
- importer determinism and loss diagnostics;
- compilation/index/lock determinism;
- plan/outcome/state migrations.

### Integration tests

- local native source with no registry;
- multiple native sources with collisions;
- public plus company registry union;
- registry native reference with pinned commit/digest;
- normalized foreign import/update/provenance;
- private Git auth failure redaction;
- offline last-known-good and uncached-object failure;
- corrupt/incompatible candidate preserving current;
- concurrent sync/object publication/manifest updates;
- Copy, immutable Symlink, mixed merge, explicit local live link;
- project and fake user-global scopes across profiles;
- setup partial success/retry/rollback/policy denial;
- baseline assessment determinism/staleness, provider crash/timeout/malformed output, bundle worst/
  range/mean/coverage, attestation trust, and policy warn/block behavior;
- reporting absent/prompt/automatic failure isolation.

### End-to-end fixtures

1. Personal user with two direct public repos and no registry.
2. Company user with a reviewed default registry plus an allowed private team source.
3. Registry maintainer referencing one native upstream and importing one foreign upstream.
4. Existing 0.1.x project migrated, updated, uninstalled, and rolled back.
5. Local editable install removed/recreated while managed symlink remains valid.
6. Local wheel install from outside the checkout with source sync and installation.

### Registry CI matrix

Each registry tests:

```text
aart registry format --check
aart registry validate --strict --frozen
aart registry lock --check
aart registry build --check
aart registry audit
aart registry test --profiles <supported>
```

Run with both minimum supported stable AART and latest compatible stable/alpha as appropriate.

## 28. Release gates

Stable `1.0.0` requires:

- [x] Protocol/source/artifact/registry/lock/index/config/policy/manifest schemas frozen at v1/v2 as
      specified.
- [x] Direct-source-only use passes without registry/reporting configuration.
- [x] Optional public/company registry federation passes with collision/trust behavior.
- [x] Native references and materialized importer output pass provenance/determinism checks.
- [x] Managed source snapshots and CAS pass atomicity, concurrency, repair, offline, and GC tests.
- [x] Copy/Symlink/update/uninstall/setup semantics pass project/user/profile matrices.
- [x] Zero-dependency baseline, optional provider isolation, digest-bound attestations, bundle
      aggregation, and security policy gates pass without adding runtime dependencies.
- [x] 0.1.x catalog and state migration/rollback pass from committed fixtures.
- [x] The audited public `M1F1/agent-artifacts-registry` reference registry passes minimum/latest
      AART CI.
- [x] Local editable and local-wheel installs work without checkout-relative operational data.
- [x] Deleting the Python environment leaves installed managed symlinks valid.
- [x] Documentation and TUI explain source, registry, default registry, trust, and importer boundaries.
- [x] Nexus/index publication remains unnecessary for the release.

## 29. Deferred capabilities

- signed artifact/registry attestations;
- hosted registry/search API;
- non-Git source transports;
- external importer plugins;
- live links to moving source channels;
- automatic registry PR creation;
- cross-platform setup beyond macOS v1;
- automatic AART update from Nexus/PyPI;
- organization-wide unique-user analytics.
