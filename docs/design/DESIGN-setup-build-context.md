# Design: a setup recipe that can build from the package it belongs to

Status: proposed. Target release `2.5.0`, contract v13.

## 1. What this has to make possible

A real artifact, `mcp/company-atlassian`, exists and cannot be expressed. It vendors two files from a
non-AART repository — `payload/server.py` and `payload/requirements.txt` — and carries an authored
wrapper beside them: a `Dockerfile`, an `mcp.json`, a `SETUP.md`, and a setup recipe. Installing it
should:

1. export the company's corporate CA certificates from the machine's system trust store;
2. build a Docker image locally from the package payload plus that certificate bundle;
3. store an Atlassian API token in the login keychain and export it into new shells;
4. leave `mcp.json` pointing at the locally built image.

Steps 3 and 4 work today. Steps 1 and 2 do not, and the maintainer's workaround is a shell script
run by hand from a clone of the registry. This design closes the gap without turning the recipe into
a shell.

The image is built **locally and never published**. Nothing is pushed to any registry, and this
design adds no way to push one.

## 2. One root cause

The setup model has two address spaces: the consumer's home, and the project. `_resolve_target`
(`setup.py:529`) resolves `~`, an absolute path, or a path relative to one of those two roots.
Every one of them is a **destination**.

There is no way for a recipe to name a **source**. The package the recipe belongs to is not in
either address space, and no step can refer to it.

The one exception proves the rule. `custom_entrypoint` is resolved by AART against the package root
and never named by a step — and the script it names is copied into a per-run temporary directory and
executed there with `cwd` set to that directory and an environment holding `AART_SETUP_PLAN_HASH`,
`RUN_DIR`, `ARTIFACT`, `PROFILE`, `SCOPE`, `SOURCE`, and `INSTALLER_HASH`. **No path to the package
is among them.** So even the arbitrary-code escape hatch cannot read the payload it shipped beside.

A recipe can say where to write. It cannot say what to read. That is the whole defect.

## 3. The package is not a workspace, and must not become one

The obvious fix — hand the recipe the package directory — is wrong, and the maintainer's own
`install.sh` shows why. It writes `company-ca.pem` into `payload/`, builds, and deletes it. That
works because it runs against a Git clone of the registry, where `payload/` is an ordinary writable
directory. It is not where an installation runs.

On a consumer's machine the package lives in the object store, and `_read_candidate`
(`io/object_store.py:225`) walks the whole tree and recomputes the digest **on every read**; a
mismatch is `loaded setup object digest is invalid`. Since `2.4.0` a vendored payload carries a
second lock: it is compared with `origin.input_digest`, and an edited copy fails `validate --strict`
and `audit`.

So the store is read-only by construction, twice over, and this design keeps it that way.

**The build context is a working copy.** `docker.build@1` materializes the declared context into the
per-run directory that `custom.install@1` already establishes
(`<data_root>/.agent-artifacts/setup-runs/<plan-hash>-<random>/`), builds there, and removes it.
Steps that contribute files to a build contribute them to that copy. Nothing writes into the object
store; the store is only ever read.

This is also what makes the certificate step expressible at all: a file that must exist beside the
`Dockerfile` at build time, and must not exist in the registry, has somewhere to be.

## 4. How the package is addressed

A new value kind: a **package-relative source path**. It is validated exactly as `custom_entrypoint`
already is — relative, no `..`, no absolute path — and resolved by AART against the queue item's
source root. It is never rendered into a step's writable target and never handed to a step as a
string it could pass somewhere else.

In this release exactly one field takes one: `docker.build@1`'s `context`.

**Deliberately not a general `${PACKAGE_ROOT}` variable.** A general variable would let any step read
or write anywhere inside the store, which is the thing §3 exists to prevent, and it would have to be
honoured by every module ever added. One field, one meaning, one place to check.

## 5. The corporate CA is a certificate, not a secret

`security find-certificate -a -p` exports certificates. It does not export private keys. A corporate
root CA is public by nature — it is what the interception proxy presents to every machine on the
network — so routing it through the recipe's secret machinery would be wrong twice: it would prompt a
human for something they do not have and cannot type, and secret inputs may only be interpolated by
`macos-keychain.store@1` anyway.

It is therefore a new, narrow module: **`trust-store.export-certificates@1`**. It reads the system
keychain, keeps the certificates whose subject contains a declared substring, and writes a PEM bundle
into the materialized build context under a name the recipe declares. It stores nothing, reads no
private key, and can write nowhere except the working copy.

It gets its own capability, **`trust-store`**, rather than reusing `keychain`. `keychain` currently
means credential-store access and the assessment reports it as `high`; reading the machine's public
certificate list is a materially smaller claim, and a review that inflated it would teach maintainers
to ignore the word.

If no certificate matches, the step fails and says so. A build that silently produced an image
without the CA would fail later, inside `pip`, with a TLS error nobody can trace back here.

## 6. A local image pins its input, because it has no output to pin

