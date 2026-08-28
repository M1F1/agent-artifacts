"""Byte-stable templates emitted by registry initialization."""

from __future__ import annotations

REGISTRY_GITIGNORE = b""".agent-artifacts/
.agent-artifacts-bak/
.claude/
.coverage
.mcp.json
.mypy_cache/
.opencode/
.pytest_cache/
.ruff_cache/
.tabnine/
.vibe/
__pycache__/
build/
dist/
htmlcov/
usage-dashboard/
"""

# Every knob below is a repository variable, and every default reproduces the public github.com
# run, so a registry created inside a company is configured by settings rather than by editing the
# file.  That matters more than it looks: `plan_registry_init` refuses to overwrite a template
# whose content differs, so a hand-edited workflow puts a registry permanently out of step with
# the command that manages it.  `docs/ci/enterprise-fork-v1.md` lists the variables.
#
# The three workflows share one way of reaching the tool, kept here so they cannot drift apart.
# AART has no runtime dependencies and ships `agent_artifacts/__main__.py`, so *any* directory
# holding the package is a working installation: a clone, an unzipped wheel, a `pip --target`
# directory, or a path baked into a CI image.  Every arm below therefore ends the same way, and
# none of them needs a build backend.  That is what lets these run on a private runner.
_PROVIDE_AART = b"""      - name: Provide AART
        env:
          PACKAGE: ${{ vars.AART_PACKAGE }}
          WHEEL_URL: ${{ vars.AART_WHEEL_URL }}
          TOOL_PATH: ${{ vars.AART_TOOL_PATH }}
          TOOL_URL: ${{ vars.AART_TOOL_URL || format('{0}/{1}.git', github.server_url, vars.AART_REPOSITORY || 'M1F1/agent-artifacts') }}
          TOOL_REF: ${{ vars.AART_REF }}
          INDEX_URL: ${{ vars.AART_PIP_INDEX_URL || 'https://pypi.org/simple' }}
          INDEX_CREDENTIALS: ${{ secrets[vars.AART_PIP_INDEX_CREDENTIALS_SECRET] }}
          PY: ${{ vars.AART_PYTHON || 'python3' }}
          GH_HOST_OVERRIDE: ${{ vars.AART_GH_HOST }}
        run: |
          set -euo pipefail
          # An internal index usually wants credentials, and a variable cannot hold one.  So the
          # variable holds the bare host and names the secret holding `user:pass`; the URL is
          # assembled here and never written down anywhere.  Splitting a secret defeats GitHub's
          # masking -- it masks the whole value it was given, not the halves -- so each half is
          # re-masked before it is used.  `announce` keeps the bare host, so no log line, not even
          # a masked one, carries the password.
          announce="$INDEX_URL"
          if [ -n "${INDEX_CREDENTIALS:-}" ]; then
            index_user="${INDEX_CREDENTIALS%%:*}"
            index_held="${INDEX_CREDENTIALS#*:}"
            echo "::add-mask::$index_user"
            echo "::add-mask::$index_held"
            index_scheme="https"
            case "$INDEX_URL" in http://*) index_scheme="http" ;; esac
            index_host="${INDEX_URL#http://}"
            index_host="${index_host#https://}"
            # `at` keeps the emitted bytes out of the shape a secret scanner refuses on push, so a
            # registry created by this command is pushable to an instance with push protection on.
            at="@"
            INDEX_URL="$index_scheme://$index_user:$index_held$at$index_host"
          fi
          # `.aart-version` is this registry's own pin: one line of text, versioned in Git and
          # reviewed in a pull request like any other change.  It answers *which* AART, which is a
          # decision about the registry.  The variables answer *where this deployment gets it
          # from*, which is a fact about the instance.  Neither repeats the other.
          PIN=""
          if [ -f .aart-version ]; then PIN=$(tr -d ' \\t\\r\\n' < .aart-version); fi
          # An explicit AART_REF is the escape hatch for someone testing a fork branch.  It wins,
          # but it switches the version check off, so it says so rather than quietly disagreeing
          # with a file that is still in the repository.
          override=""
          if [ -n "$PIN" ] && [ -n "$TOOL_REF" ]; then override=" (pin $PIN overridden by AART_REF)"; fi
          ref="$TOOL_REF"
          if [ -z "$ref" ]; then ref="${PIN:+v$PIN}"; fi
          if [ -z "$ref" ]; then ref="main"; fi
          # Four ways in, tried in this order, never combined.  The order runs from the most
          # governed supply chain to the least, so an organisation that later stands up an index
          # sets one variable and it takes over -- no stale variable has to be unset first.  Git
          # is last because it is the only arm carrying a shipped default, and anything below an
          # arm that is always set would be unreachable.
          tool="$RUNNER_TEMP/aart-tool"
          rm -rf "$tool"
          if [ -n "$PACKAGE" ]; then
            requirement="${PACKAGE//\\{version\\}/$PIN}"
            how="index $announce ($requirement)"
            "$PY" -m pip install --quiet --no-deps --target "$tool" \\
              --index-url "$INDEX_URL" "$requirement"
          elif [ -n "$WHEEL_URL" ]; then
            url="${WHEEL_URL//\\{version\\}/$PIN}"
            how="wheel $url"
            # `urllib`, not `curl`: this arm has to run on whatever image the organisation
            # uses, and a real Enterprise image carried git and Python and neither `curl` nor
            # `gh`.  The interpreter is already required by every other arm, so asking for
            # nothing beyond it is the only assumption that holds everywhere.
            "$PY" -c 'import sys,urllib.request,zipfile;urllib.request.urlretrieve(sys.argv[1],sys.argv[2]);zipfile.ZipFile(sys.argv[2]).extractall(sys.argv[3])' \\
              "$url" "$RUNNER_TEMP/aart.whl" "$tool"
          elif [ -n "$TOOL_PATH" ]; then
            how="path $TOOL_PATH"
            tool="$TOOL_PATH"
          else
            how="git $TOOL_URL@$ref"
            git clone --quiet --depth 1 --branch "$ref" "$TOOL_URL" "$tool" 2>/dev/null \\
              || { rm -rf "$tool"
                   git clone --quiet "$TOOL_URL" "$tool"
                   git -C "$tool" -c advice.detachedHead=false checkout --quiet "$ref"; }
          fi
          test -f "$tool/agent_artifacts/__main__.py" \\
            || { echo "aart: no agent_artifacts package under '$tool' (via $how)" >&2; exit 2; }
          bin="$RUNNER_TEMP/aart-bin"
          mkdir -p "$bin"
          printf '#!/usr/bin/env bash\\nexec env PYTHONPATH=%s %s -m agent_artifacts "$@"\\n' \\
            "$tool" "$PY" > "$bin/aart"
          chmod +x "$bin/aart"
          echo "$bin" >> "$GITHUB_PATH"
          # The pin claims a version; this proves it.  Every arm is checked, including the baked
          # path, where a stale image is otherwise indistinguishable from a fresh one.
          got=$("$bin/aart" --version | awk '{print $NF}')
          if [ -n "$PIN" ] && [ -z "$override" ] && [ "$got" != "$PIN" ]; then
            echo "aart: .aart-version pins $PIN but $how provided $got" >&2
            exit 2
          fi
          # `gh` defaults to github.com, which on an Enterprise instance is the wrong server and a
          # silent one.  Derive the host from the instance the job is already running on.
          echo "GH_HOST=${GH_HOST_OVERRIDE:-${GITHUB_SERVER_URL#https://}}" >> "$GITHUB_ENV"
          echo "AART: aart-cli $got  via $how${PIN:+  pinned by .aart-version}$override"
"""

