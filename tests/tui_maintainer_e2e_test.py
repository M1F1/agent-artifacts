"""End-to-end Maintainer TUI path over the real upstream command core."""

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts import tui
from agent_artifacts.commands import upstream
from agent_artifacts.model import Ok
from agent_artifacts.upstream_source import ResolvedUpstream, hash_upstream_path


def _scripted_reader(answers):
    iterator = iter(answers)

    def read(_prompt=""):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read


class MaintainerTuiEndToEndTests(unittest.TestCase):
    def test_import_check_and_update_through_real_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            catalog = root / "catalog"
            staged = root / "staged"
            (catalog / "skills/seed").mkdir(parents=True)
            (catalog / "skills/seed/SKILL.md").write_text(
                "---\nname: seed\ndescription: Seed a maintainer catalog.\n---\n# Seed\n",
                encoding="utf-8",
            )
            (staged / "skills/demo").mkdir(parents=True)
            (staged / "skills/demo/SKILL.md").write_text(
                "---\nname: demo\ndescription: Demonstrate an imported skill.\n"
                "---\n# Initial upstream\n",
                encoding="utf-8",
            )
            (staged / "agent-artifacts.import.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "artifacts": [{"type": "skill", "name": "demo", "path": "skills/demo"}],
                    }
                ),
                encoding="utf-8",
            )

            def resolve(entry, **_kwargs):
                path = staged if entry.key.name == "__scan__" else staged / "skills/demo"
                return Ok(
                    ResolvedUpstream(
                        entry=entry,
                        sha="head-sha",
                        root=str(staged),
                        path=str(path),
                        content_hash=hash_upstream_path(str(path)),
                    )
                )

            with patch.object(upstream, "resolve_upstream_source", side_effect=resolve):
                with redirect_stdout(io.StringIO()):
                    imported = tui._run_text(
                        _scripted_reader(
                            [
                                "2",
                                "4",
                                "https://github.com/acme/demo",
                                "1",
                                "",
                                "y",
                            ]
                        ),
                        lambda _text="": None,
                        source_dir=str(catalog),
                    )

                self.assertEqual(imported, 0)
                installed = catalog / "skills/demo/SKILL.md"
                self.assertIn("Initial upstream", installed.read_text(encoding="utf-8"))
                self.assertTrue((catalog / "upstreams.json").exists())

                with redirect_stdout(io.StringIO()):
                    checked = tui._run_text(
                        _scripted_reader(["2", "5", "1"]),
                        lambda _text="": None,
                        source_dir=str(catalog),
                    )
                self.assertEqual(checked, 0)

                (staged / "skills/demo/SKILL.md").write_text(
                    "---\nname: demo\ndescription: Demonstrate an imported skill.\n"
                    "---\n# Refreshed upstream\n",
                    encoding="utf-8",
                )
                with redirect_stdout(io.StringIO()):
                    updated = tui._run_text(
                        _scripted_reader(["2", "6", "1", "y"]),
                        lambda _text="": None,
                        source_dir=str(catalog),
                    )

                self.assertEqual(updated, 0)
                self.assertIn("Refreshed upstream", installed.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
