# AART 2.1.0

You could subscribe to a source. You could refresh it. You could not leave it, and you could not
follow it when it changed its name.

Live acceptance walked into the consequence. A registry was rebuilt and republished its declared
`source_id` at the same origin and the same ref. Every route out was refused, correctly and
uselessly: `sync` refused the identity change, `add` refused the alias, `add` under a new alias
refused the origin, and there was no `remove` and no way to adopt. The documented recovery was to
hand-edit `config.json` — and even that was not enough, because the identity check reads the managed
snapshot store, which is keyed by origin rather than by alias. The real recovery was to delete a
directory out of AART's own data root.

`2.1.0` gives that situation two commands and takes nothing away.

## `aart source remove`

Ends one subscription, and owns both places a subscription lives: the configuration entry and the
managed snapshot. If the alias was the default registry, that pointer is cleared too.

The snapshot is discarded before the configuration is written, deliberately. An interrupted removal
leaves a subscription whose snapshot is missing — which `aart source sync` repairs — rather than an
unsubscribed origin whose store still binds an identity nothing can reach. That was the second trap
in the original dead end, and this ordering is what keeps it from being rebuilt.

Your projects are not touched. An artifact installed from a removed source keeps its files and its
durable manifest and reconciles as `source-unavailable`; re-adding the alias restores it. A managed
symlink still resolves, because the object store is not the snapshot store.

## `aart source resubscribe`

Adopts a changed declared identity at an unchanged origin and ref, keeping alias, kind, location,
ref, and the default-registry flag. It writes no configuration at all, so those five are preserved by
construction rather than by being rewritten.

The review shows both sides:

```text
Source resubscription review:
  alias: registry
  kind: registry
  origin: github.com/acme/registry; ref: main
  identity: community-skills-registry -> acme-registry
  revision: 4f2c1ab -> 9d3e07b
  snapshot: 3a91c7f0e2d4 -> b58e1206aa73
  preserves: alias, kind, origin, ref, and the default-registry flag
  effect: publish the new snapshot and bind this alias to it
  keeps: every installed artifact and every file in every project
```

What you approve is the **transition**, not the destination. Finalize re-reads the origin and applies
that exact move or refuses — an upstream that changes again between your review and your `--yes` is
never absorbed silently. Resubscribing an identity that did not change is refused too, and names
`aart source sync`, which is the command you actually wanted.

Both commands are in the curses Sources stage as well, on `r` and `i`, dispatching the same
application requests as the flag-mode paths.

## Nothing was loosened

The identity check still refuses. It has to: installed artifacts carry coordinates keyed by source,
so re-pointing an alias at a different identity without review is a supply-chain swap. What changed
is that the refusal now names an operation that exists — and every remediation in this area is now
parsed by the real CLI parser in the test suite, so it cannot drift back into naming something the
executable does not have.

## Upgrading

Nothing to do. No protocol revision, schema, store layout, or on-disk format changed; the v9 schema
freeze is byte-identical to v8 in every declared input. No `requires_aart` window needs re-authoring
— `>= 2.0.0, < 3.0.0` admits this release. A `2.1.0` data root is fully readable by `2.0.0`.

See the [2.1.0 compatibility matrix](compatibility-v9.md) and
[release evidence](release-checklist-v9.md).