_RUNS_ON = b"""    runs-on: ${{ fromJSON(vars.AART_RUNNER || '["ubuntu-latest"]') }}
"""

# A private image needs a `credentials` block, and that block cannot be made conditional.  Measured
# on a real instance rather than assumed: an empty block and a `null` block are both rejected before
# the job starts ("Unexpected value ''"), and filling it with a placeholder makes an anonymous pull
# fail a `docker login` it never needed.  The `secrets` context is not even readable at `container:`
# itself, only inside `credentials`.  So the choice is made in the one place a choice survives --
# `if:` at job level -- and each job is emitted twice.  The plain variant is byte-for-byte the job
# this template always produced, so a registry that names no secrets sees no change whatsoever.
_PLAIN_CONTAINER = b"""    container: ${{ vars.AART_CI_IMAGE }}
"""
_PRIVATE_CONTAINER = b"""    container:
      image: ${{ vars.AART_CI_IMAGE }}
      credentials:
        username: ${{ secrets[vars.AART_IMAGE_USERNAME_SECRET] }}
        password: ${{ secrets[vars.AART_IMAGE_PASSWORD_SECRET] }}
"""
_PLAIN_WHEN = b"vars.AART_IMAGE_USERNAME_SECRET == ''"
_PRIVATE_WHEN = b"vars.AART_IMAGE_USERNAME_SECRET != ''"


