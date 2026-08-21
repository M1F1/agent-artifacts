# agent-artifacts — Options: moving AART to GitHub Enterprise and to a company's CI

Companion to [DESIGN-registry-vendoring.md](DESIGN-registry-vendoring.md),
[git-environment-v1.md](../configuration/git-environment-v1.md) and the recipe-format options note
on the `docs/recipe-format-options` branch.

**The question.** AART is easy to install on a laptop. Is it easy to move into a company that runs
GitHub Enterprise Server, private runners, and its own Docker images in CI/CD? This note measures
what already works, names the walls, and proposes six separable designs. Nothing here is
implemented.

**The short answer.** The content path is already portable and was designed that way. The *tool
delivery* path, the *network* path and the *setup* path are not. None of the three is hard; one of
them is expensive, and the expensive one is the one a company will ask for first.

---

## 1. What already works, and why

These are not assumptions. Each is a line of shipping code.

- **Sources are host-agnostic.** `git_location_parts` (`configuration/model.py:254`) accepts HTTPS,
  SSH and SCP-style locations for any hostname. A GHE host is not a special case; it is the
  ordinary case with a different name.
- **There is no API host to configure.** Per-upstream GitHub API metadata was designed and then
  deleted — `DESIGN-upstream-github-hosts.md` is marked superseded, and `2.3.0` removed
  `io/net.py`, the last module that carried a token. AART reaches Git through system Git and holds
  no credential of its own.
- **The tool is one file with no dependencies.** Zero runtime dependencies, standard library only,
  and `pip install --no-index --no-deps` installs the wheel with no index and no build step. A
  company can treat AART as a *file*, not as a network operation. This is the strongest card in the
  hand and most of this note is about playing it.
- **The registry CI already parameterises where the tool comes from.** Registry A's three workflows
  read `vars.AART_REPOSITORY` and `vars.AART_REF`, defaulting to `M1F1/agent-artifacts`. Half of
  the mirroring work is done.

---

## 2. The walls

### W1 — Getting the tool onto a runner assumes github.com

Two routes exist in the constellation and neither survives an air gap.

- Registry A checks the tool repo out with `actions/checkout` and runs
  `python -m pip install --no-deps ./.aart-tool`. On GHES, `actions/checkout` with a `repository:`
  reads *the GHES instance*, not github.com, so the tool repo must be mirrored inside the company
  first. Installing from a source directory also needs the `setuptools` build backend at install
  time, which a locked-down image may not have.
- The consumer repo installs the wheel from a github.com release URL and never checks its digest
  (`LAF-98`, open). In a company that URL is not reachable at all.

Both workflows also use `actions/setup-python@v5`, which fetches a Python build from github.com
unless the runner image has already populated the tool cache. On a private runner with no egress
this is the step that fails first, before anything of AART's is even reached.

### W2 — The route that fixes the network is a per-machine step, and runners are ephemeral

`git-environment-v1.md` is explicit and correct: the Git subprocess receives an allowlisted
environment — `HOME`, `PATH`, `SSH_AUTH_SOCK`, `XDG_CONFIG_HOME`, `SYSTEMROOT`
(`io/git.py:17`) — and `https_proxy`, `http_proxy`, `no_proxy`, `ALL_PROXY`, `GIT_SSH_COMMAND` and
`GIT_CONFIG_GLOBAL` are dropped on purpose, because a proxy URL is an ordinary hiding place for a
credential. The documented fix is Git's own configuration, which works because `HOME` is passed:

```bash
git config --global http.proxy http://proxy.example:3128
```

That is the right rule and this note does not propose weakening it. It proposes noticing what it
costs in CI. **A container has a `HOME` and no `~/.gitconfig`.** The company's proxy and its deploy
key arrive the way CI always delivers them — as environment variables, `HTTPS_PROXY` and
`GIT_SSH_COMMAND` — and AART drops both. So every job needs a preflight step that nobody wrote,
and when it is missing the failure is a raw transport error with no mention of a proxy. The
document says this failure now has a name. Nothing in the tool says the name out loud at the moment
it happens.

### W3 — Setup cannot run anywhere except a Mac

`setup.py:562` refuses any recipe whose `platforms` is not exactly `["darwin"]`. The secret step is
`macos-keychain.store@1`, and `trust-store.export-certificates@1` shells `/usr/bin/security`
(`setup.py:496`). A Linux runner has no Keychain and no `security` binary.

