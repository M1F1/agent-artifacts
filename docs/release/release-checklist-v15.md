# AART 2.6.1 release checklist and evidence

This patch release closes fifteen recorded findings and adds nothing. No command, no field, no
schema, no protocol version. The work was composed from
[`residue-register.md`](../testing/residue-register.md) during an unattended overnight run on
`2026-08-15`→`16`: the register's open rows were taken in priority order, each on its own branch,
each with a failing test first and — for anything larger than a message string or a document — a live
walk against a real locally built wheel.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v2.6.1
git checkout v2.6.1            # the stamp is taken from HEAD; a branch gives a different wheel
python scripts/release.py wheel-digest --output dist
```

The release check must pass repository/version evidence, schema freeze v15, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit, and
compatibility gates. The GitHub release must attach the wheel produced from the tagged commit, and
the release notes must carry the `sha256:<hex>  <wheel filename>` line
`python scripts/release.py wheel-digest` prints at the tag.

**`wheel-digest` now hands over the wheel it hashed** (`LAF-75`, closed in this release). `v14`'s
checklist had to warn that the command printed the digest of a wheel it then deleted while
`build_wheel.py` built a different one; `--output` writes the stamped artifact where the digest can
be checked against the file that is actually uploaded. Verify the attachment anyway — the check costs
one command and the failure it catches is a published lie:

```sh
shasum -a 256 <the file you attached>
curl -sL -o /tmp/published.whl <the release asset URL> && shasum -a 256 /tmp/published.whl
```

## Registry precondition

**None, in either direction.** No index field changes, no capability vocabulary changes, no module
added. A registry built on `2.6.0` validates on `2.6.1` and a registry built on `2.6.1` validates on
`2.6.0`. `release-check` is order-independent.

One default changes for a registry *being created*: `registry init` writes `>=2.6.1,<3.0.0` where the
wizard used to suggest `>=1.0.0,<2.0.0`. Existing registries are untouched.

## What closed

Fifteen findings, each with its own branch, test and — where the brief required one — its own live
acceptance record. The state of every one is in
[`residue-register.md`](../testing/residue-register.md), which `docs-check` enforces, and **not**
in this document; a second list is how the first stops being true.

| Finding | What an operator stops meeting |
|---|---|
| `RS-12` | a setup step that pulls a private base image can authenticate: the docker adapters get `HOME` and `DOCKER_CONFIG` |
| `LAF-75` | `wheel-digest` hands over the wheel whose digest it prints |
| `LAF-64` | the install-scope selector answers with one type, so a caller cannot read a choice as a cancel |
| `LAF-69` | the docs gate fails in both directions — a document that calls an open finding closed now fails too |
| `LAF-73` | `receipt verify` states the rollback command this executable accepts, from the record's own coordinates |
| `RS-09` | every `registry` refusal and every `validate`/`audit` finding carries a next step |
| `RS-07` | `marketplace status` reads the project after the last subscription is removed, and names the missing source |
| `LAF-45` | `audit --check-upstream` says it checked when everything is current |
| `RS-08` | a broken `aart-registry.json` fails the identity check instead of skipping it |
| `RS-01` | an `mcp` package written by hand is checked like a vendored one |
| `LAF-47`, `RS-10` | uninstall removes the merge file AART created and emptied, and never one that existed before |
| `RS-04` | the `vendor` refusal names `revendor`, the command that would work |
| `RS-02` | registry requests stop stamping a compatibility window from an AART that no longer runs |
| `LAF-49` | the Git environment AART gives a subprocess is documented |
| `LAF-90` | the wizard suggests a window the running executable is inside |

## Evidence

Nine quality gates green. `docs-check` carries one rule the previous release did not: `DOC010`, the
second direction of the register gate.

The v15 schema freeze differs from v14 in **one input and no protocol version**:
`agent_artifacts/setup.py`, where `rollback_command` was split so a persisted record can compose the
same sentence from its own coordinates. Verified rather than asserted: `protocol_versions` are equal
between `schema-freeze-v14.json` and `schema-freeze-v15.json`, and `setup.py` is the only
`schema_inputs` entry whose digest moved.

Ten live acceptance runs were walked for this release — `v4` through `v13` — each against a real
locally built wheel installed into a throwaway venv, with **no patched executable** and no
monkeypatching at the boundary. Nine of them walk both sides: a wheel built from the branch and a
wheel built from `main`, so the observation distinguishes the change rather than describing the
product. `v13` is the first run header in this repository written after `LAF-121`, and it names the
commit under test rather than the branch.

## Residues shipped open

Fifty-seven, of which one is `major` and two are `high`. That number is larger than at `2.6.0` and
the reason is worth stating plainly: the same overnight run that closed fifteen findings spent its
remaining budget measuring the product and the record, and measurement produces findings. Forty-six
of the open rows were written that night, most of them by walking commands nobody had walked cold or
reading a document against its own rules.

Four deserve naming here because they bound what this release, and this register, should be trusted
to do:

- `LAF-15` (`major`): `security scan` requires a canonical object envelope that **no `aart` command
  emits**. The scanner runs correctly when fed one by hand; nothing ships that produces one.
- `LAF-105`, `LAF-116`, `LAF-117`: the store's garbage collector exists, is specified, and has **no
  caller**. Meanwhile a plan-only review deposits objects, `marketplace status` deposits earlier, and
  `source remove` leaves the removed source's content on disk. Nothing an operator can run removes
  any of it.
- `LAF-85` (`high`): an unidentified writer touched the real data root during an unattended session
  on `2026-08-15`. Re-read read-only on `2026-08-16`: nothing has changed since, the trace is
  reproduced by an ordinary install-then-uninstall, and the first and more alarming reading was
  refuted. What wrote is still unknown.
- `LAF-101` (`high`): this register is itself incomplete. It was seeded from one walk's findings
  table and took the open rows, so three findings from that walk — two of them `major` — exist only
  as a sentence in a run log. Read the *shipped open* count above with that in mind.