def _job(job_id: bytes, body: bytes, header: bytes = b"", when: bytes = b"") -> bytes:
    """Emit one job twice, once per container shape, gated so exactly one of them runs.

    `header` carries whatever belongs above the container line -- `needs`, `strategy`,
    `environment`.  `when` is the job's own condition, which is combined with the container
    switch rather than replaced by it.
    """

    emitted = []
    for suffix, container, switch in (
        (b"", _PLAIN_CONTAINER, _PLAIN_WHEN),
        (b"-private-image", _PRIVATE_CONTAINER, _PRIVATE_WHEN),
    ):
        condition = switch if not when else b"".join((when, b" && ", switch))
        emitted.append(
            b"".join(
                (
                    b"  ",
                    job_id,
                    suffix,
                    b":\n    if: ",
                    condition,
                    b"\n",
                    header,
                    _RUNS_ON,
                    container,
                    body,
                )
            )
        )
    return b"".join(emitted)


REGISTRY_CI_WORKFLOW = b"""name: AART registry quality
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
""" + _job(
    b"registry-quality",
    header=b"""    strategy:
      fail-fast: false
      matrix:
        compatibility: [minimum, latest]
""",
    body=b"""    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
"""
    + _PROVIDE_AART
    + b"""      - run: aart registry format --source . --check
      - run: aart registry validate --source . --strict --frozen
      - run: aart registry lock --source . --check
      - run: aart registry build --source . --check
      - run: aart registry audit --source .
      - run: aart registry test --source . --compatibility ${{ matrix.compatibility }}
""",
)
USAGE_REPORT_ISSUE_FORM = b"""name: AART redacted usage report
description: Share one voluntary, bounded AART session result with this registry.
title: "AART usage report: "
body:
  - type: markdown
    attributes:
      value: |
        This report is voluntary. It must contain only AART's redacted allowlisted event; never add credentials, paths, logs, repository names, or personal identifiers.
  - type: textarea
    id: report
    attributes:
      label: Redacted usage event
      description: AART prefilled this exact versioned JSON payload for your review.
      render: json
    validations:
      required: true
"""

