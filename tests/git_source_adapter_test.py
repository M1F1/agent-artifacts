from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.git import GitProcessReceipt
from agent_artifacts.sources.git import (
    _snapshot_from_archive,
    _tree_listing,
    acquire_git_snapshot,
)
from agent_artifacts.sources.model import (
    GitSnapshotRequest,
    SnapshotLimits,
    SourceInstanceId,
)


def _archive(path: str, *, unsafe: bool = False) -> None:
    with tarfile.open(path, "w") as archive:
        name = "../escape" if unsafe else "aart-source.json"
        content = b'{"schema_version":1}'
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))


class _GitRunner:
    def __init__(self, *, fail_fetch: bool = False, unsafe_archive: bool = False):
        self.requests = []
        self.fail_fetch = fail_fetch
        self.unsafe_archive = unsafe_archive

    def __call__(self, request):
        self.requests.append(request)
        argv = request.argv
        if "init" in argv:
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        if "fetch" in argv and self.fail_fetch:
            from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity

            return Err(
                (
                    Diagnostic(
                        DiagnosticCode("source-auth-failed"),
                        Severity.ERROR,
                        "authentication failed token=[redacted]",
                    ),
                )
            )
        if "rev-parse" in argv:
            return Ok(GitProcessReceipt(("a" * 40 + "\n").encode(), b""))
        if "ls-tree" in argv:
            size = len(b'{"schema_version":1}')
            record = f"100644 blob {'b' * 40} {size}\taart-source.json\0".encode()
            return Ok(GitProcessReceipt(record, b""))
        if "archive" in argv:
            output = next(
                value.removeprefix("--output=") for value in argv if value.startswith("--output=")
            )
            _archive(output, unsafe=self.unsafe_archive)
        return Ok(GitProcessReceipt(b"", b""))


