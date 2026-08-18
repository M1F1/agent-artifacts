# Vendoring the next MCP server, using `company-atlassian` as the model

This is a repeatable procedure for adding one more MCP server to a company registry by copying a
directory out of a foreign repository that knows nothing about AART. It takes the working
`company-atlassian` package — vendored `server.py`, authored `Dockerfile`, authored descriptor,
authored recipe — as the shape to copy.

It is written to be executed either by a person or by an agent. Every command below was run against
AART `2.7.1`; every error message quoted was produced, not recalled.

[`mcp-servers-into-the-registry.md`](mcp-servers-into-the-registry.md) is the authority on the setup
recipe itself — the nine modules, their fields, why there is no `shell.run@1`, and the complete
`company-atlassian` recipe to copy. Read it when writing `setup/installer.json`. **This document is
the fast path: the order to do things in, and what refuses you when the order is wrong.**

## 0. Rules for an agent executing this

An agent following this document must obey all of these. They are not style preferences.

1. **Never type, echo, paste, or store a secret.** No API token, password, or personal access token
   goes into a command, a file, or a log. Where a credential is needed, stop and hand the step to the
   person, naming exactly which command they should run.
2. **Never run a mutating command with `--yes` before showing its review output.** Every AART
   maintainer command runs review-only without `--yes`. Show the review, then finalize.
3. **Never `git push`.** `registry publish --yes` commits and deliberately does not push. Pushing is
   the person's decision.
4. **Stop at the first error.** Do not retry a failed command with different flags to make it pass.
   Report the exact message and stop.
5. **Do not edit files under `payload/` after vendoring.** Those bytes are pinned to an upstream
   commit and their digest is verified. Editing one turns every later check into a copy-integrity
   failure.
6. **Never delete `.agent-artifacts/` in a consumer project.** It is the only record of what was
   written and what was overwritten.

## 1. Inputs to collect before running anything

Fill these in first. Every later command is a substitution of these values.

| Name | Meaning | Example |
|---|---|---|
| `NAME` | artifact name, lowercase slug | `sentry` |
| `URL` | credential-free HTTPS Git URL of the foreign repository | `https://github.com/acme/mcp-servers.git` |
| `REF` | tag or branch to resolve | `v2.4.0` |
| `SERVER_FILE` | the one upstream file the server runs | `servers/sentry/server.py` |
| `VERSION` | version **this registry** publishes the copy under | `1.0.0` |
| `IMAGE` | the image the descriptor names — `aart/mcp/$NAME:$VERSION` when the recipe builds it | `aart/mcp/sentry:1.0.0` |
| `VARS` | every environment variable the server needs, named once | `SENTRY_TOKEN`, `SENTRY_ORG` |
| `CONSUMER` | absolute path to the project the install is tested in — **never the registry** | `/Users/mifi/code/agent-artifacts-live-acceptance-project` |
| `ALIAS` | the alias this registry is configured under in `CONSUMER` | `company` |
| `REGISTRY_URL` | this registry's Git URL, once it is pushed | `https://github.com/acme/agent-artifacts-registry.git` |
| `REGISTRY_PATH` | this registry's absolute path, for testing before pushing | `/Users/mifi/code/agent-artifacts-registry-2` |
| `PROFILES` | harness profiles | `tabnine` |
| `PLATFORMS` | platforms | `darwin` |

**Every command below runs from the root of the registry checkout.** `cd` there once, and the
registry is `.` from then on: maintainer commands default `--source` to the current directory, so the
flag never appears in this document. Confirm where you are before starting — `aart-registry.json` must
be in the current directory, and `.git` must be there too, not in a parent.

```sh
ls aart-registry.json aart-source.json .git >/dev/null && echo "in the registry root"
```

**The registry is never `URL`.** `URL` is the foreign repository the bytes are copied *from*: remote,
someone else's, read-only. It reaches AART only as `--url`. The registry you are mutating is the
directory you are standing in, and it is never named on the command line.

