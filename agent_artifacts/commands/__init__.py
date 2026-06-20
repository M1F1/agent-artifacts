"""Command orchestration (WP-12..WP-18). Each module exposes ``run(request) -> int``.

Commands are thin: gather IO inputs, call the pure core to build a Plan, then execute or
print it. No decision logic lives here.
"""
