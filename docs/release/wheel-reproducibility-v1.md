# Wheel reproducibility

From `2.2.0`, `aart_cli-<version>-py3-none-any.whl` is **byte-reproducible**: rebuilding the
tagged commit anywhere produces an archive with the same sha256 digest, not merely the same
contents. Live acceptance `LAF-30` probed this by hand and it failed — two builds of one source
differed, because every archive member was dated from the build clock.

This is a standing promise, held by a test rather than by intent
(`tests/packaging_test.py::ReproducibleWheelTest`). Every later packaging change has to keep it.

## What is pinned

Poetry builds the wheel. `scripts/build_wheel.py` is the one place that invokes it, because
`poetry build` on its own does not hold this promise, and it is the script that closes each gap.

- **Member dates** are one constant, `2016-01-01`, which poetry-core writes into every member.
  They come from neither the clock nor the commit. Until
  `2.8.6` they came from the committer date `scripts/inject_commit.py` stamps into
  `agent_artifacts/_commit.py`; a constant is the stricter rule, because two commits an hour apart
  now differ only where their content differs.
- **`SOURCE_DATE_EPOCH` is removed from the environment before Poetry runs.** poetry-core honours
  it, and a digest an environment variable can move is a digest nobody can check: the publisher and
  the verifier would have to have set it the same way, and neither would know that they had to.
  This is the one guarantee that the change of builder would silently have taken away.
- **The builder's version is part of the archive.** `WHEEL` records
  `Generator: poetry-core <version>`, so an upgrade changes the digest of an unchanged commit.
  It is pinned exactly in `[build-system]`, installed at that same version by the dev group, and
  checked against the built file afterwards — so upgrading Poetry fails a build rather than
  quietly invalidating every digest already published.
- **Compression** is deflate; **create-system** is Unix, so a build on Windows cannot change the
  header.
- **Contents** are checked against the resource allowlist twice: once over the source before
  Poetry runs, and once over the archive Poetry produced. A stray file under `agent_artifacts/`
  fails the build instead of shipping inside it.

Member order is Poetry's and is no longer the sorted archive-name order. It is stable, which is
what byte-reproducibility needs; it is simply not a property this project chooses any more.

`tests/packaging_test.py::ReproducibleWheelTest` holds all of this, including a test that sets
`SOURCE_DATE_EPOCH` and asserts the bytes do not move.

## Building it needs Poetry

This is the cost of the change, stated plainly. Until `2.8.6` the wheel was built by the standard
library alone, and the only programs a fork's CI had to carry were git and an interpreter. Now it
must also carry Poetry. An image that keeps Poetry off `PATH` names it in the `AART_POETRY`
repository variable — `/opt/poetry/bin/poetry` is the usual place.

Poetry is needed for the *build* only. The quality gates install their tools with pip, from the
exact versions `poetry.lock` pins, because Poetry cannot install from a per-fork internal index:
it takes an install source only from a `[[tool.poetry.source]]` block inside `pyproject.toml`,
adding that block at run time changes the file's hash, and `poetry install` then refuses the lock.
`scripts/dev_tools.py` carries the lock's pins to pip, which reads `PIP_INDEX_URL` and always could.

## Verifying a published wheel

```sh
git checkout v<version>
make wheel
shasum -a 256 dist/aart_cli-<version>-py3-none-any.whl
```

Compare that digest with the one published beside the release artifact. `make wheel` runs
`scripts/inject_commit.py` first, which stamps the commit being verified into the source — the
stamp no longer dates the archive, but it is still content, so it is still part of the digest.

The verifier needs the pinned Poetry. Any other version builds a wheel whose `WHEEL` file names it,
and `scripts/build_wheel.py` refuses that build rather than printing a digest that will not match.

## Where the digest is published

The digest is a property of the tagged commit, so it cannot live inside it: writing it into a
tracked file would change the commit that determines it. It is therefore produced at the tag and
published with the release artifacts — the GitHub release's verification section — rather than
committed to this repository.

```sh
python scripts/release.py wheel-digest
```

The command builds the wheel this commit publishes in a throwaway copy — stamping `HEAD` exactly as
`make wheel` would — writes it into `dist/`, and prints two lines:

```
sha256:<hex>  aart_cli-<version>-py3-none-any.whl
wrote dist/aart_cli-<version>-py3-none-any.whl
```

**Attach the file it names.** The digest is read back from that file after it is written, so the
first line describes the second. `--output <dir>` writes it somewhere else instead.

Running the command at the tag, pasting the first line into the release notes, and attaching the
file named on the second is a step in each release checklist from v10 onward.

Until `2.6.0` the command hashed a wheel it then deleted, which left the publisher to produce the
attachment by a second route. `python scripts/build_wheel.py` alone is that second route and builds
a *different* file: the checkout carries no commit stamp, so `agent_artifacts/_commit.py` differs
and the digest does not match. `2.6.0` came within one `curl` of publishing a digest line that did
not describe its own attachment (`LAF-75`).
