import unittest

from agent_artifacts.compatibility import (
    INCOMPATIBLE_PROFILE,
    check_profile_compatibility,
    compatibility_from_frontmatter,
    compatibility_from_json,
    parse_profile_allow_list,
)
from agent_artifacts.model import Artifact, Compatibility, Err, Ok


class ParseProfileAllowListTests(unittest.TestCase):
    def test_json_list_dedupes_preserving_order(self):
        result = parse_profile_allow_list(["claude", "tabnine", "claude"])
        self.assertEqual(result, Ok(("claude", "tabnine")))

    def test_frontmatter_comma_list(self):
        result = parse_profile_allow_list("claude, tabnine")
        self.assertEqual(result, Ok(("claude", "tabnine")))

    def test_frontmatter_bracket_list(self):
        result = parse_profile_allow_list("[claude, tabnine]")
        self.assertEqual(result, Ok(("claude", "tabnine")))

    def test_empty_list_is_err(self):
        self.assertIsInstance(parse_profile_allow_list([]), Err)
        self.assertIsInstance(parse_profile_allow_list("[]"), Err)

    def test_non_string_item_is_err(self):
        self.assertIsInstance(parse_profile_allow_list(["claude", 3]), Err)

    def test_invalid_profile_name_is_err(self):
        self.assertIsInstance(parse_profile_allow_list(["bad/profile"]), Err)


class CompatibilityMetadataTests(unittest.TestCase):
    def test_json_missing_compatibility_is_unrestricted(self):
        self.assertEqual(compatibility_from_json({"name": "x"}, "mcp 'x'"), Ok(None))

    def test_json_nested_profiles(self):
        result = compatibility_from_json(
            {"compatibility": {"profiles": ["tabnine"]}},
            "mcp 'postgres'",
        )
        self.assertEqual(result, Ok(Compatibility(("tabnine",))))

    def test_json_bad_shape_is_err(self):
        self.assertIsInstance(
            compatibility_from_json({"compatibility": ["tabnine"]}, "mcp 'postgres'"),
            Err,
        )

    def test_json_missing_profiles_is_err(self):
        self.assertIsInstance(
            compatibility_from_json({"compatibility": {}}, "mcp 'postgres'"),
            Err,
        )

    def test_frontmatter_dotted_key(self):
        result = compatibility_from_frontmatter(
            {"compatibility.profiles": "claude, tabnine"},
            "skill 'code-review'",
        )
        self.assertEqual(result, Ok(Compatibility(("claude", "tabnine"))))

    def test_frontmatter_missing_key_is_unrestricted(self):
        self.assertEqual(compatibility_from_frontmatter({}, "skill 'x'"), Ok(None))


class CompatibilityDecisionTests(unittest.TestCase):
    def test_unrestricted_artifact_allows_any_profile(self):
        artifact = Artifact("skill", "code-review", "skills/code-review")
        decision = check_profile_compatibility(artifact, "vibe")
        self.assertTrue(decision.ok)
        self.assertIsNone(decision.reason)

    def test_allow_list_accepts_matching_profile(self):
        artifact = Artifact(
            "mcp",
            "postgres",
            "mcp/postgres.json",
            Compatibility(("tabnine",)),
        )
        decision = check_profile_compatibility(artifact, "tabnine")
        self.assertTrue(decision.ok)
        self.assertEqual(decision.allowed_profiles, ("tabnine",))

    def test_allow_list_rejects_non_matching_profile(self):
        artifact = Artifact(
            "mcp",
            "postgres",
            "mcp/postgres.json",
            Compatibility(("tabnine",)),
        )
        decision = check_profile_compatibility(artifact, "claude")
        self.assertFalse(decision.ok)
        self.assertEqual(decision.reason, INCOMPATIBLE_PROFILE)
        self.assertEqual(decision.allowed_profiles, ("tabnine",))


if __name__ == "__main__":
    unittest.main()