Beware the overloaded word: in `registry …` commands `--source` means *this registry workspace*,
while in the consumer commands `source add` / `source sync` the word *source* means *a configured
origin*. Same word, two meanings, one CLI.

Two of these are decisions, not lookups:

- **`VERSION` is yours, not upstream's.** This registry owns the copy. Upstream fixes reach consumers
  only when you vendor again.
- **`REF` should be a tag, never `main`.** A moving ref is recorded verbatim into `provenance.json`
  and makes the copy unreproducible.

## 2. The model: what a real MCP package looks like

A server that ships code and needs a credential is six files, and only two of them are yours to
write from scratch. This is the shape `company-atlassian` has, and the shape to copy:

```
artifacts/mcp/<NAME>/
  artifact.json          derived by the vendoring from your flags — never authored by hand
  provenance.json        written by the vendoring — never edited
  SETUP.md               the by-hand route; required whenever setup/ exists
  payload/
    mcp.json             AUTHORED, and it must exist before the vendoring runs
    Dockerfile           authored here, or vendored, depending on who owns the build
    server.py            vendored — the one upstream file, taken on its own
  setup/
    installer.json       AUTHORED; may be added after the vendoring
```

**One file is vendored, not the directory it lives in.** Upstream's `launcher.sh`, `README.md` and
whatever else shares that directory stay upstream. §4.1 says how, and when taking the directory is
the right call instead.

**Only those root entries are legal.** `artifact.json`, `README.md`, `SETUP.md`, `provenance.json`,
`payload/`, `setup/`. Anything else stops the compiler with `unexpected canonical package path: …`,
so a POC's `install.sh` or `TESTING.md` does not travel with the package.

A descriptor-only server — one that runs a published image and needs no build and no credential —
drops `SETUP.md`, `setup/` and everything vendored, leaving `artifact.json` plus `payload/mcp.json`.
Both shapes are ordinary packages; the difference is only how much of it you author.

### 2.1 The image tag is derived, not chosen

`docker.build@1` tags what it builds `aart/<type>/<name>:<version>`, from `setup.py:256`. There is no
`tag` field and a recipe that declares one is refused. For `mcp/<NAME>` at version `1.0.0` the tag is:

```
aart/mcp/<NAME>:1.0.0
```

`payload/mcp.json` must name that exact string. **Bumping `version` in `artifact.json` therefore
changes the image tag, and the descriptor has to change in the same commit.** Miss it and the
artifact installs cleanly, reports success, and points at an image that does not exist.

### 2.2 The one thing that differs most between servers

Not the layout — the **variable join**. A credential passes through four documents, and the name is
written out separately in each one. Nothing in AART compares them, which is `AD-30` and `AD-31`.

| Where | What it says | Example |
|---|---|---|
| `setup/installer.json` → `inputs[]` | the id AART prompts for | `"id": "api_token"` |
| `setup/installer.json` → `macos-keychain.store@1` | Keychain service and account | `service: "aart/mcp/<NAME>"`, `account: "default"` |
| `setup/installer.json` → `shell.env-from-keychain@1` | the exported variable name | `ATLASSIAN_API_TOKEN` |
| `payload/mcp.json` → `env` | the same name, on both sides of the pair | `"ATLASSIAN_API_TOKEN": "${ATLASSIAN_API_TOKEN}"` |

**Write the variable name once, then copy-paste it into the other three places.** A single character
of difference produces a server that starts, authenticates as nobody, and reports success at every
layer.

### 2.3 Where the variables actually come from

No separate file is created and nothing is `source`d. `shell.env-from-keychain@1` edits the file its
own `with.file` names — normally `~/.zshrc` — and owns exactly one sentinel-delimited block inside it.
The block below is what the module really produces, rendered by calling `managed_block` directly:

```sh
# >>> aart setup: mcp/<NAME>@tabnine >>>
export ATLASSIAN_API_TOKEN="$(/usr/bin/security find-generic-password -a default -s aart/mcp/<NAME> -w 2>/dev/null)"
# <<< aart setup: mcp/<NAME>@tabnine <<<
```

