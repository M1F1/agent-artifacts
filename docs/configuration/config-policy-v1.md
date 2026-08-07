# Configuration and organization policy v1

This document records the implemented CFG01 boundary. It refines
[`SPEC-aart-1.0.md` sections 7–8](../design/SPEC-aart-1.0.md) without wiring source acquisition or
the CLI/TUI, which are later tasks.

## Domain boundary

Configuration is split into four layers:

1. built-in defaults;
2. one user-writable `config.json`;
3. runtime CLI/environment overrides;
4. one administrator-provisioned organization policy, applied last as locked values and
   constraints.

Parsing, path resolution, precedence, policy decisions, first-run requests, and recovery planning
are pure. The application service receives explicit read/write/recover ports. Only
`agent_artifacts.io.config_store` touches the filesystem.

## User configuration

The strict schema-v1 object accepts `sources`, `default_registry`, `sync`, and `reporting` in
addition to required `schema_version`. Unknown fields, duplicate JSON keys, wrong types, unsafe Git
refs/URLs, relative local paths, and embedded URL credentials are rejected.

`sources` may be absent or empty. Supported source kinds are:

- `registry-git`: credential-free HTTPS, SSH URL, or `git@host:path` plus a Git ref;
- `source-git`: the same transport contract for a direct native source;
- `source-local`: a normalized absolute path and no Git ref.

If a Git ref is omitted it defaults to `main`. `default_registry` may be absent or `null`; when set,
it must name an enabled `registry-git` source. Reporting defaults to `disabled`, never infers a
destination from artifact origin, and requires an enabled registry alias when enabled.

Synchronization defaults to `auto` with a maximum age of 900 seconds. The canonical serializers
emit deterministic UTF-8 JSON with sorted object keys and one trailing newline.

## Organization policy

The separate strict schema-v1 policy supports:

- recommended and required source aliases;
- allowed Git hosts and repository path prefixes;
- enabling or denying direct sources;
- minimum trust for user-scope installation;
- allowed setup capabilities and custom setup-entrypoint policy;
- locked reporting mode/destination and denial of known public reporting hosts.

Recommended and required aliases cannot overlap. Policy constraints are evaluated after runtime
overrides and before any write/network performer. An override that conflicts with a locked field or
an effective configuration outside the source/reporting allow-list returns
`source-policy-denied`.

Setup/trust values are parsed and retained here; their operation-specific enforcement belongs to
the setup, marketplace, and installation tasks.

## First run and no-source behavior

Missing user configuration is valid. A local/non-content request receives immutable first-run
options derived from policy: recommended aliases, whether direct sources are permitted, and
whether continuing with no source is permitted. Required aliases are presented during interactive
first run without blocking the read-only wizard itself; they still block content commands and
writes until satisfied. Loading does not create files implicitly.

A content request with no enabled source fails with `no-source-configured` and remediation
`aart source add`. Help/version/local-status/uninstall-class callers set `content_required=false`
and therefore do not need a source or registry.

An invalid organization policy fails closed. An invalid user configuration cannot authorize a
content operation. For a non-content request, AART uses safe empty defaults and returns an explicit
recovery plan containing only path/digests/replacement bytes—never corrupt content in diagnostics.

## Platform paths and persistence

The pure resolver receives platform, home/XDG values, and independent test overrides; it never
reads the process environment.

| Value | macOS | Linux fallback |
| --- | --- | --- |
| config/data | `~/Library/Application Support/agent-artifacts` | `~/.config/agent-artifacts/config.json` and `~/.local/share/agent-artifacts` |
| cache | `~/Library/Caches/agent-artifacts` | `~/.cache/agent-artifacts` |
| policy | `/Library/Application Support/agent-artifacts/policy.json` | `/etc/agent-artifacts/policy.json` |

Linux honors injected XDG config/data/cache roots. Tests use only explicit fake roots or temporary
directories and never resolve the real user home.

Writes create a same-directory private stage file, flush and `fsync` its bytes, atomically replace
the target, set mode `0600`, and `fsync` the directory. A failure before replacement preserves the
prior target and cleans the stage best-effort; a post-replacement durability failure is reported as
an error. Recovery first verifies the corrupt document digest, writes an exact private backup, and
only then atomically installs canonical safe defaults.
