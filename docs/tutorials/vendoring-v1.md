# Tutorial: vendoring an MCP server into a company registry

Upstream publishes a useful MCP server in a monorepo. It has no `aart-source.json`, no
`artifact.json`, and no interest in acquiring either. Your consumers must install it from your
registry and from nowhere else. This is the case `aart registry vendor` exists for: it copies a
subtree of any Git repository into your registry as a package you own, pinned to a resolved commit,
with a `provenance.json` recording where the bytes came from.

If the upstream *is* a canonical AART package and you are content for consumers to reach its
repository directly, use `aart registry promote-native` instead — it pins a reference and copies
nothing, and upstream keeps ownership of the version. The three delivery modes and what each one
means for who the consumer reaches are tabulated in
[the registry protocol](../protocol/registry-v1.md).

Vendoring moves the trust boundary. After it, your registry is the distributor: your consumers
install those bytes on your word, having never seen the origin, and upstream's later fixes —
security fixes included — do not reach them until you vendor the artifact again.

## 1. The registry

```shell
aart registry init --source . --source-id company-registry --display-name "Company Registry" --yes
```

## 2. What upstream looks like

Nothing about it is AART-shaped:

```
README.md
packages/
  atlassian-mcp/
    LICENSE
    index.js
    install.sh
    lib/client.js
```

The subtree you want is `packages/atlassian-mcp`, at tag `v1.4.0`.

## 3. Author the wrapper before you copy

The copied subtree becomes the package's `payload/`. It does not contain the files the `mcp` type
requires, and it never will — upstream is not writing them for you. Author them beside it first, at
the package path this artifact will occupy:

```
artifacts/mcp/atlassian/
  SETUP.md
  payload/mcp.json
  setup/installer.json
```

`payload/mcp.json` is the `aart-mcp-v1` payload the type requires; it points at the copied entry
point:

```json
{"mcpServers": {"atlassian": {"command": "node", "args": ["payload/index.js"]}}}
```

`setup/installer.json` is a setup recipe v2 declaring what the server needs before it runs — here,
an API token in the macOS keychain. **The path must be exactly `setup/installer.json`**: a v2 recipe
is located package-relative and no other name is accepted. It must also declare `help_urls`, so an
operator asked for a secret can find out where the secret comes from. `SETUP.md` at the package root
is what a human reads before answering.

Upstream's own `install.sh` is *not* the recipe. It is payload — bytes you are about to redistribute
— and step 5 shows what AART says about it.

Files you author are recorded as authored; the vendoring will not overwrite them on this run or on
any later re-vendor.

## 4. Vendor, and read the review

```shell
aart registry vendor --source . mcp atlassian \
  --url https://github.com/example/atlassian-mcp.git \
  --ref v1.4.0 --path packages/atlassian-mcp \
  --artifact-version 1.0.0 \
  --summary "Atlassian MCP server, vendored from upstream." \
  --profile claude --platform darwin \
  --setup-recipe setup/installer.json
```

Without `--yes` this writes nothing. It renders:

```
Review canonical Maintainer action: vendor
  Review digest: sha256:6d7a84bf1e54c8309e47e568f584558f819a8a882cc4baa6504c0f251f1dd18c
  Mutation: yes, only on Finalize
  - unchanged: artifacts/mcp/atlassian/SETUP.md
  - added: artifacts/mcp/atlassian/artifact.json
  - added: artifacts/mcp/atlassian/payload/LICENSE
  - added: artifacts/mcp/atlassian/payload/index.js
  - added: artifacts/mcp/atlassian/payload/install.sh
  - added: artifacts/mcp/atlassian/payload/lib/client.js
  - unchanged: artifacts/mcp/atlassian/payload/mcp.json
  - added: artifacts/mcp/atlassian/provenance.json
  - unchanged: artifacts/mcp/atlassian/setup/installer.json
  - added: security/attestations/262af4ece….json
  - check vendor-assessment: passed
      installation risk: critical
      findings: 5
      install-effect-merge-json (medium): Installation merges values into harness JSON configuration.
      review-missing (medium): No registry review decision is attached to this artifact.
      setup-capability-filesystem (medium): Setup requests filesystem mutation authority.
      setup-capability-keychain (high): Setup requests credential-store access.
      shell-pipe-to-interpreter (critical): Shell content pipes downloaded bytes directly to an interpreter. [payload/install.sh]
  - check vendor-license: passed
      discovered: LICENSE: MIT
      recorded: MIT
  - check vendor-origin: passed
      origin: https://github.com/example/atlassian-mcp.git
      ref: v1.4.0
      resolved commit: 4d9f2c1b7a3e5f80d6c4b2a19e8f7c6d5b4a3e21
      subtree: packages/atlassian-mcp
      target: artifacts/mcp/atlassian
      declared version: 1.0.0
      payload files: 5
  warning: Vendoring copies upstream bytes into this registry and pins them to a commit; a successful vendor reports what was copied, and is not a safety claim.
  warning: Assessments reduce uncertainty; they are not safety guarantees.
  warning: This registry now owns the copy: upstream fixes do not reach consumers until it is vendored again.
  AART will not commit or push; review the working-tree diff afterward.
```

Four things in it are worth reading slowly.

