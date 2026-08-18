# AART 2.8.0

A macOS Keychain setup step could store half your token and call it a success. AART 2.8.0 says when
that happens.

## What was silent

`macos-keychain.store@1` hands the terminal to `/usr/bin/security add-generic-password -w`. That
tool reads its prompt through `getpass(3)`, whose buffer is 128 bytes. Anything longer is cut with
no error and no exit status. It asks twice and compares the two answers — and two identically
truncated pastes agree, so the check it performs cannot see the problem. AART then verified that
the item exists, never its value, which is correct for a tool that must not hold the secret and
leaves the length owned by nobody.

Downstream, the shell block exports the short value, the server authenticates as nobody, and the
only visible symptom is the word `disconnected` in a harness UI — the same word a missing image, a
stopped daemon and an unexpanded variable produce.

## What 2.8.0 does

- **Warns before the prompt.** The step says the ceiling exists, that the tool asks twice, and that
  this run will measure what was stored.
- **Measures after the add.** The receipt of a successful add carries `stored_length`.
- **Ends the run with a remedy.** When the stored length is exactly 128, a `Warnings` block prints
  after the summary with two copy-ready commands: one that sets the value from the clipboard, one
  that proves its length. They are never wrapped, because a wrapped command cannot be copied.
- **`--json` carries the same thing.** `aart marketplace install --json` gains an optional
  `warnings` array, present only when a warning fired.

The measurement never holds the secret. `security` writes the value into a pipe that only `wc`
reads; AART closes its own copy of the read end and reads the count. Putting the value in AART's
own memory — or in its `argv` — is the thing this step exists to avoid.

## What this does not fix

The ceiling is Apple's and is unchanged. An Atlassian API token is 193 bytes, so it still cannot be
stored through this prompt; the two printed commands are how you store it. `AD-34` stays open for
that reason. The route that would lift the ceiling — writing the item through
`SecKeychainAddGenericPassword` with `ctypes`, measured at 3000 bytes — is deliberately undecided,
because its price is the rule that AART never holds the secret.

A length of exactly 128 is a signature, not a proof. A secret that is genuinely 128 bytes long
earns the same warning. The warning reports what was measured and leaves the judgement to you.

## Compatibility

Minor, because the setup `--json` payload gains an optional `warnings` array and the runtime gains
a public seam. Protocol versions, persisted schemas, commands, flags, registry documents and the
setup recipe language are unchanged, and schema freeze v18 has the same protocol values and
normative input digests as v17. Upgrading from 2.7.1 needs no reinstall and no re-run of any setup
step. A consumer that rejects unknown top-level JSON keys should be updated before it meets one.

## Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low`. Three high
findings are the credential join this release only partly addresses — `AD-30` (a recipe collects a
secret an MCP descriptor cannot name), `AD-31` (every stage reported success on a server that was
never authenticated), and `AD-34` (the ceiling above). They are documented in the residue register
and remain open on purpose.

## Verifying this release

```sh
python scripts/version.py check-tag v2.8.0
git checkout v2.8.0
python scripts/release.py wheel-digest --output dist
```

The attached wheel is byte-reproducible from the tagged commit. Its exact digest is appended below
when the GitHub release is created.
