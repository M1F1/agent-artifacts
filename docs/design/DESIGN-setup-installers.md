# Design: reviewed macOS setup installers

Status: implemented for issue #20

## 1. Context and decisions

Copying an artifact can leave a harness unusable when credentials, Keychain entries, shell
lookups, external tools, or activation steps are still missing. A prose `SETUP.md` is useful
reference material, but it cannot give the TUI a reviewable plan, durable status, an ordered
queue, or a safe retry command.

Issue #20 adds a versioned setup protocol whose primary form is static data interpreted by the
reviewed `aart` runtime. An optional custom `install.sh` remains an explicit `custom-code`
escape hatch. The authoring skill is not a security boundary: catalog validation, capability
checks, source/hash binding, consent, module implementations, state redaction, and tests enforce
the contract.

The initial delivery makes these decisions:

- `setup/installer.json` is canonical; `SETUP.md` is optional reference only.
- Setup belongs to a directory-shaped artifact package. Flat guideline/memory/MCP files cannot
  declare executable setup.
- Core artifact installation finishes before setup starts. Setup failure never rolls back an
  earlier successful artifact install or an earlier configured queue item.
- One queue item is `(artifact type/name, profile, scope, installed source identity)`.
- Every item reaches a terminal state before the queue advances or stops.
- Setup state is separate from the artifact manifest and contains no input values or command
  output.
- #20 exposes immutable queue/review data that #21 will include in its persistent wizard Review.
  #20 does not implement #21's full back-navigation state machine.

## 2. Goals and non-goals

### Goals

- Parse and validate a static, versioned recipe before any custom code executes.
- Derive exact effects and capabilities through pure planning.
- Bind apply to the reviewed source, installer hash, and plan hash.
- Run setup-capable selections sequentially after a successful TUI Install.
- Give text and curses flows the same terminal-safe queue runner after curses teardown.
- Add `aart setup run|retry|status|rollback` over the same core.
- Provide shared modules for Keychain, managed shell blocks, managed JSON, directories, pinned
  Docker pulls, verification commands, and restart notices.
- Support an optional thin custom entrypoint with `plan`, `apply`, `verify`, and `rollback`
  actions, a minimal environment, controlled working directory, and structured result file.
- Record non-secret status, source/hash/version data, receipts, timestamps, and exit status.
- Use fake homes, fake Keychain/Docker/process adapters, and synthetic secrets in tests.
- Ship an `author-aart-installer` skill with the schema, module catalog, templates, validator, and
  test workflow.

### Non-goals

- Export environment variables into the parent TUI process; subprocesses cannot do this.
- Store a credential in argv, ordinary environment variables, plans, state, receipts, logs,
  backups, stdout, stderr, or JSON.
- Treat arbitrary remote bytes as trusted merely because they downloaded successfully.
- Silently install Docker, packages, or tools.
- Use `curl | sh`, floating Docker tags, or shell-string execution.
- Replace the project/user manifest introduced by #19.
- Implement the persistent wizard/session model from #21.

## 3. Artifact convention

Directory package:

```text
mcp/atlassian/
├── mcp.json
├── SETUP.md                    # optional human reference
└── setup/
    ├── installer.json          # required static recipe
    └── install.sh              # optional custom-code escape hatch
```

`installer.json` schema version 1:

```json
{
  "schema_version": 1,
  "protocol_version": 1,
  "artifact": "mcp/atlassian",
  "purpose": "Configure optional Atlassian API-token access for the selected harness.",
  "platforms": ["darwin"],
  "help_urls": [
    {
      "label": "Create an Atlassian API token",
      "url": "https://id.atlassian.com/manage-profile/security/api-tokens"
    }
  ],
  "required_tools": ["/usr/bin/security"],
  "capabilities": ["keychain", "filesystem", "process"],
  "inputs": [
    {
      "id": "api_token",
      "type": "secret",
      "prompt": "Paste the Atlassian API token",
      "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens"
    }
  ],
  "steps": [
    {
      "id": "token",
      "use": "macos-keychain.store@1",
      "with": {
        "input": "api_token",
        "service": "aart/mcp/atlassian",
        "account": "default"
      }
    },
    {
      "id": "shell",
      "use": "shell.env-from-keychain@1",
      "with": {
        "file": "~/.zshrc",
        "variables": {
          "ATLASSIAN_API_TOKEN": {
            "service": "aart/mcp/atlassian",
            "account": "default"
          }
        }
      }
    },
    {
      "id": "restart",
      "use": "restart.notice@1",
      "with": {"message": "Open a new shell and restart the harness."}
    }
  ]
}
```

