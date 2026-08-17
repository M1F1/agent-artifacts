# Porting an MCP server into the company registry

This is the procedure for turning one MCP server from `agent-mcp-servers` into an AART artifact that
a colleague installs and sets up in two commands. It was written by porting `company-atlassian`
first, against the `2.6.1` wheel, and every command and error message below was run rather than
recalled.

The shape it assumes is the one you described: **each server keeps its own `server.py` upstream, and
everything else is authored inside the registry.** The upstream repository stays a plain Python
repository that knows nothing about AART; the registry owns the packaging.

Read [`../protocol/setup-recipe-v2.md`](../protocol/setup-recipe-v2.md) alongside this. That document
is the authority on the recipe format; this one is the procedure for using it on a real server.

## 1. What one package looks like

```
artifacts/mcp/<name>/
  artifact.json          identity, compatibility, install effects, setup reference
  SETUP.md               the by-hand route; required whenever setup/ exists
  provenance.json        written by vendoring, never by hand
  payload/
    mcp.json             the descriptor; the only file a consumer receives anything from
    server.py            vendored from agent-mcp-servers
    requirements.txt     vendored
    Dockerfile           authored here
  setup/
    installer.json       the declarative recipe
```

**Only those root entries are allowed.** `artifact.json`, `README.md`, `SETUP.md`,
`provenance.json`, `payload/`, `setup/`. Anything else stops the compiler:

```
error: unexpected canonical package path: install.sh
```

So a POC's `install.sh` and `TESTING.md` do not travel with the package. The installer becomes
`setup/installer.json`; the testing notes belong in `README.md` or `SETUP.md`.

## 2. What a consumer actually receives

This governs everything else, so it goes before the procedure.

Installing an `mcp` artifact **merges the `server` object out of `payload/mcp.json` into the
profile's MCP file and copies nothing.** `server.py`, `Dockerfile` and `requirements.txt` never
appear on the consumer's disk as files. They are stored in AART's object store, and the setup recipe
builds an image out of them there.

Two consequences worth stating plainly:

- A `command` in `mcp.json` that names a payload file — `python3 payload/server.py` — names a file
  the consumer does not have. The audit says so. Name something the consumer's machine can resolve:
  a container image, or an absolute interpreter path.
- The image tag is the interface between the recipe and the descriptor. Get it wrong and the artifact
  installs cleanly, reports success, and the server never starts.

## 3. The tag is derived, not chosen

AART tags a locally built image `aart/<type>/<name>:<version>`, from
[`setup.py:256`](../../agent_artifacts/setup.py). There is no `tag` field. A recipe that tries is
refused:

```
error: step 'build' has unknown field(s): tag
```

For `company-atlassian@1.0.0` the tag is:

```
aart/mcp/company-atlassian:1.0.0
```

and `payload/mcp.json` must name that exact string. The reason for deriving it is rollback: a build
has no digest to pin before it runs, so the tag is the only thing that can identify what this run
created and is allowed to remove.

**This means bumping `version` in `artifact.json` changes the image tag.** Bump the version and the
descriptor in the same commit, always.

## 4. The recipe vocabulary

Nine modules, listed with their fields in
[`setup-recipe-v2.md`](../protocol/setup-recipe-v2.md). The four that carry a containerised server:

| Module | What it does |
|---|---|
| `command.verify@1` | runs a command and fails the setup if it exits non-zero |
| `trust-store.export-certificates@1` | exports matching certificates into the build context |
| `docker.build@1` | builds one image from a copy of the package |
| `macos-keychain.store@1` | stores one secret, prompted by `security` itself |
| `shell.env-from-keychain@1` | writes a managed block that reads the Keychain at shell start |
| `restart.notice@1` | prints a sentence and writes nothing |

Two ordering rules the parser enforces: a certificate export requires a build to write into and must
come **before** it, and a recipe may declare **at most one** build.

### There is no `shell.run@1`

A POC that shells out — `python3 extract_company_ca.py`, an inline `sed` on `~/.zshrc` — has nothing
to translate to:

