# Wheel reproducibility

From `2.2.0`, `aart_cli-<version>-py3-none-any.whl` is **byte-reproducible**: rebuilding the
tagged commit anywhere produces an archive with the same sha256 digest, not merely the same
contents. Live acceptance `LAF-30` probed this by hand and it failed — two builds of one source
differed, because every archive member was dated from the build clock.

This is a standing promise, held by a test rather than by intent
(`tests/packaging_test.py::ReproducibleWheelTest`). Every later packaging change has to keep it.

## What is pinned

- **Member dates** come from the committer date of the commit the build was stamped at, which
  `scripts/inject_commit.py` writes into `agent_artifacts/_commit.py` as `COMMIT_EPOCH`, and are
  written in UTC. A source with no stamp — an editable checkout, or a copy taken outside git —
  builds at `1980-01-01T00:00:00Z`, the earliest date a zip can hold, so dev builds are reproducible
  too.
- **Member order** is the sorted archive-name order, with `RECORD` last, rather than the order a
  directory walk returned.
- **Compression** is deflate at a fixed level; **permissions** are `0o600`; **create-system** is
  Unix, so a build on Windows cannot change the header.

Nothing in the build reads the clock, the environment, or the platform. In particular
`SOURCE_DATE_EPOCH` is deliberately **not** consulted: the commit stamp is the single source of the
date, so no environment can quietly move it.

## Verifying a published wheel

```sh
git checkout v<version>
make wheel
shasum -a 256 dist/aart_cli-<version>-py3-none-any.whl
```

Compare that digest with the one published beside the release artifact. `make wheel` runs
`scripts/inject_commit.py` first, which is what stamps the commit being verified.

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
a *different* file: the checkout carries no commit stamp, so its members are dated at the zip epoch
and the digest does not match. `2.6.0` came within one `curl` of publishing a digest line that did
not describe its own attachment (`LAF-75`).