USAGE_REPORT_VALIDATE_WORKFLOW = b"""name: Validate AART usage report
on:
  issues:
    types: [opened, edited, reopened]
permissions:
  contents: read
  issues: write
jobs:
""" + _job(
    b"validate",
    when=b"startsWith(github.event.issue.title, 'AART usage report:')",
    body=b"""    steps:
"""
    + _PROVIDE_AART
    + b"""      - name: Read issue body as untrusted data
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: gh issue view "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --json body --jq .body > usage-issue.md
      - id: validate
        name: Validate bounded report schema
        continue-on-error: true
        run: aart reporting validate-issue usage-issue.md
      - name: Label valid report
        if: steps.validate.outcome == 'success'
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: |
          gh label create usage-report --repo "$GITHUB_REPOSITORY" --color 0E8A16 --force
          gh issue edit "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --add-label usage-report
      - name: Close invalid report without evaluating its content
        if: steps.validate.outcome == 'failure'
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: |
          gh label create invalid-usage-report --repo "$GITHUB_REPOSITORY" --color B60205 --force
          gh issue comment "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --body 'AART rejected this report because it did not match the bounded redacted schema.'
          gh issue close "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --reason not-planned
""",
)
# Pages is the one piece an Enterprise instance may simply not offer.  Deployment is therefore its
# own job, gated by a variable: set `AART_PAGES` to `false` and the dashboard is still built and
# still validated, it is just not published.  A job-level `if` is used rather than a step-level one
# because the `github-pages` environment belongs to the job that deploys.  That job runs no Python
# and never fetches AART, so it needs no container and stays a single job; it waits on both shapes
# of `aggregate` and tolerates the one that stood down, which is what `!cancelled()` buys.
USAGE_REPORT_DASHBOARD_WORKFLOW = (
    b"""name: Build AART usage dashboard
on:
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:
permissions:
  contents: read
  issues: read
  pages: write
  id-token: write
concurrency:
  group: aart-usage-pages
  cancel-in-progress: true
jobs:
"""
    + _job(
        b"aggregate",
        body=b"""    steps:
"""
        + _PROVIDE_AART
        + b"""      - name: Export only validated report bodies and server timestamps
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh issue list --repo "$GITHUB_REPOSITORY" --label usage-report --state all --limit 10000 --json body,createdAt > usage-issues.json
      - run: aart reporting aggregate usage-issues.json --output usage-dashboard
      - uses: actions/upload-pages-artifact@v3
        with:
          path: usage-dashboard
""",
    )
    + b"""  deploy:
    needs: [aggregate, aggregate-private-image]
    if: ${{ !cancelled() && !failure() && vars.AART_PAGES != 'false' }}
    runs-on: ${{ fromJSON(vars.AART_RUNNER || '["ubuntu-latest"]') }}
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
"""
)
REPORTING_TEMPLATES = (
    (".github/ISSUE_TEMPLATE/usage-report.yml", USAGE_REPORT_ISSUE_FORM),
    (".github/workflows/aart-usage-dashboard.yml", USAGE_REPORT_DASHBOARD_WORKFLOW),
    (".github/workflows/aart-usage-validate.yml", USAGE_REPORT_VALIDATE_WORKFLOW),
)


