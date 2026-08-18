# Setup recipe v2 — module reference

A setup recipe is a declarative document at `<package>/setup/installer.json`. It does not describe
code; it selects from a closed set of modules that AART already implements, and supplies each one's
fields. A module AART does not know is refused by name, so an older executable fails closed rather
than guessing.

Every setup-bearing package must also ship a package-root `SETUP.md`. **The recipe is the guided
route and never the only route**: the review renders the manual alternative before consent and again
after an incomplete outcome. Each module below therefore states the command a person runs to reach
the same result by hand. A module whose effect could not be written that way would not belong here.

The document, its fields, trust, consent, receipts, and rollback are specified in
[`DESIGN-setup-installers.md`](../design/DESIGN-setup-installers.md). This file is the reference for
what a recipe may *say*.

## Recipe shape

```json
{
  "schema_version": 2,
  "protocol_version": 2,
  "artifact": "mcp/company-atlassian",
  "purpose": "Build the server image locally and store the API token.",
  "platforms": ["darwin"],
  "help_urls": [{"label": "API tokens", "url": "https://example.test/tokens"}],
  "required_tools": ["docker", "/usr/bin/security"],
  "capabilities": ["docker", "network", "process", "trust-store", "keychain", "filesystem"],
  "inputs": [{"id": "api_token", "type": "secret", "prompt": "Paste the API token"}],
  "steps": [{"id": "token", "use": "macos-keychain.store@1", "with": {}}]
}
```

Every field is required except `custom_entrypoint`. `platforms` is `["darwin"]`. An input is either
`secret` or `text`. A secret may be consumed **only** by `macos-keychain.store@1`; any other step
that mentions one is refused. A text input may be consumed only by `shell.env-from-input@1`, which
prompts with terminal echo and writes a shell export into an owned managed block. Step ids are
lowercase identifiers, unique within the recipe, and steps run in the order written.

`capabilities` is the author's declaration, checked against the modules used: a step whose capability
is not declared is refused, and a declared capability no step needs is still shown to the consumer.
The capabilities are `keychain`, `filesystem`, `docker`, `network`, `process`, `trust-store`, and
`custom-code`.

### Two vocabularies, on purpose

The declaration above is what an *author* says a recipe touches. What a consumer's *organization*
allows is a finer thing — a policy that permits managed files may still refuse to execute a build —
so each module also maps to a capability in the policy vocabulary. That second set is what a registry
index publishes, what `allowed_setup_capabilities` is written in, and what the review reports:

| module | declared | policy |
|---|---|---|
| `macos-keychain.store@1` | `keychain` | `keychain` |
| `shell.env-from-keychain@1`, `shell.env-from-input@1`, `file.managed-block@1`, `json.managed-merge@1`, `directory.create@1` | `filesystem` | `managed-file` |
| `docker.pull@1` | `docker` | `docker-pull`, `network` |
| `docker.build@1` | `docker` | `docker-build`, `network`, `process` |
| `trust-store.export-certificates@1` | `trust-store` | `trust-store` |
| `command.verify@1` | `process` | `verify-command` |
| `restart.notice@1` | none | none |
| `custom_entrypoint` | `custom-code`, `process` | `custom-code` |

A consumer recomputes the second column from the recipe bytes and refuses the artifact if it differs
from what the index published, so a tampered index cannot quietly widen what a setup may do.

## Modules

### `macos-keychain.store@1`

Capability `keychain`. Fields: `input` (a declared secret id), `service`, `account`, and optional
`replace_existing` (default `false`).

Stores one generic password. The value is never read by AART: `security` prompts for it without
echo. With `replace_existing: false` an existing item is preserved and the step reports no change;
with `true` the prior value cannot be restored, and the review says the effect is not automatically
reversible.

Review shows the service and account, never the value. By hand:

```sh
/usr/bin/security add-generic-password -a <account> -s <service> -w
```

### `shell.env-from-keychain@1`

Capability `filesystem`. Fields: `file`, `variables` (a non-empty object mapping environment
variable names to `{service, account}`).

Manages one owned block in a shell startup file that looks the value up at shell start, so the
secret is never written to disk in the clear. The block is delimited by markers derived from the
artifact — `# >>> aart setup: <type>/<name>@<profile> >>>` and the matching `<<<` line — and
rollback removes exactly that block, leaving anything else in the file untouched.

By hand, add between those two marker lines:

```sh
export NAME="$(/usr/bin/security find-generic-password -a <account> -s <service> -w 2>/dev/null)"
```

### `shell.env-from-input@1`

Capability `filesystem`. Fields: `file`, `variables` (a non-empty object mapping environment
variable names to declared `text` input ids).

