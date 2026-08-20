# AART 2.8.4

`2.8.3` was published to stop a Docker recovery note reading as if it were about some other kind of
tag. It fixed one of the two branches that produce that note, and the branch it left is the one an
ordinary first install reaches.

## What was still wrong

`_docker_build_apply` writes a different note depending on whether the image tag existed before the
run. `2.8.3` rewrote the `preexisting=True` branch — the tag was already there — and left the other
one reading:

```
Recovery
  Rollback removes this tag, which only this run created
```

That is the **first install on a clean machine**: no image, the run builds one. The note names
neither Docker nor the tag, which was the whole of the original complaint, reported again from a
real run one release later.

The sibling module carried it too. `docker.pull@1` said *Image may be shared; remove it manually
only after checking other users* — no Docker, no image name, and removal offered as the whole
remedy.

## What 2.8.4 does

Both notes open with `Docker image …` and carry the tag or image they are about.

For a tag this run created:

> Docker image tag `aart/mcp/alation:1.0.0` did not exist before this run and this run created it.
> Rollback removes it with `docker image rm`, which also deletes the image itself when no other tag
> refers to it. There is nothing to do unless you are undoing this setup, and do not remove this tag
> by hand: the server runs from it.

For an image this run pulled:

> Docker image `registry.example/tool:1.2.3` was pulled by this run and was not on this machine
> before. Rollback leaves it, because an image can be shared by other containers and nothing removes
> one automatically. Remove it by hand with `docker image rm` only after checking that nothing else
> uses it.

The difference between them is real rather than stylistic. Rollback **removes** a built tag —
`_rollback_receipt` runs `docker image rm` — and **leaves** a pulled image, returning `False` on
purpose, because a pulled image can back other containers.

Both were rendered before being believed, which is the habit `AD-36` established: a defect in what
reaches the screen is not visible in the source.

## Also in this release

The README documented no dependency at all. It now states the fact most worth stating — the
installed runtime has none, standard library only — and names each of the five packages in the
`dev` extra against the gate that consumes it, with a table of all nine gates and the command each
runs. Two rows were checked rather than assumed: `wheel` is present for
`pip wheel --no-build-isolation` in `packaging-check`, and `setuptools` is named explicitly because
newer Python versions no longer bundle it in `venv`.

## Compatibility

Patch. Protocol versions, persisted schemas, commands, flags, registry documents and the setup
recipe language do not change; no receipt field is added or renamed, and schema freeze v18 differs
from the `2.8.3` freeze in `release_version` alone. Only the text of two `recovery` strings changes.

## Known defects shipped open

Sixty-six findings remain open: one `major`, five `high`, 39 `medium`, and 21 `low` — the set
`2.8.0` shipped, unchanged. `AD-38` is closed by this release, as `AD-37` was by `2.8.3`. `AD-30`,
`AD-31` and `AD-34` remain open on purpose.

**`AD-39` is shipped open and known.** A queue that configures several artifacts renders the
`2.8.3` reload reminder once per artifact, so selecting three MCP servers that each write to
`~/.zshrc` prints the same `Next step` block three times. The de-duplication in `_shell_files_of`
is scoped to one receipt, and the queue reintroduces the repetition across receipts. It is noise
rather than wrong advice, and repetition is how a message stops landing — the reason `2.8.3`
existed — so it is recorded rather than tolerated quietly, and left for its own change.

## Verifying this release

```sh
python scripts/version.py check-tag v2.8.4
git checkout v2.8.4
python scripts/release.py wheel-digest --output dist
```