```
error: unknown or unsupported setup module 'shell.run@1'
```

This is the point of the format rather than a gap in it. Every step in a recipe is reviewable before
it runs, and a shell string is not. The two things a POC usually shells out for both have modules:
certificate extraction is `trust-store.export-certificates@1`, and the `~/.zshrc` block is
`shell.env-from-keychain@1`, which composes the export lines itself.

If a server genuinely needs something no module covers, the escape hatch is `custom_entrypoint` — a
script below `setup/`, hash-bound into the recipe, requiring the `custom-code` capability and a
`# AART manual setup: see ../SETUP.md` header. Reach for it last. It is the one step a reviewer
cannot read as a plan.

### Every input is a secret

`inputs[].type` accepts `"secret"` and nothing else:

```
error: inputs[0].type must be 'secret'
```

There is no `text`. A per-user value that is not secret — an e-mail address, a board key, a space
name — has three homes, in order of preference:

1. **Author it into the recipe or the descriptor** if it is the same for everyone. The Jira and
   Confluence URLs are in `mcp.json` as literal arguments, because they are company-wide.
2. **Keep it in the Keychain with the secrets** if it is per-user. This is what `company-atlassian`
   does with the account e-mail. It works, and the prompt is hidden, so the person types their own
   e-mail address into an unechoed field. Say so in `SETUP.md`; do not let them discover it.
3. **Read it from the environment** in `server.py`, if the company already exports it.

Recorded as `AD-17` in [the adoption register](../testing/residue-register.md).

### Secrets never pass through AART

`macos-keychain.store@1` plans this argv:

```
/usr/bin/security add-generic-password -U -a <account> -s <service> -w
```

`-w` with no value. **`security` prompts, the value goes from the keyboard into the Keychain, and
AART never holds it.** The `input` reference exists so the review can say what will be asked for.
Interpolating a secret anywhere else is refused outright.

`replace_existing: true` adds the `-U` and makes the step non-reversible — the old value is gone.
Take it anyway for API tokens: rotating an expired token should be a re-run, not a manual delete.
Without it a second setup fails because the entry already exists.

## 5. The procedure, one server at a time

**Order matters, and not in the obvious direction.** The files you author inside the registry go in
**before** the vendoring, not after. `registry vendor` adopts whatever is already sitting at the
target package path, records it as authored, and copies the upstream bytes in beside it. Section 5.1
explains why; the rest of the section is in the order to do it.

### 5.1 Authored first, then vendored

There is **no way to select individual files** out of `--path`. It takes a directory and copies it
whole: no `--include`, no `--exclude`, no file list. `VendorOptions` carries an identity, a URL, a ref
and one path, and nothing else. Two consequences:

- **The upstream directory is the unit.** Give each server its own directory holding what you want
  copied and nothing else. A loose `server.py` at a repository root cannot be vendored at all —
  `error: the requested subtree path is not a directory`, which is `AD-11`.
- **You cannot trim the copy afterwards.** `provenance.json` records a digest of what was taken, and
  `registry audit` recomputes it from the package on disk.

What you *can* do is add your own files, and this is the mechanism your registry is built on.
`_adopted_authored` at [`registry_commands/planning.py`](../../agent_artifacts/registry_commands/planning.py) line 705
takes every file already present at `artifacts/mcp/<name>/`, records it in `provenance.json` as
authored, and `verify_vendored_copy` then subtracts exactly those before recomputing the origin
digest. An authored path that collides with a taken one is refused, so the copy can never be
silently overwritten.

Measured `2026-08-17` on the integrity function directly, with one taken `payload/server.py`:

| Package on disk | Files counted | Matches the origin digest |
|---|---|---|
| taken subtree alone | 1 | yes |
| `payload/mcp.json` present and recorded as authored | 1 | **yes** |
| `payload/mcp.json` added after the vendoring | 2 | **no** |

So the rule is precise:

- **Anything you author under `payload/` must exist before you vendor.** For an MCP server that is
  `payload/mcp.json` and, if you author it rather than vendor it, `payload/Dockerfile`.
