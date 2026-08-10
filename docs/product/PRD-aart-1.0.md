# AART 1.0 Product Requirements Document

- **Status:** Released
- **Target:** `1.0.0`
- **Stable release:** `1.0.0` (preceded by `1.0.0aN`)
- **Tracking issue:** [#27](https://github.com/M1F1/agent-artifacts/issues/27)
- **Companion technical specification:**
  [`docs/design/SPEC-aart-1.0.md`](../design/SPEC-aart-1.0.md)

## 1. Executive summary

AART 1.0 turns `agent-artifacts` from a CLI coupled to one bundled catalog into an independent
compiler and package manager for agent artifacts.

Artifacts may live in any compatible local, public, or private Git repository. Optional registry
repositories add discovery, curation, review, policy, collections, and usage reporting. A user may
use no registry, one registry, several registries, only direct repositories, or any combination of
those sources.

AART compiles the configured source union into a deterministic local marketplace, resolves a
selected artifact to immutable content, and installs it into a supported agent harness. Registry
content and the AART executable are developed and versioned independently through an explicit
protocol and capability contract.

The 1.0 release remains locally installed from this repository. Publishing the executable to
Nexus or another Python index is future delivery work, but the architecture must no longer depend
on an editable checkout or a catalog located next to the Python package.

## 2. Product thesis

Agent tooling is fragmented across repositories, harness-specific directories, configuration
formats, and setup instructions. Teams need a standard that makes those artifacts portable without
requiring every artifact to be copied into one central repository.

AART provides three complementary capabilities:

1. **Standard:** a canonical artifact package and versioned source/registry protocol.
2. **Compiler:** deterministic normalization, validation, resolution, and harness-specific output.
3. **Marketplace client:** a searchable union of sources with explicit provenance and trust.

Registries remain useful, but optional. They solve discovery and governance; they are not required
for compilation or installation.

## 3. Terminology

### Artifact package

A canonical AART directory containing a versioned manifest, payload, optional setup recipe, and
the metadata required to validate, identify, compile, and install one artifact.

### Native source repository

Any Git repository or local directory that exposes one or more canonical AART artifact packages.
It may be compiled directly without appearing in a registry.

### Registry

An optional curated repository that indexes native artifact sources, contains locally authored
artifact packages, or materializes reviewed canonical copies of foreign upstreams. It also owns
collections, lock data, policy declarations, and optionally a usage-report destination/dashboard.

### Catalog source

The common runtime abstraction for a native source repository, registry, or explicit local source.
AART combines zero or more catalog sources into one marketplace view.

### Default registry

An optional configured registry used for initial TUI focus, unqualified discovery preferences, and
deployment-owned services such as usage reporting. It is not required by the AART protocol.

### Source importer

A maintainer-side, deterministic converter from one documented foreign layout into a canonical
AART artifact package. It is an escape hatch for migration and curation, not a consumer install
hook.

### Harness compiler/profile

The normal mapping from a canonical artifact package to the native paths and configuration format
of Claude, Codex, Tabnine, OpenCode, Vibe, or another supported harness.

## 4. Problem statement

The current monolithic model creates several constraints:

- the executable and curated artifacts share one repository and release lifecycle;
- public tooling cannot safely contain company-confidential artifacts;
- installing from a future wheel would not naturally provide a durable source for symlinks;
- direct artifacts from other repositories must be copied or imported into the monolith;
- source compatibility is implicit and tied to the current code;
- users either know every upstream URL or rely on one hardcoded catalog;
- review, provenance, and trust are not modeled consistently across direct and curated sources;
- foreign upstream formats invite one-off runtime parsing rules;
- company governance and open-source personal use need different defaults.

## 5. Goals

### G1. Separate tool and content

The AART repository owns the compiler, package manager, protocol, TUI, and harness profiles. Public,
company, team, and personal artifact inventories live independently.

### G2. Make sources federated

Users can configure zero or more local/Git sources and registries. No central registry is required
for basic use.

### G3. Preserve an excellent discovery path

Optional curated registries provide a marketplace that lets users discover reviewed artifacts
without knowing their original repository URLs.

### G4. Establish a canonical standard

Native artifacts follow one stable AART package contract. Harness compilers translate that
contract into supported native layouts. Harness-specific capabilities remain explicitly scoped
rather than being forced into a false universal abstraction.

### G5. Support controlled foreign imports

Known foreign layouts can be normalized by explicit, versioned maintainer importers. Converted
output is materialized, reviewed, and quality-gated before consumers can install it.

### G6. Make AART the quality gate

The same compiler used by consumers validates and builds registries in CI. Registry compatibility
is expressed through protocol versions, AART version bounds, and required capabilities.

### G7. Provide durable Copy and Symlink installs

Remote content is materialized in a stable per-user store outside the Python environment. Symlinks
do not require the consumer to retain a source checkout and do not change merely because a source
was fetched.

### G8. Preserve safe guided setup

Complex macOS setup remains reviewed, digest-bound, sequential, resumable, and secret-safe.

### G9. Prepare for later index distribution

Local editable and local-wheel installation work first. A future Nexus release changes delivery of
the executable only, not configuration, sources, registry storage, or install semantics.

### G10. Expose evidence-based installation risk without core dependencies

Every artifact may have a digest-bound security assessment. A zero-dependency baseline evaluates
provenance, declared effects, setup capabilities, and bounded static heuristics. Independently
installed analyzers may contribute normalized findings through a versioned subprocess protocol.
The product reports evidence, coverage, staleness, and installation risk; it never certifies that an
artifact is safe.

## 6. Non-goals for 1.0

- Publishing AART to Nexus, PyPI, or another package index.
- Operating a hosted non-Git marketplace service.
- Automatically discovering every artifact repository on GitHub.
- Transparently converting arbitrary layouts during consumer installation.
- Building a plugin system for repository-specific conversion hacks.
- Requiring a default or global registry.
- Requiring one exact AART patch version for every registry.
- Automatically committing or pushing maintainer changes.
- Executing unreviewed scripts from moving remote branches.
- Implementing setup effects beyond the explicitly supported macOS v1 contract.
- Claiming that static analysis proves an artifact is safe or vulnerability-free.
- Automatically installing optional security analyzers into the AART environment.

## 7. Personas

### Consumer developer

Wants to discover, install, update, inspect, and remove agent artifacts in a project or user-global
harness scope without understanding every source layout.

### Independent user

Wants to use a few known public/private repositories without joining a central registry or sharing
usage data.

### Company developer

Should see the reviewed company registry first, understand which artifacts are company-approved,
and remain protected by organization source/setup/reporting policy.

### Artifact author

Wants a clear canonical package structure, validation, scaffolding, and tests that make one
artifact consumable by supported harness profiles.

### Registry maintainer

Curates native sources, imports incompatible upstreams, reviews changes, updates locks, runs
quality gates, and publishes registry commits without AART committing on their behalf.

### Platform/security owner

Defines allowed sources, trusted registries, setup capabilities, reporting destinations, and
minimum compatibility without forking the AART executable.

## 8. Product principles

1. **Federated by default.** Central curation is available, not mandatory.
2. **Canonical at rest.** Consumers install canonical packages, not live importer output.
3. **Compile before mutation.** Resolve, validate, plan, and review before installation changes.
4. **Trust is provenance, not branding.** A source cannot declare itself company-reviewed.
5. **No silent shadowing.** Ambiguous artifact identities require qualification.
6. **Fetch is not update.** Synchronizing metadata/content never silently changes installed code.
7. **Last known good beats partial freshness.** Failed source updates preserve usable snapshots.
8. **Secrets never become state or telemetry.** Setup values remain outside manifests and reports.
9. **Policy constrains configuration.** CLI flags cannot bypass organization restrictions.
10. **Local-first, distribution-ready.** No runtime behavior depends on a package-manager layout.

## 9. Product model

The marketplace is a compiled view, not one physical repository:

```text
native Git/local repositories ───────────────┐
                                             │
foreign upstream ─ importer ─ canonical copy ├─> source compiler ─> marketplace
                                             │
curated registries ──────────────────────────┘
                                                                  │
                                                                  v
                                                     install/update/setup
                                                                  │
                                                                  v
                                                       supported harnesses
```

The user-facing source list may therefore contain:

```text
Company reviewed
  company/mcp/atlassian
  company/skill/code-review

Public registry
  public/skill/security-review

Direct sources
  team-a/internal-agents
  github-user/personal-skills
```

Each row exposes its coordinate, version, source, trust class, compatibility, and concise value
description. Trust classes are assigned by local policy and registry provenance, never accepted
from an untrusted artifact manifest.

## 10. Required workflows

### 10.1 Independent use without a registry

1. Install AART from the local tool checkout.
2. Add one or more compatible Git/local repositories.
3. Compile their catalogs into the local marketplace.
4. Install/update artifacts normally.
5. Operate with no default registry and no usage reporting.

### 10.2 Company-curated use

1. Organization provisioning recommends or preconfigures the company registry.
2. First use explains that its artifacts are reviewed and shows the policy/trust state.
3. The user may add additional sources if policy permits.
4. Company-qualified artifacts appear first without hiding other sources.
5. Setup capabilities and reporting follow organization policy.

Core AART permits the registry to be optional. An organization policy may make it required for
that deployment.

### 10.3 Native artifact publication

1. Author scaffolds a canonical package in any repository.
2. Local validation and harness matrix tests pass.
3. Consumers can add the repository directly.
4. A registry maintainer may later add a pinned reference for discovery without duplicating the
   payload.

### 10.4 Foreign upstream curation

1. Maintainer selects an explicitly supported importer.
2. AART pins the upstream commit/input digest and records the importer version.
3. The importer emits a canonical package plus warnings/provenance.
4. Validation rejects loss, ambiguity, unexpected files, or non-deterministic output.
5. Maintainer reviews and commits the normalized package.
6. Future upstream updates rerun the same importer and produce a reviewable diff.

### 10.5 Installation and update

1. AART resolves a qualified artifact from the compiled source union.
2. It checks source health, trust, compatibility, policy, digest, scope, and mode.
3. The user reviews destinations, version/digest, install effects, and setup queue.
4. Copy materializes an independent snapshot; Symlink points to immutable managed content.
5. Setup runs after payload installation with separate terminal outcomes.
6. Update resolves the recorded subscription, validates the replacement, and applies it explicitly.

## 11. Functional requirements

### Source and marketplace requirements

- **SRC-001:** AART must support zero or more configured catalog sources.
- **SRC-002:** Supported source kinds must include local directory, native Git repository, and Git
  registry.
- **SRC-003:** At most one registry may be marked as the optional default registry.
- **SRC-004:** First use must offer a recommended registry, direct source configuration, or
  continuation without a source.
- **SRC-005:** Non-interactive commands requiring content must fail with an actionable message when
  no usable source exists.
- **SRC-006:** The marketplace must merge sources deterministically and retain source identity.
- **SRC-007:** Conflicting unqualified identities must not be silently resolved by source order.
- **SRC-008:** Human and JSON output must expose trust, source, resolved commit, artifact version,
  and digest.
- **SRC-009:** Direct private repository auth must use the user's Git/SSH/credential helper; AART
  must not persist access tokens.
- **SRC-010:** Offline operation must use a validated last-known-good snapshot when available.

### Canonical package requirements

- **ART-001:** Every artifact must have a versioned manifest and stable type/name identity.
- **ART-002:** Every artifact must have a one-line value description and may have fuller help text.
- **ART-003:** The manifest must declare artifact version, payload, harness compatibility, supported
  scopes/modes, setup identity, and provenance fields.
- **ART-004:** Canonical payload conventions should reuse established harness formats where they
  provide stable semantics, such as `SKILL.md` and Markdown instructions.
- **ART-005:** Harness-specific artifacts must declare limited compatibility instead of pretending
  to be portable.
- **ART-006:** Digest changes without an appropriate artifact-version change must fail strict
  registry validation.

### Importer requirements

- **IMP-001:** Importers run only through explicit Maintainer commands.
- **IMP-002:** An importer supports a named/versioned foreign format, never one arbitrary repository.
- **IMP-003:** Equal input, importer version, and options must produce byte-identical canonical
  output.
- **IMP-004:** Output must record source URL, pinned commit/ref, input digest, importer identity,
  importer version, and warnings.
- **IMP-005:** Lossy or ambiguous conversion must fail or require a reviewed manual resolution.
- **IMP-006:** Consumer install/update must never invoke a source importer.
- **IMP-007:** Registry CI must prove committed normalized output is current with its pinned input
  and importer version.

### Registry and quality-gate requirements

- **REG-001:** A registry must declare protocol version, compatible AART bounds, and required
  capabilities.
- **REG-002:** Registry entries may reference native packages or own canonical packages.
- **REG-003:** External moving refs must resolve to commits and content digests in committed lock
  data before consumer use.
- **REG-004:** Build/index/lock output must be deterministic.
- **REG-005:** CI must validate with the minimum supported and latest compatible AART versions.
- **REG-006:** An incompatible or invalid registry update must not replace the current validated
  snapshot.
- **REG-007:** Maintainer operations must mutate only an explicit writable checkout and must not
  commit or push automatically.

### Installation requirements

- **INS-001:** Project and user-global scopes remain separate and profile-aware.
- **INS-002:** Copy remains the recommended default.
- **INS-003:** Symlink must work from durable managed content without a retained source checkout.
- **INS-004:** Managed Symlink targets are immutable; explicit update atomically retargets them.
- **INS-005:** Source sync alone must not change an installed artifact.
- **INS-006:** Explicit local developer sources may link directly to their checkout after disclosure.
- **INS-007:** Merge-only artifacts use managed merge semantics and disclose mixed-mode behavior.
- **INS-008:** State records complete source/subscription/version/digest/profile/scope/mode/effect
  proof without credentials.
- **INS-009:** Status/update/uninstall operate from recorded subscriptions and never cross scopes.
- **INS-010:** Every action returns explicit changed/current/skipped/conflict/failed/no-op outcomes.

### Setup requirements

- **SET-001:** Setup recipes are bound to a validated artifact digest and source trust decision.
- **SET-002:** Initially supported effect modules target macOS and prefer Keychain for secrets.
- **SET-003:** The TUI shows capabilities, URLs, mutations, rollback limits, and ordered queue before
  execution.
- **SET-004:** Secret values never appear in AART state, logs, command lines, or reporting payloads.
- **SET-005:** Per-artifact terminal states survive partial success, cancellation, and interruption.
- **SET-006:** Failed/incomplete setup exposes exact retry and safe rollback guidance.
- **SET-007:** Policy may reject custom setup entrypoints or capabilities for direct/unverified
  sources.

### Security-assessment requirements

- **SEC-001:** The stdlib-only baseline must be deterministic, bounded, explainable, and available
  for every canonical artifact object.
- **SEC-002:** Assessments must bind to artifact, provider, provider-version, and ruleset digests;
  content/provider/rules changes make previous evidence stale.
- **SEC-003:** Status must distinguish `not-scanned`, `complete`, `partial`, `failed`, and `stale`
  coverage and `low`, `medium`, `high`, `critical`, or `unknown` installation risk.
- **SEC-004:** External analyzers run out of process through a versioned JSON contract and are never
  auto-installed or imported into the AART interpreter.
- **SEC-005:** Analyzer absence/failure reduces coverage but does not break dependency-free core
  operation unless explicit organization policy requires that evidence.
- **SEC-006:** Bundle summaries expose worst risk/severity, range, mean risk, finding counts, and
  coverage; install policy uses the worst result and unknown coverage rather than the average.
- **SEC-007:** Registry-published assessments are digest-bound evidence and inherit trust only from
  the registry/policy relationship.
- **SEC-008:** UI and JSON output must say “installation risk” or “assessment”, never “safe”.

### Reporting requirements

- **RPT-001:** Reporting is disabled when no destination is configured.
- **RPT-002:** A default/company registry may provide a policy-approved issue destination.
- **RPT-003:** Reports never route implicitly to an artifact upstream.
- **RPT-004:** Events remain versioned, allowlist-based, bounded, redacted, and independent per
  terminal artifact/setup result.
- **RPT-005:** Interactive reporting previews the exact payload and never blocks installation.
- **RPT-006:** Deployment policy supports disabled, prompt, or authenticated automatic submission.
- **RPT-007:** Registry-owned ingestion/dashboard workflows treat issue content as untrusted input.

## 12. TUI requirements

The TUI retains the existing persistent marketplace/cart model and adds source awareness:

1. How it works.
2. User or Maintainer.
3. Source marketplace and health.
4. Harness/profile.
5. Action.
6. Project or user-global scope.
7. Copy or Symlink.
8. Artifact basket.
9. Review.
10. Finalize and outcome.

Space toggles multi-selection, Enter advances, and Backspace returns one stage. Previous choices,
cursor position, scroll position, and valid basket items survive back navigation. The stepper marks
visited/current stages.

Artifact rows must show a one-line value description, source alias, trust class, compatibility, and
installed/update state. When evidence exists, they also show installation risk, maximum severity,
coverage, and staleness. Review must show qualified coordinates, versions/digests, source commits,
destinations, actual mode projection, setup effects, trust/security/policy warnings, and any policy
gate caused by unknown/high-risk content.

Successful no-op, offline last-known-good use, partial success, failure, cancellation, unsupported
selection, and pending retry must all produce explicit final feedback.

## 13. Trust, governance, and policy

Trust is calculated from local facts:

- organization policy may designate exact registry identities/URLs as company-reviewed;
- a registry may attest that an entry passed its review, but that does not make the registry itself
  organization-trusted;
- direct sources remain direct even when their own metadata claims otherwise;
- local sources are visibly mutable and cannot reuse a reviewed remote badge;
- changed registry URL/identity/provenance invalidates prior trust until reviewed.

Policy may constrain:

- allowed/denied Git hosts and repository prefixes;
- required or recommended registries;
- whether direct sources are permitted;
- whether public reporting destinations are permitted;
- setup capabilities/custom entrypoints;
- minimum source trust for user-global installation;
- permitted harness profiles and scopes.

AART configuration chooses among allowed options. It cannot override policy.

## 14. Success measures

AART 1.0 is successful when:

- the same CLI can use a public registry, a private company registry, direct repositories, or no
  registry without code changes;
- a native external artifact can be installed without copying it into the AART tool repository;
- a foreign upstream can be converted once, reviewed, and updated reproducibly;
- users can distinguish company-reviewed, registry-reviewed, direct, local, and unverified content;
- registry CI rejects incompatible, unlocked, non-deterministic, stale-conversion, or unsafe content;
- security evidence is current for the exact artifact digest, optional analyzers remain isolated,
  and bundles cannot hide a critical/unknown member behind a favorable average;
- deleting/recreating the AART Python environment leaves managed source objects and installed
  symlinks intact;
- existing 0.1.x projects have a tested migration and rollback path;
- local checkout and local-wheel installations behave identically at runtime.

Usage-report counts are optional operational signals, not release success criteria, because AART
must work without reporting or a registry.

## 15. Versioning and release policy

This redesign changes source resolution, package boundaries, manifests, state, TUI discovery, and
compatibility contracts. The target stable release is therefore `1.0.0`, not another `0.1.x` patch.

Implementation versions use `1.0.0a1`, `1.0.0a2`, and so on. The project must not publish/tag final
`1.0.0` until:

- protocol and artifact schema v1 are frozen;
- source/registry compatibility gates pass;
- 0.1.x migration and rollback pass;
- public reference registry CI passes;
- local editable and local-wheel smoke tests pass;
- no operational catalog is required beside the installed Python package.

CLI SemVer, protocol version, artifact schema version, artifact version, importer version, harness
profile version, and registry commit are independent identifiers. Compatibility is negotiated;
registries are not pinned to one exact AART patch release.

## 16. Migration and rollout

### Phase 0: design freeze

- Approve PRD/SPEC and vocabulary.
- Freeze new features based on the monolithic package-catalog assumption.
- Record 0.1.x manifest/catalog fixtures as migration inputs.

### Phase 1: protocol and compiler alpha

- Introduce protocol/artifact/config/index/lock schemas.
- Implement canonical source compilation and deterministic diagnostics.
- Version the package as `1.0.0a1` only when the alpha code lands.

### Phase 2: durable source store

- Add source configuration, Git mirrors, immutable snapshots, content-addressed objects, health,
  offline last-known-good behavior, and garbage-collection safety.

### Phase 3: installation and TUI migration

- Migrate Copy/Symlink/state/update/setup behavior to resolved source objects.
- Replace the package/default-catalog assumption with the configured source union.

### Phase 4: registry and importer workflows

- Add scaffold/validate/format/lock/build/audit/test/import/promote commands.
- Create the public reference registry at `M1F1/agent-artifacts-registry` only after its exact
  allowlisted export passes public-content, secret, license, provenance, and CI preflight checks.
- Provide a company registry bootstrap/template without confidential content.

### Phase 5: migration and release gates

- Migrate existing manifests and current repository artifacts with backup/rollback.
- Run minimum/latest compatibility matrices and local distribution smoke tests.
- Tag stable `1.0.0` only after every gate passes.

## 17. Product acceptance criteria

- [x] A user can install from multiple direct repositories without configuring a registry.
- [x] A user can combine direct sources with public, company, team, and private registries.
- [x] An organization can recommend or require a reviewed registry without making it mandatory for
      all AART deployments.
- [x] The marketplace exposes source/trust and blocks ambiguous unqualified identities.
- [x] A native registry reference does not duplicate artifact content.
- [x] A foreign upstream import produces committed, deterministic, provenance-complete canonical
      content before consumer installation.
- [x] AART compiles canonical packages into each supported harness without requiring import-time
      conversion.
- [x] Copy, managed Symlink, project/user scope, setup queue, and explicit outcomes work from the
      source union.
- [x] Reporting is optional and disabled without a configured destination.
- [x] Every artifact can receive a zero-dependency baseline assessment, while optional out-of-
      process analyzers add evidence without adding AART runtime dependencies.
- [x] Bundle risk reports worst/range/mean/coverage and policy never relies on the mean alone.
- [x] The CLI remains locally installable and is architecturally ready for later Nexus delivery.
- [x] The public reference registry and at least one private/company-style fixture pass the AART
      quality gate across the supported compatibility matrix.
- [x] Existing 0.1.x installations have a documented, tested migration and rollback path.

## 18. Resolved decisions

- The AART tool and operational registries are separate repositories.
- A registry is optional; `default_registry` is optional.
- Git/local repositories are the 1.0 source transport; a hosted registry API is not required.
- Native AART packages are preferred over conversion.
- Foreign conversion runs at maintainer/import time and materializes canonical output.
- Consumer installation never performs implicit foreign conversion.
- JSON is the protocol serialization format to preserve Python 3.10 stdlib-only runtime.
- Managed Symlink installs target immutable content and change only through explicit update.
- Usage reporting has no implicit destination and is disabled when unconfigured.
- Security status is evidence-based, digest-bound, optional-provider friendly, and never a “safe”
  certificate.
- The public reference-registry remote is `M1F1/agent-artifacts-registry` with `PUBLIC` visibility;
  SEP01 revalidates availability and publishes only an audited deterministic export.
- The release train uses `1.0.0aN` before stable `1.0.0`.
