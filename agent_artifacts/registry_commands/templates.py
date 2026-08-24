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
          TOOL_REF: ${{ vars.AART_REF || 'main' }}
          INDEX_URL: ${{ vars.AART_PIP_INDEX_URL || 'https://pypi.org/simple' }}
          PY: ${{ vars.AART_PYTHON || 'python3' }}
          GH_HOST_OVERRIDE: ${{ vars.AART_GH_HOST }}
        run: |
          set -euo pipefail
          # Four ways in, tried in this order, never combined.  The order runs from the most
          # governed supply chain to the least, so an organisation that later stands up an index
          # sets one variable and it takes over -- no stale variable has to be unset first.  Git
          # is last because it is the only arm carrying a shipped default, and anything below an
          # arm that is always set would be unreachable.
          tool="$RUNNER_TEMP/aart-tool"
          rm -rf "$tool"
          if [ -n "$PACKAGE" ]; then
            how="index $INDEX_URL ($PACKAGE)"
            "$PY" -m pip install --quiet --no-deps --target "$tool" \\
              --index-url "$INDEX_URL" "$PACKAGE"
          elif [ -n "$WHEEL_URL" ]; then
            how="wheel $WHEEL_URL"
            curl -fsSL "$WHEEL_URL" -o "$RUNNER_TEMP/aart.whl"
            "$PY" -c 'import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \\
              "$RUNNER_TEMP/aart.whl" "$tool"
          elif [ -n "$TOOL_PATH" ]; then
            how="path $TOOL_PATH"
            tool="$TOOL_PATH"
          else
            how="git $TOOL_URL@$TOOL_REF"
            git clone --quiet --depth 1 --branch "$TOOL_REF" "$TOOL_URL" "$tool" 2>/dev/null \\
              || { rm -rf "$tool"
                   git clone --quiet "$TOOL_URL" "$tool"
                   git -C "$tool" -c advice.detachedHead=false checkout --quiet "$TOOL_REF"; }
          fi
          test -f "$tool/agent_artifacts/__main__.py" \\
            || { echo "aart: no agent_artifacts package under '$tool' (via $how)" >&2; exit 2; }
          bin="$RUNNER_TEMP/aart-bin"
          mkdir -p "$bin"
          printf '#!/usr/bin/env bash\\nexec env PYTHONPATH=%s %s -m agent_artifacts "$@"\\n' \\
            "$tool" "$PY" > "$bin/aart"
          chmod +x "$bin/aart"
          echo "$bin" >> "$GITHUB_PATH"
          # `gh` defaults to github.com, which on an Enterprise instance is the wrong server and a
          # silent one.  Derive the host from the instance the job is already running on.
          echo "GH_HOST=${GH_HOST_OVERRIDE:-${GITHUB_SERVER_URL#https://}}" >> "$GITHUB_ENV"
          echo "AART: $("$bin/aart" --version)  via $how"
"""

_RUNS_ON = b"""    runs-on: ${{ fromJSON(vars.AART_RUNNER || '["ubuntu-latest"]') }}
    container: ${{ vars.AART_CI_IMAGE }}
"""

REGISTRY_CI_WORKFLOW = (
    b"""name: AART registry quality
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  registry-quality:
    strategy:
      fail-fast: false
      matrix:
        compatibility: [minimum, latest]
"""
    + _RUNS_ON
    + b"""    steps:
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
"""
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

USAGE_REPORT_VALIDATE_WORKFLOW = (
    b"""name: Validate AART usage report
on:
  issues:
    types: [opened, edited, reopened]
permissions:
  contents: read
  issues: write
jobs:
  validate:
    if: startsWith(github.event.issue.title, 'AART usage report:')
"""
    + _RUNS_ON
    + b"""    steps:
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
"""
)

# Pages is the one piece an Enterprise instance may simply not offer.  Deployment is therefore its
# own job, gated by a variable: set `AART_PAGES` to `false` and the dashboard is still built and
# still validated, it is just not published.  A job-level `if` is used rather than a step-level one
# because the `github-pages` environment belongs to the job that deploys.
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
  aggregate:
"""
    + _RUNS_ON
    + b"""    steps:
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
  deploy:
    needs: aggregate
    if: vars.AART_PAGES != 'false'
"""
    + _RUNS_ON
    + b"""    environment:
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
