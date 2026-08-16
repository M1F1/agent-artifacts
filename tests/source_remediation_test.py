"""SL-5: every command AART names to an operator is one the shipped executable accepts.

The 2026-08-13 dead end was as much a diagnostics failure as a missing-operation failure: `sync`
advised the operator to "review the configured origin before replacing this source", and there was
no replace.  Rewriting that sentence fixes it once; this file is what keeps it fixed.

The first half of this file works through refusals: each one is produced by the real production
path, never by a literal written here, and every ``aart …`` command in its remediation is handed to
the actual CLI parser.

The second half is wider, and live acceptance v2 is why.  `tui_sources.py` told operators to run
`source doctor`, removed in `2.0.0`; the setup renderers named `aart setup retry` and
`aart setup rollback`, one renamed in `2.0.0` and one that never shipped at all.  None of them is a
`Diagnostic`, so the narrow guard above could not have seen any of them.  `SourceRemediation…Test`
scans every user-visible ``aart …`` mention in the package instead — display reasons, TUI hints,
recovery notes — and parses each one.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.application.configuration import ConfigurationRequest, load_configuration
from agent_artifacts.application.sources import sync_source
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from agent_artifacts.configuration.policy import RuntimeOverrides
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err
from agent_artifacts.tui_sources import (
    build_source_stage,
    plan_source_addition,
    plan_source_removal,
)
from tests.configuration_application_test import _FakePorts as _ConfigurationPorts
from tests.configuration_application_test import _paths
from tests.marketplace_lifecycle_e2e_test import _FIXTURE, _environment
from tests.source_sync_application_test import _candidate, _current, _FakePorts, _request

_COMMAND = re.compile(r"`(aart [^`]+)`")
_BACKTICKED = re.compile(r"`(aart\s[^`]+)`")
# The negative lookahead keeps the managed-block marker `# >>> aart setup: <coordinate> >>>` out:
# a word ending in a colon is a label, and the marker is written into a config file rather than
# offered to anyone as something to run.
_BARE = re.compile(r"\baart\s+([a-z][a-z0-9-]*)(?![\w:/-])[^,;`\n]*")
_REMOVED = re.compile(r"^\| `aart ([a-z][a-z0-9-]*)[^|]*\|", re.MULTILINE)
_PACKAGE = Path(cli.__file__).resolve().parent
_RELEASE_DOCS = _PACKAGE.parent / "docs" / "release"
_REGISTRY_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "registry-v1"
_FINDING_LINE = re.compile(r"^\s+(error|warning): ")
_PLACEHOLDER = "PLACEHOLDER"


class _Rejected(Exception):
    """Raised in place of argparse's exit, so the reason can be attributed to one command."""


