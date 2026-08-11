# Native source protocol v1

A native AART source is an acquired repository tree whose root contains `aart-source.json`.
Artifact discovery is deliberately limited to the manifest's explicit `artifact_roots`; AART does
not crawl arbitrary repository layouts during consumer installation. Foreign layouts must be
converted by a reviewed Maintainer importer before they become consumer inputs.

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

## Provenance and collections

Imported or curated content may include `provenance.json`. It binds the canonical copy to a
credential-free Git URL, a lowercase 40-hex commit, input digest, importer ID/SemVer, options
digest, and reviewable warnings. Secrets, moving refs, and absolute paths are invalid.

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
