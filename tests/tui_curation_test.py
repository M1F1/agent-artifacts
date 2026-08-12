from __future__ import annotations

import curses
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.curation.model import (
    CurationAction,
    CurationChange,
    CurationOutcome,
    CurationReview,
)
from agent_artifacts.curation.runtime import PreparedCuration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot


def _scripted(values):
    answers = iter(values)

    def read(_prompt=""):
        return next(answers)

    return read


class _Service:
    def __init__(self):
        self.prepared = []
        self.finalized = []

    def prepare(self, request):
        self.prepared.append(request)
        review = CurationReview(
            request.action,
            request.workspace,
            True,
            ObjectDigest("sha256", "a" * 64),
            ObjectDigest("sha256", "b" * 64),
            (CurationChange("artifacts/skill/demo/artifact.json", "added"),),
            follow_up_commands=("git -C /registry diff -- artifacts/skill/demo",),
        )
        return Ok(PreparedCuration(review, SourceSnapshot(SnapshotOrigin.LOCAL, ())))

    def finalize(self, prepared, reviewed_digest):
        self.finalized.append((prepared, reviewed_digest))
        return Ok(
            CurationOutcome(
                prepared.review.action,
                "succeeded",
                1,
                follow_up_commands=prepared.review.follow_up_commands,
            )
        )


class TuiCurationTest(unittest.TestCase):
    def test_curses_finalizes_with_canonical_consumer_loaded_after_maintainer_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            (root / ".git").mkdir()
            (root / "aart-registry.json").write_text("{}", encoding="utf-8")
            consumer = mock.Mock()
            consumer.finalize.return_value = Err(
                (
                    Diagnostic(
                        DiagnosticCode("expected-test-stop"),
                        Severity.ERROR,
                        "stop after proving the selected service finalized",
                    ),
                )
            )
            review = mock.Mock(review_digest=ObjectDigest("sha256", "a" * 64))

            def wrapper(callback):
                callback(object())

            def run_user(_curses, _screen, session, selection, **kwargs):
                self.assertIs(kwargs["consumer_service"], consumer)
                selection["request"] = mock.Mock()
                selection["consumer_review"] = review
                selection["wizard_session"] = session
                return session

            singles = iter((1, 10))  # Maintainer, Enter User workflows
            output = io.StringIO()
            with (
                redirect_stdout(output),
                mock.patch.object(curses, "wrapper", side_effect=wrapper),
                mock.patch.object(curses, "curs_set", return_value=None),
                mock.patch.object(
                    tui,
                    "_curses_singleselect",
                    side_effect=lambda *_args, **_kwargs: next(singles),
                ),
                mock.patch.object(tui, "_run_user_curses_wizard", side_effect=run_user),
                mock.patch(
                    "agent_artifacts.consumer.runtime.load_local_consumer_service",
                    return_value=Ok(consumer),
                ),
            ):
                code = tui._run_curses(
                    source_dir=str(root),
                    project=str(root),
                    user_home=temporary,
                )

            self.assertEqual(code, 2)
            consumer.finalize.assert_called_once_with(review, review.review_digest)
            self.assertIn("error [expected-test-stop]", output.getvalue())
            self.assertIn("Quit = q", output.getvalue())

    def test_canonical_maintainer_user_action_loads_canonical_consumer_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            (root / ".git").mkdir()
            (root / "aart-registry.json").write_text("{}", encoding="utf-8")
            consumer = mock.Mock()
            with (
                mock.patch(
                    "agent_artifacts.consumer.runtime.load_local_consumer_service",
                    return_value=Ok(consumer),
                ) as load_consumer,
                mock.patch.object(tui, "_run_user_text_wizard", return_value=0) as run_user,
            ):
                code = tui._run_text(
                    _scripted(["", "2", "11"]),
                    mock.Mock(),
                    source_dir=str(root),
                    project=str(root),
                    user_home=temporary,
                )

            self.assertEqual(code, 0)
            load_consumer.assert_called_once()
            self.assertIs(run_user.call_args.kwargs["consumer_service"], consumer)

    def test_registry_scaffold_previews_once_and_only_finalize_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            (root / ".git").mkdir()
            (root / "aart-registry.json").write_text("{}", encoding="utf-8")
            service = _Service()
            writes = []
            with mock.patch.object(tui, "_is_canonical_maintainer_workspace", return_value=True):
                code = tui._run_text(
                    _scripted(
                        [
                            "",
                            "2",
                            "2",
                            "skill",
                            "demo",
                            "Explain the reviewed demo workflow.",
                            "",
                            "codex",
                            "darwin,linux",
                            "",
                            "",
                            "back",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "finalize",
                        ]
                    ),
                    writes.append,
                    source_dir=str(root),
                    curation_service_factory=lambda _root: Ok(service),
                )

            self.assertEqual(code, 0)
            self.assertEqual(len(service.prepared), 1)
            self.assertEqual(len(service.finalized), 1)
            self.assertEqual(service.prepared[0].action, CurationAction.SCAFFOLD)
            rendered = "\n".join(writes)
            self.assertIn("Review digest", rendered)
            self.assertIn("Changed 1 managed path", rendered)

    def test_canonical_action_menu_explains_security_and_no_commit_push_boundary(self) -> None:
        labels = "\n".join(label for _action, label in tui.CANONICAL_MAINTAINER_ACTIONS)
        self.assertIn("security", labels.lower())
        self.assertIn("diff", labels.lower())
        self.assertIn("commit", labels.lower())
        self.assertIn("push", labels.lower())

    def test_curses_selects_canonical_action_then_finalizes_after_teardown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            (root / ".git").mkdir()
            (root / "aart-registry.json").write_text("{}", encoding="utf-8")
            service = _Service()
            inside = {"value": False}

            def wrapper(callback):
                inside["value"] = True
                callback(object())
                inside["value"] = False

            original_finalize = service.finalize

            def finalize(prepared, digest):
                self.assertFalse(inside["value"])
                return original_finalize(prepared, digest)

            service.finalize = finalize
            singles = iter((1, 0))  # Maintainer, Validate
            with (
                redirect_stdout(io.StringIO()),
                mock.patch.object(curses, "wrapper", side_effect=wrapper),
                mock.patch.object(curses, "curs_set", return_value=None),
                mock.patch("builtins.input", side_effect=["finalize"]),
                mock.patch.object(
                    tui,
                    "_curses_singleselect",
                    side_effect=lambda *_args, **_kwargs: next(singles),
                ),
            ):
                code = tui._run_curses(
                    source_dir=str(root),
                    curation_service_factory=lambda _root: Ok(service),
                )

            self.assertEqual(code, 0)
            self.assertEqual(len(service.prepared), 1)
            self.assertEqual(len(service.finalized), 1)
            self.assertEqual(service.prepared[0].action, CurationAction.VALIDATE)


if __name__ == "__main__":
    unittest.main()
