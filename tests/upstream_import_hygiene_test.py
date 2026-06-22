"""Import hygiene for maintainer-only upstream support."""

import json
import subprocess
import sys
import textwrap
import unittest


class UpstreamImportHygieneTests(unittest.TestCase):
    def test_cli_import_does_not_load_upstream_modules(self):
        script = textwrap.dedent(
            """
            import json
            import sys

            from agent_artifacts import cli  # noqa: F401

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

        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
