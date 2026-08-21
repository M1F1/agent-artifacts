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

# Every knob is a repository variable, and every default reproduces the public run, so a registry
# created inside a company is configured by settings rather than by editing this file.  That
# matters more here than it looks: `plan_registry_init` refuses to overwrite a template whose
# content differs, so a hand-edited workflow puts a registry permanently out of step with
# `registry init`.  Configuration therefore has to live in variables, not in edits.
#
# The tool is resolved without pip, an index, or a build backend.  AART has no runtime
# dependencies and ships `agent_artifacts/__main__.py`, so a source tree plus PYTHONPATH is a
# working installation — which is what lets these gates run on a private runner with no egress.
# `docs/ci/enterprise-fork-v1.md` lists the variables.
REGISTRY_CI_WORKFLOW = b"""name: AART registry quality
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
    runs-on: ${{ fromJSON(vars.AART_RUNNER || '["ubuntu-latest"]') }}
    container: ${{ vars.AART_CI_IMAGE }}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - name: Provide AART
        env:
          TOOL_PATH: ${{ vars.AART_TOOL_PATH }}
          TOOL_URL: ${{ vars.AART_TOOL_URL || format('{0}/{1}.git', github.server_url, vars.AART_REPOSITORY || 'M1F1/agent-artifacts') }}
          TOOL_REF: ${{ vars.AART_REF || 'main' }}
          PY: ${{ vars.AART_PYTHON || 'python3' }}
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
          echo "AART: $("$bin/aart" --version)  from $tool"
      - run: aart registry format --source . --check
      - run: aart registry validate --source . --strict --frozen
      - run: aart registry lock --source . --check
      - run: aart registry build --source . --check
      - run: aart registry audit --source .
      - run: aart registry test --source . --compatibility ${{ matrix.compatibility }}
"""

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
  validate:
    if: startsWith(github.event.issue.title, 'AART usage report:')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - uses: actions/checkout@v4
        with:
          repository: ${{ vars.AART_REPOSITORY || 'M1F1/agent-artifacts' }}
          ref: ${{ vars.AART_REF || 'main' }}
          path: .aart-tool
          persist-credentials: false
      - run: python -m pip install --no-deps ./.aart-tool
      - name: Read issue body as untrusted data
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

USAGE_REPORT_DASHBOARD_WORKFLOW = b"""name: Build AART usage dashboard
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
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - uses: actions/checkout@v4
        with:
          repository: ${{ vars.AART_REPOSITORY || 'M1F1/agent-artifacts' }}
          ref: ${{ vars.AART_REF || 'main' }}
          path: .aart-tool
          persist-credentials: false
      - run: python -m pip install --no-deps ./.aart-tool
      - name: Export only validated report bodies and server timestamps
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh issue list --repo "$GITHUB_REPOSITORY" --label usage-report --state all --limit 10000 --json body,createdAt > usage-issues.json
      - run: aart reporting aggregate usage-issues.json --output usage-dashboard
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: usage-dashboard
      - id: deployment
        uses: actions/deploy-pages@v4
"""

REPORTING_TEMPLATES = (
    (".github/ISSUE_TEMPLATE/usage-report.yml", USAGE_REPORT_ISSUE_FORM),
    (".github/workflows/aart-usage-dashboard.yml", USAGE_REPORT_DASHBOARD_WORKFLOW),
    (".github/workflows/aart-usage-validate.yml", USAGE_REPORT_VALIDATE_WORKFLOW),
)