So "AART in CI" today can only mean install, validate, build and reconcile. It cannot mean setup.
That may well be correct — see Option D — but it is currently a wall rather than a decision, and a
company reading the feature list will not find out until they try.

### W4 — Image references are literal, public and digest-pinned

`docker.pull@1` passes `config["image"]` through untouched (`setup.py:843`). Registry A's
`mcp/github-enterprise-docker` recipe pins
`ghcr.io/github/github-mcp-server@sha256:881b53d6…`. A company whose runners and laptops pull
through Artifactory or a pull-through cache cannot reach `ghcr.io`, so today it must fork every
setup-bearing artifact and rewrite the reference — and a fork is exactly the thing the digest pin
existed to make unnecessary.

### W5 — AART's own release pipeline names github.com in the file

`release.yml` clones `https://github.com/M1F1/agent-artifacts-registry.git` as a literal, runs on
`ubuntu-latest`, uses `actions/upload-artifact@v4` and finishes with `gh release upload`. On GHES
the runner labels are different, the marketplace actions may not be present, and `gh` needs
`GH_HOST` and an enterprise token.

---

## 3. Options

Six designs. They are separable and are listed in the order they should probably be paid for.

### Option A — Treat the wheel as the unit of delivery, and prove it offline

*Make "get AART onto a runner with no egress" a supported, tested, documented path.*

- The install contract becomes: a wheel, a `sha256`, and
  `pip install --no-index --no-deps <wheel>`. `scripts/release.py wheel-digest` already produces
  the digest; nothing in the constellation's CI calls it, which is `LAF-98`. Closing `LAF-98` and
  opening the enterprise path are the same piece of work.
- Publish a small install snippet — a shell function or a composite action, one file — that takes a
  wheel location and an expected digest, verifies, then installs. A company copies it into their
  shared actions repo or bakes it into their runner image.
- Document baking the wheel into the CI image as the *first-class* option, not the fallback. A job
  that needs no network for the tool cannot be broken by the network.

**Cost:** no change to AART. Packaging, one script, one page, one test. **Buys:** W1 entirely, and
a closed `LAF-98`.

### Option B — A Git configuration that is handed over on purpose

*Keep the rule "never carry a credential you were not handed"; add a way to hand one over.*

Accept an explicit path — `--git-config <file>`, or `AART_GIT_CONFIG` — and pass it to the Git
subprocess as `GIT_CONFIG_GLOBAL`. One file, written deliberately, reviewable, and named in the
receipt. Ambient `https_proxy` stays dropped; the operator who wants a proxy points at a file that
says so.

This is a smaller change than it looks: `_safe_environment` (`io/git.py:91`) grows one conditional
entry, and `tests/git_environment_docs_test.py` already forces the published tables to stay true,
so the documentation cannot drift.

**Cost:** one knob, one table row, one test. **Buys:** W2 for the ephemeral-runner case without
touching the credential rule.

### Option C — A command that says why the network will fail, before it fails

*The single highest-value item for adoption.*

A preflight command — **not** `source doctor`, which was removed in `2.0.0` and should not come
back under that name — that answers "can AART reach anything from here, and if not, why".

- Compares the ambient environment against the allowlist and says it plainly: *you exported
  `https_proxy`; AART drops it on purpose; this is the line that works.*
- Checks the ordinary preconditions: `git` present and its version, whether a global Git config
  exists at all, whether each configured source's host resolves, whether `docker` is present, and
  whether the running AART matches the version the registry's lock expects.
- Emits `--json`. `LAF-115` records that the one command group written for a machine has no machine
  channel; a command whose main consumer is CI must not repeat that.
- Fails with a named diagnostic code and a remediation sentence, the way `no-source-configured`
  already does.

**Cost:** a new command group, no protocol change. **Buys:** turns W2 from an afternoon into one
line, and gives a company a gate to put at the top of every pipeline.

### Option D — Setup somewhere other than a Mac

The expensive one. Two shapes, and the choice between them is a real decision.

**D1 — Say no clearly (cheap).** Keep `platforms: ["darwin"]`. Make the refusal first-class: on
Linux, `aart setup` names the platform the recipe declares and the platform it is running on, with
remediation. Document that setup is a laptop operation and CI is not its audience. This may simply
be the right answer — a CI job does not want a Keychain-backed MCP token.

