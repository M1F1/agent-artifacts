"""Read-only agent CLI surface for the configured canonical marketplace.

The legacy ``list`` command remains a bounded 0.1 compatibility command.  This module exposes
the compiled configured-source marketplace without silently changing that legacy contract.
Canonical install/update lifecycle command surfaces follow separately.
"""

from __future__ import annotations

import json

from agent_artifacts.consumer.runtime import load_read_only_marketplace
from agent_artifacts.domain.diagnostics import diagnostic_to_data
from agent_artifacts.domain.result import Err
from agent_artifacts.marketplace.catalog import marketplace_catalog_bytes, render_marketplace
from agent_artifacts.model import Request

from . import _common
from ._configured_runtime import load_runtime_configuration

_LIST_OPERATION = "marketplace.list"


def _emit_error(request: Request, result: Err) -> int:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": _LIST_OPERATION,
                    "diagnostics": [diagnostic_to_data(item) for item in result.diagnostics],
                },
                indent=2,
            )
        )
    else:
        for diagnostic in result.diagnostics:
            print(f"{diagnostic.severity.value}: {diagnostic.message}")
            for remediation in diagnostic.remediation:
                print(f"  remediation: {remediation}")
    return _common.ERROR


def _list(request: Request) -> int:
    # Enforce the canonical content-operation no-source contract before building a marketplace.
    runtime = load_runtime_configuration(request, content_required=True)
    if isinstance(runtime, Err):
        return _emit_error(request, runtime)
    catalog = load_read_only_marketplace(
        runtime.value.loaded.effective,
        data_root=runtime.value.paths.data_root,
    )
    if isinstance(catalog, Err):
        return _emit_error(request, catalog)
    if request.json:
        payload = json.loads(marketplace_catalog_bytes(catalog.value).decode("utf-8"))
        payload["ok"] = True
        payload["operation"] = _LIST_OPERATION
        print(json.dumps(payload, indent=2))
    else:
        rendered = render_marketplace(catalog.value)
        print(rendered, end="") if rendered else print("No marketplace artifacts are available.")
    return _common.OK


def run(request: Request) -> int:
    """Run one read-only canonical marketplace command."""

    if request.marketplace_action == "list":
        return _list(request)
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": "marketplace",
                    "diagnostics": [
                        {
                            "code": "consumer-invalid",
                            "severity": "error",
                            "message": "unsupported marketplace command action",
                            "location": None,
                            "remediation": [],
                        }
                    ],
                },
                indent=2,
            )
        )
    else:
        print("error: unsupported marketplace command action")
    return _common.ERROR


__all__ = ["run"]