Read it in order, because every line of it matters:

- **The marker is `<type>/<name>@<profile>`**, so one artifact owns one block per profile, and a
  re-run replaces its own block instead of appending a second one. `receipt undo` finds the block by
  the same marker.
- **The value is not stored in the file.** The file stores a *lookup*: every new shell runs `security`
  and reads the Keychain. Rotating the credential means replacing the Keychain item, and no shell file
  changes.
- **`2>/dev/null` swallows the failure.** A denied Keychain prompt or a missing item produces an
  **empty** variable, not an absent one and not an error. The server then starts with an empty
  credential and reports success, which is the shape of `AD-31`.
- **Only a login shell reads it.** An app launched from Dock or Spotlight never sourced `~/.zshrc`, so
  it has none of these variables. Restart the harness from a terminal where `printenv` shows them.
- **A symlinked `~/.zshrc` refuses the whole step** — the normal result of keeping dotfiles in a
  repository. The refusal is `refusing to edit symlink: <path>`, reported as a missing prerequisite,
  and it lands **before** any input is collected and before the first effect: nothing is built,
  nothing is typed, nothing is written (`AD-26`, closed). The plan does not predict it, because
  planning never touches the filesystem, so it appears only when you apply. Check `ls -l ~/.zshrc`
  first; if it is a link, remove the link before running setup:

```bash
ls -l ~/.zshrc
```

```bash
REAL="$(python3 -c 'import os;print(os.path.realpath(os.path.expanduser("~/.zshrc")))')" && rm ~/.zshrc && printf 'source %s\n' "$REAL" > ~/.zshrc && ls -l ~/.zshrc
```

`rm` deletes the link, never the file it pointed at. What replaces it is a real file that still
loads your dotfiles copy, so nothing of your own configuration is lost and setup now has a regular
file to own: it appends its block below the `source` line. Confirm the second `ls -l` prints
`-rw-r--r--` with no `->` arrow, then run setup again. If your dotfiles tool re-creates the link on
its next run, exclude `.zshrc` from it, or the managed block disappears with the link.

The Keychain item itself is written by `macos-keychain.store@1`, which plans
`/usr/bin/security add-generic-password -U -a <account> -s <service> -w` and lets `security` prompt.
**The secret goes from the keyboard into the Keychain; AART never holds it.**

### 2.4 The descriptor names its variables in `env`

```json
"server": {
  "command": "docker",
  "args": ["run","-i","--rm","aart/mcp/<NAME>:1.0.0","--jira-url","https://company.atlassian.net"],
  "env": {
    "ATLASSIAN_USERNAME": "${ATLASSIAN_USERNAME}",
    "ATLASSIAN_API_TOKEN": "${ATLASSIAN_API_TOKEN}"
  }
}
```

This is the proven shape on the target harness; keep it. Two facts about it, so nobody is surprised
later:

- AART copies `server` verbatim, so `${ATLASSIAN_API_TOKEN}` reaches the harness file as those
  literal characters. The expansion is the harness's job.
- The name inside `${…}` and the name the recipe exports must be identical. That is the join in §2.2,
  and it is the whole of `AD-30` and `AD-31`.

**The envelope is the whole point.** `name` becomes the key under `mcpServers`; `server` becomes the
value, copied verbatim. A document shaped like the harness file itself — `{"mcpServers": {…}}` — has
no `server` key, installs an empty entry, and starts nothing.

## 3. What the consumer actually receives

Read this before writing the descriptor; it invalidates the obvious approach.

An `mcp` artifact installs by `merge-json` and **copies no files**. The vendored bytes — every file
in the taken subtree — are stored in the object store and never appear on the consumer's disk.

Consequences:

- A `command` or `args` entry naming a path inside `payload/` names a file the consumer does not
  have. Name something their machine resolves on its own: a container image, or an absolute path.
