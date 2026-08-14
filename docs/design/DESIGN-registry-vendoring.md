# Design: registry vendoring

A registry maintainer can take content from a repository that knows nothing about AART, wrap it into
a canonical package inside their own registry, record verifiably where it came from, and refresh it
when upstream moves.

Companion to [the registry protocol](../protocol/registry-v1.md) and
[the native source protocol](../protocol/native-source-v1.md). Successor in intent — not in
mechanism — to the removed `aart upstream import` design,
[DESIGN-upstream-import.md](DESIGN-upstream-import.md).

## 1. The barrier this removes

AART already has one way to put foreign content in a registry: `registry promote-native`. It records
a pin — origin URL, requested ref, resolved commit, package path, and three digests — into
`aart.lock.json`, and writes nothing else. Three files change and no payload is copied
(`registry_maintenance/planning.py:729`).

That mechanism has a precondition most repositories cannot meet. `_acquired_package` calls
`load_native_source` on the upstream snapshot (`registry_maintenance/planning.py:330`), so the
foreign repository must already declare `aart-source.json`, expose `artifact_roots`, and hold a
valid `artifact.json` at exactly `<root>/<kind>/<name>`. A repository that merely *contains* useful
content — a monorepo of MCP servers, a team's collection of prompts, a vendor's reference
implementation — is refused.

The consequence is that AART's answer to "I want this thing in my registry" is "first convince its
author to restructure their repository for me." For MCP servers in particular that is not an answer.
Nobody restructures their repository to suit a consumer's packaging format.

There is a second consequence, which is what surfaced this design. A promoted artifact's payload
stays upstream: at install time the consumer clones the foreign repository itself, pinned to the
locked commit (`consumer/runtime.py:519`). So every consumer needs read access to every upstream
repository, not just to the registry. On a private GitHub Enterprise host, where the registry and
the content it references routinely live under different teams with different permissions, that
turns a registry into a list of things most of its users cannot install.

Vendoring answers both with one change: **AART's shape lives in the registry, not in the foreign
repository, and the bytes come with it.**

## 2. The protocol already supports this

This design adds commands. It does not revise a protocol, a schema, or an on-disk format, because
the format for exactly this case already exists and is already enforced end to end.

A canonical package may carry `provenance.json`. The native source protocol describes it as binding
"the canonical copy to a credential-free Git URL, a lowercase 40-hex commit, input digest, importer
ID/SemVer, options digest, and reviewable warnings" — that sentence describes a vendored artifact.
The model is `Provenance(origin: OriginProvenance, importer: ImporterProvenance, warnings)`
(`protocol/native_models.py:116`).

Everything downstream of it is already wired:

- `index_artifact_from_package` projects package provenance into `IndexProvenance` — its docstring
  already says "owned **or acquired**" (`protocol/registry_index.py:29`)
- the security baseline cross-checks the package's `provenance.json` against the index and raises
  `provenance-missing`, `provenance-unexpected`, `provenance-index-mismatch`, and `importer-warning`
  (`security/baseline.py:525`)
- the installer refuses provenance whose origin is not credential-free Git
  (`installation/application.py:1148`)

So a vendored artifact is not a new kind of thing. **It is an owned package that carries
`provenance.json`.** What is missing is the command that produces one from a repository that does
not speak AART.

This is why the release is a minor and why the compatibility story is short: a registry containing
vendored artifacts is a registry containing owned artifacts, readable by any AART that reads owned
artifacts today.

## 3. What vendoring moves, and who becomes responsible

Vendoring changes who is in the trust path, and the design is only honest if it says so plainly.

| | `promote-native` | `vendor` |
|---|---|---|
| Where the payload lives | upstream repository | the registry repository |
| Who the consumer must reach | registry **and** upstream | registry only |
| Who owns `artifact.json` | upstream author | registry maintainer |
| Who owns the version | upstream author | registry maintainer |
| Who can alter the delivered bytes | upstream author | registry maintainer |
| What upstream must look like | a valid AART source | anything |

The last two rows are the trade. A referenced artifact is tamper-evident against its upstream by
construction: the consumer fetches from upstream and verifies. A vendored artifact is distributed by
the registry, so the registry maintainer *can* alter it. That is not a flaw to be engineered away —
it is the same property that lets the maintainer add a wrapper at all, and it is the property that
makes a single access point possible.

### The maintainer is the boundary

The rule this design commits to:

> Strictness moves from the foreign repository's structure to the maintainer's judgement. AART's job
> is to make that judgement **informed, recorded, and reviewable by other people** — not to pretend
> it can be automated.

Two things follow, and both are load-bearing.

**AART must not imply that a vendored artifact is safe because it vendored cleanly.** A successful
`vendor` means the bytes were copied and pinned, nothing more. Every surface that reports on a
vendored artifact says where it came from and what the assessment found; none of them says
"verified" or "trusted". The `security` command already carries this framing in its own help —
"Assessments reduce uncertainty; they are not safety guarantees" — and vendoring adopts it verbatim.