Validation is strict and closed-world:

- unknown top-level fields, modules, module versions, step fields, or capabilities are errors;
- identity must exactly equal the containing artifact's `TYPE/NAME`;
- `purpose`, prompts, labels, and URLs are non-empty single-line strings;
- only `https` help/documentation URLs are accepted;
- input IDs, step IDs, and environment-variable names use constrained identifiers;
- every secret reference names a declared `type=secret` input;
- every module's required capability is declared;
- file targets and commands are statically declared and become resolved plan effects;
- Docker images must use an immutable `@sha256:` digest;
- `custom_entrypoint`, when present, is a relative regular file below `setup/`, cannot traverse or
  escape the package, and requires `custom-code` plus `process` capabilities.

The parser stores no secret values. A recipe hash is SHA-256 over the exact
`setup/installer.json` bytes; a custom hash additionally binds the exact entrypoint bytes.

## 4. Immutable domain and functional core

```text
SetupInstaller
  schema/protocol version, artifact key, purpose, platforms
  help URLs, required tools, declared capabilities
  inputs, steps, optional custom entrypoint
  descriptor/custom hashes and source-relative paths

SetupQueueItem
  artifact/profile/scope
  installed source + subscription
  resolved package root and installer

SetupEffect
  step/module, exact non-secret target/command, capability
  reversibility and recovery description

SetupPlan
  queue item + stable effects + plan hash

SetupResult
  terminal state, non-secret details, effects/receipts
  installer/plan hashes, timestamps, exit status, retry command
```

Pure functions own:

- schema parsing and validation;
- artifact-to-installer attachment;
- selected-artifact/profile queue derivation in stable selection order;
- home/profile placeholder resolution;
- capability and prerequisite planning;
- canonical plan hashing;
- terminal-state transitions and queue continuation/stop decisions;
- managed-block and structured-JSON transforms;
- state serialization/redaction and human/JSON projections.

Adapters own filesystem, Keychain, subprocess, platform, clock, terminal input, and consent.
No planner reads `HOME`, `sys.platform`, Keychain, the network, or a terminal.

## 5. Module catalog v1

| Module | Capability | Plan/apply/verify/rollback contract |
|---|---|---|
| `macos-keychain.store@1` | `keychain` | Prompt without echo; add/update a generic password; verify existence without reading the value; delete only a newly-created item on rollback. Replacement requires separate consent and is disclosed as not automatically reversible. |
| `shell.env-from-keychain@1` | `filesystem` | Resolve one explicit shell file; atomically insert/replace an artifact-owned block containing only quoted Keychain lookup commands; verify marker and exact block; rollback only that block while preserving later unrelated edits. |
| `file.managed-block@1` | `filesystem` | Insert/replace one marker-owned non-secret block; reject symlinks; atomically write and preserve mode; rollback only if ownership proof still matches. |
| `json.managed-merge@1` | `filesystem` | Resolve an explicit JSON file/path/key, show a structured diff, update atomically, preserve foreign keys, and rollback only the owned value if it still matches. Secret input references are forbidden. |
| `directory.create@1` | `filesystem` | Create one explicit directory; remove it on rollback only when this run created it and it remains empty. |
| `docker.pull@1` | `docker`, `network`, `process` | Require Docker to exist; inspect first; show official URL, digest-pinned image, and exact argv; pull only after granular consent; never remove an image that pre-existed and report manual cleanup for new shared images. |
| `command.verify@1` | `process` | Execute a fixed argv with `shell=False`, timeout, controlled cwd, minimal environment, and redacted/capped output. No secret interpolation. |
| `restart.notice@1` | none | Emit a non-mutating activation/restart instruction into the receipt and final summary. |

Module steps run in declared order. On apply failure or cancellation, the current installer rolls
back completed reversible steps in reverse order. Rollback never touches successful earlier queue
items. Any incomplete compensation changes the state to `rollback_incomplete` and lists manual
recovery.

## 6. Keychain and secret channel