- `${VAR}` in the descriptor reaches the harness file as **those literal characters**. AART performs
  no substitution on the MCP path (it does substitute `${SCRIPT_DIR}` for hooks; MCP is not the same
  path). Whether `${VAR}` expands is entirely the harness's business.
- Therefore the variable name in the descriptor must match, character for character, the variable the
  person exports in their shell. Nothing in the system compares the two.

## 4. Procedure

### 4.1 Author the `payload/` files first — this order is not negotiable

`registry vendor` adopts whatever already sits at `artifacts/mcp/<NAME>/`, records it in
`provenance.json` as authored, and copies the upstream bytes in beside it. The integrity check then
subtracts exactly those authored paths before recomputing the origin digest — **and it walks
`payload/` only**. That gives one hard rule and one soft one:

- **Anything under `payload/` must exist before the vendoring.** That is `payload/mcp.json`, always,
  and `payload/Dockerfile` whenever you author the build rather than take it from upstream. A file
  added under `payload/` *after* the vendoring makes every later `audit`, `validate` and `revendor`
  report a copy-integrity failure.
- **Anything outside `payload/` can come later.** `SETUP.md` and `setup/installer.json` are not in
  the integrity computation at all.
- **`artifact.json` and `provenance.json` are written by the vendoring.** Placing either yourself is
  refused: `the vendoring writes artifact.json; it is not authored alongside the payload`. Editing
  `artifact.json` afterwards is fine — it is outside `payload/`.

**Name the file, not its directory.** `--path servers/<name>/server.py` copies that file and nothing
else; it is re-rooted under its basename, so it arrives as `payload/server.py` and the intermediate
directories disappear. Measured `2026-08-18`: a lone file vendors cleanly, `provenance.json` records
`"path": "servers/<name>/server.py"`, and the package holds exactly that file plus what you authored.
This is `AD-11`, closed — older documents still say a loose file cannot be vendored at all.

Take the directory only when the server genuinely runs several of its own files. Then `--path` names
the directory and copies it **whole**: no `--include`, no `--exclude`, and no trimming afterwards,
because `provenance.json` records a digest of what was taken and `registry audit` recomputes it. Every
neighbour in that directory becomes bytes your registry owns, reviews and re-vendors forever.

Two limits that follow from one path per artifact:

- The basename is the filename. You cannot rename the file on the way in.
- One artifact records one origin path. `server.py` **and** `requirements.txt` means taking the
  directory; there is no way to name two files.

For an `mcp` the descriptor is also a precondition: vendoring refuses unless `payload/mcp.json`
exists — either among the taken bytes or in the package directory you are about to create. Taking one
`server.py` never contributes it, so you always write it yourself.

```sh
mkdir -p "artifacts/mcp/$NAME/payload"
```

Write `artifacts/mcp/$NAME/payload/mcp.json` with the envelope from §2, substituting
`NAME` and `IMAGE`.

Skipping this step produces exactly:

```
error: a vendored mcp needs payload/mcp.json; the taken subtree does not contain it, so the maintainer supplies it at artifacts/mcp/<NAME>/payload/mcp.json
  remediation: author artifacts/mcp/<NAME>/payload/mcp.json before vendoring, unless the upstream subtree supplies payload/mcp.json
```

The remediation's second clause is misleading: for upstream to supply it, upstream would need a file
literally named `mcp.json`, and you took its directory rather than the single file. If that happens,
do **not** author your own — it is refused as a collision with the taken bytes.

### 4.2 Vendor, review only

```sh
aart registry vendor mcp "$NAME" \
  --url "$URL" \
  --ref "$REF" \
  --path "$SERVER_FILE" \
  --artifact-version "$VERSION" \
  --summary "one line describing the server" \
  --profile tabnine \
  --platform darwin \
  --install-scope project \
  --install-scope user \
  --install-mode copy
```

Add `--setup-recipe setup/installer.json` when the server needs a build or a credential. It checks
for **both** files and refuses on the missing one:

```
error: the declared setup recipe requires artifacts/mcp/<NAME>/SETUP.md, which is not present
  remediation: add the declared recipe and its `SETUP.md` to the package, or drop `--setup-recipe`, then run the command again
```

