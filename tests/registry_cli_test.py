from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_artifacts import __version__, cli, tui
from agent_artifacts.commands import registry as registry_command
from agent_artifacts.curation.model import CurationAction, CurationRequest
from agent_artifacts.domain.result import Ok
from agent_artifacts.model import Request
from agent_artifacts.protocol.semver import VersionBounds, parse_semver

_SCAFFOLD = (
    "registry scaffold --source /tmp/registry skill demo --summary One. "
    "--profile codex --platform darwin"
)
_VENDOR = (
    "registry vendor --source /tmp/registry mcp atlassian --url https://example.com/up.git "
    "--path artifacts/mcp/atlassian --artifact-version 1.2.0 --summary One. "
    "--profile claude --platform darwin"
)
_PROMOTE = (
    "registry promote-native --source /tmp/registry skill demo "
    "--url https://example.com/up.git --path artifacts/skill/demo"
)


class RegistryCliTest(unittest.TestCase):
    def test_all_registry_actions_map_to_one_command_boundary(self) -> None:
        parser = cli.build_parser()
        actions = {
            "init",
            "scaffold",
            "format",
            "promote-native",
            "refresh-native",
            "vendor",
            "revendor",
            "validate",
            "lock",
            "build",
            "audit",
            "test",
            "diff",
        }
        registry = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        ).choices["registry"]
        sub = next(
            action
            for action in registry._actions
            if action.__class__.__name__ == "_SubParsersAction"
        )
        self.assertEqual(set(sub.choices), actions)
        self.assertIn("registry", cli.DISPATCH)

    def test_format_check_and_json_are_preserved_in_request(self) -> None:
        captured: list[Request] = []

        def run(request: Request) -> int:
            captured.append(request)
            return 0

        with patch.dict(cli.DISPATCH, {"registry": run}):
            result = cli.main(
                ["registry", "format", "--source", "/tmp/registry", "--check", "--json"]
            )
        self.assertEqual(result, 0)
        self.assertEqual(captured[0].registry_action, "format")
        self.assertEqual(captured[0].source_dir, "/tmp/registry")
        self.assertTrue(captured[0].check)
        self.assertTrue(captured[0].json)

    def test_the_compatibility_ceiling_defaults_to_the_running_aart(self) -> None:
        # The upper compatibility point is whichever AART is publishing, not a version frozen in
        # the parser.  A default that never moves refuses every registry whose floor rises above
        # it, and proves nothing about today's release for the ones below it.
        request = cli._to_request(cli.build_parser().parse_args(["registry", "test"]))

        self.assertEqual(request.latest_version, __version__)

    def test_rs02_no_registry_action_declares_a_window_that_excludes_the_running_aart(self) -> None:
        # `--minimum-version` and `--maximum-version` exist on `registry init` alone, so every
        # other action reaches the command boundary with both unset and takes whatever the
        # boundary substitutes.  It substituted the literals `1.0.0` and `2.0.0`: a window that
        # stops one whole major short of the AART doing the writing.  Only `init` reads the pair
        # today, which is the sole reason nothing has broken -- a value that is wrong the moment
        # anything reads it is not worth carrying.
        running = parse_semver(__version__)
        assert isinstance(running, Ok)

        for command in (_SCAFFOLD, _VENDOR, _PROMOTE):
            with self.subTest(command=command.split()[1]):
                request = cli._to_request(cli.build_parser().parse_args(command.split()))
                curation = registry_command._curation_request(
                    request, CurationAction(request.registry_action)
                )
                assert isinstance(curation, Ok)
                minimum = parse_semver(curation.value.minimum_version)
                maximum = parse_semver(curation.value.maximum_version)
                assert isinstance(minimum, Ok) and isinstance(maximum, Ok)

                self.assertTrue(
                    VersionBounds(minimum.value, maximum.value).allows(running.value),
                    f"{curation.value.minimum_version}..{curation.value.maximum_version} "
                    f"excludes the running {__version__}",
                )

    def test_rs02_init_still_carries_the_window_the_operator_asked_for(self) -> None:
        # The substitution is a fallback, not a rewrite: an author who really supports a wider
        # range says so on `init`, and that is what has to reach the manifest.
        request = cli._to_request(
            cli.build_parser().parse_args(
                "registry init --source /tmp/registry --source-id company --display-name Company "
                "--minimum-version 2.0.0 --maximum-version 4.0.0".split()
            )
        )
        curation = registry_command._curation_request(request, CurationAction.INIT)

        assert isinstance(curation, Ok)
        self.assertEqual(curation.value.minimum_version, "2.0.0")
        self.assertEqual(curation.value.maximum_version, "4.0.0")

    def test_native_promotion_maps_an_explicit_reference_and_finalize_consent(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "registry",
                    "promote-native",
                    "--source",
                    "/tmp/registry",
                    "skill",
                    "review-python",
                    "--url",
                    "https://github.com/example/review-python.git",
                    "--ref",
                    "release",
                    "--path",
                    "artifacts/skill/review-python",
                    "--review-policy",
                    "company-review-v2",
                    "--yes",
                ]
            )
        )
        self.assertEqual(request.registry_action, "promote-native")
        self.assertEqual(request.artifact_kind, "skill")
        self.assertEqual(request.names, ("review-python",))
        self.assertEqual(request.native_url, "https://github.com/example/review-python.git")
        self.assertEqual(request.ref, "release")
        self.assertEqual(request.native_path, "artifacts/skill/review-python")
        self.assertEqual(request.review_policy, "company-review-v2")
        self.assertTrue(request.yes)

    def test_scaffold_install_scope_and_mode_do_not_silently_include_defaults(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "registry",
                    "scaffold",
                    "--source",
                    "/tmp/registry",
                    "skill",
                    "demo",
                    "--summary",
                    "Demonstrate one canonical skill.",
                    "--profile",
                    "codex",
                    "--platform",
                    "darwin",
                    "--install-scope",
                    "user",
                    "--install-mode",
                    "symlink",
                ]
            )
        )
        self.assertEqual(request.registry_scopes, ("user",))
        self.assertEqual(request.registry_modes, ("symlink",))

    def test_laf90_the_wizard_defaults_name_a_window_the_running_aart_is_inside(self) -> None:
        # `LAF-90`: `RS-02` replaced the dead literals in every registry *request*, and the curses
        # wizard kept offering the same two as the defaults for `registry init`.  There they are not
        # dead: an operator who presses return at both prompts authors a registry the executable
        # that wrote it then refuses to read.  The assertion is `RS-02`'s own, applied to the
        # front-end it missed, so one statement now holds both.
        answers: list[str] = []

        def read(prompt: str) -> str:
            answers.append(prompt)
            if "ID" in prompt:
                return "company"
            if "display name" in prompt:
                return "Company"
            return ""

        prompted = tui._prompt_curation_request(
            CurationAction.INIT,
            "/tmp/registry",
            read,
            lambda message: None,
            existing=None,
        )

        assert isinstance(prompted, CurationRequest)
        running = parse_semver(__version__)
        minimum = parse_semver(prompted.minimum_version)
        maximum = parse_semver(prompted.maximum_version)
        assert isinstance(running, Ok)
        assert isinstance(minimum, Ok) and isinstance(maximum, Ok)

        self.assertTrue(
            VersionBounds(minimum.value, maximum.value).allows(running.value),
            f"pressing return offers {prompted.minimum_version}..{prompted.maximum_version}, "
            f"which excludes the running {__version__}",
        )
        self.assertIn(f"[{__version__}]", "".join(answers))


if __name__ == "__main__":
    unittest.main()
