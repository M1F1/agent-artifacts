# AART v18 release checklist and evidence — 2.8.0, 2.8.1 and 2.8.2

Two releases ship under contract v18. Everything from here to *2.8.1 change gate* is the 2.8.0
record and is left as written: a dated record is not edited to agree with today. **To verify the
current release, read the 2.8.1 sections and substitute `v2.8.1` for `v2.8.0` in the commands
below.**

This minor release ends a silence in the macOS Keychain setup step: a secret cut at the prompt was
stored and reported as success. It now warns before the prompt, measures what was stored, and ends
the run with the commands that set the value by hand. The finding is `AD-34` in
[`residue-register.md`](../testing/residue-register.md); its measurements are in
[`residue-stream-2026-08-16-adoption.md`](../testing/residue-stream-2026-08-16-adoption.md).

Run from the clean release commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.8.0
git checkout v2.8.0
python scripts/release.py wheel-digest --output dist
```

The release check must pass repository/version evidence, schema freeze v18, the system matrix,
zero-dependency wheel installation, and every public-registry format, validate, lock, build, audit,
and compatibility gate. Attach the exact wheel produced by `wheel-digest`, append its
`sha256:<hex>  <wheel filename>` line to the GitHub release body, download the asset again, and
compare its digest.

## Change gate

- The Keychain step writes the ceiling warning **before** it hands the terminal to `security`, not
  after the value is already gone.
- The receipt of a successful add carries `stored_length`. At exactly 128 it also carries
  `truncation_suspected`, `truncation_detail` and `remediation_commands`.
- The measurement never holds the secret: `security` writes into a pipe that only `/usr/bin/wc`
  reads, AART closes its own copy of the read end, and AART reads the count. No AART process
  captures the value, and no AART argv carries it.
- The measurement reports **stored bytes**, not printed characters. `security -w` prints anything
  that is not printable ASCII as unmarked hex, and prints a hex-digit password literally, so the
  shape is taken from `-g`'s `password: 0x` marker through `grep -c` and never guessed from the
  printed form. An odd hex count returns no measurement.
- A failed or unavailable measurement leaves the receipt silent. No measurement is not the same
  claim as no problem.
- `SetupRuntime.secret_length` is inert by default, so no test run reaches a real Keychain;
  `production_runtime()` is the only place that wires the real probe.
- The `Warnings` block prints **after** the summary, and its commands are never wrapped. A wrapped
  command is a command that cannot be copied.
- The `--json` payload carries `warnings` only when at least one warning fired.
- No setup module, recipe field or input kind is added. The recipe language stays setup v2.

## Quality and live acceptance

Run all nine repository gates after the final 2.8.0 version and v18 contract changes. Then build a
stamped wheel and use only isolated project, HOME, data and cache roots for these scenarios:

1. A recipe with a Keychain step stores a value shorter than the ceiling: the warning text appears
   before the prompt, the receipt carries the true length, and neither the console nor the `--json`
   payload carries a warning.
2. The same step stores a value of exactly 128 bytes: the run ends with the `Warnings` block after
   the summary, both commands appear on one line each, and `--json` carries the same commands.
3. The two printed commands, pasted into a shell, replace the item and report its length. The
   second run of the recipe reports the item as current and does not prompt again.
4. The measurement is exact across print forms. Against throwaway Keychain items holding
   non-secret values, the reported length equals the real byte length for: printable ASCII below
   the ceiling, printable ASCII at 128, a 128-byte UTF-8 value, a 64-byte UTF-8 value, a
   128-character hex-digit value, and a 128-byte value containing a tab. A missing item reports no
   measurement. Delete every probe item afterwards.
5. Installing and uninstalling an artifact with a setup recipe is unchanged from 2.7.1 in every
   other respect: same effects, same receipts otherwise, same idempotence.
6. The full release check passes against a fresh clean checkout of
   `https://github.com/M1F1/agent-artifacts-registry` at its remote default revision.
7. After publication, every README installer/source cell passes for the release asset and tag:
   `pip`, `pipx`, and `uv tool` against a downloaded wheel, the release URL, and the Git URL.

Fix every failure and repeat the affected scenario. Record exact wheel digests, version stamps,
temporary boundaries, tag commit, release URL and downloaded-asset comparison in the progress log.

## Compatibility review

Confirm schema freeze v18 has the same protocol values and schema-input digests as v17; only
`release_version` changes. Review the upgrade and downgrade directions in
[`compatibility-v18.md`](compatibility-v18.md). No protocol or persisted document revision changes.