def _parse_failure(command: str) -> str | None:
    """Hand one ``aart …`` command to the shipped parser; return why it was rejected, or ``None``.

    ``parse_args`` is the shipped surface itself, so this cannot pass against a command the parser
    does not define.  ``error`` is replaced because argparse writes to stderr and exits rather than
    raising anything a caller can attribute back to a specific command.  A command ending in
    ``--help`` is advice to go read the help, so it succeeds by exiting zero instead of returning;
    that still proves the subcommand exists, which is the claim.
    """

    arguments = command.split()[1:]

    def reject(message: str) -> None:
        raise _Rejected(message)

    with (
        patch.object(argparse.ArgumentParser, "error", side_effect=reject),
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        try:
            cli.build_parser().parse_args(arguments)
        except _Rejected as rejected:
            return str(rejected)
        except SystemExit as exited:
            if arguments[-1:] == ["--help"] and exited.code == 0:
                return None
            return f"exited with {exited.code}"
    return None


def _refusal(result) -> tuple[str, ...]:
    """Every remediation line of a refusal, with the refusal itself asserted to be one."""

    assert isinstance(result, Err), f"expected a refusal, got {result}"
    return tuple(line for diagnostic in result.diagnostics for line in diagnostic.remediation)


def _command_names() -> frozenset[str]:
    """Every top-level command the parser defines, plus every one a release document removed.

    The removed names carry as much weight as the live ones.  ``aart setup retry`` is prose to a
    regex and a dead end to an operator, and the only durable record that ``setup`` was ever a
    command is the compatibility table that removed it — so that table is what this reads.

    ``_actions`` is private argparse state.  The alternative is a second hand-maintained list of
    top-level commands, which would drift from the parser exactly when it mattered.
    """

    live = {
        name
        for action in cli.build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
        for name in action.choices
    }
    removed = {
        name
        for document in sorted(_RELEASE_DOCS.glob("compatibility-v*.md"))
        for name in _REMOVED.findall(document.read_text(encoding="utf-8"))
    }
    return frozenset(live | removed)


_COMMAND_NAMES = _command_names()


def _mentions(text: str) -> tuple[str, ...]:
    """Every command claim inside one user-visible string.

    Three shapes are a claim and prose is not: a backticked ``aart …``; a mention whose first word
    is a command name, live or removed; and a mention carrying a ``--flag``.  "aart installs your
    team's artifacts" is none of those.  A claim ends at a comma or a semicolon, because a
    remediation may keep explaining itself after the command it names.
    """

    found = [match.group(1) for match in _BACKTICKED.finditer(text)]
    for match in _BARE.finditer(_BACKTICKED.sub(" ", text)):
        if match.group(1) in _COMMAND_NAMES or " --" in match.group(0):
            found.append(match.group(0))
    return tuple(mention.strip().rstrip(".") for mention in found)


def _visible_strings(tree: ast.AST):
    """Every string literal in one module that can reach a user, docstrings excluded.

    A docstring explains the code to whoever maintains it; this file's own explanation of why
    ``aart setup rollback`` had to go would otherwise be a finding about itself.  An f-string is
    rendered whole, with each interpolation replaced by ``PLACEHOLDER`` — reading only its constant
    pieces would report ``aart source sync --alias`` as a command missing its value.
    """

    documentation = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    def walk(node: ast.AST):
        if any(node is item for item in documentation):
            return
        if isinstance(node, ast.JoinedStr):
            yield (
                "".join(
                    piece.value
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
                    else _PLACEHOLDER
                    for piece in node.values
                ),
                node.lineno,
            )
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno
            return
        for child in ast.iter_child_nodes(node):
            yield from walk(child)

    yield from walk(tree)


def _package_mentions() -> tuple[tuple[str, int, str], ...]:
    """Every command claim in the shipped package, as ``(module, line, command)``."""

    found: list[tuple[str, int, str]] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text, line in _visible_strings(tree):
            found.extend((path.name, line, command) for command in _mentions(text))
    return tuple(found)


def _interpolated_value(failure: str) -> bool:
    """Is this rejection only about a value the guard could not know?

    A choice-constrained flag rejects ``PLACEHOLDER`` because the real value is computed at run
    time.  The guard proves the command and its flags exist; it cannot prove a runtime value, and
    pretending otherwise would make every ``--scope {scope}`` a false finding.
    """

    return f"invalid choice: '{_PLACEHOLDER}'" in failure


def _remediation_in_text(output: str) -> tuple[str, ...]:
    return tuple(
        line.split("remediation:", 1)[1].strip()
        for line in output.splitlines()
        if "remediation:" in line
    )


def _remediation_in_json(payload) -> tuple[str, ...]:
    """Every remediation line anywhere in one JSON envelope.

    The families nest diagnostics differently — at the envelope root for a single operation, under
    ``sources`` for a fan-out sync, under ``checks`` for registry validation — and a parity guard
    taught those three shapes would have to be taught the fourth.
    """

    if isinstance(payload, dict):
        found: list[str] = []
        for key, value in payload.items():
            if key == "remediation" and isinstance(value, list):
                found.extend(str(line) for line in value)
            else:
                found.extend(_remediation_in_json(value))
        return tuple(found)
    if isinstance(payload, list):
        return tuple(line for item in payload for line in _remediation_in_json(item))
    return ()


def _registry(alias: str, location: str) -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), SourceKind.REGISTRY_GIT, location, "main", True)