- **Anything outside `payload/` can come later.** `SETUP.md` and `setup/installer.json` are not in the
  integrity computation at all — it only walks `<package>/payload/`.
- **`artifact.json` and `provenance.json` are derived by the vendoring**, from the command's flags.
  Placing either yourself is refused: `error: the vendoring writes artifact.json; it is not authored
  alongside the payload`. Extending `artifact.json` afterwards — the runtime-requirements block, for
  instance — is an ordinary edit, because the integrity check does not look outside `payload/`.

So the sequence is: write `payload/mcp.json`, write `payload/Dockerfile`, then

```bash
aart registry vendor mcp <name> --source . --url https://github.example.com/your-org/agent-mcp-servers.git --ref main --path servers/<name> --artifact-version 1.0.0 --summary "…" --profile claude,tabnine --platform darwin --install-scope user --install-scope project --setup-recipe setup/installer.json --yes
```

Pass `--setup-recipe` only once `setup/installer.json` and `SETUP.md` are both there — it checks for
both and refuses otherwise. Leaving it off and adding the recipe later works too; you then declare the
`setup` block in `artifact.json` by hand.

`Dockerfile` is the one file worth deciding case by case. Vendoring it keeps the build definition with
the code, which is right if upstream maintains it. Authoring it in the registry is right if it exists
only to satisfy the company proxy. `company-atlassian` authors it, because the CA line is a company
fact and not an upstream one.

### 5.2 What `artifact.json` ends up as

Most of this comes from the vendor flags rather than your editor. It is here so you know what to check
afterwards, and what to add. Write it by hand only for a package with no upstream at all.

```json
{
  "schema_version": 1,
  "type": "mcp",
  "name": "company-atlassian",
  "version": "1.0.0",
  "summary": "Jira and Confluence access for the company Atlassian instance, over a locally built MCP server.",
  "authors": ["Platform Team"],
  "homepage": "https://github.example.com/your-org/agent-mcp-servers",
  "license": "LicenseRef-company-internal",
  "compatibility": {
    "platforms": ["darwin"],
    "profiles": ["claude", "tabnine"]
  },
  "install": {
    "effects": ["merge-json"],
    "modes": ["copy"],
    "scopes": ["user", "project"]
  },
  "payload": {
    "format": "aart-mcp-v1",
    "root": "payload"
  },
  "setup": {
    "recipe": "setup/installer.json",
    "platforms": ["darwin"]
  },
  "com.m1f1.runtime-requirements": {
    "schema_version": 1,
    "requirements": [
      {
        "id": "command.docker",
        "reason": "The MCP server runs in a container built on this machine."
      }
    ]
  }
}
```

Five things that are not free choices:

- `install.effects` for `mcp` is exactly `["merge-json"]`. The compiler holds the map.
- `setup` takes `recipe` and `platforms` and no other field. A POC's `poc_script` is rejected.
- `setup.platforms` must be a subset of `compatibility.platforms`. A Keychain recipe means both are
  `["darwin"]`, and the artifact then does not offer itself on Linux, which is correct.
- `com.m1f1.runtime-requirements` is a real extension and is advisory: it feeds
  `aart marketplace health` and never blocks an install. Extension keys must be dotted and
  lowercase; `x-anything` is refused as an unknown field.
- `scopes` decides which file the descriptor is merged into. Under the `tabnine` profile, `user`
  means `~/.tabnine/mcp_servers.json` and `project` means `.tabnine/agent/settings.json`. Those are
  the two candidates in `AD-04`, which is still unverified — **user scope targets the file Tabnine's
  published documentation names**, so prefer it until someone checks on a machine running Tabnine.

### 5.3 Write `payload/mcp.json`

```json
{
  "name": "company-atlassian",
  "server": {
    "command": "docker",
    "args": [
      "run", "-i", "--rm",
      "-e", "ATLASSIAN_USERNAME",
      "-e", "ATLASSIAN_API_TOKEN",
      "aart/mcp/company-atlassian:1.0.0",
      "--jira-url", "https://company.atlassian.net",
      "--confluence-url", "https://company.atlassian.net/wiki"
    ]
  }
}
```

