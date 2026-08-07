"""P01 contracts for strict SemVer precedence and version bounds."""

from __future__ import annotations

import unittest


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


class SemVerTest(unittest.TestCase):
    def test_canonical_versions_round_trip_and_invalid_forms_fail(self):
        from agent_artifacts.protocol.semver import parse_semver

        valid = (
            "0.0.0",
            "1.2.3",
            "1.2.3-alpha.1",
            "1.2.3-alpha+build.7",
            "1.2.3+sha.abc123",
        )
        for raw in valid:
            with self.subTest(raw=raw):
                self.assertEqual(str(_unwrap(parse_semver(raw))), raw)

        invalid = (
            "1.2",
            "v1.2.3",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-01",
            "1.2.3-alpha..1",
            "1.2.3_alpha",
            "1.2.3+bad metadata",
            f"{'9' * 5000}.2.3",
            f"1.2.3-{'9' * 5000}",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertEqual(_code(parse_semver(raw)), "protocol-semver-invalid")

    def test_prerelease_precedence_matches_semver_spec(self):
        from agent_artifacts.protocol.semver import parse_semver

        raw = (
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        )
        versions = tuple(_unwrap(parse_semver(item)) for item in raw)
        self.assertEqual(tuple(sorted(reversed(versions))), versions)
        self.assertTrue(
            _unwrap(parse_semver("1.0.0+one")).same_precedence(_unwrap(parse_semver("1.0.0+two")))
        )

    def test_bounds_are_min_inclusive_max_exclusive_and_validate_order(self):
        from agent_artifacts.protocol.semver import parse_semver, version_bounds

        minimum = _unwrap(parse_semver("1.0.0"))
        maximum = _unwrap(parse_semver("2.0.0"))
        bounds = _unwrap(version_bounds(minimum, maximum))

        self.assertTrue(bounds.allows(minimum))
        self.assertTrue(bounds.allows(_unwrap(parse_semver("1.9.9"))))
        self.assertFalse(bounds.allows(_unwrap(parse_semver("1.0.0-alpha"))))
        self.assertFalse(bounds.allows(maximum))
        self.assertEqual(_code(version_bounds(maximum, minimum)), "protocol-version-bounds-invalid")
        self.assertEqual(_code(version_bounds(minimum, minimum)), "protocol-version-bounds-invalid")


if __name__ == "__main__":
    unittest.main()