def _view(*sources: ConfiguredSource):
    baseline = default_user_configuration()
    configuration = UserConfiguration(
        baseline.schema_version, sources, None, baseline.sync, baseline.reporting
    )
    stage = build_source_stage(configuration, OrganizationPolicy(1), {}, first_run=False)
    assert not isinstance(stage, Err), stage
    return stage.value


class SourceRemediationNamesRealCommandsTest(unittest.TestCase):
    def assert_runnable(self, remediation: tuple[str, ...]) -> tuple[str, ...]:
        """Assert the remediation offers at least one command, and that all of them parse.

        ``parse_args`` is the shipped surface itself, so this cannot pass against a command the
        parser does not define.  ``error`` is patched because argparse writes to stderr and exits
        rather than raising anything a test can attribute back to a specific command.  A
        remediation ending in ``--help`` is advice to go read the help, so it succeeds by exiting
        zero instead of returning; that still proves the subcommand exists, which is the claim.
        """

        found = tuple(match for line in remediation for match in _COMMAND.findall(line))
        self.assertTrue(found, f"remediation names no command: {remediation}")
        for command in found:
            failure = _parse_failure(command)
            if failure is not None:
                self.fail(f"`{command}` is not accepted: {failure}")
        return found

    def test_a_changed_declared_identity_points_at_a_command_that_exists(self) -> None:
        source = _registry("registry", "https://git.example.test/team/registry.git")
        ports = _FakePorts(
            _candidate(source, b"new"),
            _current(_candidate(source, b"old"), source_id="old-id"),
        )

        refused = sync_source(_request(source), ports.ports())

        commands = self.assert_runnable(_refusal(refused))
        self.assertIn("aart source resubscribe --alias registry", commands)

    def test_an_already_configured_alias_points_at_commands_that_exist(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")
        duplicate = _registry("registry", "https://git.example.test/other/registry.git")

        refused = plan_source_addition(_view(held), duplicate)

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(any("--alias registry" in command for command in commands), commands)

    def test_an_already_configured_origin_and_ref_point_at_commands_that_exist(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")
        same_origin = _registry("second", "https://git.example.test/team/registry.git")

        refused = plan_source_addition(_view(held), same_origin)

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(
            any("--alias registry" in command for command in commands),
            f"remediation must name the alias that holds the origin: {commands}",
        )

    def test_removing_an_unconfigured_alias_points_at_the_listing_command(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")

        refused = plan_source_removal(_view(held), SourceAlias("typo"))

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(any(command.startswith("aart source list") for command in commands))

    def test_a_content_operation_without_any_source_points_at_the_command_that_adds_one(
        self,
    ) -> None:
        """The first refusal a new operator meets, and the one that must not be a dead end."""

        refused = load_configuration(
            ConfigurationRequest(_paths(), RuntimeOverrides(), content_required=True),
            _ConfigurationPorts({}).ports(),
        )

        commands = self.assert_runnable(_refusal(refused))
        self.assertIn("aart source add --help", commands)

    def test_the_guard_rejects_a_remediation_naming_a_command_that_does_not_exist(self) -> None:
        """The guard is only worth having if it fails on the thing it claims to catch."""

        with self.assertRaises(AssertionError):
            self.assert_runnable(("run `aart source disavow --alias registry`",))


class EveryVisibleCommandMentionTest(unittest.TestCase):
    """The same rule, applied past `Diagnostic` to every string the package shows an operator."""

    def test_every_command_the_package_names_is_one_the_parser_accepts(self) -> None:
        dead_ends = tuple(
            f"{module}:{line}: `{command}` — {failure}"
            for module, line, command in _package_mentions()
            if (failure := _parse_failure(command)) is not None and not _interpolated_value(failure)
        )

        self.assertEqual(dead_ends, (), "\n".join(("",) + dead_ends))

    def test_the_scan_reaches_strings_that_are_not_diagnostics(self) -> None:
        """A guard that only saw refusals would have missed every dead end v2 actually found.

        `tui_sources.py` holds a display reason, `setup.py` a rendered retry field, `tui.py` an
        error line printed straight to the terminal.  None is a `Diagnostic`.
        """

        scanned = {module for module, _line, _command in _package_mentions()}

        for module in ("tui_sources.py", "setup.py", "tui.py", "catalog.py"):
            self.assertIn(module, scanned)

    def test_a_command_removed_in_2_0_0_is_still_read_as_a_command(self) -> None:
        """`aart setup rollback` names no live command, so only the removal record makes it legible.

        Without it the mention parses as prose, the guard skips it, and the operator is sent to a
        command that has never existed.
        """

        self.assertIn("setup", _COMMAND_NAMES)
        self.assertEqual(_mentions("aart setup rollback"), ("aart setup rollback",))
        self.assertIsNotNone(_parse_failure("aart setup rollback"))

    def test_a_planted_stale_command_is_caught(self) -> None:
        """The removal this package started from, planted back in a string shaped like the original."""

        planted = ast.parse('reason = "source state is invalid; run `aart source doctor` first"')

        mentions = tuple(
            command for text, _line in _visible_strings(planted) for command in _mentions(text)
        )

        self.assertEqual(mentions, ("aart source doctor",))
        self.assertIsNotNone(_parse_failure(mentions[0]))

    def test_prose_about_aart_is_not_read_as_a_command(self) -> None:
        """The wizard explains what AART is; it is not offering a command."""

        self.assertEqual(_mentions("aart installs your team's artifacts for you"), ())
        self.assertEqual(_mentions("press aart to reload Sources."), ())

    def test_a_docstring_is_not_a_user_visible_string(self) -> None:
        module = ast.parse('"""Run `aart source doctor` to fix this."""\n')

        self.assertEqual(tuple(_visible_strings(module)), ())


class RegistryRefusalRemediationTest(unittest.TestCase):
    """`RS-09`: a refused `registry` command must say what to do next.

    The family emitted next-step lines after a *successful* action and nothing after a refusal, so
    the operator who most needed one got none. A list of the refusals that carry remediation would
    be true on the day it was written; this reads the shipped modules instead, so the refusal added
    next month is covered by the same guard.

    Both halves are covered: `_error`, which is every `Err` the family returns, and `_diagnostic`,
    which is every finding `validate` and `audit` collect into a report. A report is where those
    two commands state a problem, so a finding with no next step is the same dead end as a refusal
    with none.
    """

    def refusals_without_remediation(self) -> tuple[str, ...]:
        """Every registry refusal or finding built without a next step, as `module:line`."""

        found: list[str] = []
        for path in (
            _PACKAGE / "commands" / "registry.py",
            _PACKAGE / "registry_commands" / "planning.py",
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id not in ("_error", "_diagnostic"):
                    continue
                if len(node.args) < 2 and not any(
                    keyword.arg == "remediation" for keyword in node.keywords
                ):
                    found.append(f"{path.name}:{node.lineno}")
        return tuple(found)

    def test_rs09_every_registry_refusal_hands_the_operator_a_next_step(self) -> None:
        silent = self.refusals_without_remediation()

        self.assertEqual(silent, (), f"refusals with no remediation: {', '.join(silent)}")

    def test_rs09_the_guard_sees_a_refusal_that_carries_nothing(self) -> None:
        """The guard is only worth having if it fails on the thing it claims to catch."""

        planted = ast.parse('return _error("registry workspace requires aart-registry.json")\n')
        calls = [
            node
            for node in ast.walk(planted)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]

        self.assertEqual(len(calls[0].args), 1)

    def test_rs09_an_audit_finding_prints_a_next_step_too(self) -> None:
        """The other half: `audit` states its problems in a report, not in a refusal."""

        with _environment() as env:
            workspace = env.root / "registry-under-audit"
            shutil.copytree(_REGISTRY_FIXTURE, workspace)
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env.xdg, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                cli.main(["registry", "audit", "--source", str(workspace)])

            printed = stdout.getvalue()
            findings = [
                line for line in printed.splitlines() if _FINDING_LINE.match(line) is not None
            ]
            self.assertTrue(findings, printed)
            self.assertEqual(
                len(findings),
                len(_remediation_in_text(printed)),
                f"every finding needs its own next step:\n{printed}",
            )

    def test_rs09_a_refused_registry_command_prints_a_next_step(self) -> None:
        """Driven through the shipped CLI, because the renderer is where `LAF-52` went wrong."""

        with _environment() as env:
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env.xdg, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = cli.main(["registry", "test", "--source", str(env.project)])

            self.assertEqual(code, 1, stdout.getvalue())
            remediation = _remediation_in_text(stdout.getvalue())
            self.assertTrue(remediation, f"no remediation printed: {stdout.getvalue()}")
            for line in remediation:
                for command in _COMMAND.findall(line):
                    failure = _parse_failure(command)
                    self.assertIsNone(failure, f"`{command}` is not accepted: {failure}")


class RendererParityTest(unittest.TestCase):
    """Parser parity proves a command exists; this proves the operator was shown it.

    `--json` was never the problem: the JSON envelope carried the remediation all along.  Text mode
    dropped it, and text mode is what a person sees.  Every family that renders both must render
    the same lines in both.

    Two families are absent because they have nothing to compare. `upgrade` defines no `--json`, so
    it has one renderer; `security` and `reporting` report through plain messages rather than a
    diagnostic envelope. `registry` was present and vacuous — both renderers agreed on nothing,
    because its refusals carried nothing. `RS-09` filled the field, and the same comparison then
    found the second half of the defect: `_emit_report` printed the message and dropped the next
    step, so the JSON envelope carried advice a person at a terminal never saw.
    """

    def _both_renderers(self, env, *argv: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Run one command twice and return its remediation as text, then as JSON."""

        rendered: list[tuple[str, ...]] = []
        for as_json in (False, True):
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env.xdg, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
                mock.patch("os.getcwd", return_value=str(env.project)),
            ):
                code = cli.main([*argv, "--json"] if as_json else list(argv))
            self.assertEqual(code, 1, f"expected a refusal from {argv}: {stdout.getvalue()}")
            raw = stdout.getvalue()
            rendered.append(
                _remediation_in_json(json.loads(raw)) if as_json else _remediation_in_text(raw)
            )
        return rendered[0], rendered[1]

    def test_marketplace_renders_the_same_remediation_in_both(self) -> None:
        with _environment() as env:
            text, envelope = self._both_renderers(
                env,
                "marketplace",
                "install",
                "unknown/skill/nothing",
                "--profile",
                "claude",
                "--project",
                str(env.project),
            )

            self.assertTrue(text)
            self.assertEqual(sorted(text), sorted(envelope))

    def test_a_single_source_operation_renders_the_same_remediation_in_both(self) -> None:
        with _environment() as env:
            text, envelope = self._both_renderers(env, "source", "sync", "--alias", "absent")

            self.assertTrue(text)
            self.assertEqual(sorted(text), sorted(envelope))

    def test_the_per_source_sync_renderer_renders_the_same_remediation_in_both(self) -> None:
        """The renderer this package repaired, on the refusal `2.1.0` exists to deliver."""

        with _environment() as staging:
            source = staging.root / "renamed-source"
            shutil.copytree(_FIXTURE, source)

            with _environment(source) as env:
                marker = source / "aart-source.json"
                document = json.loads(marker.read_text(encoding="utf-8"))
                document["source_id"] = "renamed-reference-source"
                marker.write_text(json.dumps(document, indent=2), encoding="utf-8")

                text, envelope = self._both_renderers(env, "source", "sync")

                self.assertEqual(len(text), 1, text)
                self.assertIn("aart source resubscribe --alias reference", text[0])
                self.assertEqual(sorted(text), sorted(envelope))

    def test_registry_renders_the_same_remediation_in_both(self) -> None:
        with _environment() as env:
            text, envelope = self._both_renderers(
                env, "registry", "validate", "--source", str(env.project)
            )

            self.assertTrue(text, "a refused registry validate must print a next step")
            self.assertEqual(sorted(text), sorted(envelope))


if __name__ == "__main__":
    unittest.main()
