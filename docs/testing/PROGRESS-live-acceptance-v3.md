# Live acceptance v3 — progress

Third live acceptance run, against the released `2.3.0` executable, the published registry, and a
real third-party monorepo. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md) and [v2](PROGRESS-live-acceptance-v2.md) records are the prior runs
this one is read against, and neither is ever rewritten.

**Status: agent scope complete for the vendoring surface.** Two scenarios are `blocked` for a stated
reason, not skipped. Curses and credential passes remain human-gated (design §10).

## What makes this run different

v2 stressed the subscription lifecycle a consumer lives in. This run's subject is `2.3.0`'s one new
capability — **registry vendoring** — and the question is not "does the command work" but *does a
registry that vendors somebody else's code end up telling the truth about it*:

1. **A real foreign upstream, not a fixture.** Everything vendored here comes from
   `modelcontextprotocol/servers` — a monorepo with no AART markers, cloned live over HTTPS.
2. **The whole chain, not the verb.** A vendored artifact is claimed to be an ordinary owned
   package; that claim is only tested by locking, building, auditing, publishing, and *installing*
   it into a consumer project.
3. **The refusals are the feature.** `unreachable` must not read as `up-to-date`, a hand-edited
   provenance record must fail, a duplicate identity must be refused, and a clean vendor must not
   imply the content is safe.

## Run header

| Field | Value |
|---|---|
| AART tag | `v2.3.0` |
| AART commit | `4a77364e4e6bd54637eafe74b365260661e3105e` (embedded in the wheel) |
| Wheel | `agent_artifacts-2.3.0-py3-none-any.whl` (502 919 bytes), **downloaded from the GitHub release** |
| Wheel sha256 | `b10d88cfb49fe28958993fc9d61eb0f017c3de277eb37d3b3d6976cda50f5f5e` |
| `aart --version` | `agent-artifacts 2.3.0` |
| Test venv | `$LA3/venv` — only `agent-artifacts`, `pip`, `setuptools` |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Registry A | `M1F1/agent-artifacts-registry` @ `7c7dd31`, cloned locally; **never pushed** |
| Upstream | `modelcontextprotocol/servers` @ `76d64c8` — monorepo, no AART markers, `src/<server>` |
| Historical upstream | the same repository at `0588ec09` (2026-06-14), fetched by sha |
| Sandbox root | `$LA3` = `~/.aart-live-acceptance-3` |
| Started / last updated | 2026-08-14 |

## New stressors registered for this run

The v1 (`LAS-01`..`LAS-30`) and v2 (`LAS-31`..`LAS-40`) registers carry over unchanged. Appended
here, append-only:

| ID | Stressor | Why it is plausible |
|---|---|---|
| `LAS-41` | The vendored upstream has a layout that owes AART nothing | every real vendoring |
| `LAS-42` | The upstream moves between the vendoring and the next look | the reason re-vendoring exists |
| `LAS-43` | The upstream cannot be reached when drift is checked | network, deletion, rename, private |
| `LAS-44` | The copied payload contains something a maintainer should refuse | the reason the assessment runs |
| `LAS-45` | The provenance record, or the copied payload, is edited after the fact | the record is the only origin claim |
| `LAS-46` | The subtree carries no licence, or one AART cannot name | most subdirectories of most monorepos |
| `LAS-47` | A vendored artifact is installed by a consumer | the compatibility claim |
| `LAS-48` | Two vendorings target the same identity | a maintainer repeats themselves |

## Phase status

| Phase | Scenarios | Status | Note |
|---|---|---|---|
| LA3-0 harness | 0.1 – 0.4 | **complete** | 4/4 pass; the published wheel's digest matches the one the tag computes |
| LA3-V vendoring | V1 – V6 | **complete** | real monorepo, two subtrees, wrapper adoption, duplicate refusal |
| LA3-D drift and re-vendoring | D1 – D4 | **complete** | 2 pass, 1 fail, 1 blocked live |
| LA3-A audit and licence | A1 – A4 | **complete** | licence finding and tamper refusal both fire; one reporting gap |
| LA3-C consumer end to end | C1 – C3 | **complete** | a vendored artifact installs, reconciles, and uninstalls |
| LA3-T text front-end | T1 – T2 | **complete** | vendoring driven to Finalize over a pty |
| LA3-X stressors | X1 – X3 | **complete** | 1 blocked live for the same reason as `D3` |
| LA3-H human-gated | — | not started | curses pass and MCP credential pass remain Michal's (design §10) |

## Scenario results

