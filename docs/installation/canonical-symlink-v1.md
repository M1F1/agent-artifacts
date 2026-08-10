# Durable managed Symlink boundary v1

INS02 extends the canonical prepare/review/finalize boundary with explicit Symlink requests while
keeping Copy as the default. It does not switch the legacy CLI or TUI yet; LIFE01 and the TUI tasks
will call this application service after their lifecycle and review flows are ready.

## Managed object links

A managed link always targets the exact verified object selected by the marketplace plan:

```text
<data-root>/objects/sha256/<digest>/payload[/<file>]
```

The target is never a source mirror, moving `current` pointer, Git checkout, `site-packages`, or
virtual environment path. The plan validates the complete mapping from canonical `source_path` to
that exact object path. Tree links target `payload`; pure file links target their exact file below
`payload`. The object is already materialized outside the executable environment, so deleting and
recreating the Python installation does not affect the link.

Prepare performs bounded no-follow inspection of both destination and target. Target validation
resolves the reviewed boundary and rejects intermediate symlinks, escapes, missing content, unsafe
entry kinds, or bytes whose digest differs from the verified object. The immutable plan binds the
target path, tree/file kind, content digest, exact target snapshot, destination snapshot, semantics,
and requested mode.

## Actual and mixed modes

Only pure tree/file placement effects become links:

| Artifact/effect | Symlink request |
| --- | --- |
| skill payload | immutable tree link |
| guideline Markdown | immutable file link |
| hook payload | immutable tree link |
| hook registration | copied managed JSON merge |
| MCP registration | copied managed JSON merge |
| memory managed block/file | copied managed write |

The installation record retains `requested_mode: symlink` plus `actual_mode` on every effect. A
hook therefore records a visible mixed plan: linked payload and copied merge. Merge-only artifacts
remain valid when their manifest declares Symlink compatibility; they never pretend a link was
created.

## Explicit retarget and references

Source synchronization only publishes a new source snapshot/object. It never edits an installed
destination link. A later explicit prepare/review/finalize using the recorded qualified source can
select a replacement object.

When the existing destination is the previously recorded managed link, Finalize stages a new link
in the same directory and atomically replaces the old link. The old installed-object reference
remains live during the operation while a transaction reference retains the new object. State is
written after effects; the durable installed reference is then replaced with the new digest. Any
effect, state, reference, or postcondition failure restores the old link and state and leaves the
old installed reference authoritative.

Foreign or retargeted links conflict unless `force` was part of the reviewed request. Special files
remain unconditionally rejected. Copy retains its prior fail-closed handling of existing symlink
destinations.

## Link status evidence

Manifest-v2 link effects record the absolute target, `immutable-object` or `mutable-local`
semantics, canonical source path, target content digest, and destination ownership history. The
pure classifier reports:

- `current` — expected managed target exists;
- `mutable-local` — expected explicitly mutable target exists;
- `broken` — destination still names the expected target, but the target is unavailable;
- `retargeted` — destination is a symlink to another target;
- `replaced` — destination is absent or no longer a symlink.

LIFE01 will expose these values through status/check/update/uninstall and apply their force policy;
INS02 supplies the state evidence and pure classification without prematurely changing commands.

## Explicit mutable-local developer links

`mutable_local_payload_root` is an opt-in request field, valid only with Symlink and a selected
`source-local` source. The payload root must be lexically and physically inside that source, contain
the same reviewed bytes at Finalize, and contain no intermediate or nested symlink escape. Its link
effect records `mutable-local`, making the live-edit tradeoff distinguishable from immutable managed
links. After successful installation, edits below that checkout are intentionally visible through
the destination.

Mutable-local is never inferred from source kind, never used for Git/registry sources, and never
weakens the default immutable-object path.
