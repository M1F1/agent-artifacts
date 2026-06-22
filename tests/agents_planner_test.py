"""WP-27 tests: the ``agents`` planner + the generalized sentinel placement.

Run: ``python -m unittest discover -s tests -p "agents_planner_test.py" -v``

These tests are pure: they build inline data, call the planner, and assert the resulting
`Plan` tuple exactly (golden assertions). No filesystem or network is touched. The
idempotency tests feed a planner's own output back in as ``existing_text`` and assert a
byte-identical result, mirroring the global DoD (PLAN-agents §7).
"""

import unittest

from agent_artifacts import planners
from agent_artifacts.model import (
    AgentsTarget,
    Artifact,
    CopyTarget,
    Err,
    GuidelineTarget,
    Ok,
    Profile,
    Warn,
    WriteFile,
)


# --------------------------------------------------------------------------- #
# Shared fixtures                                                              #
# --------------------------------------------------------------------------- #
def agents_artifact(name: str = "house") -> Artifact:
    return Artifact(type="agents", name=name, root=f"agents/{name}.md")


FILE_TARGET = AgentsTarget(kind="file", dest="AGENTS.md")
DIR_TARGET = AgentsTarget(kind="dir", dest=".tabnine/guidelines")

BEGIN = "<!-- >>> agent-artifacts agents:house >>> -->"
END = "<!-- <<< agent-artifacts agents:house <<< -->"


def _written(result) -> str:
    """Unwrap an ``Ok((WriteFile(...),))`` plan to the decoded WriteFile content."""
    assert isinstance(result, Ok), result
    assert len(result.value) == 1, result.value
    action = result.value[0]
    assert isinstance(action, WriteFile), action
    return action.content.decode("utf-8")


# --------------------------------------------------------------------------- #
# Sentinel markers (DESIGN-agents §3.3)                                        #
# --------------------------------------------------------------------------- #
class AgentsMarkerTests(unittest.TestCase):
    def test_html_comment_and_type_scoped(self):
        begin, end = planners.agents_sentinel_markers("house")
        self.assertEqual(begin, BEGIN)
        self.assertEqual(end, END)

    def test_distinct_from_guideline_markers(self):
        # An agents block and a same-named guideline block must not share markers, so the
        # two can coexist in one file (e.g. both target AGENTS.md).
        g_begin, _ = planners.sentinel_markers("house")
        a_begin, _ = planners.agents_sentinel_markers("house")
        self.assertNotEqual(g_begin, a_begin)


# --------------------------------------------------------------------------- #
# prepend (position="top") — golden + idempotency                             #
# --------------------------------------------------------------------------- #
class PrependModeTests(unittest.TestCase):
    def test_prepend_into_empty_file_golden(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text=None, exists=False,
            mode="prepend",
        )
        expected = f"{BEGIN}\nHouse rules.\n{END}\n"
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=expected.encode()),)))

    def test_prepend_places_block_at_top_over_foreign(self):
        existing = "# My project\nBe nice.\n"
        text = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "House rules.", existing_text=existing,
                exists=True, mode="prepend",
            )
        )
        # Our block precedes the foreign content.
        self.assertTrue(text.startswith(BEGIN))
        self.assertLess(text.index(BEGIN), text.index("# My project"))
        self.assertIn("Be nice.", text)

    def test_prepend_is_idempotent(self):
        once = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text="# Header\nx\n",
            exists=True, mode="prepend",
        )
        first = _written(once)
        twice = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text=first,
            exists=True, mode="prepend",
        )
        # Re-running with the prior output as existing_text yields a byte-identical file.
        self.assertEqual(_written(twice), first)
        self.assertEqual(first.count(BEGIN), 1)
        self.assertEqual(first.count(END), 1)

    def test_prepend_replaces_changed_block_in_place(self):
        first = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "Old.", existing_text="# Header\n",
                exists=True, mode="prepend",
            )
        )
        updated = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "New.", existing_text=first,
                exists=True, mode="prepend",
            )
        )
        self.assertIn("New.", updated)
        self.assertNotIn("Old.", updated)
        self.assertEqual(updated.count(BEGIN), 1)


