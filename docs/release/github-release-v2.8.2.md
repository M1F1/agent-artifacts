# AART 2.8.2

`2.8.0` and `2.8.1` added an advisory for a Keychain secret that is not the one the server needs.
One surface read it, and it was not the one people use.

## What was silent

Setup run through the wizard renders with `render_setup_outcome`, which reads the `recovery` field
of each receipt and nothing else. The advisory fields — `advisory`, `truncation_suspected`,
`stored_length`, `remediation_commands` — were read only by `aart marketplace install --json` and
its terminal renderer. `grep advisory agent_artifacts/tui.py` returned no hit.

So the run measured the stored length, wrote the finding into the receipt, and printed `configured`.
Reported from a real run: the value was replaced, was truncated to 128 bytes again, and the screen
said nothing about either.

## What 2.8.2 does

- **The wizard prints the advisory.** `advisory_messages` and `render_setup_advisories` sit in
  `setup.py` beside `recovery_messages`, both surfaces call them, and the JSON renderer renders
  through the same body — so the two cannot drift into saying different things about one receipt.
- **A recovery note carries its command on its own line, never wrapped.** It used to be wrapped as
  prose, arriving across three lines with the continuation unindented, to be repaired by hand
  before it could be run. It is sanitised per segment, because `public_text` flattens line breaks
  and would erase the split before it could be read.
- **A replaced value says so.** *This account already had a value in the Keychain and this run
  replaced it.* The old note read as an instruction to type something, when it is the undo for
  something already done.

## What this does not fix

The ceiling is Apple's and is unchanged. `AD-34` stays open. What changes is who gets told.

## Compatibility

Patch. Protocol versions, persisted schemas, commands, flags, registry documents and the setup
recipe language do not change; no receipt field is added or renamed, and schema freeze v18 differs
from the `2.8.1` freeze in `release_version` alone. `render_setup_outcome` gains an optional
`advisories` argument that defaults to empty.

## Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low` — the set
`2.8.0` shipped, unchanged. `AD-36` is closed by this release, as `AD-35` was by `2.8.1`. `AD-30`,
`AD-31` and `AD-34` remain open on purpose.

## Verifying this release

```sh
python scripts/version.py check-tag v2.8.2
git checkout v2.8.2
python scripts/release.py wheel-digest --output dist
```