Apple documents Keychain as the protected store for passwords and short secret values. The
installed macOS `/usr/bin/security help add-generic-password` also states that supplying a value
with `-p`/`-w` is insecure and that a trailing value-less `-w` prompts for it. Production therefore
invokes an argv containing service/account metadata only and lets the Keychain tool own the hidden
credential prompt. It never captures the value.

The adapter uses:

```text
/usr/bin/security add-generic-password [-U only for reviewed replacement] -a ACCOUNT -s SERVICE -w
```

with `-w` last and no following argv value. The default preserve-existing plan omits `-U`; an
explicit `replace_existing` plan discloses that replacement is not automatically reversible.
Existence/verification calls omit `-g` and `-w`, so
they do not print the secret. Tests use a fake Keychain executable/adapter and a PTY-like hidden
input harness; they assert the synthetic secret is absent from argv, environment snapshots,
captured output, state, receipts, backups, and errors.

The managed `.zshrc` block contains a lookup command, never the credential:

```sh
# >>> aart setup: mcp/atlassian@tabnine >>>
export ATLASSIAN_API_TOKEN="$(/usr/bin/security find-generic-password -a 'default' -s 'aart/mcp/atlassian' -w 2>/dev/null)"
# <<< aart setup: mcp/atlassian@tabnine <<<
```

This protects the value at rest in Keychain, but a new shell places it in process environment and
children inherit it. The review and final notice state that limitation. A subprocess cannot export
into the parent TUI, and GUI apps may not source `.zshrc`; the recipe must provide the applicable
restart/activation notice.

Primary references checked on 2026-08-06:

- Apple [Keychain data protection](https://support.apple.com/guide/security/keychain-data-protection-secb0694df1a/web)
  and [generic-password item identity](https://developer.apple.com/documentation/security/ksecclassgenericpassword).
- Apple [adding a password to Keychain](https://developer.apple.com/documentation/security/adding-a-password-to-the-keychain).
- Atlassian [Rovo MCP getting started](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/),
  [authentication guidance](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/authentication-and-authorization/),
  and [API-token configuration](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-authentication-via-api-token/).
- Atlassian [API-token management](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account).

Atlassian currently recommends OAuth 2.1 for interactive Rovo MCP use and permits API tokens for
enabled non-interactive scenarios. The representative test fixture demonstrates the optional
token/Keychain path; documentation recommends OAuth first. It does not invent a Docker dependency
for Atlassian's official remote server. Docker is covered by a separate generic module fixture.

## 7. Source trust, plan binding, and custom entrypoints

A queue item is created only from an artifact that was parsed from the same `Source` used for the
successful core install. The runner records and rechecks:

- artifact key and installed profile/scope;
- source label and subscription;
- absolute source package path;
- recipe and optional script hashes;
- resolved non-secret effects and plan hash.

Before apply, the user sees artifact, profile/scope, source identity, recipe/custom script path,
hashes, required capabilities, URLs, exact file/Keychain/Docker/command effects, reversibility,
and restart limitations. Consent defaults to No. If any bound value changes, apply is refused and a
new plan/review is required.

Remote sources are materialized to an immutable content-addressed snapshot. No setup runs while
bytes are being fetched or parsed. The static recipe is validated first, then the explicit review
turns that exact SHA/hash into the approved plan. Custom code never runs merely because a remote
catalog was listed or installed in flag mode.

Optional `install.sh` contract:

```text
install.sh plan --json --result RESULT_PATH
install.sh apply --plan-hash HASH --result RESULT_PATH
install.sh verify --json --result RESULT_PATH
install.sh rollback --receipt RECEIPT_PATH --result RESULT_PATH
```

The runner calls the absolute, hash-verified script without `shell=True`, from a private
`setup-runs/<run-id>/` directory with `0700` permissions. Its environment is an allowlist
(`PATH`, locale, terminal identifiers, `AART_SETUP_*` non-secret metadata); it does not inherit
credential variables or broad environment state. Output is capped and redacted, and the script
must write a validated non-secret result object. The runner snapshots the controlled directory
around `plan` and rejects a plan that mutates it. Static plans cannot prove arbitrary custom code
safe; custom code remains a reviewed capability and escape hatch, not the default module path.

## 8. State, receipts, and rollback

Scope-specific paths reuse #19's state root:

```text
project: <project>/.agent-artifacts/setup-state.json
         <project>/.agent-artifacts/setup-runs/<run-id>/receipt.json

user:    <home>/.agent-artifacts/setup-state.json
         <home>/.agent-artifacts/setup-runs/<run-id>/receipt.json
```

State identity is `(artifact type/name, profile, scope)`, so multiple harnesses cannot overwrite
one another. Each record contains only:

- terminal status and non-secret detail;
- source/subscription and resolved installer/script paths;
- schema/protocol version and hashes;
- plan hash, started/finished timestamps, and exit status;
- non-secret receipt/effect summaries, reversibility, and recovery instructions;
- safe retry and rollback commands.

It never contains input values, Keychain output, subprocess stdout/stderr, environment dumps,
merged credential headers, or complete user-file backups. Managed-file receipts retain only the
prior owned block/value, hashes, existence/mode, and stable marker/key. Atomic state writes occur
after every terminal item, so interruption does not lose earlier queue results.

Protocol v1 deliberately uses this ownership journal instead of copying whole user files into a
backup directory. A whole `.zshrc` or harness JSON backup could duplicate unrelated credentials;
the minimal prior owned block plus an atomic write is sufficient for conflict-aware rollback
without creating a second secret store.

Terminal states:

```text
configured | already_configured | cancelled | skipped | unsupported
prerequisite_missing | apply_failed_rolled_back | rollback_incomplete
verification_failed
```

`configured` and `already_configured` are complete. Every other state is incomplete and receives
a retry command. Rollback is offered only when a receipt exists and states its limitations.

## 9. CLI and TUI flows

CLI:

```sh
aart setup run mcp/atlassian --profile tabnine --scope user
aart setup retry --profile tabnine --scope user
aart setup status --scope user --json
aart setup rollback mcp/atlassian --profile tabnine --scope user
```

`run` requires explicit installed artifact keys; `retry` defaults to every incomplete record in
stable state order and may be narrowed. `status` is local-only. `rollback` requires an existing
receipt. Source overrides follow normal catalog rules; a selected setup item must still match the
installed manifest entry and reviewed source identity.

Current TUI Install sequence becomes:

```text
Harness -> Action -> Scope -> Mode -> Artifacts ->
confirmation including ordered setup queue -> Finalize core install -> setup queue -> summary
```

The existing Install confirmation gains immutable setup queue rows. After core success, the TUI
has already left curses full-screen mode, so both frontends hand the controlling terminal directly
to setup. Each entry is planned/reviewed/consented/applied/verified/recorded before the next.
Failure/cancellation defaults to continuing; an explicit Stop marks every unstarted entry skipped.

Final output separates artifact installation from setup states and lists every retry command.
When incomplete items remain, `Retry incomplete setup now? [Y/n]` is preselected. #21 will move the
same queue facts into its persistent basket/Review without changing runner semantics.

## 10. DDD boundaries and safety invariants

- Aggregate: one setup queue; each item is its own transaction boundary.
- Entities/values: immutable installer, queue item, plan, effect, result, state record.
- Domain services: validation, queue derivation, planning, hashing, state transitions,
  managed-block/JSON transforms, redaction.
- Application service: resolve installed source -> plan -> review -> consent -> apply -> verify ->
  receipt/state -> next item.
- Adapters: filesystem, Keychain, Docker/process, platform/clock, terminal.
- Anti-corruption boundary: TUI and CLI create one setup request and consume structured results;
  neither parses script prose or mutates config directly.

Hard invariants:

- No mutation before validated plan and explicit consent.
- No secret in serialized or observable channels.
- No `shell=True`, string command, unsafe path traversal, symlink target edit, or broad inherited
  environment.
- No queue item left without a terminal state.
- No rollback crosses item/profile/scope ownership.
- No automatic custom-code execution from catalog scan, flag-mode install, or unreviewed fetch.

## 11. Acceptance mapping

- Convention/schema/custom escape hatch: sections 3 and 7.
- Shared runtime, modules, transaction/rollback: sections 5 and 8.
- Hidden Keychain input and secret guarantees: section 6.
- Queue ordering, terminal states, continue/stop, retry: sections 8 and 9.
- Source identity, review, consent, controlled execution: section 7.
- CLI run/retry/status/rollback: section 9.
- Non-macOS behavior: sections 3, 5, and terminal `unsupported` state.
- Fake adapter/installers, idempotency, failure/cancel/rollback/redaction: implementation plan.
- Atlassian example and current official guidance: section 6.
- #21 review integration seam: sections 1 and 9.