## Publication

1. Commit the change, tests, v18 contract and green evidence on
   `stream/adoption-mcp-secret-join`; push it and open a draft PR to `main`.
2. Make the PR ready only after local quality and live acceptance pass. Require all GitHub checks.
3. Merge without changing the reviewed tree; fetch and verify the branch commit is in `origin/main`.
4. Run `make release-check` against the approved registry checkout.
5. Create and push annotated tag `v2.8.0` on the checked release commit.
6. Build the tagged wheel once with `wheel-digest`, create the GitHub release from
   [`github-release-v2.8.0.md`](github-release-v2.8.0.md), and attach that exact file.
7. Verify the downloaded asset digest and public 3×3 installation matrix.
8. Append publication evidence to the progress log through a post-release documentation PR; do not
   rewrite the immutable tag to record facts that occur after it.

## Residues shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low`.

**This release breaks the v17 publication rule that no high-severity adoption finding may remain
open, and does so knowingly.** Three do: `AD-30`, `AD-31` and `AD-34`. They are one problem seen
from three sides — a credential collected by a recipe, a descriptor that cannot name it, and a
prompt that cuts it — and the stream that found them is still open. `AD-34`'s silence is what this
release fixes; its ceiling stands, and the route that would lift it is left undecided because its
price is the rule that AART never holds the secret. Shipping the warning now is worth more to an
operator than holding it until the whole join is repaired, because today the only signal is one
word in a harness UI. The rule is not dropped: it returns as the gate on the release that closes
the join.

## 2.8.1 change gate

`2.8.1` ships under this same v18 contract. The finding is `AD-35` in
[`residue-register.md`](../testing/residue-register.md), and this release closes it.

| Finding | Now | Established by |
|---|---|---|
| `AD-35` — an existing Keychain item is kept and nothing says so | `closed` | the skip path measures, records and prints; the item is left as found |

- A Keychain step that finds its item already present **measures it** and records
  `existing_secret_kept`, `stored_length`, an `advisory` and `remediation_commands`.
- The measurement on that path uses the same `security`→`wc` pipe: no AART process captures the
  value and no AART argv carries it.
- **An advisory is not a change.** No `add-generic-password` runs on the skip path, and the
  pre-prompt ceiling warning is not printed for a prompt that never happens. Both are asserted by
  `tests/setup_runtime_test.py::SetupRuntimeTests::test_an_existing_secret_is_reported_rather_than_passed_over_in_silence`.
- Kept-existing and truncated-at-128 produce **one** advisory and **one** command, because one
  command fixes both.
- The reload prints `~/.zshrc`. The tilde is unquoted so the shell expands it; a path needing quotes
  is quoted after the first slash, and a path outside the home directory stays absolute.
- The receipt field `truncation_detail` is renamed `advisory`. `truncation_suspected` and
  `stored_length` keep their meaning, and the `--json` `warnings` array keeps its shape.

Steps 1–8 above are repeated unchanged for `2.8.1`, with `v2.8.1` as the tag and
[`github-release-v2.8.1.md`](github-release-v2.8.1.md) as the release body.

## 2.8.1 residues shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low` — the set
`2.8.0` shipped, unchanged. `AD-30`, `AD-31` and `AD-34` remain open for the reason stated above,
which this patch does not alter.

## 2.8.2 change gate

`2.8.2` ships under this same v18 contract. The finding is `AD-36`, and this release closes it.

| Finding | Now | Established by |
|---|---|---|
| `AD-36` — the advisory was read by one surface, and not the one people use | `closed` | both surfaces render one shared body; five tests assert the wizard output |

- The wizard renders the advisory. `advisory_messages` and `render_setup_advisories` are in
  `setup.py` beside `recovery_messages`; the JSON renderer delegates to the same body, so the two
  surfaces cannot drift.
- No rendered line is a fragment of a command. Asserted over the whole wizard output, not over the
  command list alone, because the defect was a fold and a fold is only visible in the rendering.
- A recovery note is sanitised per segment, so `public_text` still flattens author-controlled text
  and the one structural split survives.
- A replaced Keychain value states that the account already had one.

Steps 1–8 above are repeated unchanged for `2.8.2`, with `v2.8.2` as the tag and
[`github-release-v2.8.2.md`](github-release-v2.8.2.md) as the release body.