**D2 — Widen the protocol (expensive).** Admit `linux`, introduce a secret step with backends
(`macos-keychain`, an env-var handed in by the CI secret store, a `0600` file), and let the trust
step read a CA file instead of shelling `/usr/bin/security`.

The cost of D2 is not the code. `schema_version` and `protocol_version` must both be exactly `2`,
and this project ships one revision of a protocol and refuses the rest. Changing what a recipe may
say means every published recipe rises in step, and a registry rebuilt on the new revision stops
being readable to consumers who have not upgraded — the `LAF-60`/`LAF-62` rollout, a third time.

**Therefore D2 should never be paid alone.** It belongs in the same change as the recipe-format
cluster `RS-11`, `RS-13`, `RS-14`, `RS-15`, which the options note on `docs/recipe-format-options`
already treats as one decision. That bill is the same for one change or five.

**And this note supplies what that note was waiting for.** Its recommendation was to wait for two
observations, neither of which existed in any run: *a second GHE host, which is what produces a
per-operator value that is not a secret*, and *an operator who completed a setup wrongly because the
recipe could not ask for a username*. A company GHE deployment is the second host. If the move
happens, the recipe-format decision stops being hypothetical and should be reopened with this note
as its second observation.

### Option E — Reaching images through a company mirror

**E1 — Say the daemon does it (free).** A transparent pull-through cache configured on the Docker
daemon needs no AART change at all. Document it first, because for many companies it is the whole
answer.

**E2 — A rewrite map (only if the mirror is not transparent).** Artifactory-style mirrors change the
path, not just the host, so a transparent cache is not always available. Then AART needs an
operator-level mapping applied at plan time — and, critically, **shown in the review before the run,
so the operator sees the rewrite.** The argument that makes this safe is the digest: a mirror that
serves `@sha256:881b…` serves identical bytes, so the pin still means exactly what it meant. A
rewrite that drops or changes the digest must be refused.

Note that `LAF-67` is open and relevant: every published recipe uses `docker.pull@1` and none uses
`docker.build@1`, so the build-side acceptance criteria are still unreachable against published
content. A company mirror exercises the pull side only.

### Option F — Make AART's own pipeline host-agnostic, then walk it

- `runs-on: ${{ vars.AART_RUNNER || 'ubuntu-latest' }}`.
- The hardcoded reference-registry clone in `release.yml` becomes a variable.
- A documented no-marketplace-actions fallback: plain `run:` steps for checkout, Python and
  artifact upload, for a GHES instance that does not carry the actions.
- `gh` usage states `GH_HOST` and which token it needs.

Then prove it the way this repo proves everything else: run the whole pipeline once on a private
runner inside a company-shaped image, and record it as a live-acceptance walk with its own
findings. `agent-artifacts-upstream` was created as the rehearsal for pointing AART at a company
GHE host; this is the CI half of the same rehearsal.

---

## 4. Recommendation

Pay **A** and **C** first. Together they cost no protocol change, close an open finding, and remove
the two failures a company hits in their first hour — the tool will not install, and the network
will not work with no explanation. **B** follows immediately and is small.

**F** is next, because it is the rehearsal, and this repo does not trust a claim it has not walked.

**E1** is free and should simply be written down. **E2** waits for a mirror that is actually not
transparent.

**D** is a decision, not a task. Take **D1** now — a clear refusal is worth having either way — and
open **D2** only bundled with the recipe-format cluster, with the company GHE host recorded as the
second observation the earlier note was waiting for.

## 5. Open questions

1. Does the company's GHES carry the marketplace actions, or must every workflow be written with
   plain `run:` steps? This changes Option F from a variable to a rewrite.
2. Is the runner image allowed to carry a baked wheel, or must the tool be fetched per job? This
   decides whether Option A ends at "bake it" or needs the internal-URL-plus-digest path too.
3. Is egress through a proxy, or is it fully closed? A closed network makes `docker.pull@1`
   unusable without Option E and makes Option D1's refusal more attractive than D2's widening.
4. Does CI need setup at all, or only install/validate/reconcile? If the honest answer is the
   latter, D1 is the whole of Option D and the expensive branch never opens.