| ID | Result | Finding | Note |
|---|---|---|---|
| `LA3-0-01` | pass | — | the **release asset** wheel installs into a clean venv, reports `2.3.0`, embeds commit `4a77364`, and pulls in no non-stdlib dependency |
| `LA3-0-02` | **pass (v2 `LAF-30` fixed)** | — | the published wheel's sha256 is **byte-identical** to what `scripts/release.py wheel-digest` computes at the tag: `b10d88cf…`. v2's "content-reproducible but not byte-reproducible" is closed, verified against the real release asset |
| `LA3-0-03` | pass | — | the published registry (`2.0.0` contract) passes `registry validate --strict --frozen` and `registry audit` under `2.3.0` unchanged; the two new findings do not fire on non-vendored content |
| `LA3-0-04` | pass | — | `HOME` override isolates completely; no mirror, cache, or data root survives a refused vendoring |
| `LA3-V-01` | pass | — | vendoring an `mcp` **without** authoring the payload document first is refused with `a vendored mcp needs payload/mcp.json; the taken subtree does not contain it, so the maintainer supplies it` — the refusal names the file and whose job it is |
| `LA3-V-02` | pass | — | `src/git` of a real monorepo vendored at `main`: 13 payload files, `mcp.json` adopted as `unchanged`, licence discovered `MIT` from the subtree root, origin block reports URL/ref/resolved commit/subtree/target/version. Review writes nothing |
| `LA3-V-03` | pass | — | `--yes` writes exactly the reviewed paths plus the attestation; `provenance.json` records `registry-vendor-v1`, the resolved commit, and `aart.vendor: {ref: main, authored: [payload/mcp.json]}` |
| `LA3-V-04` | pass | — | `lock` → `build` → `validate --strict --frozen` accept the vendored package as ordinary owned content; validate before lock/build refuses and **names the artifact** (`compiled index disagrees with owned package mcp/mcp-git`) |
| `LA3-V-05` | pass | — | `src/filesystem`, a subtree with no licence file: review reports `discovered: no license file in the taken subtree` / `recorded: none; state one with --license, or registry audit will report it` |
| `LA3-V-06` | pass | — | `LAS-48`: vendoring the same identity again is refused — `artifact package already exists: mcp/mcp-git` — instead of overwriting a package a maintainer may have edited |
| `LA3-D-01` | pass | — | `revendor --check` against an unchanged upstream reports `up-to-date` and writes nothing |
| `LA3-D-02` | **pass** | — | `LAS-43`: with the upstream unreachable (dead proxy in the sandbox git config) the check reports `disposition: unreachable`, **fails**, exits `1`, and says `An unreachable upstream is not an up-to-date copy; nothing was compared` and `The vendored copy is unchanged and still installable; only the check failed`. The design's central refusal holds live |
| `LA3-D-03` | **fail** | `LAF-41`, `LAF-42` | `LAS-45`: a package whose payload was replaced with the same subtree at a **two-month-older commit** — real bytes, real history, `README.md`/`pyproject.toml`/`uv.lock` all different — is reported `disposition: up-to-date`, directly beneath a `recorded commit` and a `resolved commit` that differ. The comparison trusts `origin.input_digest`, which nothing re-verifies against the bytes on disk |
| `LA3-D-04` | **blocked** | `LAF-43` | `LAS-42`: the `changed` disposition could not be exercised against a real remote. Vendoring accepts only credential-free HTTPS/SSH, so a local repository cannot be an upstream, and no controllable HTTPS remote was available without publishing content. Covered hermetically by the unit suite; **not** covered live |
| `LA3-A-01` | pass | — | `registry audit` reports `vendored artifact redistributes upstream bytes with no declared license: mcp/mcp-filesystem` and still exits `0` |
| `LA3-A-02` | pass | — | `LAS-45`: editing `origin.url` in `provenance.json` by hand **fails** the audit — `the recorded vendoring instruction does not match its options digest; provenance.json has been edited by hand` — and `revendor` refuses to run at all against the edited record |
| `LA3-A-03` | pass | — | `audit --check-upstream` with the upstream unreachable reports `vendored artifact upstream could not be read, so drift is unknown: <id> (<url> at <ref>)` per artifact and still exits `0`, as designed |
| `LA3-A-04` | **fail** | `LAF-45` | `audit --check-upstream` against a current upstream prints **nothing at all** about the vendored artifacts. "Checked, and current" is indistinguishable from "the flag was never passed" |
| `LA3-C-01` | pass | — | `LAS-47`: the vendored artifacts appear in `marketplace list` with `origin=<url>@<commit>:<subtree>` — a consumer can see where the bytes came from without opening the registry |
| `LA3-C-02` | pass | — | install into a clean consumer repo succeeds; the manifest records object/payload digests and the `merge-json` effect; `status` reports `current`. The compatibility claim holds: no consumer code knows what vendoring is |
| `LA3-C-03` | **fail** | `LAF-46`, `LAF-47` | the install writes **only** `.mcp.json`; no copied payload byte reaches the project. And after uninstalling everything, the `.mcp.json` AART created survives as `{"mcpServers":{}}`, so a repo that was clean before is dirty after — v2's `LAF-17` family, with directories now reclaimed and a created file not |
| `LA3-R-01` | pass | — | a `requires` naming the vendored identity locks, builds, and validates, and the compiled index records it. The `2.2.0` residue — a promoted reference is not a `requires` target — is closed by ownership, live |
| `LA3-T-01` | **pass** | — | over a pty with `TERM=dumb`, `vendor` is action 5 in the maintainer menu, prompts for origin/subtree/version/licence/recipe/profiles/platforms, and renders the identical review — assessment, licence, origin, all three warnings. `n` writes nothing |
| `LA3-T-02` | **pass** | `LAF-48` | `y` finalizes and writes the package (12 paths). Two warts: the stage is labelled **"Native reference details"** while vendoring, and declining at the Finalize prompt re-renders the same review, re-fetching the upstream |
| `LA3-X-01` | pass (residue) | `LAF-44` | a private or non-existent upstream reports `fatal: unable to get password from user` with remediation `retry source synchronization` — the wrong diagnosis and a remediation naming an operation that is not part of vendoring |
| `LA3-X-02` | pass (question) | `LAF-49` | AART runs Git with an allowlisted environment (`HOME`, `PATH`, `SSH_AUTH_SOCK`, `XDG_CONFIG_HOME`, `SYSTEMROOT`), so `https_proxy` is dropped. Deliberate — proxy URLs carry credentials — and undocumented; on a proxy-only network every vendoring fails, and the `~/.gitconfig` workaround is undiscoverable |
| `LA3-X-03` | **blocked** | `LAF-43` | the "repository contains a symlink" refusal could not be exercised: the fixture is necessarily a local repository, and vendoring will not take one |

