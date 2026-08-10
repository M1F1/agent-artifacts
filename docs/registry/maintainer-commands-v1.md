# Registry maintainer commands v1

`aart registry` turns a local Git checkout into a canonical, reviewable AART registry. The command
boundary never commits or pushes. Maintainers review the resulting files and use their normal Git
workflow after the command succeeds.

## Command contract

| Command | Effect | Purpose |
|---|---|---|
| `init` | writes | Add protocol markers and the minimum/latest GitHub Actions workflow |
| `scaffold` | writes | Add one canonical native artifact manifest and starter payload |
| `format` | writes, or reads with `--check` | Canonicalize every managed JSON document |
| `validate` | reads | Validate protocol, compatibility, lock/index, native packages, and graph |
| `lock` | writes, or reads with `--check` | Resolve every approved native reference to an exact commit and digests |
| `build` | writes, or reads with `--check` | Compile the payload-free marketplace index from owned and locked artifacts |
| `audit` | reads | Check review, provenance, setup, license, and currently available risk evidence |
| `test` | reads | Validate the registry at its minimum and/or a supplied latest compatible version |
| `diff` | reads | Show deterministic canonical-format drift without changing the checkout |
| `migrate` | preview by default; writes with `--apply` | Convert a pinned 0.1.x catalog into a canonical registry |

Mutation requires a writable real directory containing `.git` (a directory or worktree gitfile).
Managed symlinks and special files are rejected. Writes use exact snapshot and per-file digest
preconditions, atomic replacements, post-write verification, and rollback on a partial failure.
Read-only commands work on a plain snapshot with no `.git` and do not require write permission.

`format --check`, `lock --check`, and `build --check` return `0` when generated content is current
and `1` when drift exists. They never apply their plan. Human output describes every changed path;
`--json` emits a stable operation, changed-path count, review digest, and diagnostics.

## Bootstrap and scaffold

Start from an empty Git checkout:

```console
git init company-agent-artifacts-registry
aart registry init --source company-agent-artifacts-registry \
  --source-id company-registry --display-name "Company Agent Artifacts"
```

The generated workflow checks out AART into an isolated `.aart-tool` directory and installs it from
that local checkout with `pip --no-deps`; it does not require PyPI or Nexus. `AART_REPOSITORY` and
`AART_REF` repository variables can select a reviewed company mirror/ref and otherwise default to
`M1F1/agent-artifacts` at `main`. It then runs format, strict/frozen validation, lock, build, audit,
and minimum/latest compatibility checks. The workflow has read-only repository permissions and
contains no commit or push step.

Create a package with an explicit compatibility and installation contract:

```console
aart registry scaffold --source company-agent-artifacts-registry skill review-python \
  --summary "Review Python changes against the company checklist." \
  --profile codex --profile tabnine --platform darwin --platform linux \
  --install-scope project --install-mode copy
```

The starter content is intentionally small. A maintainer must review the manifest and payload,
declare setup only through the native setup recipe protocol, and add honest license/provenance
metadata before relying on the audit result.

## Lock, build, and audit

Registry entries remain authored references to credential-free Git URLs. `lock` acquires each ref
through the bounded, hook-free Git snapshot adapter, verifies the referenced native package, and
records its resolved commit and content digests. `build` reacquires the sources, rejects any lock
mismatch, compiles registry-owned packages and references, and writes no payload bytes into
`aart.index.json`.

An entry whose review status is not `approved` cannot be locked and fails `audit`. Audit warnings
are evidence gaps, not installation-risk conclusions: missing license/provenance and absent
per-object assessment evidence are reported explicitly. The stdlib-only baseline is documented in
[`baseline-v1.md`](../security/baseline-v1.md); later security tasks wire assessment caches,
attestations, policy, and CLI commands into this existing registry command boundary.

## Migration

Migration always previews first. The input must be an immutable Git revision. A remote HTTPS Git
URL records its own origin; a local checkout additionally requires `--origin-url` so generated
provenance never invents or leaks a host path.

```console
aart registry migrate --legacy-source /path/to/legacy-checkout \
  --origin-url https://github.example/company/legacy-artifacts.git --ref main \
  --source /path/to/empty-registry --source-id company-registry \
  --display-name "Company Agent Artifacts" --profile tabnine

# After reviewing the paths and review digest:
aart registry migrate --legacy-source /path/to/legacy-checkout \
  --origin-url https://github.example/company/legacy-artifacts.git --ref main \
  --source /path/to/empty-registry --source-id company-registry \
  --display-name "Company Agent Artifacts" --profile tabnine --apply
```

The destination must contain no managed registry files. Migration emits canonical packages,
collections, provenance, registry markers, and the CI workflow; it deliberately does not create a
lock or index. Run `lock` and `build` after reviewing any authored external entries.
