# Native source protocol v1

A native AART source is an acquired repository tree whose root contains `aart-source.json`.
Artifact discovery is deliberately limited to the manifest's explicit `artifact_roots`; AART does
not crawl arbitrary repository layouts during consumer installation. A foreign layout must be
re-authored as a native source before it becomes a consumer input; AART does not convert legacy
catalogs at runtime.

The executable reference fixture is
[`tests/fixtures/protocol/native-source-v1`](../../tests/fixtures/protocol/native-source-v1). It
contains one canonical skill, optional import provenance, and one collection.

## Source document

`aart-source.json` declares schema/protocol version 1, a stable lowercase `source_id`, a display
name, half-open AART compatibility bounds, required compiler capabilities, one or more artifact
roots, and optional collection roots. A source never declares its own trust class. Unknown fields
fail unless they use an explicitly supported lowercase namespaced extension such as
`com.example.channel`.

## Canonical artifact package

Every package lives at `<artifact-root>/<type>/<name>/` and contains `artifact.json` plus a
`payload/` directory. The path identity and manifest identity must agree. Supported protocol-v1
payloads are:

| Type | Format | Required payload |
|---|---|---|
| `skill` | `aart-skill-v1` | `payload/SKILL.md` plus optional supporting files |
| `guideline` | `aart-guideline-v1` | exactly one Markdown document |
| `memory` | `aart-memory-v1` | exactly one Markdown document |
| `mcp` | `aart-mcp-v1` | strict JSON object at `payload/mcp.json` |
| `hook` | `aart-hook-v1` | strict JSON object at `payload/hook.json`, plus optional resources |

The manifest also requires a one-line summary, SemVer, explicit profile/platform compatibility,
install scopes/modes/effects, and an optional package-relative setup recipe. It may declare
`requires_aart` as a half-open executable-version range. This bound is artifact-local and opt-in:
omitting it adds no restriction, and maintainers raise it only when the artifact actually depends
on newer executable behavior. A routine AART release never changes it automatically. Optional
authors, license, and HTTPS homepage fields are informational only and never assign trust.

## What installation delivers

A package is not shipped to the consumer; the effects its type declares are applied. For four types
the whole payload arrives, and for one it does not:

| Type | Effects | What reaches the consumer | May the payload be referenced? |
|---|---|---|---|
| `skill` | `copy-tree` | the whole payload tree | yes, it is on disk |
| `guideline` | `write-file` | the one Markdown document | that is the whole payload |
| `memory` | `write-file`, `managed-block` | the one Markdown document | that is the whole payload |
| `hook` | `copy-tree`, `merge-json` | the whole payload tree, plus the merged entry | yes — `${SCRIPT_DIR}` resolves to where it was copied |
| `mcp` | `merge-json` | the `server` object from `payload/mcp.json`, and nothing else | no |

`aart-mcp-v1` is `{"name": …, "server": {…}}`, and only `server` is merged into the profile's MCP
configuration. Two consequences follow. A descriptor whose `command` or `args` names a path inside
`payload/` names a file no consumer will have. And a document shaped like the harness file it is
merged into — `{"mcpServers": {…}}` — has no `server` key, so it delivers an empty entry that starts
nothing. Registry curation reports both (`aart registry vendor`, `aart registry audit`); the loader
accepts what it always accepted.

## Provenance and collections

Imported or curated content may include `provenance.json`. It binds the canonical copy to a
credential-free Git URL, a lowercase 40-hex commit, input digest, importer ID/SemVer, options
digest, and reviewable warnings. Secrets, moving refs, and absolute paths are invalid.

A package produced by `aart registry vendor` is an ordinary package of its declared type that
carries such a document, with importer ID `registry-vendor-v1`; the copied subtree is its
`payload/`, and any wrapper the maintainer authored beside it — the `mcp.json` the type requires, a
`SETUP.md`, a setup recipe — is part of the same package and is reviewed and assessed with it. No
loader, index, or installer treats it specially, which is why an AART that predates vendoring reads
it unchanged.

Re-vendoring needs two facts a `provenance.json` does not hold — the ref the copy was taken at, and
which files the maintainer wrote rather than copied — so the vendoring writes them as the namespaced
extension `aart.vendor`, an object with a `ref` string and an `authored` array of package-relative
paths. It is verified against `importer.options_digest`, which already covers URL, ref, and path, so
an edited record is refused rather than trusted. Namespaced extensions are preserved unchanged by
every reader that does not understand them, so this adds no protocol revision and no requirement on
consumers.

Each direct `<collection-root>/<name>.json` file contains a one-line summary, structured artifact
selectors with optional half-open version bounds, and optional references to other collections.
P02 rejects duplicate selectors and direct self-reference; P03 owns full dangling/cycle graph
validation.

## Snapshot boundary

The P02 loader consumes an already acquired immutable `SourceSnapshot`. Local and pinned-Git
snapshots with the same files compile to the same frozen manifests and SHA-256 identities,
regardless of entry order or explicit directory entries. Filesystem/network acquisition and
last-known-good publication belong to SRC01. Protocol v1 rejects duplicate paths and rejects
symlinks or special device/FIFO/socket entries inside the marker and declared artifact/collection
roots. Unrelated repository content is not heuristically compiled.