**The failure mode this design accepts is a maintainer who vendors without thinking.** That risk is
real and cannot be removed, only made expensive to walk into. So the review is not a formality: it
is where the assessment is presented, and the maintainer cannot finalize without seeing it.

### The tools the maintainer already has

AART has a substantial zero-dependency assessment engine that the vendoring flow should use rather
than reinvent. `assess_installation_risk` (`security/baseline.py:1001`) runs eight rule families over
an immutable object with no IO, network, or process execution, and among its rules are precisely the
ones a maintainer vendoring an MCP server needs to see:

| Rule | Why it matters when vendoring |
|---|---|
| `embedded-credential` | a token committed upstream would be copied into your registry |
| `unpinned-package-install` | the setup installs whatever `latest` means on the day a user runs it |
| `mcp-shell-dispatch` | the MCP server dispatches through a shell |
| `shell-pipe-to-interpreter` | classic `curl … \| sh` in an install script |
| `shell-privilege-escalation`, `shell-destructive-broad-path` | what the wrapper's script will do |
| `python-dynamic-execution`, `python-os-system`, `python-unsafe-deserialization` | what the payload does at runtime |
| `custom-setup-entrypoint` | flags *your own* `install.sh`, so the wrapper is assessed too |

The last row matters. The maintainer's own wrapper is not exempt from the assessment — it is scanned
with the payload, because the wrapper is usually where the dangerous part is.

**The change:** the vendor review renders this assessment inline and refuses to finalize without an
approved review record, the same gate `promote-native` already applies
(`registry_maintenance/planning.py:643`). The assessment is stored with the artifact, so a second
maintainer reviewing the pull request sees what the first one saw.

## 4. Versioning: the registry owns the version, and must say so

`refresh-native` gets a new version for free, because upstream's `artifact.json` declares one. A
vendored artifact has no such declaration — upstream may have no version at all, or a version scheme
that means nothing in AART's SemVer contract.

Deriving one would be a guess presented as a fact. So:

**`--version` is required on vendor, and required again on re-vendor whenever the payload digest
changed.** The review states the upstream movement — `a1b2c3 → d4e5f6`, N files added/changed/removed
— and the maintainer supplies the version that movement deserves. If the payload digest is unchanged,
re-vendor is a no-op and says so.

This makes vendored refresh exactly one human decision slower than `refresh-native`. That is the
correct cost: the person who did not write the code is the person claiming the compatibility.

## 5. Subsetting: what may be taken, and what fails closed

The acquisition takes a subtree of an upstream snapshot — `--path servers/foo` — rather than a whole
repository. Everything AART already applies to a source snapshot applies here: `SnapshotLimits`
bounds files, per-file bytes, total bytes, and depth (`sources/model.py:75`); paths are
`SafeRelativePath`; the URL must be credential-free (`configuration/model.py:254`); Git runs with a
cleared environment and no hooks (`io/git.py:17`).

Two additional rules, both failing closed:

1. **A symlink whose target leaves the taken subtree is refused**, naming the link and its target. It
   is not silently dropped and not silently followed: dropping it produces a package that is quietly
   incomplete, and following it copies content the maintainer did not review.
2. **A subtree that would produce an empty package is refused.** A typo in `--path` must not produce
   a valid, empty, vendored artifact.

Executable bits are preserved, because an install script that arrives non-executable is a defect the
maintainer will debug at the wrong layer.

## 6. Drift: a vendored copy must not go stale in silence

A pin cannot rot; a copy can. Once vendored, the registry's copy and upstream diverge with no signal.

`registry revendor <kind> <name>` re-resolves the recorded `origin.url` at the recorded ref and
reports one of three dispositions, reusing the shape `check_native_reference` already establishes
(`registry_maintenance/planning.py:739`):

- `up-to-date` — the upstream subtree digest equals `origin.input_digest`
- `changed` — it moved; the review shows the diff and requires `--version`
- `unreachable` — upstream could not be read; this is reported, never treated as up-to-date

`registry audit` gains the same check in read-only form, so CI can report "3 vendored artifacts are
behind upstream" without mutating anything. Unreachable upstreams are reported as unknown rather than
as drift, because a maintainer who loses access to an upstream must not be told their copy is fine.

## 7. Licensing

Vendoring copies someone else's work into a repository that will redistribute it. `ArtifactManifest`
already has a `license` field (`protocol/native_models.py:93`), informational and trust-free.

The vendor review reports any license file discovered in the taken subtree and pre-fills the
manifest's `license` from it when it is unambiguous. `registry audit` raises a finding for a vendored
artifact with no license recorded. Neither refuses: AART is not qualified to adjudicate a license,
and a maintainer vendoring internal company code has nothing to record. The obligation is to make the
omission visible, not to block on it.

