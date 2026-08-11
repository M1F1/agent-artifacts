"""Pure coordinate-selector parsing for the canonical non-interactive lifecycle (LIFE02).

Agents address artifacts by text.  These tests pin the exact accepted grammar, the deterministic
ambiguity contract, and the refusal to guess a source, kind, or version.
"""

from __future__ import annotations

import unittest

from agent_artifacts.consumer.coordinates import (
    ArtifactSelector,
    parse_artifact_selector,
    parse_artifact_selectors,
)
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok


class ArtifactSelectorParsingTests(unittest.TestCase):
    def test_source_qualified_selector_binds_alias_kind_and_name(self) -> None:
        parsed = parse_artifact_selector("team/skill/code-review")

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            parsed.value,
            ArtifactSelector(
                ArtifactIdentity("skill", "code-review"),
                source=SourceAlias("team"),
                version=None,
            ),
        )

    def test_source_qualified_selector_accepts_an_exact_version(self) -> None:
        parsed = parse_artifact_selector("team/skill/code-review@2.1.0")

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(parsed.value.version, "2.1.0")
        self.assertEqual(parsed.value.source, SourceAlias("team"))

    def test_unqualified_selector_leaves_the_source_unbound_for_catalog_resolution(self) -> None:
        parsed = parse_artifact_selector("skill/code-review")

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertIsNone(parsed.value.source)
        self.assertEqual(parsed.value.identity, ArtifactIdentity("skill", "code-review"))

    def test_unknown_artifact_kind_is_rejected_instead_of_guessed(self) -> None:
        parsed = parse_artifact_selector("team/binary/code-review")

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertEqual(parsed.diagnostics[0].code.value, "consumer-invalid")
        self.assertIn("artifact kind", parsed.diagnostics[0].message)

    def test_a_bare_name_without_a_kind_is_rejected(self) -> None:
        parsed = parse_artifact_selector("code-review")

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertIn("<source>/<kind>/<name>", parsed.diagnostics[0].message)

    def test_extra_path_segments_are_rejected(self) -> None:
        parsed = parse_artifact_selector("team/extra/skill/code-review")

        self.assertIsInstance(parsed, Err)

    def test_empty_and_blank_selectors_are_rejected(self) -> None:
        for raw in ("", "   ", "/", "team/skill/"):
            with self.subTest(raw=raw):
                self.assertIsInstance(parse_artifact_selector(raw), Err)

    def test_an_empty_version_suffix_is_rejected(self) -> None:
        self.assertIsInstance(parse_artifact_selector("team/skill/code-review@"), Err)

    def test_selectors_are_deduplicated_and_ordered_deterministically(self) -> None:
        parsed = parse_artifact_selectors(
            ("team/skill/b", "team/skill/a", "team/skill/b"),
        )

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            tuple(str(selector) for selector in parsed.value),
            ("team/skill/a", "team/skill/b"),
        )

    def test_every_invalid_selector_is_reported_in_one_deterministic_diagnostic_set(self) -> None:
        parsed = parse_artifact_selectors(("team/binary/x", "nope"))

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertEqual(len(parsed.diagnostics), 2)

    def test_qualified_and_unqualified_selectors_for_one_identity_stay_orderable(self) -> None:
        # Ordering must never compare ``None`` against a ``SourceAlias``.
        parsed = parse_artifact_selectors(("skill/code-review", "team/skill/code-review"))

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            tuple(str(selector) for selector in parsed.value),
            ("skill/code-review", "team/skill/code-review"),
        )

    def test_an_empty_selector_list_parses_to_an_empty_selection(self) -> None:
        parsed = parse_artifact_selectors(())

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(parsed.value, ())


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
