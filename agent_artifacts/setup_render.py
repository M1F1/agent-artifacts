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

__all__ = ["render_setup_payload"]


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
