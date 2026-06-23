"""WP-27 tests: the ``memory`` planner + the generalized sentinel placement.

Run: ``python -m unittest discover -s tests -p "memory_planner_test.py" -v``

These tests are pure: they build inline data, call the planner, and assert the resulting
`Plan` tuple exactly (golden assertions). No filesystem or network is touched. The
idempotency tests feed a planner's own output back in as ``existing_text`` and assert a
byte-identical result, mirroring the global DoD (PLAN-memory §7).
"""

import unittest

from agent_artifacts import planners
from agent_artifacts.model import (
    Artifact,
    CopyTarget,
    Err,
    MemoryTarget,
    Ok,
    Profile,
    Warn,
    WriteFile,
)


# --------------------------------------------------------------------------- #
# Shared fixtures                                                              #
# --------------------------------------------------------------------------- #
def memory_artifact(name: str = "house") -> Artifact:
    return Artifact(type="memory", name=name, root=f"memory/{name}.md")


FILE_TARGET = MemoryTarget(kind="file", dest="AGENTS.md")
DIR_TARGET = MemoryTarget(kind="dir", dest=".tabnine/guidelines")

BEGIN = "<!-- >>> agent-artifacts memory:house >>> -->"
END = "<!-- <<< agent-artifacts memory:house <<< -->"


def _written(result) -> str:
    """Unwrap an ``Ok((WriteFile(...),))`` plan to the decoded WriteFile content."""
    assert isinstance(result, Ok), result
    assert len(result.value) == 1, result.value
    action = result.value[0]
    assert isinstance(action, WriteFile), action
    return action.content.decode("utf-8")


# --------------------------------------------------------------------------- #
# Sentinel markers (DESIGN-memory §3.3)                                        #
# --------------------------------------------------------------------------- #
class MemoryMarkerTests(unittest.TestCase):
    def test_html_comment_and_type_scoped(self):
        begin, end = planners.memory_sentinel_markers("house")
        self.assertEqual(begin, BEGIN)
        self.assertEqual(end, END)


# --------------------------------------------------------------------------- #
# prepend (position="top") — golden + idempotency                             #
# --------------------------------------------------------------------------- #
class PrependModeTests(unittest.TestCase):
    def test_prepend_into_empty_file_golden(self):
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text=None,
            exists=False,
            mode="prepend",
        )
        expected = f"{BEGIN}\nHouse rules.\n{END}\n"
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=expected.encode()),)))

    def test_prepend_places_block_at_top_over_foreign(self):
        existing = "# My project\nBe nice.\n"
        text = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "House rules.",
                existing_text=existing,
                exists=True,
                mode="prepend",
            )
        )
        # Our block precedes the foreign content.
        self.assertTrue(text.startswith(BEGIN))
        self.assertLess(text.index(BEGIN), text.index("# My project"))
        self.assertIn("Be nice.", text)

    def test_prepend_is_idempotent(self):
        once = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text="# Header\nx\n",
            exists=True,
            mode="prepend",
        )
        first = _written(once)
        twice = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text=first,
            exists=True,
            mode="prepend",
        )
        # Re-running with the prior output as existing_text yields a byte-identical file.
        self.assertEqual(_written(twice), first)
        self.assertEqual(first.count(BEGIN), 1)
        self.assertEqual(first.count(END), 1)

    def test_prepend_replaces_changed_block_in_place(self):
        first = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "Old.",
                existing_text="# Header\n",
                exists=True,
                mode="prepend",
            )
        )
        updated = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "New.",
                existing_text=first,
                exists=True,
                mode="prepend",
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
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text=None,
            exists=False,
            mode="append",
        )
        expected = f"{BEGIN}\nHouse rules.\n{END}\n"
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=expected.encode()),)))

    def test_append_places_block_at_bottom_over_foreign(self):
        existing = "# My project\nBe nice.\n"
        text = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "House rules.",
                existing_text=existing,
                exists=True,
                mode="append",
            )
        )
        # Foreign content precedes our block.
        self.assertTrue(text.startswith("# My project"))
        self.assertLess(text.index("Be nice."), text.index(BEGIN))

    def test_append_is_idempotent(self):
        once = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text="# Header\nx\n",
            exists=True,
            mode="append",
        )
        first = _written(once)
        twice = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "House rules.",
            existing_text=first,
            exists=True,
            mode="append",
        )
        self.assertEqual(_written(twice), first)
        self.assertEqual(first.count(BEGIN), 1)

    def test_prepend_and_append_differ_only_in_placement(self):
        existing = "# Foreign\nbody\n"
        pre = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "Ours.",
                existing_text=existing,
                exists=True,
                mode="prepend",
            )
        )
        app = _written(
            planners.plan_memory(
                memory_artifact(),
                FILE_TARGET,
                "Ours.",
                existing_text=existing,
                exists=True,
                mode="append",
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
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text="prior\n",
            exists=True,
            mode="replace",
        )
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 4)
        self.assertIn("--force", result.reason)

    def test_replace_nonempty_with_force_backs_up_then_writes(self):
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text="prior\n",
            exists=True,
            mode="replace",
            force=True,
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
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text=None,
            exists=False,
            mode="replace",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))

    def test_replace_over_whitespace_only_file_treated_as_empty(self):
        # An existing-but-blank file is not "non-empty": no --force needed, no .bak.
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text="\n  \n",
            exists=True,
            mode="replace",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))


