# agent-artifacts - Design: per-upstream GitHub host metadata

Companion to [DESIGN-upstream.md](DESIGN-upstream.md) and GitHub issue
[#5](https://github.com/M1F1/agent-artifacts/issues/5).

The upstream tracking feature currently assumes one GitHub API host for all tracked sources.
That is enough for public GitHub or for a single GitHub Enterprise Server configured through
`GITHUB_API_URL`, but it is not enough for a mixed catalog that tracks artifacts from several
GitHub hosts.

This design keeps the existing review boundary intact: catalog maintainers may check and import
from many upstream repos, but consumers still install and update from one curated
agent-artifacts catalog repo.

## 1. Goal and scope

Add first-class per-upstream GitHub host metadata to `upstreams.json`.

**In scope**

- Keep existing `repo: "owner/name"` entries working unchanged.
- Allow a source entry to specify its own GitHub API endpoint.
- Allow HTTPS GitHub web URLs as a convenience for non-public GitHub hosts.
- Support mixed catalogs where one artifact tracks public GitHub and another tracks GitHub
  Enterprise Server.
- Preserve source metadata when `aart upstream update` rewrites `last_synced`.
- Avoid cache collisions between identical `owner/name@sha` values on different hosts.
- Preserve the zero-runtime-dependency rule.

**Out of scope**

- GitLab, Bitbucket, generic Git remotes, SSH remotes, or local mirror sources.
- Per-host credential stores. The existing token story remains environment based.
- Consumer-side multi-source update.
- Automatic PR creation.

## 2. Current limitation

Today the source model is:

```json
{
  "kind": "github",
  "repo": "example/review-skills",
  "ref": "main",
  "path": "skills/code-review"
}
```

The implementation validates `repo` as `owner/name`, then uses a module-level API root from
`GITHUB_API_URL` or `https://api.github.com`. That means a process can target public GitHub or
one enterprise host, but not both at the same time unless every network call is externally
rewired.

There is also a cache concern. Snapshots are cached by `repo` and SHA today. If two hosts both
have `acme/widgets` at the same SHA string, they would share a cache namespace unless host
identity becomes part of the cache key.

## 3. Source schema

The preferred persisted shape remains compact:

```json
{
  "kind": "github",
  "repo": "platform/agent-skills",
  "api_url": "https://github.my-company.com/api/v3",
  "ref": "main",
  "path": "skills/code-review"
}
```

`source.api_url` is optional. When omitted, the resolver uses the existing default behavior:
`GITHUB_API_URL` if present, otherwise `https://api.github.com`.

For operator convenience, `source.repo` may also be an HTTPS GitHub web URL:

```json
{
  "kind": "github",
  "repo": "https://github.my-company.com/platform/agent-skills",
  "ref": "main",
  "path": "skills/code-review"
}
```

The URL form is normalized for execution:

- repo slug: `platform/agent-skills`
- API URL: `https://github.my-company.com/api/v3`
- web URL: `https://github.my-company.com/platform/agent-skills`

If both a full `repo` URL and `api_url` are provided, the explicit `api_url` wins. This handles
enterprise deployments where the API path is not the standard `/api/v3`.

An optional `web_url` may be supported for display and diagnostics:

```json
{
  "kind": "github",
  "repo": "platform/agent-skills",
  "api_url": "https://github.my-company.com/api/v3",
  "web_url": "https://github.my-company.com/platform/agent-skills",
  "ref": "main",
  "path": "skills/code-review"
}
```

The canonical documented form should be `repo: "owner/name"` plus `api_url` for enterprise
hosts. The full URL form is accepted so maintainers can paste a browser URL without needing to
know the API endpoint pattern.

## 4. Normalization contract

Introduce a small pure helper that turns `UpstreamSource` into a resolved GitHub location:

```python
@dataclass(frozen=True, slots=True)
class GitHubSourceLocation:
    repo: str          # owner/name
    api_url: str       # normalized, no trailing slash
    web_url: str       # best-effort display URL
    cache_key: str     # host-qualified, filesystem-safe namespace
```

Rules:

- `repo: "owner/name"` remains valid.
- `repo: "https://github.com/owner/name"` resolves to public GitHub.
- `repo: "https://github.com/owner/name.git"` resolves to public GitHub.
- `repo: "https://github.my-company.com/owner/name"` resolves to
  `https://github.my-company.com/api/v3`.
- URLs must not contain credentials, query strings, or fragments.
- URLs must identify exactly an owner and repo after trimming one optional `.git` suffix.
- `api_url`, when present, must be an absolute HTTP(S) URL with no query or fragment.
- Persisted secrets are forbidden. Tokens remain environment variables.

The helper should be used by validation, upstream source resolution, JSON output, and any future
command that needs to display a source.

## 5. Network behavior

Network calls should stop relying on one import-time `_API` value. Instead, the API root should
flow into each call:

```python
resolve_ref(repo, ref, api_url=location.api_url, token=token, opener=opener)
fetch_tarball(repo, sha, api_url=location.api_url, token=token, opener=opener)
compare(repo, base, head, api_url=location.api_url, token=token, opener=opener)
```

When `api_url` is not passed, these helpers should preserve the existing fallback:

1. `GITHUB_API_URL`
2. `https://api.github.com`

This keeps existing consumer and maintainer behavior stable while allowing upstream tracking to
choose a host per artifact.

## 6. Cache behavior

The snapshot cache must include host identity, not only `owner/name`.

Good cache namespaces:

```text
github.com/acme/widgets
github.my-company.com/acme/widgets
```

The filesystem path may still sanitize separators, but the logical key must include the host so
two different hosts cannot share one immutable snapshot directory accidentally.

The resolved location's `cache_key` should be passed to the cache layer while the normalized
`repo` slug is passed to GitHub API URLs.

## 7. JSON and human output

Existing JSON fields should remain:

```json
{
  "artifact": "skill/code-review",
  "repo": "platform/agent-skills",
  "ref": "main",
  "path": "skills/code-review"
}
```

For non-default or explicitly configured hosts, JSON should include machine-readable host
metadata:

```json
{
  "artifact": "skill/code-review",
  "repo": "platform/agent-skills",
  "api_url": "https://github.my-company.com/api/v3",
  "web_url": "https://github.my-company.com/platform/agent-skills",
  "ref": "main",
  "path": "skills/code-review"
}
```

For standard public GitHub `owner/name` entries without explicit host metadata, output may keep
the old compact shape to avoid noisy contract churn.

Human output should continue to favor concise `repo@ref` labels. If a source uses a non-default
host, diagnostics should include the host when it helps disambiguate.

## 8. Persistence behavior

`aart upstream update` rewrites `upstreams.json` after successful updates. It must preserve:

- `source.api_url`
- `source.web_url`
- a full URL in `source.repo`, if the implementation chooses to preserve the author-written
  form

If the implementation canonicalizes full URL `repo` values into `repo: "owner/name"` plus
`api_url`, that behavior must be explicit, deterministic, and covered by parse/dump tests.
Preserving the author-written form is less surprising for a focused issue.

## 9. Compatibility

Existing entries remain valid:

```json
"repo": "example/review-skills"
```

Existing global enterprise workflows remain valid:

```sh
GITHUB_API_URL=https://github.my-company.com/api/v3 aart upstream check --all
```

Mixed catalogs should prefer explicit per-source `api_url` values and avoid relying on a global
host override.

## 10. Open questions

1. Should the dumper preserve a full `repo` URL exactly, or canonicalize it into `repo` plus
   `api_url`?
2. Should `web_url` be persisted, derived only for output, or omitted until a real UI needs it?
3. Should `GH_TOKEN` be accepted alongside `GITHUB_TOKEN` in upstream commands? This is adjacent
   to the host work but not required to solve per-source API URLs.
4. Should HTTP `api_url` values be allowed only in tests, or rejected everywhere in persisted
   metadata?
