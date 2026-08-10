# Canonical Maintainer curation TUI v1

TUI03 adds a typed AART 1.0 Maintainer path without removing the 0.1.x catalog compatibility
workflow. A checkout containing `aart-registry.json`, or an otherwise empty Git checkout selected
for initialization/import, enters canonical curation. A legacy catalog with `skills/`,
`guidelines/`, `upstreams.json`, or the other legacy roots continues through the established
upstream wizard.

## Boundaries

The canonical path accepts only an explicit normalized absolute workspace. Every mutating preview
first proves that it is a writable real Git checkout (`.git` may be a directory or worktree file).
Symlinked/special managed paths are rejected by the registry workspace adapter. Read-only
validate, audit, and diff can inspect an inert snapshot without `.git`.

The path imports no consumer installation, state, reference-store, or content-addressed-store
writer. Its output port can write only canonical registry managed paths. There is no commit, push,
pull-request, or credential-writing operation. Git publication remains a separate maintainer
choice after reviewing the working tree.

## Actions

The action selector exposes:

- **Init** — initialize an empty registry checkout and minimum/latest CI template;
- **Scaffold** — generate one native artifact manifest and starter payload;
- **Promote native** — acquire one credential-free Git URL/ref, validate its canonical package,
  and review the entry/lock/index projection;
- **Import foreign** — pin a legacy Git input and run the closed `legacy-catalog-v1` converter into
  an otherwise empty registry checkout;
- **Update upstream** — reacquire one existing approved native entry and produce an up-to-date or
  changed entry/lock/index plan;
- **Lock / Build** — acquire approved references, resolve committed lock evidence, and compile the
  payload-free index;
- **Validate** — show protocol, compatibility, generated-evidence, and graph checks;
- **Audit** — show review, provenance, setup, license, and available installation-risk evidence;
- **Diff** — show canonical-format drift without applying it;
- **User workflows** — return to the shared consumer marketplace.

The current closed importer is intentionally narrow. Its review always names
`legacy-catalog-v1`, includes deterministic importer/artifact warnings, and asks the maintainer to
inspect every normalized file. Arbitrary repository conversion and consumer-time import are not
supported.

## Review and Finalize

Preparation produces an immutable `CurationReview`. Workspace plans reuse their canonical review
digest. Native promotion/update plans reuse the registry-input mutation digest. Read-only reviews
derive a digest from the exact source snapshot, action, checks, diff, and warnings.

Review displays:

- absolute checkout;
- mutating versus read-only status;
- exact snapshot and review digest;
- each added/changed/unchanged managed path;
- named quality checks and diagnostics;
- audit/security and conversion limitations;
- the fact that AART will not commit or push.

Back returns to the applicable details/action stage with entered values and basket state intact.
An unchanged form reuses the prepared plan; changing a value invalidates it. Quit, Back, a failed
preview, or a declined confirmation applies nothing. Curses collects role/source/action in the
full-screen selector, tears it down, and then uses the same line-oriented detail/review service so
network and filesystem output remains visible.

Finalize accepts only the shown digest. Workspace changes, native registry-input changes, and
read-only snapshot changes are detected as stale. The filesystem adapter uses exact prior file
digests, an exclusive checkout lock, atomic replacements, post-write verification, and rollback
on partial failure.

## Outcomes and recovery

Outcomes distinguish:

- changed managed paths;
- a successful mutation no-op (including an already-current upstream);
- a completed read-only action;
- failed validate/audit checks with no writes;
- canonical drift observed by diff while zero paths were changed.

Every mutation prints commands equivalent to:

```sh
git -C /absolute/registry diff -- <reviewed-paths>
aart registry validate --source /absolute/registry --strict
aart registry audit --source /absolute/registry
```

Paths are shell-quoted by the runtime. Init, scaffold, and foreign import first suggest non-strict
validation followed by lock/build; actions that already produce generated evidence suggest strict
validation. A failed Finalize keeps the remediation visible and directs the maintainer to rerun the
same action; it never substitutes a new unreviewed plan.
