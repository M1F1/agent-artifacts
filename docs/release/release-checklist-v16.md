# AART 2.7.0 release checklist and evidence

This minor release closes the full company-adoption stream: every `AD-01` through `AD-27` row is
`closed` in the authoritative
[`residue-register.md`](../testing/residue-register.md). The chronological implementation, test,
live-acceptance, and publication record is
[`PROGRESS-company-adoption-repair.md`](../testing/PROGRESS-company-adoption-repair.md).

Run from the clean release commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.7.0
git checkout v2.7.0
python scripts/release.py wheel-digest --output dist
```

The release check must pass repository/version evidence, schema freeze v16, the system matrix,
zero-dependency wheel installation, and every public-registry format, validate, lock, build, audit,
and compatibility gate. Attach the exact wheel produced by `wheel-digest`; put its
`sha256:<hex>  <wheel filename>` line in the GitHub release body and verify the downloaded asset.

## Registry precondition

Use a clean checkout of `https://github.com/M1F1/agent-artifacts-registry` at the remote default
revision. A registry created or built by 2.6.1 remains valid. Rebuild only when adopting a new
2.7.0 authoring capability such as a setup recipe `text` input, and set the artifact's
`requires_aart.min_inclusive` accordingly.

## Quality and live acceptance

Before the release commit, the nine repository gates must pass: format, lint, typecheck, unit,
integration/E2E, validate/version, coverage, packaging, and docs. After the final version and
release-contract changes, run them again rather than carrying forward a result from 2.6.1.

Live acceptance must install the stamped 2.7.0 wheel into isolated environments and cover:

- clean registry initialization, Git preconditions, reporting-service authoring, collection,
  discovery, single-file vendoring, batch finalization, lock/build/audit, preview, publish, and an
  unchanged publish rerun;
- clean consumer source add/sync, install/status/update/uninstall, two Tabnine memories sharing one
  file, both Tabnine MCP scopes, and repeated operations;
- setup review/finalize/repeat after same-version source bytes change, plus non-interactive reporting
  behavior and origin-aware freshness;
- the 2.6.1-to-2.7.0 Tabnine target migration (safe update refusal, uninstall, reinstall) and the
  public 3×3 installer matrix after the GitHub asset and tag exist.

Every failure is fixed and the affected scenario repeated before publication. Exact commands,
commit stamps, temporary-environment boundaries, and results belong in the progress log.

## Compatibility review

Protocol revisions are unchanged. Confirm schema freeze v16 matches the normative inputs and review
the upgrade/downgrade asymmetries in [`compatibility-v16.md`](compatibility-v16.md): the retired
runtime-extension spelling, setup `text` compatibility floor, shared-memory downgrade boundary, and
Tabnine project MCP move. The expected v15→v16 freeze delta is exactly one input,
`agent_artifacts/setup.py`, and no protocol-version value.

## Publication

1. Commit the final contract and green evidence; push `stream/company-adoption`.
2. Merge the reviewed release commit to `main` without changing its tree; fetch and verify it is in
   `origin/main`.
3. Run `make release-check` against the approved clean reference registry.
4. Create and push annotated tag `v2.7.0` on the checked release commit.
5. Check out the tag, run `wheel-digest --output dist`, and create the GitHub release from
   [`github-release-v2.7.0.md`](github-release-v2.7.0.md), appending the digest line.
6. Download the release asset, compare its digest, and exercise every README installer/source cell.
7. Record the release URL, tag commit, wheel digest, asset verification, and final status in the
   progress log.

## Residues shipped open

Fifty-six unrelated findings remain `open`: one `major`, two `high`, 32 `medium`, and 21 `low`.
`LAF-15` is the major security-scan input gap; `LAF-85` and `LAF-101` are the high audit/register
uncertainties. No `AD` finding remains open. This release does not weaken a gate or fold those
unrelated streams into the adoption repair.
