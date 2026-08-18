# AART 2.8.0 compatibility matrix

AART `2.8.0` is a minor release over `2.7.1`. It ends a silence: a macOS Keychain setup step that
stored a truncated secret and reported success now says so. This is a minor rather than a patch
because the setup `--json` payload gains an optional `warnings` array and the runtime gains a
public seam, `SetupRuntime.secret_length`. Protocol versions, persisted schemas, commands, flags,
registry documents and the setup recipe language do not change.

| Boundary | Supported in 2.8.0 | Change from 2.7.1 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Configuration schema | v1 | none | configuration tests |
| Source store | v2 | none | source runtime tests |
| Installation state | v2 | none | lifecycle and schema tests |
| Setup recipe | v2 only | none — no new module, field or input kind | setup parser tests |
| Setup `--json` payload | adds optional `warnings` | additive; absent when empty | setup runtime and render tests |
| Setup console output | adds a `Warnings` block after the summary | additive | setup render tests |
| `macos-keychain.store@1` receipt | adds `stored_length` and, at the ceiling, three keys | additive | setup runtime tests |
| `SetupRuntime.secret_length` | new field, inert by default | new seam | setup runtime tests |
| Tabnine project / user MCP | `.tabnine/agent/settings.json` · `mcpServers` | none | Tabnine CLI E2E |
| Security assessment | v1, ruleset `baseline-v1.1` | none | security tests |
| Published wheel | byte-reproducible from the tag | new minor artifact | packaging and release checks |

## What changed and why

`macos-keychain.store@1` hands the terminal to `/usr/bin/security add-generic-password -w`.
That tool reads its prompt through `getpass(3)`, whose static buffer is `_PASSWORD_LEN` in
`pwd.h` — 128 bytes. A longer value is discarded past that point with no error and no exit status.
The tool prompts twice and compares, so two identically truncated pastes agree with each other.
AART then verified existence only, which is correct for a tool that must not hold the secret, and
left the length unowned by anyone (`AD-34`).

2.8.0 does three things. It warns before the prompt that the ceiling exists. It measures what was
stored afterwards. When the stored length is exactly 128 it ends the run with the commands that set
the value by hand.

The measurement never holds the secret. `security` writes the value into a pipe that only
`/usr/bin/wc` reads; AART closes its own copy of the read end and reads the count. Capturing the
value to measure it would put the secret into AART's memory, which is the one property this step
exists to preserve.

## Evidence boundary

The ceiling is Apple's and is unchanged by this release. An Atlassian API token is 193 bytes, so it
still cannot be stored through this prompt. What 2.8.0 removes is the silence, not the ceiling.
`AD-34` stays open for that reason, and the route that would lift it — writing the item through
`SecKeychainAddGenericPassword` with `ctypes`, measured at 3000 bytes — is left undecided on
purpose: its price is the rule that AART never holds the secret.

A stored length below the ceiling proves nothing was cut. A stored length of exactly 128 is a
signature, not a proof: a secret that is genuinely 128 bytes long produces the same number and
earns the same warning. The warning says what was measured and leaves the judgement to the
operator.

## Upgrade direction

- From **2.7.1**: upgrade normally. No installation record, state document, harness file or recipe
  changes. Nothing needs reinstalling, and no setup step needs re-running.
- A secret stored by an earlier version is not re-measured. AART measures only what a run of the
  step just stored. To check an existing item, run the `find-generic-password … | wc -c` command
  the warning prints.
- Consumers of `aart marketplace install --json` see `warnings` only when a warning fired. A
  consumer that rejects unknown top-level keys must be updated before it meets one.

## Downgrade direction

2.7.1 and 2.6.1 read every document 2.8.0 writes; state and protocol shapes are unchanged. The only
loss is the warning itself: the older executables store the truncated value and still report
success.

## Schema-freeze comparison

Schema freeze v18 retains every v17 protocol number and every normative input digest, byte for
byte. Only `release_version` changes, from `2.7.1` to `2.8.0`. The changed modules —
`setup_runtime.py`, `commands/marketplace.py`, `setup_render.py` — are outside the frozen schema
inputs, and `setup.py`, which is inside them, is untouched.

## Residues

| Finding | Now | Established by |
|---|---|---|
| `AD-34` — a truncated secret passes every check | `open` | the ceiling stands; only the silence is fixed |
| `AD-31` — every stage reported success on an unauthenticated server | `open` | no post-install check that a server can authenticate |
| `AD-30` — a recipe collects a secret an MCP descriptor cannot name | `open` | no substitution on the descriptor path |
| `AD-32` — recipe help links are parsed, validated and rendered nowhere | `open` | unchanged by this release |
| `AD-33` — a vendored copy's taken subtree cannot be narrowed | `open` | unchanged by this release |
| `AD-29` — a partial profile override replaces the whole builtin record | `open` | unchanged by this release |
