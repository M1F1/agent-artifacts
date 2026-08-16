# AART 2.6.1

Nothing is added. No command, no flag, no field, no schema, no protocol version. Fifteen recorded
defects stop happening, and that is the whole release.

It was composed the way this project has been saying releases should be composed: from
[`residue-register.md`](../testing/residue-register.md), the file that says what is open, taken in
priority order, one branch per finding, a failing test first, and — for anything larger than a
message string or a document — a live walk against a real locally built wheel installed into a
throwaway venv. No patched executable, no fakes, no monkeypatching at the boundary. Ten such runs,
`v4` through `v13`, nine of which walk both a wheel built from the branch and a wheel built from
`main`, so the record distinguishes the change instead of describing the product.

## The wizard wrote a registry it then refused to read

`aart registry init` asks two questions and offers the answers. Pressing return at both gave
`1.0.0` and `2.0.0`, and the command exited `0`, wrote `requires_aart {1.0.0, 2.0.0}`, and closed by
recommending four next commands. The first of them:

```text
$ aart registry validate
registry workspace is incompatible with this AART version
```

The suggested window stopped a whole major short of the executable that made the suggestion. Nothing
the operator typed was wrong.

The rule was already in the package — `RS-02`, earlier in this same release, had removed exactly
those two literals from every registry *request* and derived the window from the running executable.
The wizard was the one front-end that did not get it. Now both ask with the same two constants, and
the prompt shows what pressing return means before you press it:

```text
Minimum AART version [2.6.1]:
Maximum AART version (exclusive) [3.0.0]:
```

## A digest that described a wheel nobody received

`release wheel-digest` built a wheel in a temporary directory, hashed it, deleted it, and printed the
digest. The wheel an operator then uploaded came from `build_wheel.py` — a different invocation, a
different file. The published digest and the published artifact were never proved to be the same
bytes.

`--output` writes the wheel that was hashed, where it can be checked against the file that is
actually attached (`LAF-75`).

## A setup step could not reach the credentials you had already stored

The docker adapters ran with a sanitised environment that dropped `HOME` and `DOCKER_CONFIG`, so
`docker pull` from a private registry failed even though `docker login` had succeeded minutes
earlier, and the failure named neither variable. Both now reach the adapter (`RS-12`).

## Refusals say what to do next

Every `registry` refusal and every `validate`/`audit` finding named what was wrong and stopped
(`RS-09`). They now carry a next step. So does `vendor` on a package that already exists, which names
`revendor` — the command that would have worked (`RS-04`). And `marketplace status` on a project
whose last subscription was removed now names the missing source rather than reporting an empty
project (`RS-07`).

## Uninstall reclaims the file it created

`marketplace uninstall` emptied a `.mcp.json` or `.claude/settings.json` that AART had created for
the install, and left the empty file behind. It is now removed — and a file that existed *before* the
install is still never removed, on either version. That boundary is the whole point of the change and
is walked from both sides in live acceptance v11 (`LAF-47`, `RS-10`).

## The gate that checks the documents now fails in both directions

`docs-check` failed a document that listed as *shipped open* something the register had closed. It
passed a document that called an open finding `closed` — the direction that asserts a safety which is
not there. `DOC010` closes it, and it reproduces on a real case: the register moved a finding back to
`open` while two release documents kept saying `visible`, for a whole release, with the gate green
(`LAF-69`).

Also fixed: `receipt verify` states the rollback command *this* executable accepts, composed from the
record's own coordinates (`LAF-73`); `audit --check-upstream` says it checked when everything is
current (`LAF-45`); a malformed `aart-registry.json` fails the identity check instead of being
skipped as if absent (`RS-08`); an `mcp` package written by hand is checked like a vendored one
(`RS-01`); the install-scope selector answers with one type so a caller cannot read a choice as a
cancel (`LAF-64`); and the Git environment AART hands a subprocess is documented (`LAF-49`).

## Upgrading

Nothing to do, in either direction. No state migration, no re-`build`, no index recompilation. A
`2.6.0` data root is fully readable by `2.6.1` and a `2.6.1` data root is fully readable by `2.6.0`.
A registry built on either validates on the other.

**No obligation for a registry maintainer.** `registry init` writes a narrower default window for a
registry being *created* — `>=2.6.1,<3.0.0` instead of `>=1.0.0,<2.0.0` — and that is the repair.
An existing registry keeps whatever window it declares; nothing rewrites it.

The v15 schema freeze differs from v14 in one input — `agent_artifacts/setup.py`, where
`rollback_command` was split so a persisted record can compose the same sentence from its own
coordinates — and carries identical protocol versions. That is the machine-checked statement that no
boundary moved.

## Known defects shipped open

Fifty-seven, which is more than at `2.6.0`, and the reason should be said plainly: the run that
closed fifteen findings spent the rest of its budget walking commands nobody had walked cold and
reading documents against their own rules, and that produces findings. Forty-six of the open rows
were written that night.

Four bound what this release should be trusted to do:

- **`security scan` has no input** (`LAF-15`, `major`). It requires a canonical object envelope that
  no `aart` command emits. The scanner is correct when handed one; nothing ships that produces one.
- **Nothing removes anything from the object store** (`LAF-105`, `LAF-116`, `LAF-117`). The garbage
  collector exists and is specified, and has no caller — while a plan-only review deposits objects,
  `marketplace status` deposits earlier, and `source remove` leaves the removed source's content on
  disk.
- **An unidentified writer touched the real data root** during an unattended session (`LAF-85`,
  `high`). Re-read read-only the next day: nothing has changed since, the trace is reproduced by an
  ordinary install-then-uninstall, and the first and more alarming reading was refuted. What wrote is
  still unknown.
- **The register is itself incomplete** (`LAF-101`, `high`). It was seeded from one walk's findings
  table and took the open rows, so three findings from that walk — two of them `major` — exist only
  as a sentence in a run log. Read the count above with that in mind.

Everything else, with a disposition and — where something closed — the reproduction that closed it,
is in [`residue-register.md`](../testing/residue-register.md). `docs-check` fails if any current
plan, design or release document disagrees with it, now in both directions.

## Verifying this release

```sh
python scripts/version.py check-tag v2.6.1
git checkout v2.6.1
python scripts/release.py wheel-digest --output dist
```

The wheel attached to this release is byte-reproducible from the tagged commit, and — as of this
release — it is the same file whose digest the command prints. The digest is below.

## Not in this release

`LAF-15`, the garbage-collection cluster, and the input path that would feed `security scan` are
untouched. Each needs its own stream and its own design; folding any of them into a patch release
would have made this a list of features again.