Before any effect runs, AART prompts once for every referenced text input. The terminal echoes the
value because it is not a secret. The review shows each prompt and the managed-file target, but not
the machine-specific value. The module shell-quotes the value and manages an owned block whose
marker includes the step id, so it can coexist with Keychain lookup blocks and other text inputs.
Rollback removes exactly that block.

By hand, ask for the declared value and add between the marker lines:

```sh
export NAME='<shell-quoted text value>'
```

### `file.managed-block@1`

Capability `filesystem`. Fields: `file`, `content`, optional `marker` (default
`<type>/<name>@<profile>:<step id>`).

The same owned-block mechanics for arbitrary declared content. The content is withheld from the
review — it is shown in the recipe itself, which is hashed and displayed by path and digest.

By hand: paste `content` between the marker lines in `file`.

### `json.managed-merge@1`

Capability `filesystem`. Fields: `file`, `path` (a non-empty list of object keys), `value`, optional
`replace_existing` (default `false`).

Merges one value into a JSON object, creating intermediate objects as needed. An identical existing
value is not a change. A *different* existing value is a conflict and fails, unless
`replace_existing` is set — in which case the effect is not automatically reversible and the review
says so. Rollback removes the key only if it still holds exactly what this run wrote.

By hand: edit `file` and set the nested key.

### `directory.create@1`

Capability `filesystem`. Field: `path`.

Creates one directory with mode `0700` if it is absent; an existing directory is left alone and is
not removed by rollback. A path that exists as a symlink or a non-directory fails.

```sh
mkdir -m 700 -p <path>
```

### `docker.pull@1`

Capability `docker`; also requires `network` and `process`. Fields: `image`, optional `official_url`.

`image` must end in an immutable `@sha256:<64 hex>` digest — the point of a pull is to name bytes
fetched from elsewhere, so it names them exactly. An image that is already present is not pulled
again and is never removed by rollback, because it may be shared with something else on the machine.

```sh
docker pull <image>@sha256:<digest>
```

### `docker.build@1`

Capability `docker`; also requires `network` and `process`, and `docker` in `required_tools`.
Fields: `context` (required) and `dockerfile` (optional, default `Dockerfile`).

Builds one image locally from the package's own bytes. Nothing is pushed, and AART has no way to
push.

`context` is a **package-relative source path**: one name directly below the package root, such as
`payload`. It is the only kind of path in a recipe that points at something to *read* rather than
somewhere to write, and it is resolved at plan time so the review already names it. AART copies that
subtree into a private working directory, builds there, and deletes it when the run ends. The
package is never written to.

`dockerfile` is relative to the context and may not escape it. A recipe may contain **at most one**
build step, and may not name its own tag: the tag is derived as `aart/<type>/<name>:<version>`, so
two versions of one artifact cannot collide and `payload/mcp.json` can name the image before it
exists. Rollback removes the tag only if this run created it; a tag that already existed is left
alone.

The receipt records the digest of the context that was built, the tag, and the resulting local image
id. The review states that the build file's instructions execute, with network access.

By hand — copy the context somewhere writable first, because the package must not be modified. An
installed package lives in the object store, which is read-only by design, and `cp -R` reproduces
those modes, so make the copy writable before anything writes into it:

```sh
cp -R <package>/payload /tmp/aart-build && chmod -R u+w /tmp/aart-build && cd /tmp/aart-build
docker build --tag aart/<type>/<name>:<version> --file Dockerfile .
rm -rf /tmp/aart-build
```

The image a hand build produces has the same contents as the one AART builds and not the same
digest: the working copy AART writes is mode `0600`, a shell redirect writes `0644`, each build
stamps its own mtimes, and a hand build inherits whatever `buildx` defaults the machine has. The two
routes agree on the machine state, not on an image id.

### `trust-store.export-certificates@1`

Capability `trust-store`; requires `/usr/bin/security` in `required_tools`. Fields:
`subject_contains` and `output`.

Writes the machine's matching public certificates into the build context as a PEM bundle, so a build
can trust an interception proxy that only exists on this network. It reads certificates and never
private keys, which is why it is not the secret machinery and does not prompt anyone: a root CA is
public by nature, and nobody could type one anyway.

The capability is deliberately *not* `keychain`. Credential-store access is reported high; reading
the machine's public certificate list is a materially smaller claim, and conflating them would teach
reviewers to discount the word.

`subject_contains` is matched by `security` itself, against the certificate's common name, in the
login and System keychains — not the system root bundle. `output` is relative to the build context,
may not escape it, and may not overwrite a file the package ships. Matching nothing is a failure
naming the substring, because an image built without the CA fails much later inside the container
with an unrelated-looking TLS error.

