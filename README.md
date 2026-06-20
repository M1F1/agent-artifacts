# agent-artifacts

Install a team's AI artifacts — **skills, guidelines, MCP configs, and hooks** — from one
source-of-truth repo into multiple agentic harnesses (OpenCode, Claude Code, Tabnine, …).
Zero runtime dependencies, functional core, offline-installable.

> Status: under construction. See [DESIGN.md](DESIGN.md) and [PLAN.md](PLAN.md). Full usage
> docs land with WP-23.

## Install (offline, no external index)

```sh
python3 scripts/build_wheel.py                 # build the pure-Python wheel (stdlib only)
pip install --no-index dist/agent_artifacts-*.whl
```

Then `agent-artifacts --help` (or the short alias `aa --help`).
