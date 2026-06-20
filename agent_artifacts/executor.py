"""Executor — imperative shell (WP-9). The only place a Plan touches disk (DESIGN.md §14).

`execute` dispatches each `Action` to a performer (using io.fs); `render_plan`/`plan_to_json`
present a Plan for ``--dry-run`` / ``--json`` without performing any effect.
"""

from __future__ import annotations

from .model import Plan

_TODO = "WP-9: not implemented"


def execute(plan: Plan, fs=None):
    """Execute every Action in order; return a Report. `fs` is injectable for testing."""
    raise NotImplementedError(_TODO)


def render_plan(plan: Plan) -> str:
    """Human-readable ``--dry-run`` rendering."""
    raise NotImplementedError(_TODO)


def plan_to_json(plan: Plan) -> str:
    """Machine-readable ``--json`` rendering."""
    raise NotImplementedError(_TODO)