This step must appear **before** the `docker.build@1` step it feeds, and a recipe that declares it
without a build step is refused.

```sh
/usr/bin/security find-certificate -a -c "<subject_contains>" -p > /tmp/aart-build/<output>
```

### `command.verify@1`

Capability `process`. Fields: `argv` (non-empty string list), optional `cwd`, optional `timeout`
(1–300 seconds, default 30).

Runs one fixed argv, with no shell, to check that what was configured actually works. A non-zero
exit fails the run and the recipe is rolled back. The arguments are withheld from the review body;
they are in the hashed recipe.

By hand: run the argv.

### `restart.notice@1`

No capability. Field: `message`.

Displays one message. It runs nothing, changes nothing, and is the only module whose review says
there is no automated command.

## `custom_entrypoint`

A recipe may instead name one executable file directly below `setup/`, requiring both `custom-code`
and `process`. It is hash-pinned, copied into a private run directory, and executed there through a
fixed four-phase protocol (`plan`, `apply`, `verify`, `rollback`), each phase writing a result
document with exactly `status`, `detail`, `reversible`, and `recovery`. Its first line must be
`# AART manual setup: see ../SETUP.md`.

It is the escape hatch, priced accordingly: `custom-code` is reported critical. It also cannot read
the package — the run directory holds only the copied script — so it is not a way around the rules
above.

## A worked artifact

An `mcp` package whose payload is partly vendored from a foreign repository (`server.py`,
`requirements.txt`) and partly authored beside it (`Dockerfile`, `mcp.json`), needing a locally built
image, a corporate CA, and an API token:

```json
{
  "schema_version": 2,
  "protocol_version": 2,
  "artifact": "mcp/company-atlassian",
  "purpose": "Build the Atlassian MCP server image locally and store its API token.",
  "platforms": ["darwin"],
  "help_urls": [{"label": "API tokens", "url": "https://id.example.test/api-tokens"}],
  "required_tools": ["docker", "/usr/bin/security"],
  "capabilities": ["trust-store", "docker", "network", "process", "keychain", "filesystem"],
  "inputs": [
    {"id": "api_token", "type": "secret", "prompt": "Paste the Atlassian API token"}
  ],
  "steps": [
    {
      "id": "certificates",
      "use": "trust-store.export-certificates@1",
      "with": {"subject_contains": "Example Corp Root", "output": "company-ca.pem"}
    },
    {
      "id": "image",
      "use": "docker.build@1",
      "with": {"context": "payload", "dockerfile": "Dockerfile"}
    },
    {
      "id": "token",
      "use": "macos-keychain.store@1",
      "with": {
        "input": "api_token",
        "service": "aart/mcp/company-atlassian",
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
            "service": "aart/mcp/company-atlassian",
            "account": "default"
          }
        }
      }
    },
    {
      "id": "restart",
      "use": "restart.notice@1",
      "with": {"message": "Restart the harness to pick up the new server."}
    }
  ]
}
```

The certificate lands beside the `Dockerfile` in the working copy, so the build file can `COPY
company-ca.pem` even though no such file exists in the registry — and must not, since a certificate
from one company's network is not part of the artifact. `payload/mcp.json` names
`aart/mcp/company-atlassian:<version>`, which is exactly the tag the build produces.

## Limits this states rather than hides

**A local build is only as offline as its `FROM` line.** `FROM python:3.11-slim` fetches from a
public registry and `RUN pip install` reaches the network — that is why the CA is needed at all.
"Built locally" means the image is not distributed; it does not mean nothing leaves the machine.

**A private base image will not authenticate.** Setup process steps run with a minimal environment —
`PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TERM` — and no `HOME`, so the Docker CLI reads no
`~/.docker/config.json` and finds no registry credentials or non-default context. The daemon itself
is reachable and the build itself works; only credentialed registry access does not. This is
pre-existing behaviour that already affects `docker.pull@1`, and the environment is narrow on
purpose.

**Publishing one of these modules withholds the registry from every older consumer, and no
`requires_aart` floor prevents it.** The floor is an artifact-level bound, and the refusal happens
before any artifact is considered: a recipe is parsed while the source snapshot is validated. On
`2.4.0`, `source add` refuses the whole registry — `unknown or unsupported setup module
'docker.build@1'` — and a consumer already subscribed keeps their last-known-good snapshot, with
`source sync` failing (`unknown capabilities: trust-store`) and everything they already had still
installable. Closed rather than silent, and named precisely, which is the correct failure; it is
still a failure, and it applies to *every* artifact in that registry rather than to the one using
the module. Raise the floor to `min_inclusive: "2.5.0"` anyway — it is true — but plan the rollout
around the consumers, not around the field.
