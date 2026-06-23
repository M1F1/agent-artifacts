# agent-artifacts - Implementation Plan: per-upstream GitHub host metadata

Companion to [DESIGN-upstream-github-hosts.md](DESIGN-upstream-github-hosts.md) and GitHub
issue [#5](https://github.com/M1F1/agent-artifacts/issues/5).

This plan follows TDD: each work package starts by adding failing tests, then implements the
smallest production change that makes those tests pass.

## 1. Target behavior

Maintainers can track upstream artifacts from multiple GitHub hosts in one `upstreams.json`:

```json
{
  "version": 1,
  "artifacts": {
    "skill/public-demo": {
      "source": {
        "kind": "github",
        "repo": "openai/public-skills",
        "ref": "main",
        "path": "skills/public-demo"
      },
      "last_synced": {
        "sha": "abc123",
        "content_hash": "sha256:...",
        "synced_at": "2026-06-23T10:00:00Z"
      }
    },
    "skill/company-demo": {
      "source": {
        "kind": "github",
        "repo": "platform/company-skills",
        "api_url": "https://github.my-company.com/api/v3",
        "ref": "main",
        "path": "skills/company-demo"
      },
      "last_synced": {
        "sha": "def456",
        "content_hash": "sha256:...",
        "synced_at": "2026-06-23T10:00:00Z"
      }
    }
  }
}
```

`aart upstream check --all` resolves each artifact against its own host, preserves source
metadata during updates, and keeps snapshot caches host-qualified.

## 2. Parallelization shape

Use a short sequential bootstrap, then split into workers.

**Sequential bootstrap**

- Agree on the model fields and helper API:
  - `UpstreamSource.api_url: Optional[str] = None`
  - `UpstreamSource.web_url: Optional[str] = None`
  - `resolve_github_location(source) -> Result[GitHubSourceLocation]`
- Add the helper module or stubs before delegating implementation slices.

**Parallel workers after bootstrap**

- Worker A owns schema/model/parser/validation.
- Worker B owns network/resolver/cache.
- Worker C owns command JSON/docs/fixtures.

These write sets are mostly disjoint. Worker C should start with tests and may need to wait for
Worker A's model fields before final implementation.

## 3. Work packages

### WP-H1 - Schema, parser, dumper, validation

**Owns**

- `agent_artifacts/upstreams.py`
- optional new helper module such as `agent_artifacts/github_source.py`
- `tests/upstreams_test.py`
- `tests/upstream_validate_test.py`

**Tests first**

- Parse and dump an existing `owner/name` source unchanged.
- Parse and dump a source with `api_url`.
- Parse and dump a source with `web_url`.
- Accept `repo: "https://github.my-company.com/org/repo"`.
- Accept `repo: "https://github.com/org/repo.git"`.
- Reject malformed URLs, credentials in URLs, query strings, fragments, missing owner/repo, and
  unsupported schemes.
- Validate `api_url` independently from `repo`.
- Verify unknown source metadata is not silently dropped if the chosen behavior is to reject
  unknown fields; otherwise document and test preservation.

**Implementation**

- Add optional fields to `UpstreamSource`.
- Update `_parse_source` and `dump_upstreams`.
- Add pure GitHub source normalization.
- Update `validate_upstreams` to validate normalized GitHub locations.
- Keep all existing `owner/name` entries valid.

**Done when**

- `python -m unittest discover -s tests -p "upstreams_test.py" -v` passes.
- `python -m unittest discover -s tests -p "upstream_validate_test.py" -v` passes.

### WP-H2 - Network endpoint plumbing and host-qualified cache

**Owns**

- `agent_artifacts/io/net.py`
- `agent_artifacts/io/cache.py`
- `agent_artifacts/upstream_source.py`
- `tests/net_test.py`
- `tests/upstream_source_test.py`

**Tests first**

- `resolve_ref` builds public GitHub URLs by default.
- `resolve_ref`, `fetch_tarball`, and `compare` use a passed `api_url`.
- `GITHUB_API_URL` fallback still works when no per-call `api_url` is passed.
- `resolve_upstream_source` sends commit and tarball requests to the entry's `api_url`.
- A full web URL in `source.repo` is normalized before network calls.
- Public and enterprise entries with the same `owner/name@sha` use different cache paths.
- Existing cache reuse for the same host/repo/SHA still works.

**Implementation**

- Replace import-time `_API` use with a `default_api_url()` helper read at call time.
- Add optional `api_url` parameters to GitHub network helpers.
- In `resolve_upstream_source`, normalize the source once and pass:
  - normalized `repo` to API URL paths
  - normalized `api_url` to network helpers
  - host-qualified `cache_key` to the cache layer
- Keep opener injection unchanged.

**Done when**

- `python -m unittest discover -s tests -p "net_test.py" -v` passes.
- `python -m unittest discover -s tests -p "upstream_source_test.py" -v` passes.

### WP-H3 - Command output and metadata persistence

**Owns**

- `agent_artifacts/commands/upstream.py`
- `tests/upstream_json_test.py`
- `tests/upstream_command_test.py`

**Tests first**

- `aart upstream check --json` includes `api_url` and `web_url` for enterprise sources.
- Existing public GitHub JSON contracts remain compact or are updated intentionally.
- `aart upstream update --dry-run --json` reports enterprise host metadata.
- A real update rewrites `last_synced` without dropping `source.api_url` or `source.web_url`.
- A full URL in `source.repo` is preserved or canonicalized according to the final design choice.

**Implementation**

- Route status serialization through the normalization helper.
- Include host metadata in JSON only when useful or explicitly configured.
- Ensure `_with_updated_sync` preserves all source fields.
- Keep human output concise.

**Done when**

- `python -m unittest discover -s tests -p "upstream_json_test.py" -v` passes.
- `python -m unittest discover -s tests -p "upstream_command_test.py" -v` passes.

### WP-H4 - Fixtures and docs

**Owns**

- `tests/fixtures/upstreams/`
- `tests/upstream_fixtures_test.py`
- `README.md`
- `DESIGN-upstream.md`
- `DESIGN-upstream-github-hosts.md`

**Tests first**

- Add a fixture assertion that includes one enterprise source shape.
- If fixture hashes or golden snapshots exist, update them after the fixture change.

**Implementation**

- Add a minimal `api_url` example to README.
- Update the upstream design schema and network/cache sections.
- Link the focused host design from the broader upstream design.
- Document that consumers still update from the reviewed catalog repo.

**Done when**

- Fixture tests pass.
- README and design examples show both public and enterprise source shapes.

### WP-H5 - Integration and verification

**Owns**

- Whole feature integration.

**Tests first**

- Add or extend an end-to-end upstream test that runs against a mixed public/enterprise fake
  opener or fixture source.

**Implementation**

- Resolve any integration seams between workers.
- Make sure import hygiene still holds: consumer commands must not import upstream network code.

**Required verification**

```sh
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make test
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make validate
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make lint
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make typecheck
```

## 4. Suggested sub-agent dispatch

After the sequential bootstrap lands, dispatch at most three workers:

- **Worker A - schema contract**
  - Files: `agent_artifacts/upstreams.py`, optional `agent_artifacts/github_source.py`,
    `tests/upstreams_test.py`, `tests/upstream_validate_test.py`.
  - Deliverable: parse/dump/validation support for `api_url`, `web_url`, and full HTTPS repo
    URLs.

- **Worker B - network/cache contract**
  - Files: `agent_artifacts/io/net.py`, `agent_artifacts/io/cache.py`,
    `agent_artifacts/upstream_source.py`, `tests/net_test.py`,
    `tests/upstream_source_test.py`.
  - Deliverable: per-entry API endpoint use and host-qualified cache namespaces.

- **Worker C - command/docs contract**
  - Files: `agent_artifacts/commands/upstream.py`, `tests/upstream_json_test.py`,
    `tests/upstream_command_test.py`, `tests/fixtures/upstreams/`, `README.md`,
    `DESIGN-upstream.md`.
  - Deliverable: JSON output/persistence/docs updated for enterprise source metadata.

Worker C can write tests early, but final implementation may depend on Worker A's helper. The
integrating agent should review all changes, resolve any shared helper naming issues, and run
the full verification suite.

## 5. Risks and decisions to make during implementation

- **Preserve vs canonicalize full URL repo values.** Preserving the author-written value avoids
  surprising rewrites. Canonicalizing simplifies output. Pick one and test it.
- **HTTP URLs.** Strict HTTPS is safer for persisted metadata. Test-only HTTP can be avoided by
  using injected openers with HTTPS fake URLs.
- **Token behavior.** `GH_TOKEN` support is adjacent but not required for issue #5. Avoid
  expanding scope unless tests show the current upstream token flow is broken.
- **JSON contract churn.** Add host fields only for enterprise/custom host sources unless there
  is a strong reason to make every record include `api_url`.
- **Cache migration.** Existing public GitHub cache entries may move if the cache namespace
  changes. This is acceptable because snapshots are disposable, but the behavior should be
  mentioned in code comments or docs if visible.
