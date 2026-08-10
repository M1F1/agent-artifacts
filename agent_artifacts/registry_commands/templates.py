"""Byte-stable templates emitted by registry initialization."""

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
      matrix:
        compatibility: [minimum, latest]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
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