Legend: `pass` · `fail` (finding filed) · `blocked` · `deferred`.

## Findings — residues

**Record, do not fix** (design §8). Numbering continues from v2 (`LAF-40` was its last).

| ID | Sev | Scenario | Stressor | Component | Symptom | Reproduction | Blocks |
|---|---|---|---|---|---|---|---|
| `LAF-41` | major | `LA3-D-03` | `LAS-45` | `provenance.json` `origin.input_digest` ↔ every gate | **Nothing verifies that the bytes a registry ships are still the bytes its provenance describes.** `input_digest` is written at vendoring time and never checked again: not by `registry validate --strict --frozen`, not by `registry audit`, not by `revendor`. Replace a vendored package's payload, re-run `lock` and `build`, and every gate is green while `origin.input_digest` describes a subtree that is no longer there. The lock and index pin the *current* bytes, so they agree with the tampered copy by construction. Vendoring's one claim — this is where these bytes came from — has no gate behind it | vendor an artifact; overwrite files under its `payload/`; `registry lock --yes`, `registry build --yes`, `registry validate --strict --frozen`, `registry audit` — all pass | nothing; it is the trust boundary the release documents |
| `LAF-42` | major | `LA3-D-03` | `LAS-42`, `LAS-45` | `revendor` drift disposition | **`revendor --check` reported `up-to-date` for a copy two months behind upstream.** The disposition is computed from the recorded `input_digest` against the freshly resolved subtree, not from the payload on disk, so a copy whose bytes no longer match its own record is compared as if it did. The same block prints `recorded commit: 0588ec09…` and `resolved commit: 76d64c82…` — two commits, sixty commits apart on that subtree, with `disposition: up-to-date` between them and no line reconciling them. Even in the healthy case this rendering is ambiguous: in a monorepo most upstream commits do not touch the vendored subtree, so differing commits under `up-to-date` is the *normal* output and an operator has no way to tell it from this failure | reconstruct a vendored package from an older commit of the same subtree (payload bytes and `origin.resolved_commit`), then `revendor --check` | drift detection for any registry whose copy has been touched |
| `LAF-46` | major | `LA3-C-03` | `LAS-47` | `aart-mcp-v1` install effect ↔ `docs/tutorials/vendoring-v1.md` | **A vendored `mcp` payload is never delivered to the consumer.** Installing `mcp/mcp-git` wrote exactly one thing: `.mcp.json`, via `merge-json`. The 13 copied upstream files stay in the registry and the object store and never reach the project, so an `mcp.json` whose command references a path inside the payload cannot work. **The `2.3.0` tutorial ships exactly such a config** — `{"command": "node", "args": ["payload/index.js"]}` — and the worked example would fail at runtime. It also means that for this type the assessment reports risk in bytes the consumer never executes, which is worth stating rather than leaving for a reader to discover | install any vendored `mcp` artifact into a clean project; `find . -type f` shows `.mcp.json` and nothing from `payload/` | the tutorial's worked example; the reader's mental model of what vendoring delivers |
| `LAF-47` | minor | `LA3-C-03` | `LAS-10` | `marketplace uninstall` teardown | **Uninstall leaves the harness JSON file it created.** After install → uninstall of the only artifact, `.agent-artifacts/` is correctly gone (v2's `LAF-17` fix holds), but `.mcp.json` survives as `{"mcpServers":{}}` — a file AART created (`created_destination: true` in the record) and did not reclaim. `git status --porcelain` reports `?? .mcp.json` on a repo that was clean before. `2.2.0` reclaimed emptied directories and the manifest; an emptied destination file is the remaining case | clean checkout, install one `mcp` artifact, uninstall it, `git status --porcelain` | the same teardown assertion `LAF-17` tracked |
| `LAF-43` | minor | `LA3-D-04`, `LA3-X-03` | `LAS-42` | `sources/git._allowed_location` ↔ `registry vendor` | **A vendoring cannot be rehearsed against a local repository.** `file://` and plain paths are refused with `Git source location must be credential-free HTTPS/SSH` — a consumer-side rule inherited by a maintainer-side command. Consequences: no offline rehearsal before copying somebody else's code into your registry; no hermetic CI coverage of the vendoring path; and in this run, neither the `changed` disposition nor the symlink refusal could be exercised live, because both need an upstream the runner controls. `source add --kind source-local` accepts a local path, so the asymmetry is visible from one command to the next | `registry vendor --url "file:///path/to/repo" …` | live coverage of upstream movement |
| `LAF-45` | minor | `LA3-A-04` | `LAS-43` | `registry audit --check-upstream` reporting | **Success is silent.** With every vendored artifact current, `--check-upstream` prints nothing about them; with the upstream unreachable it prints a line each. An operator who runs it in CI cannot distinguish "checked, all current" from "the flag was dropped from the command line", which is the same class of ambiguity the drift design exists to remove. One summary line — *n vendored artifacts checked against their origins* — would settle it | `registry audit --check-upstream` on a registry whose vendored artifacts are current | nothing; it is a reporting gap in the command that exists to report |
| `LAF-44` | minor | `LA3-X-01` | `LAS-43` | vendoring acquisition diagnostics | A private or non-existent upstream is reported as `Git command failed … fatal: unable to get password from user`, with remediation `retry source synchronization`. The diagnosis is wrong (the repository does not exist, or the operator has no access to it), and the remediation names an operation vendoring does not perform. Same family as v2's `LAF-40` and v1's `LAF-19`: the failure names a mechanism instead of a next step | `registry vendor --url https://github.com/<org>/<no-such-repo>.git …` | nothing |
| `LAF-48` | minor | `LA3-T-02` | `LAS-41` | `tui.py` maintainer wizard | Two warts in the vendoring path of the text front-end: the stage is labelled **"Native reference details"** while a vendoring is being described — vendoring is precisely *not* a native reference — and declining at `Finalize exact reviewed action? [y/N]` returns to the same stage and re-renders the whole review, re-fetching the upstream over the network to do it. `VN-9` reused the existing stage rather than adding one; that decision is recorded in the plan, its label was not | drive `aart` in a registry checkout, action `vendor`, answer `n` at Finalize | nothing |
| `LAF-49` | question | `LA3-X-02` | `LAS-39` | `io/git._safe_environment` | AART runs Git with an allowlisted environment, so `https_proxy`/`HTTP_PROXY` never reach it. Deliberate — a proxy URL is a place credentials hide — and it means that on a network whose only egress is a proxy, every source sync and every vendoring fails, with the transport error and no hint that the proxy was dropped. `~/.gitconfig`'s `http.proxy` still works, because `HOME` is passed, so the workaround exists and nothing names it. Whether to document it, or to pass a credential-free proxy URL through, is the decision | set `https_proxy` to a live proxy on a network without direct egress; run `registry vendor` | egress-restricted networks |

### Closed by `2.4.0`

Composed response:
[DESIGN-vendored-copy-integrity.md](../design/DESIGN-vendored-copy-integrity.md) and
[PLAN-vendored-copy-integrity.md](../plan/PLAN-vendored-copy-integrity.md).

| Finding | How it is closed | Verified against |
|---|---|---|
| `LAF-41` | The copied subtree's digest is recomputed from the package on disk — payload minus `aart.vendor.authored` — and compared with `origin.input_digest`. `validate --strict` and `audit` fail on a mismatch, offline; re-locking and rebuilding do not clear it | `registry-drift`: `validate --strict` and `audit` both exit 1 naming `mcp/mcp-git`, with both digests printed. `registry-a` still validates clean |
| `LAF-42` | `revendor` verifies the copy **before** it opens a connection, so a tampered copy is refused with upstream never contacted; `up-to-date` now prints the line reconciling a recorded and a resolved commit that differ, or says the ref has not moved | the reproduction in `LAS-45` no longer reaches the network; unit and CLI tests hold both `up-to-date` renderings |
| `LAF-46` | The `vendor-delivery` check states what installing an `mcp` delivers and that the assessment covered bytes the consumer never receives; it fails on a descriptor naming a withheld payload file, and `audit` errors. The per-type delivery table is in the native source protocol, and the tutorial's example is one the checks pass | the corrected tutorial descriptor is fed to the review's own function by `tests/vendoring_docs_test.py` |
| `LAF-50` *(below)* | The same check fails a descriptor that declares no `server` | `registry-a`: `audit` exits 1 on both `mcp/mcp-filesystem` and `mcp/mcp-git` |

**`LAF-50` | major | found while fixing `LAF-46`, not during the run | `aart-mcp-v1` descriptor shape.** A
`payload/mcp.json` shaped `{"mcpServers": {"<name>": {…}}}` — the shape of the harness file the entry
is merged *into*, not the artifact's `{"name": …, "server": {…}}` — parses, loads, validates,
installs, and merges `{"mcpServers": {"<name>": {}}}`: a named server that starts no process, with
every gate reporting success. The `2.3.0` tutorial teaches that shape, this repository's vendoring
fixtures used it, and **both vendored `mcp` artifacts in this run's `registry-a` were written that
way** — which is how the finding was confirmed against something other than a fixture. Refusing it in
the loader was considered and rejected: it would make every registry already carrying one unloadable
on upgrade, consumers included. An owned, non-vendored `mcp` package with the same mistake is still
unchecked and stays a residue.

### Verified against the prior runs

| Prior finding | Prior symptom | v3 result |
|---|---|---|
| `LAF-30` question | published wheel content-reproducible but not byte-reproducible | **fixed** — `LA3-0-02`; the release asset's sha256 equals the digest computed at the tag |
| `LAF-38` question | `requires` could not name content from elsewhere | **answered** — `LA3-R-01`; vendoring makes the content owned, and the dependency resolves |
| `LAF-17` minor | teardown litters `.agent-artifacts/` | **partly fixed** — the directory and manifest are reclaimed; a created destination file is not (`LAF-47`) |

## What this run says about the release

The refusals `2.3.0` was written for hold live and hold well: an unreachable upstream is
`unreachable` and fails, a hand-edited provenance record is refused by name, a duplicate identity is
refused, a missing payload document is refused before anything is copied, and the licence finding
fires and does not fail the audit. The compatibility claim also holds: a vendored artifact locks,
builds, validates, lists with its origin, installs, reconciles, and uninstalls with no consumer-side
knowledge of vendoring at all.

The gap this run found is one level below all of that. AART verifies the *instruction* — URL, ref,
path, against `options_digest` — and does not verify the *result*: no gate compares the bytes under
`payload/` with the `input_digest` the same document records. Everything downstream re-derives from
the bytes on disk, so a copy that has drifted from its own record is consistent with every gate and,
worse, is compared against upstream as though it had not (`LAF-41`, `LAF-42`). That is the residue
this run hands to whatever comes next.

`2.4.0` is what came next, and it closed that residue along with `LAF-46` and the descriptor-shape
defect found while fixing it. The strongest thing this run produced was not a transcript: it was the
registry the run itself built. Both of its vendored `mcp` artifacts, written by following the `2.3.0`
tutorial, install an entry that starts nothing — and `2.4.0`'s audit says so.