## 8. Why a separate verb, not a flag on `promote-native`

`promote --vendor` would read as a variation. §3's table shows six properties differing between the
two modes, including who owns the version and who can alter the delivered bytes. A flag that changes
who is in the trust path is a flag that will be passed without noticing.

So: `registry vendor` and `registry revendor` stand beside `registry promote-native` and
`registry refresh-native`, and `registry --help` states the distinction in one line each. The
vocabulary is already committed: the plan for `SI-9` names vendoring as the supported way to depend
on foreign content, which is currently a documented route with no implementation. This design is what
makes that sentence true, and `SI-9` should not ship its protocol text before it.

## 9. Relationship to the removed importer

`DESIGN-upstream-import.md` described this workflow for the pre-`2.0.0` catalog model: scan a GitHub
repository, select candidates, "vendor them into the catalog, track their upstream origins." The
intent was right and is preserved here. The mechanism is not, and the differences are deliberate:

| | removed importer | this design |
|---|---|---|
| Transport | GitHub REST API | Git, the same path every source uses |
| Hosts | GitHub, via `GITHUB_API_URL` | any credential-free HTTPS/SSH Git host |
| Credentials | `GITHUB_TOKEN` in the environment | none; system Git's own configuration |
| Target | `catalog` + `upstreams.json` | a registry, `artifacts/` + `provenance.json` |
| Mutation | direct | review-first, `--yes` to finalize |
| Discovery | heuristic scanning of a whole repo | one explicit `--path` per invocation |

The credential difference is the important one. `agent_artifacts/io/net.py` still contains the
importer's token handling — `GITHUB_TOKEN`, `GITHUB_API_URL`, and a hint about GitHub Enterprise and
`/api/v3` — and is imported by nothing but its own test. It advertises a capability the product does
not have. **It is removed as part of this work.** AART reaches Git through system Git and holds no
token; a private GitHub Enterprise origin is reached with an SSH key or a Git credential helper,
because `HOME` and `SSH_AUTH_SOCK` are the only relevant variables the subprocess receives.

Batch discovery — "scan this repo and show me candidates" — is deliberately not revived here; see
§10.

## 10. Non-goals

- **No batch or heuristic discovery.** One `vendor` invocation takes one explicit subtree to one
  explicit identity. Guessing which parts of a foreign repository are artifacts is how the removed
  importer produced results a maintainer had to audit line by line. If it returns, it returns as an
  orchestration layer over this primitive, never as a replacement for it.
- **No upstream version detection.** No parsing of `package.json`, `pyproject.toml`, or tags to guess
  a version. §4.
- **No automatic re-vendoring.** No command re-vendors on a schedule or in CI without a human
  supplying a version. Drift is *reported* automatically; adopting it is not.
- **No credential handling.** No token field, no `--token`, no environment token. §9.
- **No protocol, schema, or on-disk format revision.** §2.
- **No change to `promote-native`.** Both modes remain, and a registry may use both.

## 11. Acceptance criteria

1. `registry vendor <kind> <name> --url <git> --ref <ref> --path <dir> --version <semver>` produces a
   canonical owned package under `artifacts/<kind>/<name>/` carrying a valid `provenance.json`,
   from an upstream repository containing no AART markers whatsoever.
2. Without `--yes` it writes nothing, and the review states origin, resolved commit, taken subtree,
   file count, license finding, and the full baseline assessment.
3. `--yes` refuses without an approved review record, matching `promote-native`'s existing gate.
4. The resulting registry passes `registry validate --strict --frozen`, `lock`, `build`, and `audit`
   with no change to those commands' contracts.
5. A consumer installs the vendored artifact with access to **the registry only**, and never contacts
   the upstream origin.
6. The baseline assessment covers the maintainer's own wrapper: a planted `curl … | sh` in the added
   `install.sh` appears in the review as `shell-pipe-to-interpreter`.
7. A symlink escaping the taken subtree refuses the vendor with a diagnostic naming the link and its
   target; an empty result refuses naming the path.
8. `revendor` reports `up-to-date` when the upstream subtree digest is unchanged, `changed` with a
   file-level diff when it moved, and `unreachable` when upstream cannot be read — never conflating
   the third with the first.
9. `revendor` on changed content refuses to finalize without an explicit `--version`.
10. `registry audit` reports vendored artifacts behind upstream, and reports a vendored artifact with
    no recorded license, without failing the audit for either on its own.
11. A vendored artifact's `provenance.json` verifies independently: re-running the same acquisition
    against the recorded commit and path reproduces `origin.input_digest`.
12. `agent_artifacts/io/net.py` is gone, and no surface in the package mentions `GITHUB_TOKEN` or
    `GITHUB_API_URL`.
13. `2.0.0`–`2.2.x` AART reads a registry containing vendored artifacts without modification, since
    they are owned packages.
