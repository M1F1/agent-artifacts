"""Import hygiene for maintainer-only upstream support."""

import json
import subprocess
import sys
import textwrap
import unittest


class UpstreamImportHygieneTests(unittest.TestCase):
    def test_cli_import_does_not_load_upstream_modules(self):
        self.assertEqual(_loaded_upstream_modules("from agent_artifacts import cli"), [])

    def test_consumer_command_imports_do_not_load_upstream_modules(self):
        for statement in (
            "from agent_artifacts.commands import status",
            "from agent_artifacts.commands import check",
            "from agent_artifacts.commands import update",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(_loaded_upstream_modules(statement), [])


def _loaded_upstream_modules(import_statement: str):
    script = textwrap.dedent(
        f"""
        import json
        import sys

        {import_statement}  # noqa: F401

        loaded = sorted(
            name
            for name in sys.modules
            if name == "agent_artifacts.commands.upstream"
            or name.startswith("agent_artifacts.upstream")
        )
        print(json.dumps(loaded))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        text=True,
        capture_output=True,
    )

    return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
