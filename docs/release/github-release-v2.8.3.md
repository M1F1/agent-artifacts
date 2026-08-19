# AART 2.8.3

Setup writes `export ATLASSIAN_API_TOKEN=…` into `~/.zshrc`, prints `configured`, and stops. The
shell you launched it from still has the environment it started with, and so does every process it
goes on to spawn — the agent harness among them.

## What was silent

A child process cannot alter its parent's environment. That is not a defect and cannot be fixed;
what was missing is that nobody said it. `shell.env-from-keychain@1` and `shell.env-from-input@1`
append their export block to the file named in the receipt's `path`, and the closing screen named
neither the file nor the consequence.

So the operator reads `configured`, restarts nothing, and the server comes up without the variable.
The only symptom is `disconnected` — which `AD-31` already showed is also what a missing image, a
stopped daemon and an unexpanded variable produce.

The advice existed before, as a fragment: the remediation commands `AD-34` and `AD-35` print carry
`&& source ~/.zshrc` glued to the end of a `security` command. So it appeared exactly where a secret
was suspected, and a run that wrote variables cleanly said nothing at all.

## What 2.8.3 does

A run that wrote variables into a shell file ends with a `Next step` block:

```
Next step
  what  this run put variables in ~/.zshrc, and a shell that is already open does not
        have them yet
    source ~/.zshrc
  or open a new terminal window and start the agent harness from there
```

- **The path comes from the receipt, not from a guess.** `shell_reload_reminder` reads each shell
  step's own `path`, so a recipe writing to `~/.bash_profile` or anywhere else is named correctly
  without knowing this release exists. Several shell steps in one run produce one block per distinct
  file, in write order.
- **It prints `~/.zshrc`, not your home directory in full**, through the same `home_relative` the
  remediation commands use, with the tilde left unquoted so the shell still expands it.
- **The command prints unwrapped**, for the reason `AD-36` established: a folded command has to be
  repaired by hand before it can be run.
- **The alternative prints beside it**, because it is the one that also works for a harness launched
  from the GUI — which never reads `.zshrc` at all, since `.zshrc` is read by interactive shells
  only.
- **Both surfaces render one body.** The wizard through `render_setup_outcome`, `--json` through a
  `next_steps` payload row. That is the drift `AD-36` demonstrated, closed by construction.

## Also in this release

The Docker build step's recovery note said the pre-existing tag *is left alone; remove it manually
if it is yours*, which is wrong twice over: `docker build --tag` reassigns the tag, and removing it
is the one thing that breaks the server. Measured on Docker 29.5.2 with the containerd snapshotter —
the previously tagged image is deleted, not left dangling, so nothing can restore the old binding.
The note now says that, and says not to remove the tag.

The README states the licence: MIT, free for any use including commercial, no warranty and no
liability on the author.

## Compatibility

Patch. Protocol versions, persisted schemas, commands, flags, registry documents and the setup
recipe language do not change; no receipt field is added or renamed, and schema freeze v18 differs
from the `2.8.2` freeze in `release_version` alone. `render_setup_outcome` gains an optional
`reminders` argument that defaults to empty; `--json` gains a `next_steps` array, absent when no
shell file was written.

## Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low` — the set
`2.8.0` shipped, unchanged. `AD-37` is closed by this release, as `AD-36` was by `2.8.2`. `AD-30`,
`AD-31` and `AD-34` remain open on purpose.

## Verifying this release

```sh
python scripts/version.py check-tag v2.8.3
git checkout v2.8.3
python scripts/release.py wheel-digest --output dist
```
