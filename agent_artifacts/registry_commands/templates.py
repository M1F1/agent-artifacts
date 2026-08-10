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
