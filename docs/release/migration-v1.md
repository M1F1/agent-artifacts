# Migrating from AART 0.1.x to 1.0.0

> **Historical record — not a supported route on AART 2.0.0 or later.**
>
> Every command on this page was removed in `2.0.0`: `migrate`, `list`, `install`, `status`,
> `check`, `update`, `uninstall`, `setup`, `upstream`, and `registry migrate`. The 0.1 boundary is
> now refused rather than converted. A retired 0.1 state file is rejected at the boundary with one
> diagnostic naming the only supported move — remove the retired state and reinstall from a
> configured canonical source with `aart marketplace install`.
>
> The page is kept because it is the released evidence for `1.0.0`, and released evidence is never
> rewritten. Read it as a record of what `1.0.0` did, not as instructions. If you are still on
> 0.1.x, the supported path is to migrate under a `1.x` executable first, or to reinstall from a
> canonical source under `2.0.0`.

AART `1.0.0` separates the executable from operational artifact sources. Migration is explicit,
preview-first, backup-backed, and reversible; it never guesses between colliding source identities.

## 1. Install the 1.0.0 executable locally

Use a reviewed checkout or wheel. No package index is required:

```shell
python -m pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts
# or
python -m pip install --no-index --no-deps /path/to/agent_artifacts-1.0.0-py3-none-any.whl
```

Removing the old Python environment does not remove managed source snapshots or content-addressed
objects. An existing managed Symlink remains bound to its immutable object.

## 2. Configure canonical sources

Open `aart`, use the Sources stage, and add the direct repositories and optional registries that
own your artifacts. The public reference registry is optional. A company policy may recommend or
require a private reviewed registry.

Legacy `--source`/`--repo` remains a disclosed 0.1.x compatibility path during the transition; it
never becomes an implicit registry or silently resolves an ambiguous artifact.

## 3. Migrate installed state

Run the command in the affected project, or select user scope explicitly. Preview first:

```shell
aart migrate state --from 0.1 --scope project --dry-run
aart migrate state --from 0.1 --scope project --apply
```

If the same legacy identity exists in more than one configured source, add an explicit mapping:

```shell
aart migrate state --from 0.1 --scope project \
  --source-map skill/code-review@claude=company --dry-run
```

The applied operation writes canonical state v2 only after effect/source evidence is complete. It
keeps an exact deterministic backup and durable review-bound journal. To restore the exact 0.1.x
bytes in a later process:

```shell
aart migrate state --from 0.1 --scope project --rollback
```

User-global migration uses `--scope user`. A failed/interrupted apply preserves or compensates to a
complete side; an incomplete rollback keeps its recovery evidence and command.

## 4. Curate a legacy catalog

Maintainers convert foreign 0.1.x catalog content into canonical packages in an explicit writable
registry checkout:

```shell
aart registry migrate --legacy-source /path/to/legacy-catalog \
  --origin-url https://github.com/example/catalog.git --ref <40-hex-commit> \
  --source /path/to/registry --source-id company --display-name "Company artifacts" \
  --artifact-version 1.0.0 --license INTERNAL --dry-run
```

Review the deterministic diff and warnings, rerun with `--apply`, then run registry format,
validate, lock, build, audit, and compatibility checks. Consumer installation never performs this
conversion implicitly.

## 5. Verify and recover

After migration, run `aart status`, `aart check`, and a reviewed `aart update`. Use `aart uninstall`
only after verifying the canonical subscription and effects. Backups and migration journals remain
recovery evidence; cleanup is an explicit retention decision.
