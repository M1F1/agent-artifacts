"""P01 contracts for safe paths, capabilities, and protocol architecture."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pathlib
import unittest
from typing import Protocol, cast

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _DataclassParams(Protocol):
    frozen: bool


def _unwrap(result):
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


def _code(result) -> str:
    from agent_artifacts.domain.result import Err

    if not isinstance(result, Err):
        raise AssertionError(f"expected Err, got {result!r}")
    return result.diagnostics[0].code.value


class SafeRelativePathTest(unittest.TestCase):
    def test_safe_paths_use_portable_posix_form(self):
        from agent_artifacts.protocol.paths import parse_relative_path

        valid = _unwrap(parse_relative_path("artifacts/skill/café"))
        self.assertEqual(valid.parts, ("artifacts", "skill", "café"))
        self.assertEqual(str(valid), "artifacts/skill/café")

        invalid = (
            "",
            "/absolute",
            "../escape",
            "a/../escape",
            "./relative",
            "a//b",
            "a\\b",
            "C:/windows",
            "a/\x00b",
            "cafe\u0301",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertEqual(_code(parse_relative_path(raw)), "protocol-path-invalid")


class CapabilityNegotiationTest(unittest.TestCase):
    def test_required_capabilities_block_while_optional_capabilities_degrade(self):
        from agent_artifacts.protocol.capabilities import negotiate_capabilities, parse_capability

        manifest = _unwrap(parse_capability("artifact-manifest-v1"))
        security = _unwrap(parse_capability("security-evidence-v1"))
        available = _unwrap(parse_capability("compiler-core-v1"))

        incompatible = negotiate_capabilities((manifest,), (security,), (available, security))
        self.assertFalse(incompatible.compatible)
        self.assertEqual(incompatible.missing_required, (manifest,))
        self.assertEqual(incompatible.enabled, (security,))

        compatible = negotiate_capabilities((manifest,), (security,), (manifest,))
        self.assertTrue(compatible.compatible)
        self.assertEqual(compatible.enabled, (manifest,))
        self.assertEqual(compatible.unsupported_optional, (security,))

    def test_capability_names_are_strict_and_negotiation_is_sorted_and_deduplicated(self):
        from agent_artifacts.protocol.capabilities import negotiate_capabilities, parse_capability

        for raw in ("", "UPPER", "leading-", "two--dashes", "has space", "ümlaut"):
            with self.subTest(raw=raw):
                self.assertEqual(_code(parse_capability(raw)), "protocol-capability-invalid")

        alpha = _unwrap(parse_capability("alpha-v1"))
        zeta = _unwrap(parse_capability("zeta-v1"))
        decision = negotiate_capabilities((zeta, alpha, alpha), (), (alpha, zeta, alpha))
        self.assertEqual(decision.required, (alpha, zeta))
        self.assertEqual(decision.enabled, (alpha, zeta))

        overlap = negotiate_capabilities((alpha,), (zeta, alpha), (alpha,))
        self.assertEqual(overlap.required, (alpha,))
        self.assertEqual(overlap.optional, (zeta,))
        self.assertEqual(overlap.unsupported_optional, (zeta,))


class ProtocolArchitectureTest(unittest.TestCase):
    def test_protocol_values_are_frozen_and_modules_have_no_io_or_host_locale_imports(self):
        protocol = ROOT / "agent_artifacts" / "protocol"
        self.assertTrue(protocol.is_dir(), protocol)
        forbidden = {"locale", "os", "pathlib", "shutil", "socket", "subprocess", "urllib"}
        violations: list[str] = []
        mutable: list[str] = []
        found: list[str] = []

        for path in sorted(protocol.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules = () if node.module is None else (node.module,)
                else:
                    continue
                violations.extend(
                    f"{path.name}: {module}"
                    for module in modules
                    if module.split(".", 1)[0] in forbidden
                )

            module = importlib.import_module(f"agent_artifacts.protocol.{path.stem}")
            for value in vars(module).values():
                if not isinstance(value, type) or value.__module__ != module.__name__:
                    continue
                if not dataclasses.is_dataclass(value):
                    continue
                found.append(f"{path.stem}.{value.__name__}")
                params = cast(_DataclassParams, vars(value)["__dataclass_params__"])
                if not params.frozen:
                    mutable.append(f"{path.stem}.{value.__name__}")

        self.assertEqual(violations, [])
        self.assertGreater(len(found), 0)
        self.assertEqual(mutable, [])


if __name__ == "__main__":
    unittest.main()
