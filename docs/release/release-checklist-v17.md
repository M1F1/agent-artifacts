# AART 2.7.1 release checklist and evidence

This patch restores the Tabnine MCP target measured in the company build and reverses the shipped
2.7.0 target regression. The chronological evidence belongs in
[`PROGRESS-company-adoption-repair.md`](../testing/PROGRESS-company-adoption-repair.md), and finding
dispositions remain authoritative in
[`residue-register.md`](../testing/residue-register.md).

Run from the clean release commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.7.1
git checkout v2.7.1
python scripts/release.py wheel-digest --output dist
```

The release check must pass repository/version evidence, schema freeze v17, the system matrix,
zero-dependency wheel installation, and every public-registry format, validate, lock, build, audit,
and compatibility gate. Attach the exact wheel produced by `wheel-digest`, append its
`sha256:<hex>  <wheel filename>` line to the GitHub release body, download the asset again, and
compare its digest.

## Repair gate

- Project Tabnine MCP target is exactly `.tabnine/agent/settings.json` under `mcpServers`.
- User Tabnine MCP target is exactly `~/.tabnine/agent/settings.json` under `mcpServers`.
- User scope remains supported; skills, guidelines, hooks and memory targets are unchanged.
- The real CLI E2E requires both settings files, requires both `mcp_servers.json` files to remain
  absent, reports both scopes current, and uninstalls either without touching the other.
- Current tutorials and designs name the company-build measurement and retain the standalone-file
  discrepancy as an unmeasured verify item.
- The live `disconnected` server runtime and `AD-29` profile override behavior stay separate.

## Quality and live acceptance

Run all nine repository gates after the final 2.7.1 version and v17 contract changes. Then build a
stamped wheel and use only isolated project, HOME, data and cache roots for these scenarios:

1. Fresh project and user installs write the restored files and no standalone file; repeat install,
   status and update remain current/no-op; uninstall either scope preserves the other.
2. A real installation made by the published 2.7.0 wheel remains byte-identical when 2.7.1 update
   refuses with exact uninstall/install remediation. Executing those commands removes the old
   standalone entry and writes the restored settings entry at the same scope.
3. A real project installation made by the published 2.6.1 wheel is already on the restored target;
   2.7.1 status/update must not report a target migration.
4. The full release check passes against a fresh clean checkout of
   `https://github.com/M1F1/agent-artifacts-registry` at its remote default revision.
5. After publication, every README installer/source cell passes for the release asset and tag:
   `pip`, `pipx`, and `uv tool` against a downloaded wheel, the release URL, and the Git URL.

Fix every failure and repeat the affected scenario. Record exact wheel digests, version stamps,
temporary boundaries, tag commit, release URL and downloaded-asset comparison in the progress log.

## Compatibility review

Confirm schema freeze v17 has the same protocol values and schema-input digests as v16; only
`release_version` changes. Review the 2.6.1, 2.7.0 and downgrade directions in
[`compatibility-v17.md`](compatibility-v17.md). No protocol or persisted document revision changes.

## Publication

1. Commit the repaired profile, tests, v17 contract and green evidence on
   `fix/tabnine-mcp-target-regression`; push it and open a draft PR to `main`.
2. Make the PR ready only after local quality and live acceptance pass. Require all GitHub checks.
3. Merge without changing the reviewed tree; fetch and verify the branch commit is in `origin/main`.
4. Run `make release-check` against the approved registry checkout.
5. Create and push annotated tag `v2.7.1` on the checked release commit.
6. Build the tagged wheel once with `wheel-digest`, create the GitHub release from
   [`github-release-v2.7.1.md`](github-release-v2.7.1.md), and attach that exact file.
7. Verify the downloaded asset digest and public 3×3 installation matrix.
8. Append publication evidence to the progress log through a post-release documentation PR; do not
   rewrite the immutable tag to record facts that occur after it.

## Residues shipped open

After this repair closes `AD-28`, 57 findings remain open: one `major`, two `high`, 33 `medium`, and
21 `low`. `AD-29` is the only open adoption id introduced by this repair and is medium. No known
high-severity adoption problem may remain at publication.
