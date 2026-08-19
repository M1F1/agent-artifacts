# AART 2.8.1

2.8.0 added a warning for a truncated Keychain secret. It could not reach the machine that reported
the problem, because that machine already had the item.

## What was silent

`macos-keychain.store@1` looks for the item before it asks for anything. When
`find-generic-password` exits 0 and the effect does not ask for a replacement, the step returns
there: no prompt, no measurement, and no receipt field beyond `created: false`. The run reports
`configured`.

That is true about the configuration and says nothing about the value. Finding the item already
there is the **normal** outcome of every run after the first, so a credential rotated since it was
stored is never re-read and never mentioned; the server keeps authenticating with the old one until
someone reads `disconnected` in a harness UI. The warning 2.8.0 added lives on the add path, which
this case never reaches.

## What 2.8.1 does

- **Measures the item it kept.** The skip path now reads the stored length through the same
  `security`→`wc` pipe the parent never reads, and records `existing_secret_kept`, `stored_length`,
  an `advisory` and `remediation_commands`.
- **Reports both findings as one.** Kept-existing and truncated-at-128 end in the same place — the
  stored secret is not the one the server needs — and one command fixes both, so they join into one
  advisory instead of two mechanisms to learn.
- **Prints `~/.zshrc`.** The reload used to spell out the operator's home directory. The path was
  always read from the run's own receipt, never hardcoded, but it did not read that way. The tilde
  is left unquoted so the shell still expands it; anything needing quotes is quoted after the first
  slash.
- **Says what the command is for.** The header is `to replace what is stored:`, which is true
  whether the value was truncated or simply old.

An advisory is not a change. The item is left exactly as it was found, nothing is written on this
path, and the pre-prompt ceiling warning is not printed for a prompt that never happens. Both are
asserted by tests rather than described.

## What this does not fix

The ceiling is Apple's and is unchanged. `AD-34` stays open: an Atlassian API token is 193 bytes and
still cannot be pasted into that prompt. The printed command is how you store it.

A length of exactly 128 remains a signature, not a proof, and a run cannot tell a rotated credential
from a current one. Both report what was measured and leave the judgement to you.

## Compatibility

Patch. Protocol versions, persisted schemas, commands, flags, registry documents and the setup
recipe language do not change; schema freeze v18 differs from the 2.8.0 freeze in `release_version`
alone. Upgrading from 2.8.0 needs no reinstall and no re-run of any setup step.

One receipt field is renamed: `truncation_detail` is now `advisory`, because it carries both
findings. `truncation_suspected` and `stored_length` keep their meaning, and the `--json` `warnings`
array keeps its shape — `key`, `detail`, `commands`. A record written by 2.8.0 is read unchanged;
nothing reads the old field by name.

## Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low` — the same set
2.8.0 shipped. `AD-35` is closed by this release. The three high findings of the credential join
remain open on purpose: `AD-30`, `AD-31` and `AD-34`.

## Verifying this release

```sh
python scripts/version.py check-tag v2.8.1
git checkout v2.8.1
python scripts/release.py wheel-digest --output dist
```

The attached wheel is byte-reproducible from the tagged commit. Its exact digest is appended below
when the GitHub release is created.
