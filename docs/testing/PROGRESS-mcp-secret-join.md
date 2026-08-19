# MCP secret join progress

Execution record for the `stream/adoption-mcp-secret-join` work and the AART 2.8.0 release it
produced. Finding dispositions remain authoritative in
[`residue-register.md`](residue-register.md); the findings themselves are in
[`residue-stream-2026-08-16-adoption.md`](residue-stream-2026-08-16-adoption.md).

## 2026-08-19 — release of 2.8.0

### Release gate found a defect in the change being released

- The first measurement counted what `security -w` **printed**. `-w` prints any value that is not
  printable ASCII as hex and marks it in no way, so a 128-byte UTF-8 secret measured `256`.
- Halving anything hex-shaped is not the fix: a password of nothing but hex digits prints
  literally, so a 128-character hex token would have measured `64` and lost the warning outright.
- `-g` is the discriminator — `password: 0x<hex>` for the hex form, a quoted string otherwise. The
  shape now comes from `grep -c` on that marker and the length from `wc -c` on `-w`. Two counts,
  each one a number, and the value in neither.
- Measured against throwaway Keychain items holding non-secret values: ASCII at 93 and at 128,
  UTF-8 at 64 and at 128 bytes, 128 hex digits, and 128 bytes ending in a tab all measure to the
  byte. A missing item returns no measurement. Every probe item was deleted afterwards.
- Fixed in `1476ebb` before publication, with five tests covering the decision.

### Compatibility, measured rather than asserted

- A `v2.7.1` worktree parsed a state record written by 2.8.0: accepted, and all four new receipt
  keys preserved. `parse_setup_state` carries no allow-list of receipt keys.
- Schema freeze v18 differs from v17 in exactly one line, `release_version`. No normative input
  digest changed; `setup.py` is untouched.
- Code changed in three modules only: `setup_runtime.py`, `commands/marketplace.py`,
  `setup_render.py`. No new command, flag, setup module or input kind.
- The credential-shape scan over a receipt carrying the new keys reports nothing. That scan matches
  vendor shapes and private keys only — an Atlassian-shaped token is outside it by the documented
  limit in `DESIGN-token-containment.md` §4.4. Receipts carry the length, never the value.

### Publication

- All nine quality gates green at 2.8.0: format-check, lint, typecheck, unit, integration,
  validate, coverage, packaging-check, docs-check.
- Merged [`#97`](https://github.com/M1F1/agent-artifacts/pull/97) as merge commit
  `65e08d2849bb7c200e68e92b8116a387198e433c`, containing branch commit
  `1476ebb89de36bc8c752d92baf7daf0b4668f25b`. Both GitHub check runs passed on Python 3.10 and 3.14.
- Cloned the reference registry from its exact HTTPS origin at clean commit
  `f25eba97bf71c4e6a4b224f2b081a6bb7c7327f9`. `make release-check` passed all 11 gates.
- Created and pushed annotated tag `v2.8.0`; tag object
  `d6c98081f521a7b92d28261c3008b4c85fa26a44` resolves to merge commit `65e08d2`.
- Built the 571,810-byte `agent_artifacts-2.8.0-py3-none-any.whl` from the detached tag. SHA-256
  `bdeed6d55e0d6d4fcba0e6c5f093e110a5e79b7580110859c85e4c40b4b1f7ad`.
- Published the non-draft, non-prerelease release
  [`v2.8.0`](https://github.com/M1F1/agent-artifacts/releases/tag/v2.8.0). Downloaded the asset into
  a fresh directory; its digest equals the tagged build exactly.
- Installation matrix: **6 of 9 cells exercised**, all passing `agent-artifacts 2.8.0` — `pip` and
  `pipx` against the downloaded wheel, the release URL, and the tagged Git URL. The three `uv tool`
  cells were **not run**: `uv` is absent from this host. The README states that boundary rather
  than implying the whole matrix was re-run.
- One host defect met and dismissed as unrelated: Homebrew `python@3.14` cannot create a venv with
  `pip` anywhere on this machine — `ensurepip` fails in `$HOME` as well as in a temporary root — so
  a fresh `PIPX_HOME` failed until pipx was pointed at Python 3.11. Nothing to do with the wheel.

### Shipped open, knowingly

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low`. This release
breaks the v17 rule that no high-severity adoption finding may remain open. `AD-30`, `AD-31` and
`AD-34` are three sides of one credential join; 2.8.0 ends `AD-34`'s silence, not its cause. The
ceiling is Apple's and stands: a 193-byte token still cannot pass through this prompt. The rule
returns as the gate on the release that closes the join.
