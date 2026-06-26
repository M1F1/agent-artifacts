# agent-artifacts - Design: batch upstream import

Companion to [DESIGN-upstream.md](DESIGN-upstream.md) and
[DESIGN-frictionless-adoption.md](DESIGN-frictionless-adoption.md).

This document specifies a maintainer workflow for importing many artifacts from one GitHub
repo or subdirectory, selecting the desired candidates, vendoring them into the catalog,
tracking their upstream origins, and optionally creating or updating a bundle.

The existing `aart upstream add <type/name> <url>` remains the primitive for one artifact.
Batch import is an orchestration layer over the same safety model: upstream repos are never a
consumer install source; they are scanned by catalog maintainers, copied into this reviewed
catalog, and then installed by consumers from the catalog.

---

## 1. Goals

Maintainers should be able to do this:

```sh
aart upstream import https://github.com/org/superpowers/tree/main \
  --bundle superpowers \
  --interactive
```

and get a curated result:

```text
skills/debugging/
skills/refactoring/
memory/superpowers.md
mcp/github/mcp.json
bundles/superpowers.json
upstreams.json
```

without hand-running `aart upstream add ...` for every GitHub URL.

**In scope**

- Scan a GitHub repo or subdirectory once and discover candidate artifacts.
- Support two discovery modes:
  - **manifest mode** for repos that declare their artifacts explicitly;
  - **heuristic mode** for ordinary repos with no manifest.
- Present candidates for review in a stable textual output, JSON output, and later an
  interactive picker.
- Vendor selected artifacts into the correct catalog destinations.
- Write or update matching `upstreams.json` entries.
- Create or update a bundle containing the selected imports.
- Support `--dry-run`, `--json`, `--force`, and source path/ref overrides.

**Out of scope**

- Consumer installs directly from many upstream repos.
- Automatic trust or execution of upstream code.
- Dependency solving between artifacts.
- Automatic PR creation.
- Non-GitHub providers in the first implementation.
- Perfect classification of arbitrary markdown without maintainer confirmation.

## 2. Command surface

Two commands are introduced:

```sh
aart upstream scan <github-url> [--mode auto|manifest|heuristic] [--json]

aart upstream import <github-url>
  [--mode auto|manifest|heuristic]
  [--bundle NAME]
  [--bundle-description TEXT]
  [--bundle-mode append|replace|fail]
  [--select type/name[,type/name...]]
  [--interactive]
  [--dry-run]
  [--force]
  [--json]
```

`scan` is read-only. It resolves the URL, lists candidates, and reports validation problems.

`import` vendors selected candidates into the catalog, updates `upstreams.json`, and optionally
writes a bundle.

`--mode auto` is the default:

1. Look for an import manifest at the scan root.
2. If present and valid, use manifest mode.
3. If absent, use heuristic mode.
4. If present but invalid, fail instead of silently falling back to heuristics.

`--source DIR` keeps its existing maintainer meaning: the catalog repo to modify, defaulting to
the current working directory. The GitHub URL names the upstream repo to scan.

## 3. Shared model

The scanner produces immutable candidate records before any files are written:

```python
ImportCandidate(
    key=UpstreamKey(type="skill", name="debugging"),
    source=UpstreamSource(kind="github", repo="org/superpowers", ref="main", path="skills/debugging"),
    detected_by="manifest" | "heuristic",
    confidence="explicit" | "high" | "medium" | "ambiguous",
    upstream_kind="tree" | "file",
    local_destination="skills/debugging",
    descriptor_path=None,
    title=None,
    description=None,
    warnings=(),
)
```

Candidate keys use the existing `<type>/<name>` contract. Candidate validation reuses the
existing catalog parsers:

- `skill`: directory containing `SKILL.md`;
- `hook`: directory containing `hook.json`;
- `mcp`: JSON file with `name` and `server`, or directory containing `mcp.json` or
  `<name>.json`;
- `memory`: markdown file accepted by the memory parser;
- `guideline`: markdown file accepted by the guideline parser.

The importer also produces a pure plan before it performs writes:

```python
ImportPlan(
    candidates=(...),
    actions=(CopyTree(...), WriteFile(...), WriteFile(upstreams.json), WriteFile(bundle.json)),
    bundle=Optional[Bundle],
    warnings=(...),
    conflicts=(...),
)
```