# --------------------------------------------------------------------------- #
# skip — seed-if-missing                                                       #
# --------------------------------------------------------------------------- #
class SkipModeTests(unittest.TestCase):
    def test_skip_when_exists_warns_no_write(self):
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text="prior\n",
            exists=True,
            mode="skip",
        )
        self.assertEqual(
            result,
            Ok((Warn(message="memory 'house': AGENTS.md exists; skipped"),)),
        )
        # Belt-and-braces: no WriteFile at all.
        self.assertFalse(any(isinstance(a, WriteFile) for a in result.value))

    def test_skip_when_absent_writes_once(self):
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text=None,
            exists=False,
            mode="skip",
        )
        self.assertEqual(result, Ok((WriteFile(path="AGENTS.md", content=b"Ours."),)))


# --------------------------------------------------------------------------- #
# dir kind (Tabnine) — copy as <name>.md                                       #
# --------------------------------------------------------------------------- #
class DirKindTests(unittest.TestCase):
    def test_dir_copy_writes_name_md(self):
        result = planners.plan_memory(
            memory_artifact(),
            DIR_TARGET,
            "Ours.",
            existing_text=None,
            exists=False,
            mode="prepend",  # content modes don't apply to dir kind; still a plain copy
        )
        self.assertEqual(
            result,
            Ok((WriteFile(path=".tabnine/guidelines/house.md", content=b"Ours."),)),
        )

    def test_dir_skip_when_exists_is_empty_plan(self):
        result = planners.plan_memory(
            memory_artifact(),
            DIR_TARGET,
            "Ours.",
            existing_text=None,
            exists=True,
            mode="skip",
        )
        self.assertEqual(result, Ok(()))

    def test_dir_skip_when_absent_writes(self):
        result = planners.plan_memory(
            memory_artifact(),
            DIR_TARGET,
            "Ours.",
            existing_text=None,
            exists=False,
            mode="skip",
        )
        self.assertEqual(
            result,
            Ok((WriteFile(path=".tabnine/guidelines/house.md", content=b"Ours."),)),
        )


# --------------------------------------------------------------------------- #
# Error paths                                                                  #
# --------------------------------------------------------------------------- #
class MemoryErrorTests(unittest.TestCase):
    def test_unknown_mode_is_err(self):
        result = planners.plan_memory(
            memory_artifact(),
            FILE_TARGET,
            "Ours.",
            existing_text=None,
            exists=False,
            mode="bogus",
        )
        self.assertIsInstance(result, Err)


# --------------------------------------------------------------------------- #
# _plan_one dispatch (input-gathering + None-guard)                            #
# --------------------------------------------------------------------------- #
def _profile_with_memory() -> Profile:
    return Profile(name="vibe", memory=MemoryTarget(kind="file", dest="AGENTS.md"))


def _profile_without_memory() -> Profile:
    return Profile(name="claude", skills=CopyTarget(dir=".claude/skills/<name>/"))


class PlanOneMemoryDispatchTests(unittest.TestCase):
    def test_dispatch_gathers_inputs_and_resolves_mode(self):
        art = memory_artifact()
        files = {
            "memory:house": "House rules.",
            "existing-memory:vibe:house": "# Foreign\nx\n",
            "memory-exists:vibe:house": True,
            "memory-mode:house": "append",
        }
        result = planners._plan_one(
            art, "vibe", files, {"vibe": _profile_with_memory()}, {}, force=False
        )
        text = _written(result)
        # append → foreign content first, our block last.
        self.assertTrue(text.startswith("# Foreign"))
        self.assertTrue(text.rstrip("\n").endswith(END))

    def test_dispatch_defaults_mode_to_prepend(self):
        art = memory_artifact()
        files = {"memory:house": "House rules."}  # no memory-mode key → default prepend
        result = planners._plan_one(
            art, "vibe", files, {"vibe": _profile_with_memory()}, {}, force=False
        )
        text = _written(result)
        self.assertTrue(text.startswith(BEGIN))  # prepend default

    def test_dispatch_missing_body_is_err(self):
        art = memory_artifact()
        result = planners._plan_one(
            art, "vibe", {}, {"vibe": _profile_with_memory()}, {}, force=False
        )
        self.assertIsInstance(result, Err)
        self.assertIn("memory text", result.reason)

    def test_dispatch_profile_without_memory_is_err(self):
        art = memory_artifact()
        files = {"memory:house": "House rules."}
        result = planners._plan_one(
            art, "claude", files, {"claude": _profile_without_memory()}, {}, force=False
        )
        self.assertIsInstance(result, Err)
        self.assertIn("does not support memory", result.reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
