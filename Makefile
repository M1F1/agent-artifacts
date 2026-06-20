# agent-artifacts — build & validation tasks (WP-21).
#
# Zero runtime deps; build tooling is stdlib-only (no setuptools / wheel / build needed
# for the offline path). The wheel produced by `make wheel` installs with:
#     pip install --no-index dist/agent_artifacts-<v>-py3-none-any.whl

PYTHON ?= python

.PHONY: test wheel validate clean

# Run the full unittest suite.
test:
	$(PYTHON) -m unittest discover -s tests -p "*_test.py"

# Stamp the git commit, then build the stdlib wheel into dist/.
wheel:
	$(PYTHON) scripts/inject_commit.py
	$(PYTHON) scripts/build_wheel.py

# (1) catalog integrity over the local source and (2) a no-non-stdlib-import gate.
validate:
	$(PYTHON) -c "import sys; from agent_artifacts.model import Request; from agent_artifacts.source import open_source; from agent_artifacts.catalog import validate_catalog; src = open_source(Request(command='list', source_dir='.')); cat = src.value.catalog() if hasattr(src, 'value') else sys.exit('open_source failed: ' + getattr(src, 'reason', repr(src))); errs = validate_catalog(cat.value) if hasattr(cat, 'value') else sys.exit('catalog failed: ' + getattr(cat, 'reason', repr(cat))); print('catalog OK' if not errs else 'catalog errors:'); [print('  - ' + e.reason) for e in errs]; sys.exit(1 if errs else 0)"
	$(PYTHON) -c "import ast, sys, pathlib; pkg = pathlib.Path('agent_artifacts'); allowed = set(sys.stdlib_module_names) | {'agent_artifacts'}; bad = []; [bad.append((str(p), top)) for p in pkg.rglob('*.py') for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))) if isinstance(node, (ast.Import, ast.ImportFrom)) for top in ([n.name.split('.')[0] for n in node.names] if isinstance(node, ast.Import) else ([node.module.split('.')[0]] if node.level == 0 and node.module else [])) if top not in allowed]; [print('non-stdlib import: ' + m + ' in ' + f) for f, m in bad]; print('import gate OK' if not bad else 'import gate FAILED'); sys.exit(1 if bad else 0)"

# Remove build leftovers (safe: only the dist/ wheels and build/ tree).
clean:
	rm -f dist/*.whl
	rm -rf build