The flag makes the vendoring write the `setup` block into `artifact.json` for you —
`{"recipe": "setup/installer.json", "platforms": [<your --platform values>]}`. Leaving it off and
adding the recipe later also works; you then write that block by hand.

Measured `2026-08-18`, a vendored package authored this way records all four files, payload and
non-payload alike:

```json
"aart.vendor": { "authored": ["SETUP.md", "payload/mcp.json", "setup/installer.json"], "ref": "…" }
```

One field of the recipe surprises everyone once: **`help_urls` is required.** A recipe without it is
refused with `invalid setup installer for mcp/<NAME>: missing field(s): help_urls`. Supply the page a
reader needs in order to produce the credential — and know that AART renders it nowhere (`AD-32`), so
repeat the link in `SETUP.md`, which is the one document a reader can actually reach.

Check three lines in the review before going further:

- `payload files: N` — with one taken `server.py`, an authored `mcp.json` and an authored
  `Dockerfile` that is `3`. A larger number means you named a directory rather than the file.
- `target: artifacts/mcp/<NAME>` — the package path.
- `declared version` — the version you chose.

**`--install-scope` and `--install-mode` are repeatable flags and both default to the narrowest
value.** Omitting `--install-scope user` produces `scopes: ["project"]`, and a consumer then meets:

```
error: scope 'user' is not supported; supported scopes: project
```

That is only fixable by editing `artifact.json`, bumping the version, and publishing again.

### 4.3 Finalize the vendor

```sh
aart registry vendor mcp "$NAME" … --yes
```

Same command, `--yes` appended. It writes:

```
artifacts/mcp/<NAME>/artifact.json
artifacts/mcp/<NAME>/provenance.json
artifacts/mcp/<NAME>/payload/mcp.json        (yours)
artifacts/mcp/<NAME>/payload/…               (copied subtree)
```

`provenance.json` records the resolved commit, the input digest, and — under the namespaced key
`aart.vendor` — the `ref` and the list of files you authored rather than copied:

```json
"aart.vendor": { "authored": ["payload/mcp.json"], "ref": "v2.4.0" }
```

That list is what makes `registry revendor` possible later. Never edit it by hand; it is verified
against `importer.options_digest`.

### 4.4 Publish

```sh
aart registry format --yes
```

```sh
aart registry publish
```

Review-only. It computes lock and index in memory, runs `validate` and `audit` over that exact
snapshot, and lists every path it would commit. Read the list. Then:

```sh
aart registry publish --yes -m "Add mcp/<NAME> vendored from <URL>@<REF>"
```

It commits and does **not** push. Pushing is a separate, human decision.

Warnings of the form `owned package has no provenance document: skill/…` are normal for
hand-authored packages and are not about the one you just vendored.

### 4.5 Install and verify on a consumer

**This is the one step that does not run in the registry.** Everything below runs in `CONSUMER`, the
project whose `.tabnine/` the entry should land in. The registry reaches it as a configured source,
by `ALIAS`, never by path.

```sh
cd "$CONSUMER"
```

`CONSUMER` must not be the registry checkout, and it must not be a directory you are unwilling to have
`.tabnine/` and `.agent-artifacts/` written into. A throwaway project is the right kind of place; the
registry itself is the wrong one, because a test install there leaves harness files inside the
repository you publish. Guard it:

```sh
[ -f aart-registry.json ] && echo "REFUSE: this is the registry, not a consumer project"
```

If `ALIAS` is not configured here yet, add it once. Which kind you choose depends on whether the
registry commit has been pushed, and the choice has consequences beyond convenience.

After pushing — this is what a colleague uses:

```sh
aart source add --alias "$ALIAS" --kind registry-git --location "$REGISTRY_URL" --ref main --default
```

Before pushing, to test the commit you just made without publishing it:

```sh
aart source add --alias "$ALIAS" --kind source-local --location "$REGISTRY_PATH"
```

