"""Byte-stable templates emitted by registry initialization."""

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
# AART has no runtime dependencies and ships `agent_artifacts/__main__.py`, so a source tree plus
# PYTHONPATH is a working installation - no pip, no package index, and no build backend.  That is
# what lets these run on a private runner with no egress.
_PROVIDE_AART = b"""      - name: Provide AART
        env:
          TOOL_PATH: ${{ vars.AART_TOOL_PATH }}
          TOOL_URL: ${{ vars.AART_TOOL_URL || format('{0}/{1}.git', github.server_url, vars.AART_REPOSITORY || 'M1F1/agent-artifacts') }}
          TOOL_REF: ${{ vars.AART_REF || 'main' }}
          PY: ${{ vars.AART_PYTHON || 'python3' }}
          GH_HOST_OVERRIDE: ${{ vars.AART_GH_HOST }}
        run: |
          set -euo pipefail
          tool="$TOOL_PATH"
          if [ -z "$tool" ]; then
            tool="$RUNNER_TEMP/aart-tool"
            rm -rf "$tool"
            git clone --quiet --depth 1 --branch "$TOOL_REF" "$TOOL_URL" "$tool" 2>/dev/null \\
              || { rm -rf "$tool"
                   git clone --quiet "$TOOL_URL" "$tool"
                   git -C "$tool" -c advice.detachedHead=false checkout --quiet "$TOOL_REF"; }
          fi
          test -f "$tool/agent_artifacts/__main__.py" \\
            || { echo "aart: no agent_artifacts package under '$tool'" >&2; exit 2; }
          bin="$RUNNER_TEMP/aart-bin"
          mkdir -p "$bin"
          printf '#!/usr/bin/env bash\\nexec env PYTHONPATH=%s %s -m agent_artifacts "$@"\\n' \\
            "$tool" "$PY" > "$bin/aart"
          chmod +x "$bin/aart"
          echo "$bin" >> "$GITHUB_PATH"
          # `gh` defaults to github.com, which on an Enterprise instance is the wrong server and a
          # silent one.  Derive the host from the instance the job is already running on.
          echo "GH_HOST=${GH_HOST_OVERRIDE:-${GITHUB_SERVER_URL#https://}}" >> "$GITHUB_ENV"
          echo "AART: $("$bin/aart" --version)  from $tool"
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