The command shell executes the existing actions through the existing executor where possible.
The upstream tracking write should remain atomic and last, as in `upstream add`, so a partial
vendor operation does not create tracking metadata for content that was not written.

## 4. Manifest mode

Manifest mode is for repos maintained with `agent-artifacts` consumption in mind. It avoids
guessing.

### 4.1 Manifest location

The scanner looks for these files at the scan root, in order:

```text
agent-artifacts.import.json
.agent-artifacts/import.json
```

The first found file wins. A command flag can later add `--manifest PATH`, but the initial
contract can keep locations fixed.

### 4.2 Manifest schema

Draft schema:

```json
{
  "version": 1,
  "artifacts": [
    {
      "type": "skill",
      "name": "debugging",
      "path": "skills/debugging",
      "description": "Debugging workflow"
    },
    {
      "type": "memory",
      "name": "superpowers",
      "path": "memory/superpowers.md"
    },
    {
      "type": "mcp",
      "name": "github",
      "path": "mcp/github"
    }
  ],
  "bundles": [
    {
      "name": "superpowers",
      "description": "Imported superpowers kit",
      "includes": {
        "skills": ["debugging"],
        "memory": ["superpowers"],
        "mcp": ["github"]
      }
    }
  ]
}
```

Required artifact fields: `type`, `name`, `path`.

Optional artifact fields:

- `description`: display only, not a catalog schema field for all types.
- `bundle`: one bundle name to include this artifact in.
- `rename_to`: a catalog-local name if the upstream descriptor name should remain untouched.

The MVP should avoid `rename_to` unless tests prove the naming flow is ready. The simpler rule
is: the manifest `name` must match the artifact's declared name where the parser can see one.

### 4.3 Validation rules

Manifest mode is strict:

- invalid JSON is a usage error;
- unknown `version` is a usage error;
- unknown artifact `type` is a usage error;
- duplicate `type/name` entries are a usage error;
- paths must be relative, normalized, and stay inside the scanned root;
- each candidate must parse as its declared type;
- source shape must match type rules;
- bundle references must point to selected or declared artifacts.

This strictness is valuable because manifest mode is meant to be automation-friendly.

### 4.4 Selection

If `--select` is omitted, manifest mode selects every valid artifact in the manifest. If the
manifest declares bundles and the CLI passes `--bundle NAME`, the importer may either:

- use the manifest bundle named `NAME` as the selected set, if present;
- or create/update a local catalog bundle with the selected artifacts.

The first implementation should keep this simple:

- `--select` narrows artifacts by `type/name`;
- `--bundle NAME` controls the local catalog bundle to write;
- manifest-declared bundles are scanned and reported, but do not automatically change
  selection until a follow-up work package adds that behavior.

## 5. Heuristic mode

Heuristic mode is for arbitrary repos. It should help maintainers quickly find candidates but
must be honest about ambiguity.

### 5.1 Discovery rules

The scanner recursively walks the requested GitHub tree, ignoring:

- `.git/`;
- `node_modules/`;
- `.venv/`, `venv/`;
- `dist/`, `build/`, `target/`;
- paths larger than a configurable scan size limit;
- hidden directories except `.agent-artifacts/`.

Candidate detection:

| Pattern | Candidate type | Confidence |
| --- | --- | --- |
| `*/SKILL.md` with valid skill frontmatter | `skill` | high |
| `*/hook.json` with valid hook descriptor | `hook` | high |
| `*/mcp.json` with valid MCP descriptor | `mcp` directory | high |
| `*/<dirname>.json` with valid MCP descriptor | `mcp` directory | medium |
| `*.json` with valid MCP descriptor | `mcp` file | high |
| `memory/*.md`, `memories/*.md`, `context/*.md` | `memory` | medium |
| `guidelines/*.md`, `rules/*.md`, `docs/guidelines/*.md` | `guideline` | medium |
| other markdown with compatible frontmatter | ambiguous markdown | ambiguous |

The scanner should not classify generic `README.md` files as artifacts unless a manifest names
them or explicit frontmatter marks them.

### 5.2 Name derivation

Name precedence:

1. Parser-declared `name` field if present.
2. Directory basename for tree artifacts.
3. File stem for file artifacts.
4. User override in interactive mode.

