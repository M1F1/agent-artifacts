#!/usr/bin/env python3
"""Cut a release: check everything, tag it, publish it. One command, or one button.

The release used to be eight commands typed in order, and typing them in order was the only thing
holding the order together.  A step skipped looked exactly like a step that passed, and the two
that actually matter -- the checklist and the tag's ancestry -- were the easiest to forget.

So the order lives here instead.  Every precondition is checked before anything is written, and
nothing is written until all of them pass: a run either produces a tag and a release, or produces
neither.  The two decisions a human genuinely makes -- which version, and what the notes say --
are made before this runs, in a reviewed change on `main`.  This script only refuses to proceed
when they are missing; it never invents them.

The wheel is not built or attached here.  The action that runs this calls the release action next,
which builds the wheel and attaches it -- one builder of release artifacts rather than two that can
disagree.  It is called rather than triggered: GitHub raises no workflow event for anything done
with the repository token, so a release published here sets nothing off.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_api  # noqa: E402
import install_commands  # noqa: E402
import release as release_module  # noqa: E402
import release_docs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Refused(RuntimeError):
    """A precondition said no, in words that name the fix."""


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(("git", *arguments), cwd=ROOT, capture_output=True, text=True)
    if check and result.returncode:
        detail = result.stderr.strip() or "(git said nothing)"
        raise Refused(f"git {' '.join(arguments)} failed ({result.returncode})\n{detail}")
    return result


def _run(step: str, *command: str) -> None:
    print(f"\n==> {step}", flush=True)
    if subprocess.run(command, cwd=ROOT).returncode:
        raise Refused(f"{step} failed; nothing was tagged or published")


def preconditions(version: str, tag: str, notes: Path, remote: str) -> None:
    """Everything that must be true before a single byte is written anywhere."""

    if _git("status", "--porcelain").stdout.strip():
        raise Refused("the worktree has uncommitted changes; commit or stash them first")

    # The source version and the tag are one claim, and `check-tag` is the gate that says so.
    _run(f"version matches {tag}", sys.executable, "scripts/version.py", "check-tag", tag)

    if not notes.exists() or not notes.read_text(encoding="utf-8").strip():
        raise Refused(
            f"no release notes at {notes.relative_to(ROOT)}\n"
            "Write them first: the release job refuses to build without them, and notes written "
            "after the fact are notes nobody read."
        )

    # `release_docs.py` writes the headings and leaves visible TODO lines where the prose goes.
    # They are easy to leave behind, and the checklist would not notice: it asks whether the
    # documents name this version, not whether anyone finished writing them.
    open_markers = release_docs.open_markers(version, ROOT)
    if open_markers:
        listed = "\n".join(f"  {line}" for line in open_markers)
        raise Refused(
            f"{len(open_markers)} release document placeholder(s) still open:\n{listed}\n"
            "Write them, or delete the lines if they do not apply to this release."
        )

    if _git("ls-remote", "--tags", remote, f"refs/tags/{tag}").stdout.strip():
        raise Refused(
            f"{tag} already exists on {remote}\n"
            f"A published version is not re-cut.  Release the next version, or -- if that tag was "
            f"never released -- delete it deliberately: git push {remote} :refs/tags/{tag}"
        )

    # The tag must name a commit already in `main`.  The release job proves this too, but proving
    # it here means finding out before the tag exists rather than after.
    _git("fetch", "--no-tags", remote, "+refs/heads/main:refs/remotes/{}/main".format(remote))
    if _git("merge-base", "--is-ancestor", "HEAD", f"{remote}/main", check=False).returncode:
        raise Refused(
            f"HEAD is not in {remote}/main\n"
            "Merge the release commit first.  A tag outside main names source no one reviewed."
        )
    print(
        f"\n==> {version} is ready to cut from {_git('rev-parse', '--short', 'HEAD').stdout.strip()}"
    )


def publish(tag: str, version: str, notes: Path, remote: str) -> str:
    """Tag, push, and create the release.  Returns the release's URL."""

    name, digest = release_module.wheel_digest(ROOT, output_dir=ROOT / "dist")
    api, repository = github_api.origin(remote)
    # The commands name this instance, because the release page is where someone goes to get the
    # version and a README cannot say it: nothing interpolates a variable into a markdown file, so
    # a fork's README shows whatever host upstream wrote.  Here the address is derived, not typed.
    install = install_commands.lines(github_api.repository_url(remote), version)
    body = (
        f"{notes.read_text(encoding='utf-8').rstrip()}\n\n```\n{digest}  {name}\n```\n\n{install}\n"
    )

    _git("tag", "-a", tag, "-m", f"AART {version}")
    _git("push", remote, f"refs/tags/{tag}")
    print(f"\n==> pushed {tag}")

    created = github_api.json_request(
        f"{api}/repos/{repository}/releases",
        method="POST",
        payload={"tag_name": tag, "name": f"AART {version}", "body": body},
        auth=github_api.token(),
    )
    return str(created.get("html_url", f"{tag} published"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the version to cut, without the leading v")
    registry = parser.add_mutually_exclusive_group(required=True)
    registry.add_argument("--registry", type=Path, help="checkout of the reference registry")
    registry.add_argument(
        "--without-registry",
        action="store_true",
        help="skip the seven registry checks; they are reported skipped, never passed",
    )
    parser.add_argument("--remote", default="origin")
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        help="the gates already ran in this job; CI passes this, a laptop should not",
    )
    arguments = parser.parse_args(argv[1:])

    version = arguments.version.lstrip("v")
    tag = f"v{version}"
    notes = ROOT / "docs" / "release" / f"github-release-{tag}.md"

    try:
        preconditions(version, tag, notes, arguments.remote)
        if not arguments.skip_gates:
            _run("quality gates", sys.executable, "scripts/quality.py")
        checklist = (
            ["--without-registry"]
            if arguments.without_registry
            else ["--registry", str(arguments.registry)]
        )
        _run("release checklist", sys.executable, "scripts/release.py", "check", *checklist)
        url = publish(tag, version, notes, arguments.remote)
    except (Refused, github_api.GitHubError) as error:
        print(f"\ncut-release refused: {error}", file=sys.stderr)
        return 2

    print(f"\nreleased {tag}: {url}")
    print("The wheel is built and attached next, by the release action this job calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