`docker.pull@1` demands an immutable `sha256` digest, because the whole point of a pull is to name
bytes fetched from elsewhere. A build has no digest before it runs, and two consumers building the
same context get different image ids. The invariant does not transfer.

What does transfer is the other half, and `2.4.0` already supplies it: the *inputs* are pinned. The
payload is digest-verified on every read, and for a vendored package `origin.input_digest` ties it to
the upstream subtree. So the honest statement is **"builds from these bytes"**, and the receipt
records the digest of the materialized context, the tag, and the resulting local image id.

The tag is derived, not authored: `aart/<type>/<name>:<version>`. It is predictable when the
descriptor is written, so `mcp.json` can name the image without any new interpolation in
`aart-mcp-v1`. A recipe may not choose an arbitrary tag; two versions of one artifact must not
collide, and rollback must know what it is removing. `company-atlassian-mcp:latest` is exactly the
shape this refuses.

Rollback removes the tag **only if this run created it**. A tag that already existed is left alone,
the same care `docker.pull@1` takes with a shared image, for the same reason.

## 7. The manual route is not optional, and neither is the review

Every setup-bearing package already must ship a package-root `SETUP.md`, and the review renders the
manual alternative **before consent** and again after an incomplete outcome
(`render_manual_alternative`). The recipe is the guided route; it never becomes the only route. A
maintainer may reasonably expect a consumer to do all of this by hand, and the protocol already
holds that open.

Two consequences for this design:

- Each new module supplies its own `_effect_identity` and `_effect_details` line. Without them a
  build renders as the generic "Run a reviewed setup effect", which for something that executes a
  Dockerfile with network access would be a review that understates what it is asking for.
- The documentation requires the `SETUP.md` route for a build to be a command a human can paste,
  producing the same tag. A manual route that does not reproduce the automated result is not a
  manual route.

**The review must say plainly that a build runs the Dockerfile's instructions.** `RUN` is arbitrary
code with network access; this is not the same claim as pulling a pinned image, and the capability
set (`docker`, `network`, `process`) says so.

### The Dockerfile is not assessed today

`_text_like` (`security/baseline.py:675`) treats a file as scannable when it ends in a known suffix,
carries the executable bit, or starts with a shebang. A file named `Dockerfile` has none of the
three, so **the baseline does not read it at all**. That is tolerable while AART only redistributes
it. It is not tolerable once AART executes it: the artifact would run bytes the assessment never
looked at, in a release whose entire subject is the gap between what is copied and what is run.

`Dockerfile`, `*.dockerfile`, and `Containerfile` become text-like, so the existing rules — pipe to
interpreter, secret assignments, remote fetch — fire on `RUN` lines.

## 8. What this deliberately does not do

- **It does not add arbitrary shell.** `shell.run@1` stays unknown. The two things the real artifact
  needed shell for are the two modules added here; anything else remains the custom entrypoint's
  business, with the capability and the hash that entails.
- **It does not make the payload writable.** The store is read-only, and the working copy is AART's,
  not the recipe's.
- **It does not push, tag for a registry, or authenticate to one.** The image is local. A build that
  needs a private base image is discussed below as a limitation, not solved.
- **It does not change what `mcp` installs.** Delivery is still `merge-json`; the artifact reaches
  the consumer as a config entry naming an image that setup built.
- **It does not add a `text` input type.** The real artifact wants to prompt for a username, which is
  not a secret, and `inputs` accepts only `type: "secret"`. Recorded as a residue; `SETUP.md` covers
  it in the meantime.
- **It does not touch `docker.pull@1`.**

## 9. Limits this release states rather than hides

**A local build is only as offline as its `FROM` line.** `FROM python:3.11-slim` pulls from a public
registry, and `RUN pip install` reaches the network — that is the whole reason the CA is needed.
"Built locally" means the image is not distributed; it does not mean nothing leaves the machine, and
the documentation says so in those words.

**A private base image will not authenticate.** Setup process steps run under `_minimal_env` — `PATH`,
`LANG`, `LC_ALL`, `LC_CTYPE`, `TERM` — with **no `HOME`**, so the Docker CLI cannot read
`~/.docker/config.json` and will not find registry credentials or a non-default context. The daemon
itself is reachable without `HOME`. This is a pre-existing property that already affects
`docker.pull@1`; this design records it and does not widen the environment, because the environment
is narrow on purpose. Whether AART should pass a Docker configuration path explicitly is a separate
decision.

**An artifact using these modules must raise its `requires_aart` floor.** An older AART rejects an
unknown module by name, which is the correct failure — closed, not silent — but it is a failure, and
the artifact should declare `min_inclusive: "2.5.0"` rather than let a consumer discover it.

## 10. Release shape

Minor: `2.5.0`, contract v13. Two new modules, one new capability, one new value kind in the recipe,
one analyzer widening. Nothing is removed, no existing recipe changes meaning, and no consumer-side
install effect changes.

The setup recipe stays at protocol version 2. Adding modules is additive: a recipe that uses one is
rejected by name on an older executable, and a recipe that does not is unaffected. There is no
second revision of the recipe format and no migration.
