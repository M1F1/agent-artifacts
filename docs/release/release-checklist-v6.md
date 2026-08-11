# AART 1.3.1 release checklist and evidence

This patch release preserves every protocol/schema version and repairs the agent-facing setup
Review boundary.

Run from a clean commit merged into `origin/main`:

```sh
make quality
make release-check REGISTRY=/path/to/a-clean-public-registry
python scripts/version.py check-tag v1.3.1
python -m build --wheel
```

The release check must pass repository/version evidence, schema freeze v6, the system matrix,
zero-dependency wheel installation, and all public-registry format, validate, lock, build, audit,
and compatibility gates. The GitHub release must attach the wheel produced from the tagged commit.

Setup-specific acceptance requires:

- read-only marketplace setup emits canonical plans for installed setup-capable artifacts;
- no payload or setup Finalize occurs without `--yes`;
- authorizations remain explicit and default denied;
- artifacts without setup produce an empty setup queue;
- the complete unit, integration, e2e, type, lint, docs, and packaging suites remain green.