class GitSourceAdapterTest(unittest.TestCase):
    def test_bare_mirror_fetch_resolve_and_archive_use_fixed_hook_free_commands(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = GitSnapshotRequest(
                SourceInstanceId("git-" + "a" * 32),
                SourceAlias("team"),
                "https://example.test/team/repo.git",
                "main",
                str(Path(root) / "mirror.git"),
                str(Path(root) / "tmp"),
                SnapshotLimits(),
                timeout_seconds=30,
            )
            runner = _GitRunner()

            result = acquire_git_snapshot(request, runner=runner)

            self.assertIsInstance(result, Ok)
            assert isinstance(result, Ok)
            self.assertEqual(result.value.resolved_revision, "a" * 40)
            self.assertEqual(result.value.snapshot.origin.value, "immutable-git")
            flattened = tuple(item for call in runner.requests for item in call.argv)
            self.assertIn("init", flattened)
            self.assertIn("fetch", flattened)
            self.assertIn("rev-parse", flattened)
            self.assertIn("archive", flattened)
            self.assertTrue(
                all("core.hooksPath=/dev/null" in call.argv for call in runner.requests)
            )
            self.assertEqual(tuple(Path(request.temporary_root).glob("*.tar")), ())

            second = acquire_git_snapshot(request, runner=runner)
            self.assertIsInstance(second, Ok)
            self.assertTrue(
                any("remote" in call.argv and "set-url" in call.argv for call in runner.requests)
            )

    def test_fetch_failure_and_unsafe_archive_never_return_a_candidate(self) -> None:
        for runner in (_GitRunner(fail_fetch=True), _GitRunner(unsafe_archive=True)):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as root:
                request = GitSnapshotRequest(
                    SourceInstanceId("git-" + "b" * 32),
                    SourceAlias("team"),
                    "https://example.test/team/repo.git",
                    "main",
                    str(Path(root) / "mirror.git"),
                    str(Path(root) / "tmp"),
                    SnapshotLimits(),
                    30,
                )

                result = acquire_git_snapshot(request, runner=runner)

                self.assertIsInstance(result, Err)

    def test_git_tree_listing_rejects_unsafe_types_duplicates_and_every_bound(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = dict(
                instance_id=SourceInstanceId("git-" + "e" * 32),
                alias=SourceAlias("team"),
                location="https://example.test/team/repo.git",
                ref="main",
                mirror_path=str(Path(root) / "mirror.git"),
                temporary_root=str(Path(root) / "tmp"),
                timeout_seconds=30,
            )

            def request(limits: SnapshotLimits) -> GitSnapshotRequest:
                return GitSnapshotRequest(limits=limits, **base)

            object_id = "a" * 40
            cases = (
                (b"malformed\0", SnapshotLimits()),
                (f"120000 blob {object_id} 1\tlink\0".encode(), SnapshotLimits()),
                (
                    (
                        f"100644 blob {object_id} 1\tfile\0100644 blob {object_id} 1\tfile\0"
                    ).encode(),
                    SnapshotLimits(),
                ),
                (
                    (f"100644 blob {object_id} 1\tone\0100644 blob {object_id} 1\ttwo\0").encode(),
                    SnapshotLimits(max_files=1),
                ),
                (f"100644 blob {object_id} 2\tfile\0".encode(), SnapshotLimits(max_file_bytes=1)),
                (
                    f"100644 blob {object_id} 2\tfile\0".encode(),
                    SnapshotLimits(max_total_bytes=1),
                ),
                (
                    f"100644 blob {object_id} 1\tone/two\0".encode(),
                    SnapshotLimits(max_depth=1),
                ),
                (f"100644 blob {object_id} -1\tfile\0".encode(), SnapshotLimits()),
            )
            for listing, limits in cases:
                with self.subTest(listing=listing, limits=limits):
                    self.assertIsInstance(_tree_listing(listing, request(limits)), Err)

    def test_git_archive_rejects_mismatch_links_duplicates_and_corrupt_tar(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = GitSnapshotRequest(
                SourceInstanceId("git-" + "f" * 32),
                SourceAlias("team"),
                "https://example.test/team/repo.git",
                "main",
                str(Path(root) / "mirror.git"),
                str(Path(root) / "tmp"),
                SnapshotLimits(),
                30,
            )
            archive_path = str(Path(root) / "archive.tar")

            _archive(archive_path)
            self.assertIsInstance(
                _snapshot_from_archive(archive_path, {"aart-source.json": 999}, request), Err
            )

            with tarfile.open(archive_path, "w") as archive:
                link = tarfile.TarInfo("link")
                link.type = tarfile.SYMTYPE
                link.linkname = "target"
                archive.addfile(link)
            self.assertIsInstance(_snapshot_from_archive(archive_path, {}, request), Err)

            with tarfile.open(archive_path, "w") as archive:
                for _index in range(2):
                    content = b"x"
                    info = tarfile.TarInfo("duplicate")
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
            self.assertIsInstance(
                _snapshot_from_archive(archive_path, {"duplicate": 1}, request), Err
            )

            with tarfile.open(archive_path, "w"):
                pass
            self.assertIsInstance(
                _snapshot_from_archive(archive_path, {"missing": 1}, request), Err
            )

            with tarfile.open(archive_path, "w") as archive:
                content = b"x"
                info = tarfile.TarInfo("nested/file")
                info.size = 1
                archive.addfile(info, io.BytesIO(content))
            nested = _snapshot_from_archive(archive_path, {"nested/file": 1}, request)
            self.assertIsInstance(nested, Ok)
            assert isinstance(nested, Ok)
            self.assertIn("nested", {str(entry.path) for entry in nested.value.entries})

            Path(archive_path).write_bytes(b"not a tar")
            self.assertIsInstance(_snapshot_from_archive(archive_path, {}, request), Err)

    def test_every_git_command_failure_and_noncanonical_commit_stops_acquisition(self) -> None:
        failure = Err(
            (Diagnostic(DiagnosticCode("source-unavailable"), Severity.ERROR, "command failed"),)
        )
        for marker in ("init", "remote", "fetch", "rev-parse", "ls-tree", "archive"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as root:
                request = GitSnapshotRequest(
                    SourceInstanceId("git-" + "1" * 32),
                    SourceAlias("team"),
                    "https://example.test/team/repo.git",
                    "main",
                    str(Path(root) / "mirror.git"),
                    str(Path(root) / "tmp"),
                    SnapshotLimits(),
                    30,
                )
                base = _GitRunner()

                def runner(process_request, failed_marker=marker, delegate=base):
                    if failed_marker in process_request.argv:
                        return failure
                    return delegate(process_request)

                self.assertIsInstance(acquire_git_snapshot(request, runner=runner), Err)

        with tempfile.TemporaryDirectory() as root:
            request = GitSnapshotRequest(
                SourceInstanceId("git-" + "2" * 32),
                SourceAlias("team"),
                "https://example.test/team/repo.git",
                "main",
                str(Path(root) / "mirror.git"),
                str(Path(root) / "tmp"),
                SnapshotLimits(),
                30,
            )
            base = _GitRunner()

            def bad_commit(process_request):
                if "rev-parse" in process_request.argv:
                    return Ok(GitProcessReceipt(b"not-a-commit\n", b""))
                return base(process_request)

            self.assertIsInstance(acquire_git_snapshot(request, runner=bad_commit), Err)

            with patch("agent_artifacts.sources.git.Path.mkdir", side_effect=OSError("storage")):
                self.assertIsInstance(acquire_git_snapshot(request, runner=base), Err)

    def test_embedded_credentials_and_unapproved_file_transport_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = dict(
                instance_id=SourceInstanceId("git-" + "c" * 32),
                alias=SourceAlias("team"),
                ref="main",
                mirror_path=str(Path(root) / "mirror.git"),
                temporary_root=str(Path(root) / "tmp"),
                limits=SnapshotLimits(),
                timeout_seconds=30,
            )
            secret = GitSnapshotRequest(
                location="https://user:secret@example.test/repo.git", **base
            )
            local = GitSnapshotRequest(location=f"file://{root}/repo.git", **base)

            for request in (secret, local):
                result = acquire_git_snapshot(request, runner=_GitRunner())
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertNotIn("secret", repr(result.diagnostics))

            for location in ("file://remote-host/path/repo.git", f"{root}/nested/../repo.git"):
                unsafe_local = GitSnapshotRequest(
                    location=location, allow_local_transport=True, **base
                )
                self.assertIsInstance(acquire_git_snapshot(unsafe_local, runner=_GitRunner()), Err)

    def test_system_git_updates_bare_mirror_and_resolves_branch_and_tag(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"

        def git(*arguments: str) -> str:
            completed = subprocess.run(
                ("git", *arguments),
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return completed.stdout.strip()

        with tempfile.TemporaryDirectory() as root:
            repository = Path(root) / "repository"
            shutil.copytree(fixture, repository)
            git("init", "-b", "main", str(repository))
            git("-C", str(repository), "config", "user.email", "test@example.invalid")
            git("-C", str(repository), "config", "user.name", "AART Test")
            git("-C", str(repository), "add", ".")
            git("-C", str(repository), "commit", "-m", "initial")
            first_commit = git("-C", str(repository), "rev-parse", "HEAD")
            git("-C", str(repository), "tag", "v1")
            mirror = Path(root) / "managed" / "mirror.git"
            temporary = Path(root) / "managed" / "tmp"

            def request(ref: str) -> GitSnapshotRequest:
                return GitSnapshotRequest(
                    SourceInstanceId("git-" + "d" * 32),
                    SourceAlias("reference"),
                    repository.as_uri(),
                    ref,
                    str(mirror),
                    str(temporary),
                    SnapshotLimits(),
                    30,
                    allow_local_transport=True,
                )

            first = acquire_git_snapshot(request("main"))
            tagged = acquire_git_snapshot(request("v1"))
            full_branch = acquire_git_snapshot(request("refs/heads/main"))
            self.assertIsInstance(first, Ok)
            self.assertIsInstance(tagged, Ok)
            self.assertIsInstance(full_branch, Ok)
            assert isinstance(first, Ok)
            assert isinstance(tagged, Ok)
            assert isinstance(full_branch, Ok)
            self.assertEqual(first.value.resolved_revision, first_commit)
            self.assertEqual(tagged.value.resolved_revision, first_commit)
            self.assertEqual(full_branch.value.resolved_revision, first_commit)
            self.assertEqual(first.value.snapshot_digest, tagged.value.snapshot_digest)
            self.assertEqual(git("-C", str(mirror), "rev-parse", "--is-bare-repository"), "true")
            self.assertNotIn(".git", {str(entry.path) for entry in first.value.snapshot.entries})

            readme = repository / "README.md"
            readme.write_text("second revision\n", encoding="utf-8")
            git("-C", str(repository), "add", "README.md")
            git("-C", str(repository), "commit", "-m", "second")
            second_commit = git("-C", str(repository), "rev-parse", "HEAD")

            second = acquire_git_snapshot(request("main"))

            self.assertIsInstance(second, Ok)
            assert isinstance(second, Ok)
            self.assertEqual(second.value.resolved_revision, second_commit)
            self.assertNotEqual(second.value.snapshot_digest, first.value.snapshot_digest)


if __name__ == "__main__":
    unittest.main()