**The path list is the whole change.** Nothing outside those paths is touched, and the three
`unchanged:` lines are the files you authored: the vendoring recognises them and leaves them alone.

**`vendor-assessment` is the assessment of the bytes that would be written**, not of upstream's
repository or its reputation. `shell-pipe-to-interpreter (critical)` is `install.sh`, which fetches
a URL and pipes it into a shell. That finding does not block the vendoring, and it should not: the
decision is yours. What you do with it is a maintainer's judgement — drop the file from the copy by
vendoring a narrower subtree, keep it and say so in `SETUP.md`, or decline the upstream. Deciding
nothing is also a decision, and `review-missing` is AART recording that you have not attached one.

**`vendor-license` is the copy's licensing.** `discovered:` is what AART read at the subtree root;
`recorded:` is what your `artifact.json` will publish it under. AART only reports a licence where
the text settles the SPDX identifier, and it never guesses between GPL `-only` and `-or-later`. If
it discovers nothing, state the identifier yourself with `--license`; a vendored artifact recording
none is reported by `aart registry audit`.

**`vendor-origin` is the pin.** `ref` is what you asked for and `resolved commit` is what it meant
at this moment. Only the commit is recorded as the origin; the ref is kept separately, so that
re-vendoring knows which moving name to re-resolve.

The checks passed. Read the warnings anyway: passing means the copy was made and pinned, and
nothing more.

## 5. Finalize, then treat it as ordinary content

```shell
aart registry vendor --source . mcp atlassian … --yes
aart registry lock --source . --yes
aart registry build --source . --yes
aart registry audit --source .
aart registry validate --source . --strict --frozen
```

Nothing in those four commands knows what vendoring is. `artifact.json` is an ordinary manifest:

```json
{"compatibility":{"platforms":["darwin"],"profiles":["claude"]},
 "install":{"effects":["merge-json"],"modes":["copy"],"scopes":["project"]},
 "license":"MIT","name":"atlassian","payload":{"format":"aart-mcp-v1","root":"payload"},
 "schema_version":1,"setup":{"platforms":["darwin"],"recipe":"setup/installer.json"},
 "summary":"Atlassian MCP server, vendored from upstream.","type":"mcp","version":"1.0.0"}
```

The one document that marks it as a copy is `provenance.json`, which AART has read since `2.0.0`:

```json
{"aart.vendor":{"authored":["SETUP.md","payload/mcp.json","setup/installer.json"],"ref":"v1.4.0"},
 "importer":{"id":"registry-vendor-v1","options_digest":"sha256:e00930d8…","version":"2.3.0"},
 "origin":{"input_digest":"sha256:76f0be36…","kind":"git","path":"packages/atlassian-mcp",
           "resolved_commit":"4d9f2c1b7a3e5f80d6c4b2a19e8f7c6d5b4a3e21",
           "url":"https://github.com/example/atlassian-mcp.git"},
 "schema_version":1,"warnings":[]}
```

`aart.vendor` is the namespaced extension holding the two facts re-vendoring needs and a provenance
document does not otherwise carry: the ref the copy was taken at, and which files you wrote rather
than copied. It is verified against `importer.options_digest`, so a hand-edited record is refused
rather than believed — editing `ref` there to point somewhere else fails `aart registry audit`.

Commit the working tree yourself. AART never commits and never pushes.

## 6. When upstream moves

```shell
aart registry revendor --source . mcp atlassian --check
```

```
  - check vendor-drift: failed
      disposition: changed
      ref: v1.4.0
      recorded commit: 4d9f2c1b7a3e5f80d6c4b2a19e8f7c6d5b4a3e21
      resolved commit: 9b1c7e4a2f6d8035c1a9b7e6d4f2c0a8b6d4e2f1
      upstream files added: 1
      upstream files changed: 2
      upstream files removed: 0
      state the version this movement deserves with --artifact-version to plan it
  warning: Upstream moved. This registry owns the version, so it states the new one.
  warning: Nothing was written.
```

The tag moved under you — which is exactly why the commit, not the ref, is what was recorded.
`--check` exits non-zero on `changed`, so it belongs in the registry's scheduled job.

There are three dispositions and the third matters: an upstream that cannot be reached reports
`unreachable`, never `up-to-date`. Silence is not evidence that nothing changed.

Applying the movement requires the version you state for it. Upstream declares no version AART can
trust — that is the price of owning the copy — so there is no default and no inference:

```shell
aart registry revendor --source . mcp atlassian --artifact-version 1.1.0 --yes
```

The review lists the same assessment again, over the new bytes, and the same three `unchanged:`
lines for the files you authored. Then re-run `lock`, `build`, `audit`, and `validate`, and publish;
until you do, your consumers are still installing `1.0.0`.

## 7. Keeping the copy honest

`aart registry audit` is a pure function of the committed snapshot by default: it reaches no
network, so it works offline and in CI without a Git remote. Ask it to look upstream explicitly:

```shell
aart registry audit --source . --check-upstream
```

It then reports every vendored artifact that is behind its origin, and reports an unreachable origin
as unknown. Neither finding fails the audit — being behind upstream is a fact about the world, not a
defect in the registry — but both are printed, and a registry that never looks will never know.
