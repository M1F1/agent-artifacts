# Wheel reproducibility

From `2.2.0`, `agent_artifacts-<version>-py3-none-any.whl` is **byte-reproducible**: rebuilding the
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
shasum -a 256 dist/agent_artifacts-<version>-py3-none-any.whl
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
`make wheel` would — and prints `sha256:<hex>  <wheel filename>`. Running it at the tag and pasting
the line into the release notes is a step in each release checklist from v10 onward.