For MCP directory artifacts, the descriptor's `name` wins over the directory basename, but the
candidate warns if they differ.

### 5.3 Ambiguity

Heuristic mode reports ambiguous candidates but does not import them in non-interactive mode
unless `--select` names them with an explicit type.

Interactive mode can show actions per ambiguous candidate:

```text
[ ] docs/prompting.md            markdown      ambiguous
    choose: memory | guideline | skip
```

Non-interactive behavior:

- high confidence candidates may be selected by default;
- medium confidence candidates are selected by default only if under a strong type directory;
- ambiguous candidates are skipped with warnings;
- `--json` includes skipped/ambiguous records so automation can decide what to do next.

### 5.4 Conflict handling

Heuristic mode often finds names that collide with local catalog artifacts. Import should fail
on collisions unless `--force` is set. Interactive mode can offer per-candidate choices:

- skip;
- replace existing catalog artifact and tracking entry;
- rename local catalog artifact.

The first implementation should support skip and replace. Rename can be planned as a follow-up
because it touches parser name checks, bundle includes, and upstream tracking keys.

## 6. Bundle creation

`--bundle NAME` creates or updates `bundles/<name>.json`.

Default bundle behavior:

```text
--bundle-mode append
```

Modes:

- `append`: preserve existing description, extends, pins, and includes; add selected artifacts
  if absent;
- `replace`: overwrite includes with exactly the selected artifacts, preserve description only
  if `--bundle-description` is omitted;
- `fail`: error if `bundles/<name>.json` already exists.

If the bundle does not exist, it is created:

```json
{
  "name": "superpowers",
  "description": "Imported superpowers kit",
  "includes": {
    "skills": ["debugging", "refactoring"],
    "memory": ["superpowers"],
    "mcp": ["github"]
  }
}
```

No pins are added by default. Upstream tracking already records the source commit and content
hash. Bundle pins retain their existing meaning and can remain a separate maintainer choice.

## 7. Output

Human `scan` output should group candidates by type:

```text
skill
  [high] debugging      skills/debugging
  [high] refactoring    skills/refactoring

memory
  [medium] superpowers  memory/superpowers.md

ambiguous
  [ambiguous] prompting docs/prompting.md  choose memory/guideline or skip
```

`--json` output should be stable and scriptable:

```json
{
  "mode": "heuristic",
  "repo": "org/superpowers",
  "ref": "main",
  "scan_root": "",
  "candidates": [
    {
      "key": "skill/debugging",
      "path": "skills/debugging",
      "confidence": "high",
      "selected_by_default": true,
      "warnings": []
    }
  ],
  "warnings": []
}
```

Dry-run import output should include:

- selected candidates;
- files/directories that would be written;
- upstream entries that would be created or replaced;
- bundle file changes;
- skipped ambiguous candidates;
- conflicts.

## 8. Safety and idempotency

- Import never executes upstream code.
- Import validates every candidate before writing it.
- Import refuses to write outside the catalog root.
- Import writes tracking metadata last.
- Re-running the same import should be idempotent when upstream content is unchanged.
- `--force` is required to replace an existing local artifact or existing tracking entry.
- Existing bundles are appended to without duplicating includes.
- Invalid manifest mode fails fast; heuristic mode may continue around invalid candidates with
  warnings.

## 9. Relationship to existing commands

`upstream import` should reuse these existing components wherever possible:

- GitHub URL parsing from `github_source.py`;
- upstream source resolution and hashing from `upstream_source.py`;
- catalog parsing and validation from `catalog.py` and `source.py`;
- destination rules from `upstream add`;
- tracking schema from `upstreams.py`;
- tree/file write actions from `upstream_planner.py` and `executor.py`;
- bundle parsing from `catalog.parse_bundle`.

`upstream add` remains useful for one-off precise adoption. `upstream import` should not fork
the metadata format or create a second kind of tracking entry.

## 10. Open questions

1. Should manifest bundles influence selection in v1, or only be reported?
2. Should heuristic mode default-select medium-confidence markdown candidates?
3. Should interactive mode be text-only first, with curses/TUI as a later enhancement?
4. Should `rename_to` be supported in manifest mode immediately, or deferred until rename
   semantics are designed for descriptors whose internal `name` must match the catalog key?
5. Should raw GitHub URLs be accepted as file-only imports in the same workstream?
