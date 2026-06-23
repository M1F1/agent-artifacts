import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from agent_artifacts.commands import list as list_cmd
from agent_artifacts.model import Request

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _source_with_restricted_mcp(tmp: str) -> str:
    source = os.path.join(tmp, "source")
    shutil.copytree(FIXTURES, source)
    path = os.path.join(source, "mcp", "tabnine-postgres.json")
    pathlib.Path(path).write_text(
        json.dumps(
            {
                "name": "tabnine-postgres",
                "compatibility": {"profiles": ["tabnine"]},
                "server": {"command": "npx"},
            }
        ),
        encoding="utf-8",
    )
    return source


def _run(request: Request) -> dict:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = list_cmd.run(request)
    if code != 0:
        raise AssertionError(out.getvalue())
    return json.loads(out.getvalue())


class CompatibilityListTests(unittest.TestCase):
    def test_json_includes_compatibility_for_restricted_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _source_with_restricted_mcp(tmp)
            data = _run(Request(command="list", source_dir=source, json=True))

            by_name = {item["name"]: item for item in data["artifacts"]}
            self.assertEqual(
                by_name["tabnine-postgres"]["compatibility"],
                {"profiles": ["tabnine"]},
            )
            self.assertNotIn("compatibility", by_name["postgres"])

    def test_type_filter_preserves_compatibility_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _source_with_restricted_mcp(tmp)
            data = _run(
                Request(
                    command="list",
                    source_dir=source,
                    json=True,
                    type_filter="mcp",
                )
            )

            restricted = [item for item in data["artifacts"] if item["name"] == "tabnine-postgres"][
                0
            ]
            self.assertEqual(restricted["compatibility"]["profiles"], ["tabnine"])
            self.assertNotIn("bundles", data)


if __name__ == "__main__":
    unittest.main()
