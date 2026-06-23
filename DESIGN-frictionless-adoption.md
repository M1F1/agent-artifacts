# agent-artifacts - Design: paste-a-link upstream adoption

Companion to [DESIGN-upstream.md](DESIGN-upstream.md) and
[DESIGN-upstream-github-hosts.md](DESIGN-upstream-github-hosts.md).

**Status (2026-06-23):** Part B (`aart upstream add`) is **implemented and verified** —
`parse_github_url` + the command, with unit/command tests, mypy/ruff clean, and a live
end-to-end adoption of `mattpocock/skills` that round-trips as `up_to_date`. Part A remains a
recorded decision (no code). Open questions resolved with the proposed defaults
(first-segment-is-ref + `--ref` override; `--force` = overwrite destination; raw URLs deferred).

Two friction points were investigated while using the tool. One — the default catalog source —
turned out to already be handled for the supported install path and needs no build; it is
recorded here as a decision (Part A). The other — adopting an external artifact by pasting its
GitHub link — is the actual feature this document specifies (Part B). They are kept in one
document as a single workstream.

## 1. Goals and scope

**In scope**

- A pure helper that parses a GitHub **deep-link URL** (`/tree/<ref>/<path>`, `/blob/<ref>/<path>`)
  into `(repo, ref, path, host)`.
- `aart upstream add <type/name> <url>` — resolve, vendor into the catalog, and write the
  `upstreams.json` entry in one step.
- Record the default-source decision and one optional hardening (a clearer "no catalog" error).

**Out of scope (decided)**

- Non-editable install support (`pipx`, built wheel) without `--source`. `aart` is installed with
  `pip install -e .`; the editable default already serves that case (Part A). Making a wheel
  install self-contained would require bundling the catalog or a remote fallback — explicitly not
  pursued.
- Catalog auto-detection from the current directory, `$AART_SOURCE`/`$AART_REPO` env resolution,
  and a compiled-in remote fallback. All dropped as unnecessary for the `-e` workflow.
- Loosening the persisted `source.repo` contract (deep links are decomposed, never stored whole).
- GitLab/Bitbucket/SSH remotes; consumer-side multi-source.

---

## 2. Part A — Default source (decision: no change required)

**Finding.** With `pip install -e .`, `aart` already defaults the catalog source to the repo it
was installed from, from any working directory. `open_source` derives it as
`os.path.dirname(pkg_dir)` from `agent_artifacts.__file__` ([source.py:221](agent_artifacts/source.py:221));
the editable finder makes `__file__` resolve to the real checkout, so the default root is the
repo. Verified: `aart list` and `aart install` resolve to the repo with no `--source`, even run
from outside it. The original "`--source` required / `list` shows nothing" symptom reproduces only
under a **non-editable** install, where the package sits in `site-packages/` with no catalog
alongside it.

**Decision.** `aart` is installed editable; the existing behavior satisfies the requirement. No
catalog detection, env resolution, or remote fallback is added. The non-editable install case is
accepted as out of scope.

**Accepted limitation.** A `pipx`/wheel install has no catalog at the package directory and would
need `--source`. This is documented, not fixed.

**Optional hardening (not required for this workstream).**

- *Clearer empty-catalog error.* When the resolved default directory contains no catalog, commands
  currently produce a silent empty listing (`list`) or an "unknown artifact" error (`install`).
  A targeted message — `no catalog found at <dir>; pass --source DIR` — would turn the one
  confusing state into a self-explaining one, cheaply, without any resolution-logic change.
- *Recorded-source consistency.* `_common.DEFAULT_REPO`/`repo_of` record `M1F1/agent-artifacts`
  while `Source.label()` records `local:<abspath>`. Under `-e` this divergence is cosmetic (both
  name the same repo); left as-is unless it causes confusion.

---

## 3. Part B — Paste-a-link adoption (`aart upstream add`)

Resolves open question [DESIGN-upstream.md §11 Q3](DESIGN-upstream.md).

### 3.1 Current limitation

The browser URL for a skill is a **deep link** to its folder:

```
https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling
                   └──── repo ────┘ tree └ref┘ └────────── path ──────────────┘
```

It already carries the three fields an upstream needs — `repo`, `ref`, `path` — but
[`_parse_repo_url`](agent_artifacts/github_source.py) requires the path to be *exactly*
`owner/name` (`if len(raw_parts) != 2: Err("must identify exactly an owner and repository")`)
and rejects query/fragment outright. The "paste a browser URL" convenience the host design
intended ([DESIGN-upstream-github-hosts.md §3](DESIGN-upstream-github-hosts.md)) never covered the
realistic paste. Separately, there is no command to create an upstream entry — `aart upstream`
exposes only `check` and `update`.

### 3.2 Deep-link parsing contract

A new pure helper in [github_source.py](agent_artifacts/github_source.py), **separate from**
`_parse_repo` (which keeps its strict "exactly owner/name" contract for the `source.repo` field):

```python
@dataclass(frozen=True, slots=True)
class GitHubUrlParts:
    repo: str                  # owner/name
    ref: Optional[str]         # None for a bare repo-root URL
    path: Optional[str]        # None for a repo-root or branch-root URL
    is_file: Optional[bool]    # True for /blob, False for /tree, None when absent
    api_url: Optional[str]     # set for non-public hosts (per the hosts design)
    web_url: str

def parse_github_url(url: str) -> Result[GitHubUrlParts]: ...
```

**Recognized forms**

