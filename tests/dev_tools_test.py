"""The lock is the contract between Poetry, which decides the tools, and pip, which installs them.

`scripts/dev_tools.py` reads `poetry.lock` with a hand-written parser, because the gates run on
Python 3.10 and `tomllib` arrived in 3.11.  These tests hold that shortcut to the format and hold
the two places that pin the build backend to each other.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

from tests.packaging_test import REPO_ROOT, _load_script

LOCK = REPO_ROOT / "poetry.lock"
PYPROJECT = REPO_ROOT / "pyproject.toml"


class LockParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = _load_script("dev_tools")

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is the reference and arrived in 3.11")
    def test_the_hand_parser_agrees_with_tomllib(self) -> None:
        """The shortcut exists for 3.10 only, so on 3.11+ it is checked against the real thing."""

        import tomllib

        mine = {
            (record["name"], record["version"], record["markers"], record["groups"])
            for record in self.tools.packages(LOCK.read_text(encoding="utf-8"))
        }
        with open(LOCK, "rb") as handle:
            reference = {
                (
                    package["name"],
                    package["version"],
                    package.get("markers", ""),
                    ",".join(package.get("groups", [])),
                )
                for package in tomllib.load(handle)["package"]
            }

        self.assertEqual(mine, reference)

    def test_nested_tables_are_not_mistaken_for_packages(self) -> None:
        """`[package.dependencies]` carries names and versions of its own, and is not a package."""

        lock = (
            '[[package]]\nname = "alpha"\nversion = "1.0"\ngroups = ["dev"]\n\n'
            '[package.dependencies]\nbeta = ">=2.0"\n\n'
            '[[package]]\nname = "gamma"\nversion = "3.0"\ngroups = ["main"]\n'
        )

        parsed = self.tools.packages(lock)

        self.assertEqual([record["name"] for record in parsed], ["alpha", "gamma"])

    def test_a_marker_survives_into_the_pin_with_its_quotes_intact(self) -> None:
        """`tomli` is locked for one interpreter only, and pip is what decides whether it applies."""

        pins = self.tools.requirements("dev")

        markered = [pin for pin in pins if ";" in pin]
        self.assertTrue(markered, pins)
        for pin in markered:
            self.assertNotIn("\\", pin, "a TOML escape reached pip as a literal backslash")

    def test_an_empty_lock_is_refused_by_name(self) -> None:
        with self.assertRaises(self.tools.LockError):
            self.tools.packages("# nothing here\n")


class PinAgreementTest(unittest.TestCase):
    """Two files pin the build backend, and a build fails loudly only if they agree."""

    def setUp(self) -> None:
        self.tools = _load_script("dev_tools")
        self.build = _load_script("build_wheel")
        self.pyproject = PYPROJECT.read_text(encoding="utf-8")

    def test_the_dev_group_installs_the_backend_version_the_build_system_pins(self) -> None:
        """`build_wheel.py` refuses a wheel built by any other version, so the two must match.

        They are pinned apart because they answer different questions -- `[build-system]` says
        what may build this project, the dev group says what to install -- and a project that
        installs one backend and refuses its output has a green gate and no wheel.
        """

        installed = [
            pin for pin in self.tools.requirements("dev") if pin.startswith("poetry-core==")
        ]
        self.assertEqual(len(installed), 1, installed)
        version = installed[0].split("==", 1)[1].split(";", 1)[0].strip()

        self.assertEqual(version, self.build.pinned_backend())

    def test_the_formatter_is_pinned_exactly_rather_than_by_a_range(self) -> None:
        """A floor, or a caret, is not a version for a tool whose output has to match.

        `ruff>=0.6` once let a laptop hold 0.12 while CI installed 0.16; the two formatted the
        same file differently and `format-check` failed on code ruff had just formatted.
        """

        group = self.pyproject.split("[tool.poetry.group.dev.dependencies]", 1)[1]
        self.assertRegex(group, r'\nruff = "\d+\.\d+\.\d+"')

    def test_the_runtime_declares_no_dependencies_at_all(self) -> None:
        project = self.pyproject.split("[project]", 1)[1].split("[tool.poetry]", 1)[0]
        self.assertIn("dependencies = []", project)


class RequirementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = _load_script("dev_tools")

    def test_every_gate_tool_is_pinned_by_the_lock(self) -> None:
        pins = self.tools.requirements("dev")
        names = {pin.split("==", 1)[0] for pin in pins}
        self.assertLessEqual({"ruff", "mypy", "coverage", "poetry-core"}, names)
        for pin in pins:
            self.assertIn("==", pin, "a range reached pip; the lock is meant to pin exactly")

    def test_an_unknown_group_is_refused_rather_than_installing_nothing(self) -> None:
        with self.assertRaises(self.tools.LockError):
            self.tools.requirements("no-such-group")

    def test_the_lock_file_is_present_where_the_script_looks_for_it(self) -> None:
        self.assertTrue(pathlib.Path(self.tools.LOCK).is_file(), self.tools.LOCK)


if __name__ == "__main__":
    unittest.main()