# --------------------------------------------------------------------------- #
# append (position="bottom") — golden + idempotency                           #
# --------------------------------------------------------------------------- #
class AppendModeTests(unittest.TestCase):
    def test_append_into_empty_file_golden(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text=None, exists=False,
            mode="append",
        )
        expected = f"{BEGIN}\nHouse rules.\n{END}\n"
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=expected.encode()),)))

    def test_append_places_block_at_bottom_over_foreign(self):
        existing = "# My project\nBe nice.\n"
        text = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "House rules.", existing_text=existing,
                exists=True, mode="append",
            )
        )
        # Foreign content precedes our block.
        self.assertTrue(text.startswith("# My project"))
        self.assertLess(text.index("Be nice."), text.index(BEGIN))

    def test_append_is_idempotent(self):
        once = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text="# Header\nx\n",
            exists=True, mode="append",
        )
        first = _written(once)
        twice = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "House rules.", existing_text=first,
            exists=True, mode="append",
        )
        self.assertEqual(_written(twice), first)
        self.assertEqual(first.count(BEGIN), 1)

    def test_prepend_and_append_differ_only_in_placement(self):
        existing = "# Foreign\nbody\n"
        pre = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "Ours.", existing_text=existing,
                exists=True, mode="prepend",
            )
        )
        app = _written(
            planners.plan_agents(
                agents_artifact(), FILE_TARGET, "Ours.", existing_text=existing,
                exists=True, mode="append",
            )
        )
        self.assertNotEqual(pre, app)
        self.assertTrue(pre.startswith(BEGIN))
        self.assertTrue(app.rstrip("\n").endswith(END))


# --------------------------------------------------------------------------- #
# replace — .bak + --force gate (CONFLICT code 4)                              #
# --------------------------------------------------------------------------- #
class ReplaceModeTests(unittest.TestCase):
    def test_replace_nonempty_without_force_is_conflict(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text="prior\n", exists=True,
            mode="replace",
        )
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 4)
        self.assertIn("--force", result.reason)

    def test_replace_nonempty_with_force_backs_up_then_writes(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text="prior\n", exists=True,
            mode="replace", force=True,
        )
        self.assertEqual(
            result,
            Ok(
                (
                    WriteFile(path="AGENTS.md.agent-artifacts-bak", content=b"prior\n"),
                    WriteFile(path="AGENTS.md", content=b"Ours."),
                )
            ),
        )

    def test_replace_over_absent_file_single_write_no_bak(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text=None, exists=False,
            mode="replace",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))

    def test_replace_over_whitespace_only_file_treated_as_empty(self):
        # An existing-but-blank file is not "non-empty": no --force needed, no .bak.
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text="\n  \n", exists=True,
            mode="replace",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))


# --------------------------------------------------------------------------- #
# skip — seed-if-missing                                                       #
# --------------------------------------------------------------------------- #
class SkipModeTests(unittest.TestCase):
    def test_skip_when_exists_warns_no_write(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text="prior\n", exists=True,
            mode="skip",
        )
        self.assertEqual(
            result,
            Ok((Warn(message="agents 'house': AGENTS.md exists; skipped"),)),
        )
        # Belt-and-braces: no WriteFile at all.
        self.assertFalse(any(isinstance(a, WriteFile) for a in result.value))

    def test_skip_when_absent_writes_once(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text=None, exists=False,
            mode="skip",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))


# --------------------------------------------------------------------------- #
# dir kind (Tabnine) — copy as <name>.md                                       #
# --------------------------------------------------------------------------- #
class DirKindTests(unittest.TestCase):
    def test_dir_copy_writes_name_md(self):
        result = planners.plan_agents(
            agents_artifact(), DIR_TARGET, "Ours.", existing_text=None, exists=False,
            mode="prepend",  # content modes don't apply to dir kind; still a plain copy
        )
        self.assertEqual(
            result,
            Ok((WriteFile(path=".tabnine/guidelines/house.md", content=b"Ours."),)),
        )

    def test_dir_skip_when_exists_is_empty_plan(self):
        result = planners.plan_agents(
            agents_artifact(), DIR_TARGET, "Ours.", existing_text=None, exists=True,
            mode="skip",
        )
        self.assertEqual(result, Ok(()))

    def test_dir_skip_when_absent_writes(self):
        result = planners.plan_agents(
            agents_artifact(), DIR_TARGET, "Ours.", existing_text=None, exists=False,
            mode="skip",
        )
        self.assertEqual(
            result,
            Ok((WriteFile(path=".tabnine/guidelines/house.md", content=b"Ours."),)),
        )