| Input | repo | ref | path | is_file |
| --- | --- | --- | --- | --- |
| `https://github.com/o/n` | `o/n` | — | — | — |
| `https://github.com/o/n.git` | `o/n` | — | — | — |
| `.../o/n/tree/main/skills/x` | `o/n` | `main` | `skills/x` | `False` |
| `.../o/n/blob/v1.2/guidelines/x.md` | `o/n` | `v1.2` | `guidelines/x.md` | `True` |
| `https://github.my-co.com/o/n/tree/main/skills/x` | `o/n` | `main` | `skills/x` | `False` |

Host derivation (api_url/web_url) reuses today's bare-URL rules. The parser is a strict superset
of `_parse_repo_url` for the first two rows.

- **Query/fragment are stripped, not rejected** (browser URLs carry `?plain=1`, `#L40`). This
  softening is *local* to `parse_github_url`; the persisted-metadata validators
  ([`_normalise_url`](agent_artifacts/github_source.py)) stay strict.
- **Slashed-ref ambiguity.** `.../tree/feature/login/skills/x` cannot be split from the string
  alone (GitHub resolves it server-side). The parser uses the only safe local rule — first
  segment after `tree`/`blob` is the ref, remainder is the path — correct for simple refs
  (`main`, tags, SHAs). The escape hatch is `--ref`/`--path` overrides (§3.3), and the command
  prints the resolved `repo@ref:path` so a wrong split is caught before write.
- **What stays strict.** `_parse_repo`/`resolve_github_location` are untouched. We do not teach
  `repo` to swallow extra segments — that would silently drop the ref/path a deep link carries
  (§3.4).

### 3.3 Command: `aart upstream add`

```
aart upstream add <type/name> <url> [--ref REF] [--path PATH] [--force] [--dry-run] [--json]
```

**Flow**

1. Parse the key ([`parse_upstream_key`](agent_artifacts/upstreams.py)) and the URL (§3.2). Merge
   `--ref`/`--path` overrides (flags win). Error if no ref or path can be determined.
2. **Type ↔ shape check.** `skill`/`hook` import directories (`tree`); `guideline`/`mcp`/`memory`
   import single files (`blob`) — the table in [DESIGN-upstream.md §4](DESIGN-upstream.md). A
   `blob` URL for a `skill` (or vice-versa) is rejected. A bare repo + flags carries no shape
   hint; rely on step 4.
3. Build an [`UpstreamSource`](agent_artifacts/upstreams.py) and resolve it through the existing
   [`resolve_upstream_source`](agent_artifacts/upstream_source.py) — which already resolves the
   ref to a SHA, materializes an immutable snapshot, locates the sub-`path` with an escape guard,
   and content-hashes the result. No new network or hashing code.
4. **Validate** the fetched content parses as the declared type, reusing `_validate_resolved`
   ([commands/upstream.py](agent_artifacts/commands/upstream.py)).
5. **Guards.** Destination exists (`skills/<name>/`, …) → `CONFLICT` unless `--force`. An
   `upstreams.json` entry for the key exists → `USAGE` pointing at `aart upstream update`, unless
   `--force`.
6. **Vendor + record** (executor-driven, JSON write last/atomic): [`CopyTree`](agent_artifacts/model.py)
   for directories / [`WriteFile`](agent_artifacts/model.py) for files into the catalog, then
   upsert the entry into `upstreams.json` (`last_synced = {sha, content_hash, synced_at}`) via
   [`dump_upstreams`](agent_artifacts/upstreams.py) + [`fs.write_atomic`](agent_artifacts/io/fs.py).
   Create `upstreams.json` if absent.
7. `--dry-run` prints the plan and touches nothing; `--json` mirrors the `check`/`update` result
   shape.

**Example**

```sh
$ aart upstream add skill/domain-modeling \
    https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling
Resolved mattpocock/skills@9f3c1ab (ref main)
Vendored skills/domain-modeling/  (4 files)
Tracked  skill/domain-modeling -> upstreams.json
```

The written entry is byte-identical to a hand-authored one, so `check`/`update` work immediately.

### 3.4 Why decompose instead of storing the URL

Storing the deep link verbatim in `source.repo` is rejected: `repo` means `owner/name` everywhere
(cache key, API paths, host derivation); overloading it forks that meaning and duplicates state
(the URL's `main`/path vs. the entry's `ref`/`path`, free to drift). Decomposing keeps one source
of truth per field and sidesteps the preserve-vs-canonicalize question — deep links always
canonicalize into the three fields, deterministically, covered by parse/dump tests.

### 3.5 Errors

Reuse the `_common` vocabulary (PLAN.md §7): `USAGE (2)` for a bad key, unparseable/ambiguous URL,
type↔shape mismatch, or an existing entry without `--force`; `NETWORK (3)` for resolve/fetch
failure; `CONFLICT (4)` for an existing destination without `--force`; `OK (0)` on success or
`--dry-run`.

---

## 4. Compatibility

- **Part A** changes nothing. The editable default is unchanged; the only possible additions are
  the optional error message and consistency note in §2, both behind explicit decision.
- **Part B** is purely additive. `parse_github_url` is new; `_parse_repo`/`resolve_github_location`
  are untouched, so every existing `repo` value still resolves. `add`-written `upstreams.json`
  round-trips identically to hand-written files.

## 5. Open questions

1. **Slashed-ref URL:** hard-error demanding `--ref` (safest) vs. guess-and-print the assumption
   (proposed).
2. **`add --force` overload:** one flag for both "overwrite destination" and "replace entry", or
   split? (Proposal: keep destination-overwrite; leave re-adoption to `update`.)
3. **`raw.githubusercontent.com/<o>/<n>/<ref>/<path>`** as a second recognized file-only form for
   `add` — include in v1 or defer?
4. **Ship the optional §2 error message** in this workstream, or leave Part A entirely untouched?
