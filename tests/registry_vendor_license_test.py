"""VN-6: what the copy is licensed under is recorded or visibly missing, and drift reaches CI.

Vendoring redistributes somebody else's work (design §7). AART is not qualified to adjudicate a
licence, so nothing here refuses: the licence file is read where it settles the identifier by
itself, the maintainer's own statement always wins, and everything else is reported for a human.
What must not happen is a copy of foreign bytes carrying no licence and no finding.

The second half is design §6 from CI's side. `registry audit` can resolve vendored origins and say
which copies are behind upstream, read-only and without failing on the finding — and an origin it
cannot read is reported as unknown, never as an up-to-date copy.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.curation.runtime import LocalCurationService
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SourceSnapshot
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from tests.registry_revendor_test import _MOVED_COMMIT, _moved_repository
from tests.registry_vendoring_projection_test import (
    _COMMIT,
    _MCP_JSON,
    _URL,
    _file,
    _foreign_repository,
)

_PACKAGE = "artifacts/mcp/atlassian"
_REGISTRY_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "registry-v1"
_MIT = (
    b"MIT License\n\nCopyright (c) 2024 Example\n\nPermission is hereby granted, free of charge, "
    b"to any person obtaining a copy of this software and associated documentation files.\n"
)
_APACHE = b"                              Apache License\n                        Version 2.0\n"
_GPL = b"                    GNU GENERAL PUBLIC LICENSE\n                       Version 3\n"


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _licensed(*licenses: tuple[str, bytes]) -> SourceSnapshot:
    return _foreign_repository(
        *(_file(f"servers/atlassian/{name}", content) for name, content in licenses)
    )


def _unreachable(_url: str, _ref: str) -> Err:
    return Err(
        (Diagnostic(DiagnosticCode("source-invalid"), Severity.ERROR, "cannot reach origin"),)
    )


def _acquire(snapshot: SourceSnapshot, commit: str = _COMMIT):
    return lambda _url, _ref: Ok(NativeReferenceAcquisition(_URL, "v1.4.0", commit, snapshot))


def _vendor(root: Path, *extra: str) -> tuple[str, ...]:
    return (
        "registry",
        "vendor",
        "--source",
        str(root),
        "mcp",
        "atlassian",
        "--url",
        _URL,
        "--ref",
        "v1.4.0",
        "--path",
        "servers/atlassian",
        "--artifact-version",
        "1.0.0",
        "--summary",
        "Atlassian MCP server, vendored from upstream.",
        "--profile",
        "claude",
        "--platform",
        "darwin",
        *extra,
    )


def _checks(payload: dict) -> dict[str, dict]:
    review = payload.get("review", payload)
    return {item["name"]: item for item in review["checks"]}


def _manifest(root: Path) -> dict:
    return json.loads((root / _PACKAGE / "artifact.json").read_text())


def _audit_messages(output: str) -> tuple[str, ...]:
    report = json.loads(output)
    return tuple(
        f"{item['severity']}: {item['message']}"
        for check in report["checks"]
        for item in check["diagnostics"]
    )


class _RegistryFixture(unittest.TestCase):
    """One registry holding one vendored package, driven through the real CLI."""

    @contextlib.contextmanager
    def _registry(self, upstream: SourceSnapshot, *vendor_flags: str):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertEqual(
                _run(
                    "registry",
                    "init",
                    "--source",
                    str(root),
                    "--source-id",
                    "company-registry",
                    "--display-name",
                    "Company Registry",
                    "--yes",
                )[0],
                0,
            )
            document = root / _PACKAGE / "payload/mcp.json"
            document.parent.mkdir(parents=True)
            document.write_bytes(_MCP_JSON)
            service = LocalCurationService(str(root), native_acquirer=_acquire(upstream))
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                code, output = _run(*_vendor(root, "--yes", "--json", *vendor_flags))
                self.assertEqual(code, 0, output)
                yield root, json.loads(output)


class LicenseCaptureTest(_RegistryFixture):
    def test_one_license_file_at_the_subtree_root_is_reported_and_recorded(self) -> None:
        with self._registry(_licensed(("LICENSE", _MIT))) as (root, review):
            check = _checks(review)["vendor-license"]

            self.assertTrue(check["passed"])
            self.assertIn("discovered: LICENSE: MIT", check["details"])
            self.assertIn("recorded: MIT", check["details"])
            self.assertEqual(_manifest(root)["license"], "MIT")

    def test_the_identifier_comes_from_the_text_rather_than_the_file_name(self) -> None:
        with self._registry(_licensed(("COPYING.md", _APACHE))) as (root, review):
            self.assertIn(
                "discovered: COPYING.md: Apache-2.0", _checks(review)["vendor-license"]["details"]
            )
            self.assertEqual(_manifest(root)["license"], "Apache-2.0")

    def test_two_license_files_report_ambiguity_and_record_nothing(self) -> None:
        with self._registry(_licensed(("LICENSE", _MIT), ("COPYING", _APACHE))) as (root, review):
            check = _checks(review)["vendor-license"]

            self.assertTrue(check["passed"])
            details = " ".join(check["details"])
            self.assertIn("several license files at the subtree root", details)
            self.assertIn("LICENSE", details)
            self.assertIn("COPYING", details)
            self.assertNotIn("license", _manifest(root))

    def test_a_license_below_the_subtree_root_is_reported_and_never_adopted(self) -> None:
        """A `LICENSE` beside a bundled dependency covers the dependency, not the taken work."""

        with self._registry(_licensed(("lib/LICENSE", _MIT))) as (root, review):
            details = " ".join(_checks(review)["vendor-license"]["details"])

            self.assertIn("below the subtree root", details)
            self.assertIn("lib/LICENSE", details)
            self.assertNotIn("license", _manifest(root))

    def test_a_gpl_text_is_named_and_its_grant_is_not_guessed(self) -> None:
        """`-only` and `-or-later` are chosen by the work, not stated in the licence document."""

        with self._registry(_licensed(("LICENSE", _GPL))) as (root, review):
            details = " ".join(_checks(review)["vendor-license"]["details"])

            self.assertIn("GNU General Public License", details)
            self.assertIn("-or-later", details)
            self.assertIn("--license", details)
            self.assertNotIn("license", _manifest(root))

    def test_no_license_file_records_nothing_and_says_which_it_is(self) -> None:
        with self._registry(_foreign_repository()) as (root, review):
            details = _checks(review)["vendor-license"]["details"]

            self.assertIn("discovered: no license file in the taken subtree", details)
            self.assertIn(
                "recorded: none; state one with --license, or registry audit will report it",
                details,
            )
            self.assertNotIn("license", _manifest(root))

    def test_the_stated_license_wins_over_the_discovered_one_and_both_are_shown(self) -> None:
        with self._registry(_licensed(("LICENSE", _MIT)), "--license", "MIT AND OFL-1.1") as (
            root,
            review,
        ):
            details = _checks(review)["vendor-license"]["details"]

            self.assertIn("discovered: LICENSE: MIT", details)
            self.assertIn("stated: MIT AND OFL-1.1", details)
            self.assertIn("recorded: MIT AND OFL-1.1", details)
            self.assertEqual(_manifest(root)["license"], "MIT AND OFL-1.1")

    def test_re_vendoring_keeps_the_license_this_registry_recorded(self) -> None:
        """Upstream movement must not turn a licensed copy into an unlicensed one."""

        with self._registry(_licensed(("LICENSE", _MIT))) as (root, _review):
            service = LocalCurationService(
                str(root), native_acquirer=_acquire(_moved_repository(), _MOVED_COMMIT)
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                code, output = _run(
                    "registry",
                    "revendor",
                    "--source",
                    str(root),
                    "mcp",
                    "atlassian",
                    "--artifact-version",
                    "2.0.0",
                    "--yes",
                )

            self.assertEqual(code, 0, output)
            self.assertEqual(_manifest(root)["version"], "2.0.0")
            self.assertEqual(_manifest(root)["license"], "MIT")


class VendoredAuditTest(_RegistryFixture):
    """Design §6 and §7 from CI's side: findings that report, and an audit that still passes."""

    @contextlib.contextmanager
    def _audited(self, upstream: SourceSnapshot, *vendor_flags: str):
        with self._registry(upstream, *vendor_flags) as (root, _review):
            for action in ("lock", "build"):
                code, output = _run("registry", action, "--source", str(root), "--yes")
                self.assertEqual(code, 0, output)
            yield root

    def test_an_unlicensed_vendored_artifact_is_named_and_the_audit_still_passes(self) -> None:
        with self._audited(_foreign_repository()) as root:
            code, output = _run("registry", "audit", "--source", str(root), "--json")

            self.assertEqual(code, 0, output)
            messages = _audit_messages(output)
            self.assertIn(
                "warning: vendored artifact redistributes upstream bytes with no declared "
                "license: mcp/atlassian",
                messages,
            )

    def test_a_licensed_vendored_artifact_raises_no_license_finding(self) -> None:
        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            code, output = _run("registry", "audit", "--source", str(root), "--json")

            self.assertEqual(code, 0, output)
            self.assertNotIn("license", " ".join(_audit_messages(output)))

    def test_the_audit_reaches_no_upstream_unless_it_is_asked_to(self) -> None:
        """An audit that quietly used the network would fail offline and depend on somebody's uptime."""

        def refuse(_url: str, _ref: str):
            raise AssertionError("registry audit resolved an origin without --check-upstream")

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch("agent_artifacts.commands.registry.default_native_acquirer", refuse):
                code, output = _run("registry", "audit", "--source", str(root), "--json")

            self.assertEqual(code, 0, output)
            self.assertNotIn("upstream", " ".join(_audit_messages(output)))

    def test_check_upstream_reports_a_copy_behind_upstream_without_failing(self) -> None:
        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch(
                "agent_artifacts.commands.registry.default_native_acquirer",
                _acquire(_moved_repository(), _MOVED_COMMIT),
            ):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            messages = " ".join(_audit_messages(output))
            self.assertIn("vendored artifact is behind upstream: mcp/atlassian", messages)
            self.assertIn(_COMMIT[:12], messages)
            self.assertIn(_MOVED_COMMIT[:12], messages)

    def test_check_upstream_reports_an_unreachable_origin_as_unknown_rather_than_drift(
        self,
    ) -> None:
        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch("agent_artifacts.commands.registry.default_native_acquirer", _unreachable):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            messages = " ".join(_audit_messages(output))
            self.assertIn("drift is unknown: mcp/atlassian", messages)
            self.assertNotIn("behind upstream", messages)

    def test_an_unmoved_upstream_raises_no_drift_finding(self) -> None:
        """No *finding*, which is not the same as no output — see the `LAF-45` tests below."""

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch(
                "agent_artifacts.commands.registry.default_native_acquirer",
                _acquire(_licensed(("LICENSE", _MIT))),
            ):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            findings = [
                message for message in _audit_messages(output) if not message.startswith("info: ")
            ]
            self.assertNotIn("upstream", " ".join(findings))

    def test_laf45_a_completed_check_says_so_when_every_copy_is_current(self) -> None:
        """`LAF-45`: silence on success is indistinguishable from a flag that was never passed.

        This is the whole finding. An operator running the audit in CI saw exactly nothing about
        the vendored artifacts when they were current, and exactly nothing when `--check-upstream`
        was dropped from the command line — two different states, one output.
        """

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch(
                "agent_artifacts.commands.registry.default_native_acquirer",
                _acquire(_licensed(("LICENSE", _MIT))),
            ):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            self.assertIn(
                "info: checked 1 vendored artifact against its upstream: "
                "1 up-to-date, 0 changed, 0 unreachable",
                _audit_messages(output),
            )

    def test_laf45_the_audit_says_nothing_of_the_kind_without_the_flag(self) -> None:
        """The line is only worth printing if its absence means the check did not run."""

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            code, output = _run("registry", "audit", "--source", str(root), "--json")

            self.assertEqual(code, 0, output)
            self.assertNotIn("checked", " ".join(_audit_messages(output)))

    def test_laf45_the_summary_counts_a_copy_that_is_behind(self) -> None:
        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch(
                "agent_artifacts.commands.registry.default_native_acquirer",
                _acquire(_moved_repository(), _MOVED_COMMIT),
            ):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            messages = _audit_messages(output)
            self.assertIn(
                "info: checked 1 vendored artifact against its upstream: "
                "0 up-to-date, 1 changed, 0 unreachable",
                messages,
            )
            # The summary states the count; the warning is still the thing that names which copy.
            self.assertIn(
                "warning: vendored artifact is behind upstream: mcp/atlassian copies "
                f"servers/atlassian at {_COMMIT[:12]}, and v1.4.0 now resolves to "
                f"{_MOVED_COMMIT[:12]}",
                messages,
            )

    def test_laf45_an_origin_that_could_not_be_read_is_counted_as_unreachable(self) -> None:
        """An unreadable origin must not be counted as a copy that was compared and matched."""

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            with patch("agent_artifacts.commands.registry.default_native_acquirer", _unreachable):
                code, output = _run(
                    "registry", "audit", "--source", str(root), "--check-upstream", "--json"
                )

            self.assertEqual(code, 0, output)
            self.assertIn(
                "info: checked 1 vendored artifact against its upstream: "
                "0 up-to-date, 0 changed, 1 unreachable",
                _audit_messages(output),
            )

    def test_a_hand_edited_vendoring_record_fails_the_audit(self) -> None:
        """The record the next re-vendor reads is checked against the digest written with it."""

        with self._audited(_licensed(("LICENSE", _MIT))) as root:
            document = root / _PACKAGE / "provenance.json"
            provenance = json.loads(document.read_text())
            provenance["aart.vendor"]["ref"] = "attacker-branch"
            document.write_text(json.dumps(provenance))

            code, output = _run("registry", "audit", "--source", str(root), "--json")

            self.assertEqual(code, 1, output)
            self.assertIn("edited by hand", " ".join(_audit_messages(output)))


class UnvendoredAuditTest(unittest.TestCase):
    """`LAF-45` at its worst: a registry that vendors nothing said nothing either way."""

    def test_laf45_a_registry_with_nothing_vendored_still_says_the_check_ran(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            shutil.copytree(_REGISTRY_FIXTURE, root)

            code, output = _run(
                "registry", "audit", "--source", str(root), "--check-upstream", "--json"
            )

            self.assertEqual(code, 0, output)
            self.assertIn(
                "info: no vendored artifacts to check against upstream", _audit_messages(output)
            )


if __name__ == "__main__":
    unittest.main()
