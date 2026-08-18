# AART 2.7.0

AART 2.7.0 closes the complete company-adoption stream: first contact, registry authoring and
publication, source freshness, consumer lifecycle, Tabnine targets, reporting, and repeatable setup.
All 27 recorded `AD` findings are closed.

## A complete maintainer path

Registry maintainers can now create collections, conservatively discover upstream candidates,
accept an explicit batch manifest, vendor a single loose file with pinned provenance, and publish a
reviewed lock/index/audit projection as one Git commit. The new public commands are:

```text
aart registry collection
aart registry discover
aart registry vendor-batch
aart registry publish
```

Discovery rejects every candidate by default. Preview operations do not write, batch finalization is
atomic, and publish never pushes or bypasses validate/audit gates.

## Fresh means the origin still agrees

Source health now compares validated source identity, resolved revision, and snapshot digest. A
snapshot does not become stale merely because it is old, and a recent snapshot is not called current
when its origin differs. Automatic mode synchronizes before marketplace/TUI projection; manual mode
distinguishes `not-synchronized` from `could-not-check`.

## Reporting is wired end to end

`registry init --usage-reporting-repository OWNER/REPOSITORY` writes the service advertisement beside
the issue templates. Finalized CLI actions and the TUI retain routing failures instead of silently
dismissing them. Interactive CLI reporting keeps two default-No consents; JSON returns an inert exact
plan, non-interactive text never opens a browser, and provider failures remain advisory.

## Tabnine and memory ownership

Tabnine MCP servers now go to the documented `.tabnine/mcp_servers.json` project file and
`~/.tabnine/mcp_servers.json` user file, both under `mcpServers`. Distinct named memory artifacts can
share one instruction file, report status independently, and be uninstalled without touching one
another.

## Setup that survives the second run

Setup recipe v2 gains reviewed, echoed `text` inputs through `shell.env-from-input@1`; secrets stay
Keychain-only. Setup now preserves policy through the TUI, reports install/update based on the
payload transaction, names manual and authorization routes, explains Keychain prompts, refuses
symlink targets before effects, keeps exact persistence failures and compensation evidence, and
moves setup state correctly after same-version package bytes change.

## Upgrading

- Rename `com.m1f1.runtime-requirements` to `aart.runtime-requirements` in authored artifacts.
- Set `requires_aart.min_inclusive` to `2.7.0` for artifacts using setup `text` inputs.
- For a Tabnine project MCP artifact installed by 2.6.1, run `marketplace uninstall` and then
  `marketplace install` under 2.7.0. Update refuses that target migration with the exact commands
  rather than orphaning the old settings entry.
- Do not downgrade a data root after installing two named memories into one destination without
  first uninstalling one; 2.6.1 rejects that ownership combination.

No registry protocol or persisted schema revision changes. Existing registries remain valid and
need rebuilding only when they adopt a new 2.7.0 authoring capability.

## Known defects shipped open

Fifty-six unrelated findings remain open: one `major`, two `high`, 32 `medium`, and 21 `low`.
`LAF-15` is the major security-scan input gap; `LAF-85` and `LAF-101` are the high audit/register
uncertainties. No adoption-stream finding remains open.

## Verifying this release

```sh
python scripts/version.py check-tag v2.7.0
git checkout v2.7.0
python scripts/release.py wheel-digest --output dist
```

The wheel attached to this release is byte-reproducible from the tagged commit and is the exact file
whose digest is printed below.