`source-local` cannot take `--default` — `only a registry source can become the default registry` —
and its trust class is `local`, so any setup recipe will require `--authorize-untrusted-source`. A
registry's own packages carry no review record either, so `registry-git` reads as `unverified` and
needs the same flag. Expect it in both cases; it is not a symptom of anything being wrong.

`source add` also refuses a second alias for an origin already configured, so switching from local to
Git means `aart source remove --alias "$ALIAS" --yes` first — and that leaves the installation record
behind, which is what produces `installation effect ownership must be unique across the manifest` on
the next install. Uninstall under the old alias before re-adding.

Then, before every install, re-synchronize. Source health reports the snapshot's age, not its
agreement with the origin (`AD-16`), so a registry that moved still reads as healthy until you sync:

```sh
aart source sync --alias "$ALIAS"
```

```sh
aart marketplace install --profile tabnine "$ALIAS/mcp/$NAME"
```

Review-only; it prints the destination file. Then append `--yes`.

Verification is not "the command said succeeded". Run all three:

```sh
python3 -m json.tool .tabnine/agent/settings.json
```

The entry must sit under `mcpServers.<name-from-descriptor>` and its `server` body must be what you
authored, modulo key ordering — AART writes JSON canonically, so keys come out sorted. Array order,
which is the part that matters, is preserved.

```sh
docker image inspect "$IMAGE" --format 'ok {{.Id}}'
```

An image that is not present and not pullable is a server that will never start, whatever the install
reported.

```sh
ps -Ao args | grep -c '}'
```

Refine that grep to your own variable name — e.g. `grep -c 'SENTRY_TOKEN}'`. **A non-zero count means
the harness did not expand `${…}` and the server received the literal variable name as its
credential.** This is the failure that reports success at every layer.

## 5. Failures worth knowing before you meet them

| Symptom | Cause | Move |
|---|---|---|
| `registry mutation requires a writable local Git checkout` | `.git` must be in the current directory, not in a parent | `cd` to the repository root and re-run |
| `a vendored mcp needs payload/mcp.json` | descriptor not authored first | §4.1 |
| `authored file collides with the taken subtree` | upstream already ships `mcp.json` at the subtree root | delete your copy, vendor upstream's |
| `scope 'user' is not supported` | `--install-scope` given once | edit `artifact.json`, bump version, republish |
| `installation effect ownership must be unique across the manifest` | a stale install record under an old source alias still owns the merge key | `marketplace uninstall OLD-ALIAS/mcp/<NAME> --yes`, then install |
| `JSON merge identity … already differs` on `marketplace update` | the merged entry's body changed between versions | `marketplace update --force --yes` |
| `setup from unverified requires explicit source authorization` | trust class; a registry's own packages are never `registry-reviewed` | `marketplace setup --authorize-untrusted-source --approve-setup-effects --yes` |
| `Usage report not offered` | reporting needs a `registry-git` source advertising a `usage_reporting` service | informational; ignore |

Two structural facts behind that table, worth internalizing:

- **A registry never marks its own packages as reviewed.** The `review` record lives on `entries/`
  references only; owned packages are indexed with `review: null`, which the consumer reads as
  `unverified`. Setup from your own registry therefore always needs the authorization flag.
- **`source remove` does not remove installations.** The install record survives, keeps owning its
  destination, and blocks the next install under a different alias.

## 6. Agent report format

An agent finishing this procedure reports exactly this, and nothing that it did not observe:

```
artifact:      mcp/<NAME> @ <VERSION>
upstream:      <URL> @ <REF> → <resolved commit from provenance.json>
authored:      payload/mcp.json
scopes/modes:  <from artifact.json>
publish:       <commit sha> — not pushed
install:       <outcome line from marketplace install>
descriptor:    <mcpServers key written> in <destination path>
image present: yes | no
literal ${} in process args: <count>
blocked at:    <step number and exact error, or "none">
```

If any step was skipped, say which and why. Do not report a step as done because the preceding one
succeeded.