`name` becomes the key under `mcpServers` and `server` becomes its value. Everything else in the file
is ignored by the merge, so a `description` is free.

Note the bare `-e NAME` form. It passes the variable through from whatever process launches `docker`,
which is the MCP host, which inherits from the shell. The alternative — `"env": {"X": "${Y}"}` in the
descriptor — depends on the host expanding `${…}`, and whether Tabnine does is one more thing nobody
has checked. Bare pass-through needs no host cooperation at all.

### 5.4 Write `setup/installer.json`

The `company-atlassian` recipe, complete. This is the pattern to copy.

```json
{
  "schema_version": 2,
  "protocol_version": 2,
  "artifact": "mcp/company-atlassian",
  "purpose": "Export the company root CA, build the Atlassian MCP server image locally from it, store the Atlassian credentials in the login Keychain, and export them into new shells.",
  "platforms": ["darwin"],
  "capabilities": ["keychain", "filesystem", "docker", "network", "process", "trust-store"],
  "required_tools": ["/usr/bin/security", "docker"],
  "help_urls": [
    {
      "label": "Create an Atlassian API token",
      "url": "https://id.atlassian.com/manage-profile/security/api-tokens"
    }
  ],
  "inputs": [
    {
      "id": "atlassian_username",
      "type": "secret",
      "prompt": "Your Atlassian account e-mail (name@company.com)"
    },
    {
      "id": "atlassian_api_token",
      "type": "secret",
      "prompt": "Atlassian API token",
      "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens"
    }
  ],
  "steps": [
    {
      "id": "docker_running",
      "use": "command.verify@1",
      "with": { "argv": ["docker", "info"], "timeout": 60 }
    },
    {
      "id": "company_ca",
      "use": "trust-store.export-certificates@1",
      "with": { "subject_contains": "Company", "output": "company-ca.pem" }
    },
    {
      "id": "image",
      "use": "docker.build@1",
      "with": { "context": "payload", "dockerfile": "Dockerfile" }
    },
    {
      "id": "store_username",
      "use": "macos-keychain.store@1",
      "with": {
        "input": "atlassian_username",
        "service": "aart/mcp/company-atlassian/username",
        "account": "atlassian",
        "replace_existing": true
      }
    },
    {
      "id": "store_token",
      "use": "macos-keychain.store@1",
      "with": {
        "input": "atlassian_api_token",
        "service": "aart/mcp/company-atlassian/api-token",
        "account": "atlassian",
        "replace_existing": true
      }
    },
    {
      "id": "shell_env",
      "use": "shell.env-from-keychain@1",
      "with": {
        "file": "~/.zshrc",
        "variables": {
          "ATLASSIAN_USERNAME": {
            "service": "aart/mcp/company-atlassian/username",
            "account": "atlassian"
          },
          "ATLASSIAN_API_TOKEN": {
            "service": "aart/mcp/company-atlassian/api-token",
            "account": "atlassian"
          }
        }
      }
    },
    {
      "id": "restart",
      "use": "restart.notice@1",
      "with": {
        "message": "Open a new shell and start your MCP host from it, so the host process inherits ATLASSIAN_USERNAME and ATLASSIAN_API_TOKEN."
      }
    }
  ]
}
```

Rules the parser applies to this file, each of which produced an error the first time:

- **Every top-level field except `custom_entrypoint` is required**, including `help_urls` and
  `required_tools` even when empty lists would do.
- **No comments.** JSON has none, and `_comment` is an unknown field:
  `error: unknown field(s): _comment`. It is rejected inside `steps` and `inputs` too. Explanation
  goes in `purpose`, in the step `id`, and in `SETUP.md`.
- `schema_version` and `protocol_version` are both `2`. Nothing older is accepted.
- `artifact` must equal `<type>/<name>` of the containing package.
- `platforms` must be exactly `["darwin"]`.
- Capabilities are declared by the author and checked against the modules used. `docker.build@1`
  additionally requires `network` and `process` to be declared, and `docker` to be in
  `required_tools`; `trust-store.export-certificates@1` requires `/usr/bin/security` there.