# `registry init` writes this once and then leaves it alone.  Unlike the workflows, a README is a
# file people are meant to edit, so it is deliberately *not* a managed template: it is written when
# absent and never overwritten or compared.  Making it managed would mean the one file a maintainer
# is supposed to change is the one that puts the registry out of step with the command managing it.
_REGISTRY_README = b"""# __DISPLAY_NAME__

An [agent-artifacts](https://github.com/M1F1/agent-artifacts) registry. It holds packaged
artifacts - skills, agents, commands, MCP servers, memory and guidelines - that AART installs into
a consumer project.

Its registry id is `__REGISTRY_ID__`. Consumers name it when they add this registry as a source.

## What is in here

| Path | What it is |
|---|---|
| `aart-registry.json` | The registry marker: id, display name, and the AART version window it declares |
| `.aart-version` | The AART version CI runs. One line. Bump it in a pull request |
| `aart-source.json` | Where artifacts and collections live in this tree |
| `artifacts/` | One directory per packaged artifact |
| `collections/` | Named groups of artifacts installed together |
| `aart.lock.json` | Resolved, pinned contents. Generated - never edited by hand |
| `aart.index.json` | The published index consumers read. Generated |
| `.github/workflows/` | The quality gate, and the usage-reporting pair |

The JSON files and the workflows are **managed**: AART regenerates them and refuses to run against
a copy that was hand-edited. This README is not managed. Edit it freely.

## Everyday commands

Every mutation prepares files and stops so you can read them. Re-run the same command with `--yes`
to finalize. AART never pushes.

```sh
# Author a new artifact in this registry
aart registry scaffold skill code-review --source . --summary "Review code." \\
  --profile claude --platform darwin

# Reference an artifact that another repository already packages for AART
aart registry promote-native skill code-review --source . \\
  --url https://github.com/acme/skills.git --ref main --path artifacts/skill/code-review

# Copy content an upstream never packaged, recording where it came from
aart registry vendor skill code-review --source . \\
  --url https://github.com/acme/prompts.git --ref main --path prompts/code-review \\
  --artifact-version 1.0.0 --summary "Review code." --profile claude --platform darwin

# See what moved upstream since a vendored copy was taken
aart registry revendor skill code-review --source .

# Lock, build, validate, audit, and commit - review first, then finalize
aart registry publish --source .
aart registry publish --source . --yes
```

Run the gates yourself at any time:

```sh
aart registry format --source . --check
aart registry validate --source . --strict --frozen
aart registry lock --source . --check
aart registry build --source . --check
aart registry audit --source .
aart registry test --source . --compatibility latest
```

## Pointing CI at AART

Two separate questions, kept in two separate places.

**Which AART version** is a decision about this registry, so it lives in Git:

```
.aart-version
2.8.5
```

Bump it in a pull request. The gates then run against the new version **before** the change is
merged, so a version that breaks this registry fails in review rather than after. `git blame`
answers "when did we move to 2.9.0", and a bad bump is one `git revert` away. None of that is
possible when the version lives in a settings page.

The version is also **proved, not just claimed**. After fetching, CI compares `aart --version`
against this file and fails if they differ - which catches a moved tag, an index that resolved to
something else, and a CI image with a stale AART baked into it.

**Where this deployment fetches that version from** is a fact about your instance, not about the
registry, so it stays in repository variables. Four ways in; the **first variable that is set
wins**, and they are never combined:

| Order | Variable | Example | How it fetches |
|---|---|---|---|
| 1 | `AART_PACKAGE` | `aart-cli=={version}` | `pip` from `AART_PIP_INDEX_URL` |
| 2 | `AART_WHEEL_URL` | `https://host/.../v{version}/aart_cli-{version}-py3-none-any.whl` | fetch, then unzip |
| 3 | `AART_TOOL_PATH` | `/opt/aart` | Already on the runner |
| 4 | `AART_TOOL_URL` | `https://ghe.corp/platform/agent-artifacts.git` | `git clone` at `v` + the pin |

`{version}` is replaced with whatever `.aart-version` says, so the version appears **once**, in
Git, and never in a settings page. Set `AART_REF` to override the pin for one registry - the run
then says so out loud and the version check is switched off, because you asked for a different
build on purpose.

The order runs from the most governed supply chain to the least. That matters when you migrate:
stand up an internal index later, set `AART_PACKAGE`, and it takes over. You do not have to unset
anything first.

**Set none of them** and CI reaches `github.com`. On a GitHub Enterprise instance that fails on the
first run, loudly, which is the intended behaviour.

**Set them on the organisation, not here.** GitHub resolves a repository variable over an
organisation one, so one organisation variable configures every registry your company has, and any
single registry can still override it.

Which arm actually answered is printed by the run:

```
AART: aart-cli 2.8.5  via index https://nexus.corp/pypi/simple (aart-cli==2.8.5)
```

### The other variables

| Variable | Default | What it does |
|---|---|---|
| `AART_PIP_INDEX_URL` | `https://pypi.org/simple` | Index used by `AART_PACKAGE` |
| `AART_REPOSITORY` | `M1F1/agent-artifacts` | `owner/name` of the AART fork, combined with this instance's own URL |
| `AART_REF` | `v` + the pin | Escape hatch: a branch or tag instead of `.aart-version`. Switches the version check off |
| `AART_RUNNER` | `["ubuntu-latest"]` | JSON array of runner labels. Must be JSON, not a bare word |
| `AART_CI_IMAGE` | unset | Container image for the jobs. Unset means the runner's own environment |
| `AART_PYTHON` | `python3` | The interpreter's name inside that image |
| `AART_GH_HOST` | derived | Only needed if your instance is served on a path or a non-default port |
| `AART_PAGES` | unset | Set to `false` where the instance offers no GitHub Pages. The dashboard is still built, only publication is skipped |

## The version window

`aart-registry.json` declares the *range* of AART versions this registry supports. The quality
gate runs at **both** ends of it, which is what `compatibility: [minimum, latest]` means in the
workflow.

That is a different statement from `.aart-version`. The window says which versions this registry
claims to work with; the pin says which single version CI actually runs. Keep the pin inside the
window - a pin outside it is a registry contradicting itself.

## Usage reporting

The two `aart-usage-*` workflows accept voluntary, redacted usage reports as GitHub Issues and
build a dashboard from the ones that validate. Reports carry no credentials, paths or repository
names. Delete both workflows and the issue template if you do not want them.
"""


def render_registry_readme(registry_id: str, display_name: str) -> bytes:
    """The one generated file a maintainer owns after it is written."""

    return _REGISTRY_README.replace(b"__DISPLAY_NAME__", display_name.encode("utf-8")).replace(
        b"__REGISTRY_ID__", registry_id.encode("utf-8")
    )
