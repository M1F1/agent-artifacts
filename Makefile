# agent-artifacts — build & validation tasks (WP-21).
#
# Zero runtime deps. Poetry builds the wheel and installs the developer tooling; nothing it
# installs reaches the runtime, which stays standard-library only. The wheel produced by
# `make wheel` still installs with no index at all:
#     pip install --no-index dist/aart_cli-<v>-py3-none-any.whl

PYTHON ?= python
REGISTRY ?=
QUALITY = $(PYTHON) scripts/quality.py

.PHONY: test unit integration system-matrix release-freeze release-check wheel validate clean lint format format-check typecheck coverage packaging-check docs-check secret-shape-check quality version-check version-show version-next-alpha version-bump-alpha version-finalize version-set

# Aggregate. The Python discovery is the broad unit/regression gate; integration is end to end.
test: unit integration

unit:
	$(QUALITY) unit

integration:
	$(QUALITY) integration

system-matrix:
	$(PYTHON) scripts/system_matrix.py

release-freeze:
	$(PYTHON) scripts/release.py freeze --write

release-check:
	@test -n "$(REGISTRY)" || (echo "REGISTRY=/path/to/agent-artifacts-registry is required" >&2; exit 2)
	$(PYTHON) scripts/release.py check --registry "$(REGISTRY)"

# Stamp the git commit, then build the wheel into dist/ with Poetry.
wheel:
	$(PYTHON) scripts/inject_commit.py
	$(PYTHON) scripts/build_wheel.py

validate:
	$(QUALITY) validate

# --------------------------------------------------------------------------- #
# Optional developer tooling. Requires Poetry's dev group:  poetry install --with dev
# These are developer/CI dependencies only; the installed runtime stays stdlib-only.
# --------------------------------------------------------------------------- #
lint:
	$(QUALITY) lint

format:
	$(PYTHON) -m ruff format agent_artifacts tests scripts

format-check:
	$(QUALITY) format-check

typecheck:
	$(QUALITY) typecheck

coverage:
	$(QUALITY) coverage

packaging-check:
	$(QUALITY) packaging-check

docs-check:
	$(QUALITY) docs-check

secret-shape-check:
	$(QUALITY) secret-shape-check

quality:
	$(QUALITY)

version-check:
	$(PYTHON) scripts/version.py check

version-show:
	$(PYTHON) scripts/version.py show

version-next-alpha:
	$(PYTHON) scripts/version.py next-alpha

version-bump-alpha:
	$(PYTHON) scripts/version.py bump-alpha --write

version-finalize:
	$(PYTHON) scripts/version.py finalize --write

version-set:
	$(PYTHON) scripts/version.py set "$(VERSION)" --write

# Remove build leftovers (safe: only the dist/ wheels and build/ tree).
clean:
	rm -f dist/*.whl
	rm -rf build
