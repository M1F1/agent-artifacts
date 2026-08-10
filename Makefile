# agent-artifacts — build & validation tasks (WP-21).
#
# Zero runtime deps; build tooling is stdlib-only (no setuptools / wheel / build needed
# for the offline path). The wheel produced by `make wheel` installs with:
#     pip install --no-index dist/agent_artifacts-<v>-py3-none-any.whl

PYTHON ?= python
QUALITY = $(PYTHON) scripts/quality.py

.PHONY: test unit integration e2e system-matrix wheel validate clean lint format format-check typecheck coverage packaging-check docs-check quality version-check version-show version-next-alpha version-bump-alpha version-set

# Backwards-compatible aggregate. The Python discovery remains the broad unit/regression gate.
test: unit e2e

unit:
	$(QUALITY) unit

integration:
	$(QUALITY) integration

e2e:
	$(QUALITY) e2e

system-matrix:
	$(PYTHON) scripts/system_matrix.py

# Stamp the git commit, then build the stdlib wheel into dist/.
wheel:
	$(PYTHON) scripts/inject_commit.py
	$(PYTHON) scripts/build_wheel.py

validate:
	$(QUALITY) validate

# --------------------------------------------------------------------------- #
# Optional developer tooling. Requires the dev extra:  pip install -e ".[dev]"
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

version-set:
	$(PYTHON) scripts/version.py set "$(VERSION)" --write

# Remove build leftovers (safe: only the dist/ wheels and build/ tree).
clean:
	rm -f dist/*.whl
	rm -rf build
