# AART 2.2.0

Live acceptance v2 ran forty scenarios against `2.1.0` and filed thirteen residues. This release
closes nine of them. There is no new feature here in the usual sense — what changed is that when
AART refuses, it now tells you which layer refused and which command fixes it, and that the review
you read is the one that gets applied.

## The review you read is the one that runs

Every review-first consumer command takes `--expect <review-digest>`, and `aart source resubscribe`
takes `--expect <from>:<to>`. Finalize proceeds only if the recomputed review still matches what you
read; otherwise it refuses and renders the new plan, in text and in JSON.

That was impossible until this release, for an unglamorous reason: the review digest was a clock.
`source_age_seconds` was part of the digested value, so two reviews of a completely unchanged
workspace, two seconds apart, disagreed. It is gone from the digest — and freshness, which is
information you actually want, is now rendered where it belongs: a `Source freshness:` line in the
text review and a `source_freshness` field beside `review` in JSON, never inside it.

`--yes` alone means exactly what it always meant.

## An identity change no longer orphans your installations

`2.1.0` let you adopt a source that re-declared its `source_id`. What it could not do was tell the
projects. Every artifact installed under the previous identity reported `source-unavailable`
forever, while the resubscription review promised the opposite.

The installation record was conflating two things. The subscription — alias, kind, origin, ref — is
what resolution follows; the identity the origin declares is evidence carried inside it. Split
apart, an intact subscription declaring a different identity is `identity-changed`, and
`aart marketplace update` acts on it in the project that owns the installation: the review states
both identities, finalize rebinds the record. One project, one review, one operator — the same shape
as every other reconciliation. The review field is digest-bound, so consent read for a rebinding to
one identity cannot apply a rebinding to another.

## Refusals that name the layer that failed

Three unrelated situations — an alias never configured, one configured but never synchronized, and a
cold cache read under `--offline` — all used to report `artifact-not-found` with empty remediation,
about the one part of your request that was never wrong. Each now names its own layer and carries a
next step. `artifact-not-found` survives for the case where it is true.

`aart marketplace uninstall` plans from the durable manifest instead of resolving through the source,
so removing a subscription no longer strands the artifacts installed from it. This is the one gate
this release loosens, and only here: uninstall is not a content operation — it reads what your
project already has.

A registry whose `aart-registry.json` and `aart-source.json` declare different identities is now
refused when it is acquired, naming both values and both files. That registry already failed
`registry validate --strict --frozen`; the consumer was the half that did not look. If your registry
passes its own maintainer gate, nothing changes for you.

A `requires` that cannot resolve says why. `skill/x requires missing skill/y` read as "not published
yet", so a maintainer waited for a publication that would never make the build pass. It now states
that the dependency must be published by this registry, distinguishes an identity the registry does
not publish from one it references from another origin, and carries remediation. The rule is
deliberate — a cross-registry dependency breaks whenever a maintainer who does not own the artifact
changes their own registry — and it is now written down in the registry protocol instead of being
discovered one build failure at a time.

## Every command AART names is one it accepts

`aart source sync` carried the `aart source resubscribe` line — the entire point of `2.1.0` — only
under `--json`. In text mode the renderer printed the message and dropped the fix. It no longer
does, and a parity test holds text and JSON to the same lines for every family that renders both.

The guard that was supposed to catch this could not: it only read `Diagnostic.remediation`, and none
of it was a diagnostic. It now parses every user-visible `aart …` mention in the shipped package
through the real CLI parser, and it found four more dead ends — the `aart setup` group renamed in
`2.0.0` and still offered as `retry` and `rollback`, `aart source add` without its required
`--kind`, and `aart registry init` without `--source-id` and `--display-name`.

One of them has no replacement: nothing reverses a completed setup. Rather than invent a verb, that
field now names the artifact, profile, and scope to undo from the recorded receipt and says plainly
that no command does it.

A busy source lock now reports how long the holder has held it, which pid on which host, whether
that pid is alive, and how wide the stale window is — the four facts that decide whether to wait.

## Uninstall leaves your repository as it found it

A checkout that was clean before an install was dirty after uninstalling everything: the emptied
`.agent-artifacts/manifest.json`, its lock, and the empty `.claude/skills` all survived, so
`git status` reported AART's own litter as your change. An uninstall now reclaims what it emptied —
its own profile directories, and the manifest and lock with the last record in a scope.

Two boundaries keep that safe. `rmdir` is the guard rather than a check in front of one, so a
directory holding anything the install did not put there refuses to be removed, without racing a
concurrent install. And a harness root such as `.claude` is never reclaimed at all: it is shared with
your agent, and no record proves an install created it.

## The wheel reproduces from the tag

Rebuilding the tagged commit anywhere now produces the same archive digest, not merely the same
member contents. Member dates come from the committer date of the commit the build was stamped at,
in UTC; member order, compression, permissions, and create-system are written explicitly rather than
taken from the build platform. `SOURCE_DATE_EPOCH` is deliberately not consulted — an environment
variable that silently moves the published bytes is the defect being removed, not a feature to add.

To verify this release:

```sh
git checkout v2.2.0
make wheel
shasum -a 256 dist/agent_artifacts-2.2.0-py3-none-any.whl
```

Compare the result with the digest published in this release's verification section.

## Upgrading

Nothing to do. No protocol revision, schema, store layout, or on-disk format changed, and `2.2.0`
writes nothing new — `identity-changed` is computed at reconciliation time, never stored. No
`requires_aart` window needs re-authoring; `>= 2.0.0, < 3.0.0` admits this release. A `2.2.0` data
root is fully readable by `2.1.0` and `2.0.0`.

The one behaviour to know about: uninstalling everything now removes the emptied `.agent-artifacts/`
directory it used to leave behind.

See the [2.2.0 compatibility matrix](compatibility-v10.md) and
[release evidence](release-checklist-v10.md).