- `help_urls` entries are exactly `{label, url}` and the URL must be `https`.

### 5.5 Write `SETUP.md`

Required whenever `setup/` exists — the compiler refuses the package without it. Write the same steps
as shell commands anyone can run by hand.

It is not a formality. It is the only thing a colleague has when the recipe fails halfway, and it is
what makes the recipe reviewable: a plan you can perform yourself is a plan you can judge.

The `company-atlassian` one has a table of what lands where, the seven commands, and a closing
section naming what the artifact does **not** fix — `server.py` disables TLS verification for its own
Atlassian calls, which is upstream's decision to change, not the registry's.

### 5.6 Publish

```bash
scripts/registry_publish.py --source /path/to/registry --yes
```

`lock`, `build`, `validate`, `audit`, then one commit listing every file. See `AD-14`.

## 6. Check it before anyone installs it

`registry validate` proves the package compiles. It does not prove the recipe does what you meant.
Two checks worth running on every port:

**Does the recipe parse, and what does the review say?**

```bash
python3 -c "
from agent_artifacts.setup import parse_installer, plan_setup, render_setup_review
from agent_artifacts.model import SetupQueueItem
pkg='artifacts/mcp/company-atlassian'
raw=open(pkg+'/setup/installer.json','rb').read()
inst=parse_installer(raw, artifact_key='mcp/company-atlassian', descriptor_path='setup/installer.json').value
item=SetupQueueItem(artifact_type='mcp', artifact_name='company-atlassian', profile='tabnine',
                    scope='user', source_label='company', source_root=pkg,
                    installer=inst, artifact_version='1.0.0')
print('\n'.join(render_setup_review(plan_setup(item, target_root='/tmp/p', platform='darwin', home_root='/tmp/h'))))
"
```

This prints exactly what a colleague will be asked to approve, without touching anything. Read it as
they will. For `company-atlassian` it names seven effects, the derived tag
`aart/mcp/company-atlassian:1.0.0`, the two Keychain services, and `~/.zshrc`.

**Does the tag in the review match the tag in the descriptor?** Compare the `docker.build@1` target
line against the image argument in `mcp.json`. This is the one mismatch that produces a working
install and a dead server.

## 7. Per-server checklist

For each new server in `agent-mcp-servers`:

| | In order | What changes |
|---|---|---|
| 1 | author `payload/mcp.json` | the image tag `aart/mcp/<name>:<version>`, and the server's own arguments |
| 2 | author `payload/Dockerfile` | usually nothing, if the servers build the same way |
| 3 | author `setup/installer.json` | `artifact`, `purpose`, Keychain services `aart/mcp/<name>/<what>`, and the variable names the server reads |
| 4 | author `SETUP.md` | rewritten for those names |
| 5 | `aart registry vendor` | `--path servers/<name>`, `--summary`, `--artifact-version 1.0.0` |
| 6 | check `artifact.json` | add the runtime-requirements block if the server needs one |

Steps 1 and 2 are before step 5 and not after it: a `payload/` file that arrives after the vendoring
is counted as part of the copy and breaks the origin digest. Steps 3, 4 and 6 may come either side.

The Keychain services are namespaced per server on purpose. Two servers sharing
`aart/mcp/…/api-token` would overwrite each other's credential with no error anywhere.

What does **not** change between servers, as long as they all run in company-built containers: the
step list, its order, the capabilities, the required tools, and the Dockerfile's CA lines. That is
the part this port was for.

## 8. Where this was proven

A registry initialised from scratch, the package built as above, then `lock`, `build`, `validate`,
`audit` — validate passed, audit passed with the three warnings a registry with no security evidence
and no external references always reports. The recipe was parsed and planned through AART's own
functions, and the review rendered seven effects.

Nothing was applied. Applying it needs Docker, a company-managed Mac, and someone at the keyboard to
type two secrets into `security`'s own prompt — which is the whole point of how the Keychain module
is built.