# --------------------------------------------------------------------------- #
# Error paths                                                                  #
# --------------------------------------------------------------------------- #
class AgentsErrorTests(unittest.TestCase):
    def test_unknown_mode_is_err(self):
        result = planners.plan_agents(
            agents_artifact(), FILE_TARGET, "Ours.", existing_text=None, exists=False,
            mode="bogus",
        )
        self.assertIsInstance(result, Err)


# --------------------------------------------------------------------------- #
# _plan_one dispatch (input-gathering + None-guard)                            #
# --------------------------------------------------------------------------- #
def _profile_with_agents() -> Profile:
    return Profile(name="vibe", agents=AgentsTarget(kind="file", dest="AGENTS.md"))


def _profile_without_agents() -> Profile:
    return Profile(name="claude", skills=CopyTarget(dir=".claude/skills/<name>/"))


class PlanOneAgentsDispatchTests(unittest.TestCase):
    def test_dispatch_gathers_inputs_and_resolves_mode(self):
        art = agents_artifact()
        files = {
            "agents:house": "House rules.",
            "existing-agents:vibe:house": "# Foreign\nx\n",
            "agents-exists:vibe:house": True,
            "agents-mode:house": "append",
        }
        result = planners._plan_one(
            art, "vibe", files, {"vibe": _profile_with_agents()}, {}, force=False
        )
        text = _written(result)
        # append → foreign content first, our block last.
        self.assertTrue(text.startswith("# Foreign"))
        self.assertTrue(text.rstrip("\n").endswith(END))

    def test_dispatch_defaults_mode_to_prepend(self):
        art = agents_artifact()
        files = {"agents:house": "House rules."}  # no agents-mode key → default prepend
        result = planners._plan_one(
            art, "vibe", files, {"vibe": _profile_with_agents()}, {}, force=False
        )
        text = _written(result)
        self.assertTrue(text.startswith(BEGIN))  # prepend default

    def test_dispatch_missing_body_is_err(self):
        art = agents_artifact()
        result = planners._plan_one(
            art, "vibe", {}, {"vibe": _profile_with_agents()}, {}, force=False
        )
        self.assertIsInstance(result, Err)
        self.assertIn("agents text", result.reason)

    def test_dispatch_profile_without_agents_is_err(self):
        art = agents_artifact()
        files = {"agents:house": "House rules."}
        result = planners._plan_one(
            art, "claude", files, {"claude": _profile_without_agents()}, {}, force=False
        )
        self.assertIsInstance(result, Err)
        self.assertIn("does not support agents", result.reason)


# --------------------------------------------------------------------------- #
# Regression: the _replace_sentinel_block refactor preserved guideline output #
# --------------------------------------------------------------------------- #
class GuidelineSentinelRefactorGuardTests(unittest.TestCase):
    def test_guideline_append_sentinel_byte_identical_golden(self):
        # Pins the exact bytes the guideline path produced before the position= refactor,
        # proving _replace_marked_block(position="bottom") is byte-for-byte compatible.
        art = Artifact(type="guideline", name="python-style", root="guidelines/python-style.md")
        target = GuidelineTarget(mode="append-sentinel", dest="CLAUDE.md")
        result = planners.plan_guideline(
            art, target, "Use black.", existing_text="# My project rules\nBe nice.\n"
        )
        expected = (
            "# My project rules\n"
            "Be nice.\n"
            "\n"
            "# >>> agent-artifacts: python-style >>>\n"
            "Use black.\n"
            "# <<< agent-artifacts: python-style <<<\n"
        )
        self.assertEqual(result, Ok((WriteFile(path="CLAUDE.md", content=expected.encode()),)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
