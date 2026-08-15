"""RR-2A: the text renderer prints what the ``setup`` JSON payload carries.

`LAF-52` and `LAF-54` are one defect seen twice. The review path renders only
``setup_queue.plans``, so a planning failure produces no line at all; the finalized path
renders ``planned=0, failures=1``, a count over a payload that holds the reason, the artifact
key and the manual route. Both are failures of rendering, not of storage — the design's §3.4
rule is that counts may accompany content and may not replace it.

This module renders the payload dict itself rather than the objects it was built from, so the
two outputs cannot drift: a field added to the payload is a field this renderer sees.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

from agent_artifacts.setup import public_text
from agent_artifacts.tui_layout import CONTENT_MEASURE, field_block, wrap

__all__ = ["receipt_payload", "render_receipt_payload", "render_setup_payload"]


def receipt_payload(record: Any, *, location: Any) -> dict[str, Any]:
    """Project one persisted record into the value both `--json` and the text renderer read.

    Built once, here, rather than in the command: `RR-2A` established that a text path
    rendering different objects than the JSON path drifts, and a receipt read a week after the
    run is exactly where that drift would not be noticed.
    """

    return {
        "coordinate": location.coordinate,
        "profile": location.profile,
        "scope": location.scope,
        "setup_state_ref": location.setup_state_ref,
        "state_path": location.state_path,
        "artifact": f"{record.artifact_type}/{record.artifact_name}",
        "status": record.status,
        "detail": record.detail,
        "source_label": record.source_label,
        "trust": record.trust,
        "plan_hash": record.plan_hash,
        "installer_path": record.installer_path,
        "installer_hash": record.installer_hash,
        "recipe_digest": record.recipe_digest,
        "object_digest": record.object_digest,
        "canonical_review_digest": record.canonical_review_digest,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "exit_status": record.exit_status,
        "retry_command": record.retry_command,
        "rollback_command": record.rollback_command,
        "steps": [dict(step) for step in record.receipt],
    }


def render_receipt_payload(
    payload: Mapping[str, Any],
    *,
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """Render a persisted setup record: every field the receipt payload carries."""

    lines = wrap(
        f"Setup receipt: {_text(payload.get('artifact'), fallback='unknown')}"
        f"@{_text(payload.get('profile'), fallback='unknown')}"
        f" ({_text(payload.get('scope'), fallback='unknown')})",
        width=width,
    )
    lines += field_block(
        (
            ("coordinate", _text(payload.get("coordinate"), fallback="unknown")),
            ("status", _text(payload.get("status"), fallback="unknown")),
            ("details", _text(payload.get("detail"), fallback="none recorded")),
            ("source", _text(payload.get("source_label"), fallback="unknown")),
            ("trust", _text(payload.get("trust"), fallback="unknown")),
            ("started", _text(payload.get("started_at"), fallback="not recorded")),
            ("finished", _text(payload.get("finished_at"), fallback="not recorded")),
            ("exit status", _text(payload.get("exit_status"), fallback="not recorded")),
            ("plan hash", _text(payload.get("plan_hash"), fallback="not recorded")),
            ("installer", _text(payload.get("installer_path"), fallback="not recorded")),
            ("installer hash", _text(payload.get("installer_hash"), fallback="not recorded")),
            ("recipe digest", _text(payload.get("recipe_digest"), fallback="not recorded")),
            ("object digest", _text(payload.get("object_digest"), fallback="not recorded")),
            (
                "review digest",
                _text(payload.get("canonical_review_digest"), fallback="not recorded"),
            ),
            ("record", _text(payload.get("state_path"), fallback="unknown")),
        ),
        indent=2,
        width=width,
    )
    for label, key in (("retry", "retry_command"), ("rollback", "rollback_command")):
        command = _text(payload.get(key))
        if command:
            lines += field_block(((label, command),), indent=2, width=width)

    steps = _rows(payload, "steps")
    if not steps:
        # `LAF-45` again: a receipt with no steps is a real outcome — a run that planned and
        # applied nothing — and must not look like a renderer that gave up.
        return lines + ("Steps: none recorded; this run applied no effect.",)
    lines += ("Steps",)
    for index, step in enumerate(steps, start=1):
        lines += wrap(
            f"{index}. {_text(step.get('module'), fallback='unknown module')}"
            f" — {_text(step.get('step_id'), fallback='unnamed step')}",
            width=width,
        )
        known = ("module", "step_id")
        fields = tuple(
            (key, _text(step.get(key)))
            for key in sorted(step)
            if key not in known and _text(step.get(key))
        )
        if fields:
            lines += field_block(fields, indent=3, width=width)
    return lines + (f"Steps: {len(steps)}",)


def _text(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    return public_text(str(value))


def _rows(payload: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    value = payload.get(key)
    return value if isinstance(value, list) else ()


def _manual_lines(manual: Any, *, indent: int, width: int) -> Tuple[str, ...]:
    if not isinstance(manual, Mapping):
        return ()
    return field_block(
        (
            ("manual instructions", _text(manual.get("relative_path"), fallback="unknown")),
            ("manual source", _text(manual.get("source"), fallback="unknown")),
        ),
        indent=indent,
        width=width,
    )


def _planned_lines(plans: Sequence[Mapping[str, Any]], *, width: int) -> Tuple[str, ...]:
    lines: Tuple[str, ...] = ()
    for plan in plans:
        lines += wrap(f"Setup planned: {_text(plan.get('key'), fallback='unknown')}", width=width)
        lines += field_block(
            (
                ("trust", _text(plan.get("trust"), fallback="unknown")),
                ("recipe", _text(plan.get("recipe"), fallback="unknown")),
                ("review digest", _text(plan.get("review_digest"), fallback="unknown")),
            ),
            indent=2,
            width=width,
        )
        lines += _manual_lines(plan.get("manual"), indent=2, width=width)
        effects = plan.get("effects")
        if isinstance(effects, list) and effects:
            lines += ("  Effects",)
            for effect in effects:
                lines += wrap(
                    f"  {_text(effect.get('index'), fallback='-')}. "
                    f"{_text(effect.get('identity'), fallback='unnamed effect')}",
                    width=width,
                )
                lines += field_block(
                    (
                        ("target", _text(effect.get("target"), fallback="no filesystem target")),
                        ("capability", _text(effect.get("capability"), fallback="none")),
                        ("recovery", _text(effect.get("recovery"), fallback="none recorded")),
                        ("details", _text(effect.get("details"))),
                    ),
                    indent=3,
                    width=width,
                )
    return lines


def _failure_lines(failures: Sequence[Mapping[str, Any]], *, width: int) -> Tuple[str, ...]:
    lines: Tuple[str, ...] = ()
    for failure in failures:
        # The key first: an operator reading a failed run needs to know which artifact it is
        # before they can act on why.
        lines += wrap(
            f"Setup not planned: {_text(failure.get('key'), fallback='unknown artifact')}",
            width=width,
        )
        lines += field_block(
            (("reason", _text(failure.get("detail"), fallback="no reason recorded")),),
            indent=2,
            width=width,
        )
        lines += _manual_lines(failure.get("manual"), indent=2, width=width)
    return lines


def _item_lines(items: Sequence[Mapping[str, Any]], *, width: int) -> Tuple[str, ...]:
    lines: Tuple[str, ...] = ()
    for item in items:
        lines += wrap(
            f"Setup {_text(item.get('status'), fallback='unknown')}: "
            f"{_text(item.get('key'), fallback='unknown artifact')}",
            width=width,
        )
        detail = _text(item.get("detail"))
        if detail:
            lines += field_block((("details", detail),), indent=2, width=width)
    return lines


def render_setup_payload(
    payload: Mapping[str, Any],
    *,
    planned_effects: bool = True,
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """Render every field the ``setup`` payload carries, as lines for the text front-end.

    ``planned_effects=False`` at the review call site only, where ``render_setup_review``
    already renders each plan in fuller form than the payload holds — the flag exists so the
    same effects are not printed twice, never so the text may carry less than the JSON.
    """

    plans = _rows(payload, "planned")
    failures = _rows(payload, "planning_failures")
    items = _rows(payload, "items")

    lines: Tuple[str, ...] = ()
    if planned_effects:
        lines += _planned_lines(plans, width=width)
    lines += _failure_lines(failures, width=width)
    lines += _item_lines(items, width=width)

    if not plans and not failures and not items:
        # `LAF-45`: a path that prints nothing on success is indistinguishable from a flag that
        # was dropped. This one says it looked.
        return ("Setup: no selected artifact declares a setup recipe; nothing to configure.",)

    summary = f"Setup: planned={len(plans)}, failures={len(failures)}"
    if "configured" in payload or "incomplete" in payload:
        summary += (
            f", configured={_text(payload.get('configured'), fallback='0')}"
            f", incomplete={_text(payload.get('incomplete'), fallback='0')}"
        )
    return lines + (summary,)
